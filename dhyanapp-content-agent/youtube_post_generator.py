"""YouTube-sourced post generator.

Each bot persona has a list of source YouTube channels (stored in
`dhyanapp.bot_personas.<id>.youtube_channels`). On each run we pick one
eligible bot (cooldown = 1 day), list recent shorts from its channels via
yt-dlp, pull a transcript via the `/youtube/transcript` API, and ask
gpt-5-mini to generate a post in the transcript's language, matching its
tone. The post is written to MongoDB as a YouTube video post
(`isYouTubeVideo=true`, `videoUrl=<short url>`).
"""

import argparse
import json
import logging
import os
import random
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from openai import OpenAI
from pymongo import MongoClient

from llm_usage_tracker import record_openai_response

from bot_personas_store import _db, get_all_personas

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb://dhyanadmin:Dhyan%40Mongo2026!@localhost:27017/dhyanapp?authSource=admin&replicaSet=rs0",
)
DHYANAPP_SERVICES_URL = "https://services.dhyanapp.org"
TRANSCRIPT_URL = f"{DHYANAPP_SERVICES_URL}/youtube/transcript"

def _resolve_yt_dlp() -> str:
    """Locate the yt-dlp binary instead of assuming a single install path.

    Order: $YT_DLP_PATH override -> PATH lookup -> common install dirs ->
    bare 'yt-dlp' (resolved by subprocess via PATH as a last resort).
    """
    override = os.getenv("YT_DLP_PATH", "").strip()
    if override and os.path.exists(override):
        return override
    found = shutil.which("yt-dlp")
    if found:
        return found
    for cand in (
        os.path.expanduser("~/.local/bin/yt-dlp"),
        "/usr/local/bin/yt-dlp",
        "/opt/homebrew/bin/yt-dlp",
        "/home/admin/.local/bin/yt-dlp",
    ):
        if os.path.exists(cand):
            return cand
    return "yt-dlp"


YT_DLP = _resolve_yt_dlp()
# yt-dlp anti-block options (env-first; can be overridden per-run from Mongo secrets).
# YT_DLP_PROXY: e.g. http://user:pass@host:port or socks5://host:port
# YT_DLP_COOKIES: path to a cookies.txt exported for youtube.com
# YT_DLP_COOKIES_FROM_BROWSER: e.g. chrome / firefox (yt-dlp --cookies-from-browser)
YT_DLP_PROXY = os.getenv("YT_DLP_PROXY", "").strip()
YT_DLP_COOKIES = os.getenv("YT_DLP_COOKIES", "").strip()
YT_DLP_COOKIES_FROM_BROWSER = os.getenv("YT_DLP_COOKIES_FROM_BROWSER", "").strip()
# Optional generic webhook for loud alerts (Slack-compatible {"text": ...} payload).
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "").strip()

SHORTS_LIST_LIMIT = 15
MAX_VIDEO_ATTEMPTS = 6
COOLDOWN_DAYS = 1
STATE_ID = "youtube_post_state"
HEALTH_ID = "youtube_post_health"
POST_HISTORY_LIMIT = 60
GPT_MODEL = "gemma4:cloud"


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _yt_dlp_extra_args(
    proxy: Optional[str] = None,
    cookies: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
) -> list[str]:
    """Build optional anti-block flags for yt-dlp from config."""
    args: list[str] = []
    proxy = proxy if proxy is not None else YT_DLP_PROXY
    cookies = cookies if cookies is not None else YT_DLP_COOKIES
    cfb = cookies_from_browser if cookies_from_browser is not None else YT_DLP_COOKIES_FROM_BROWSER
    if proxy:
        args += ["--proxy", proxy]
    if cookies:
        args += ["--cookies", cookies]
    elif cfb:
        args += ["--cookies-from-browser", cfb]
    return args


def _looks_like_block(stderr: str) -> bool:
    """True if yt-dlp stderr indicates YouTube bot-detection / IP blocking."""
    s = (stderr or "").lower()
    return any(
        m in s
        for m in (
            "sign in to confirm",
            "not a bot",
            "http error 403",
            "http error 429",
            "blocked",
            "captcha",
            "unable to download webpage",
        )
    )


def _list_channel_shorts(
    channel_handle: str,
    proxy: Optional[str] = None,
    cookies: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
) -> tuple[list[dict], Optional[str]]:
    """Return (videos, error) where videos is [{id,title}, ...] of recent shorts.

    error is None on a clean listing (even if empty). On failure it is a short
    string, prefixed with "BLOCK:" when the failure looks like YouTube
    bot-detection / IP blocking. channel_handle may be '@handle' or a full URL.
    """
    handle = channel_handle.lstrip("@")
    url = f"https://www.youtube.com/@{handle}/shorts"
    cmd = [
        YT_DLP,
        *_yt_dlp_extra_args(proxy, cookies, cookies_from_browser),
        "--flat-playlist",
        "--print",
        "%(id)s\t%(title)s",
        "--playlist-end",
        str(SHORTS_LIST_LIMIT),
        url,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60
        )
    except FileNotFoundError:
        logger.error(f"[yt-dlp] binary not found at '{YT_DLP}' (set $YT_DLP_PATH)")
        return [], f"yt-dlp not found at {YT_DLP}"
    except subprocess.TimeoutExpired:
        logger.warning(f"[yt-dlp] timeout listing {url}")
        return [], "timeout"
    if result.returncode != 0:
        last = (result.stderr.strip().splitlines() or [""])[-1]
        logger.warning(f"[yt-dlp] failed listing {url}: {last}")
        prefix = "BLOCK:" if _looks_like_block(result.stderr) else ""
        return [], f"{prefix}{last[:200]}"
    out = []
    for line in result.stdout.strip().splitlines():
        if "\t" not in line:
            continue
        vid, title = line.split("\t", 1)
        if len(vid) == 11:
            out.append({"id": vid, "title": title})
    return out, None


def _fetch_transcript(video_id: str) -> Optional[dict]:
    """POST to /youtube/transcript. Returns dict on success, None otherwise."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        r = requests.post(TRANSCRIPT_URL, json={"url": url}, timeout=45)
    except requests.RequestException as e:
        logger.warning(f"[transcript] request failed for {video_id}: {e}")
        return None
    if r.status_code != 200:
        try:
            err = r.json().get("error", r.text[:120])
        except Exception:
            err = r.text[:120]
        logger.info(f"[transcript] {video_id} -> {r.status_code} {err}")
        return None
    try:
        return r.json()
    except Exception:
        logger.warning(f"[transcript] {video_id} invalid json")
        return None


def _transcript_text(payload: dict) -> str:
    """Extract a plain-text transcript from the service response."""
    if not isinstance(payload, dict):
        return ""
    if isinstance(payload.get("text"), str) and payload["text"].strip():
        return payload["text"].strip()
    segments = payload.get("segments") or payload.get("transcript") or []
    if isinstance(segments, list):
        parts = []
        for seg in segments:
            if isinstance(seg, dict):
                t = seg.get("text") or seg.get("content") or ""
                if t:
                    parts.append(t)
            elif isinstance(seg, str):
                parts.append(seg)
        return " ".join(parts).strip()
    return ""


class YouTubePostGenerator:
    def __init__(self) -> None:
        self.accounts = get_all_personas()
        self._init_mongo()
        self._init_openai()
        self._load_yt_settings()

    def _load_yt_settings(self) -> None:
        """Resolve yt-dlp anti-block settings: env first, then Mongo config/secrets."""
        self.yt_proxy = YT_DLP_PROXY
        self.yt_cookies = YT_DLP_COOKIES
        self.yt_cookies_from_browser = YT_DLP_COOKIES_FROM_BROWSER
        self.alert_webhook = ALERT_WEBHOOK_URL
        try:
            secrets = self.db["config"].find_one({"_id": "secrets"}) or {}
        except Exception as e:
            logger.warning(f"[config] could not load yt settings from Mongo: {e}")
            secrets = {}
        self.yt_proxy = self.yt_proxy or (secrets.get("YT_DLP_PROXY") or "").strip()
        self.yt_cookies = self.yt_cookies or (secrets.get("YT_DLP_COOKIES") or "").strip()
        self.yt_cookies_from_browser = self.yt_cookies_from_browser or (
            secrets.get("YT_DLP_COOKIES_FROM_BROWSER") or ""
        ).strip()
        self.alert_webhook = self.alert_webhook or (secrets.get("ALERT_WEBHOOK_URL") or "").strip()
        logger.info(
            f"[yt-dlp] path={YT_DLP} proxy={'yes' if self.yt_proxy else 'no'} "
            f"cookies={'yes' if (self.yt_cookies or self.yt_cookies_from_browser) else 'no'}"
        )

    def _init_mongo(self) -> None:
        self.mongo_client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
        self.mongo_client.admin.command("ping")
        self.db = self.mongo_client["dhyanapp"]
        logger.info("[SUCCESS] MongoDB initialized for YouTube posts")

    def _init_openai(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY", "")
        try:
            secrets = self.db["config"].find_one({"_id": "secrets"}) or {}
            api_key = secrets.get("OPENAI_API_KEY", api_key)
        except Exception as e:
            logger.warning(f"[config] could not load secrets from Mongo: {e}")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        self.openai = OpenAI(api_key="ollama", base_url="http://localhost:11434/v1")

    # ---- state ----

    def _load_state(self) -> dict:
        doc = _db()["bot_config"].find_one({"_id": STATE_ID}) or {}
        return doc.get("bots", {})

    def _save_state(self, state: dict) -> None:
        _db()["bot_config"].update_one(
            {"_id": STATE_ID},
            {"$set": {"bots": state, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    def _pick_eligible_bot(self, state: dict, force_bot: Optional[str]) -> Optional[str]:
        if force_bot:
            if force_bot not in self.accounts:
                logger.error(f"unknown bot id: {force_bot}")
                return None
            return force_bot
        cutoff_ms = _now_ms() - COOLDOWN_DAYS * 86400 * 1000
        eligible = []
        for bot_id, acc in self.accounts.items():
            if not acc.get("youtube_channels"):
                continue
            last_run = state.get(bot_id, {}).get("last_run_at", 0)
            if last_run <= cutoff_ms:
                eligible.append((bot_id, last_run))
        if not eligible:
            logger.info("no bot eligible (all within 3-day cooldown)")
            return None
        eligible.sort(key=lambda x: x[1])
        return eligible[0][0]

    # ---- candidate selection ----

    def _collect_candidates(
        self, bot_id: str, account: dict, posted_ids: set
    ) -> tuple[list[dict], dict]:
        channels = list(account.get("youtube_channels") or [])
        random.shuffle(channels)
        candidates: list[dict] = []
        stats = {
            "channels": len(channels),
            "channels_ok": 0,          # returned a clean listing (may be empty)
            "channels_with_videos": 0,
            "errors": [],              # short "handle: error" strings
            "blocked": False,          # any listing looked like an IP/bot block
        }
        for handle in channels:
            vids, err = _list_channel_shorts(
                handle,
                proxy=self.yt_proxy,
                cookies=self.yt_cookies,
                cookies_from_browser=self.yt_cookies_from_browser,
            )
            if err:
                stats["errors"].append(f"{handle}: {err}")
                if err.startswith("BLOCK:") or err.startswith("yt-dlp not found"):
                    stats["blocked"] = True
                continue
            stats["channels_ok"] += 1
            if vids:
                stats["channels_with_videos"] += 1
            for v in vids:
                if v["id"] in posted_ids:
                    continue
                candidates.append({**v, "channel": handle})
            if len(candidates) >= MAX_VIDEO_ATTEMPTS * 2:
                break
        random.shuffle(candidates)
        return candidates, stats

    # ---- health / alerts ----

    def _record_health(self, status: str, detail: str, extra: Optional[dict] = None) -> None:
        """Persist a heartbeat so stalls are detectable (last_success_at)."""
        now = datetime.now(timezone.utc)
        doc = {"status": status, "detail": detail, "updated_at": now}
        if status == "ok":
            doc["last_success_at"] = now
        if extra:
            doc.update(extra)
        try:
            _db()["bot_config"].update_one({"_id": HEALTH_ID}, {"$set": doc}, upsert=True)
        except Exception as e:
            logger.warning(f"[health] could not record health: {e}")

    def _alert(self, subject: str, detail: str) -> None:
        """Loud, monitorable alert for silent-stall conditions."""
        logger.error(f"[ALERT] YouTube post bot: {subject} — {detail}")
        if not self.alert_webhook:
            return
        try:
            requests.post(
                self.alert_webhook,
                json={"text": f":warning: YouTube post bot: {subject}\n{detail}"},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"[alert] webhook post failed: {e}")

    def _already_posted_video_ids(self, bot_id: str, state: dict) -> set:
        ids: set = set(state.get(bot_id, {}).get("last_video_ids", []))
        # also block anything already in posts collection across all bots
        try:
            cursor = self.db["posts"].find(
                {"videoUrl": {"$regex": "youtu", "$options": "i"}},
                {"videoUrl": 1},
            )
            for d in cursor:
                url = d.get("videoUrl") or ""
                for token in ("watch?v=", "youtu.be/", "/shorts/"):
                    if token in url:
                        tail = url.split(token, 1)[1]
                        vid = tail.split("&", 1)[0].split("?", 1)[0].split("/", 1)[0]
                        if len(vid) == 11:
                            ids.add(vid)
        except Exception as e:
            logger.warning(f"[dedup] posts scan failed: {e}")
        return ids

    # ---- generation ----

    def _generate_post_content(
        self, account: dict, video: dict, transcript_text: str
    ) -> Optional[dict]:
        persona_block = (
            f"Persona: {account['name']}\n"
            f"Style: {account.get('conversational_style', '')}\n"
            f"Description: {account.get('persona', '')}\n"
            f"Comment style: {account.get('comment_style', '')}\n"
            f"Typical topics: {', '.join(account.get('topics', []))}"
        )
        system = (
            "You craft short social posts for a spiritual app. "
            "Each post reacts to a YouTube video the bot persona just watched. "
            "Write in the SAME language as the transcript — do not translate. "
            "Imitate the speaker's tone, vocabulary, rhythm, and honorifics. "
            "Do NOT summarize the video; respond TO it in first person as the persona. "
            "Length: 80–140 words. No hashtags, no emojis, no markdown headings. "
            "Return strict JSON: "
            '{"content": "<post body>", "language": "<detected language>", "title": "<3-6 word hook>"}'
        )
        transcript_clip = transcript_text[:6000]
        user = (
            f"{persona_block}\n\n"
            f"Video title: {video.get('title', '')}\n"
            f"Channel: {video.get('channel', '')}\n"
            f"Video URL: https://youtu.be/{video['id']}\n\n"
            f"Transcript:\n{transcript_clip}"
        )
        try:
            resp = self.openai.chat.completions.create(
                model=GPT_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as e:
            logger.warning(f"[openai] generation failed: {e}")
            return None
        record_openai_response(resp, service="youtube_post.generate")
        try:
            import re as _re
            raw = resp.choices[0].message.content.strip()
            raw = _re.sub(r"^```(?:json)?\s*\n?", "", raw)
            raw = _re.sub(r"\n?```\s*$", "", raw)
            data = json.loads(raw)
        except Exception as e:
            logger.warning(f"[openai] invalid json: {e}")
            return None
        content = (data.get("content") or "").strip()
        if not content:
            return None
        return {
            "content": content,
            "language": data.get("language", "unknown"),
            "title": data.get("title", ""),
        }

    def _insert_post(
        self, account: dict, video: dict, post: dict
    ) -> Optional[str]:
        post_id = str(uuid.uuid4())
        now_ms = int(datetime.now(IST).timestamp() * 1000)
        doc = {
            "_id": post_id,
            "selfID": post_id,
            "content": post["content"],
            "createdAt": now_ms,
            "createdBy": account["user_id"],
            "creatorName": account["name"],
            "deleted": False,
            "deletedAt": None,
            "deletedByAdmin": False,
            "globallyHidden": False,
            "commentCount": 0,
            "likeCount": 0,
            "viewCount": 0,
            "isLikedByCurrentUser": None,
            "isReportedByCurrentUserStatus": None,
            "isViewedByCurrentUser": None,
            "lastEditedAt": None,
            "location": "",
            "composition": "SEPARATE_CONTENT",
            "isYouTubeVideo": True,
            "videoUrl": f"https://youtu.be/{video['id']}",
            "imageUrl": None,
            "thumbnailUrl": None,
            "audioUrl": None,
            "audioBackgroundUrl": None,
            "isAudioBackgroundFromGallery": False,
            "_botGenerated": True,
            "_source": "youtube_pipeline",
            "_sourceChannel": video.get("channel"),
            "_sourceVideoId": video["id"],
            "_sourceVideoTitle": video.get("title"),
            "_language": post.get("language"),
        }
        self.db["posts"].insert_one(doc)
        logger.info(f"[SUCCESS] Inserted YouTube post {post_id} for {account['name']}")
        return post_id

    # ---- main ----

    def run(self, force_bot: Optional[str] = None, dry_run: bool = False) -> Optional[str]:
        state = self._load_state()
        bot_id = self._pick_eligible_bot(state, force_bot)
        if not bot_id:
            return None
        account = self.accounts[bot_id]
        logger.info(f"Selected bot: {bot_id} ({account['name']})")

        posted_ids = self._already_posted_video_ids(bot_id, state)
        candidates, stats = self._collect_candidates(bot_id, account, posted_ids)
        logger.info(
            f"[listing] channels={stats['channels']} ok={stats['channels_ok']} "
            f"with_videos={stats['channels_with_videos']} "
            f"candidates={len(candidates)} errors={len(stats['errors'])}"
        )
        if not candidates:
            # Distinguish a silent stall (blocking / all listings failing) from a
            # genuine "nothing new to post" so monitoring can catch the former.
            if stats["blocked"] or (stats["channels"] and stats["channels_ok"] == 0):
                detail = (
                    f"bot={bot_id}: all {stats['channels']} channel listings failed "
                    f"(blocked={stats['blocked']}); errors: {'; '.join(stats['errors'][:5])}"
                )
                self._record_health(
                    "blocked", detail, {"bot_id": bot_id, "errors": stats["errors"][:10]}
                )
                self._alert("channel listing blocked / failing", detail)
            else:
                logger.warning(f"no candidate videos for {bot_id}")
                self._record_health(
                    "no_candidates",
                    f"bot={bot_id}: listings ok but no new videos to post",
                    {"bot_id": bot_id},
                )
            return None

        for idx, video in enumerate(candidates[:MAX_VIDEO_ATTEMPTS]):
            logger.info(
                f"[{idx + 1}/{min(len(candidates), MAX_VIDEO_ATTEMPTS)}] "
                f"trying {video['id']} from {video['channel']}: {video['title'][:60]}"
            )
            payload = _fetch_transcript(video["id"])
            if not payload:
                continue
            text = _transcript_text(payload)
            if len(text) < 120:
                logger.info(f"  transcript too short ({len(text)} chars), skipping")
                continue

            post = self._generate_post_content(account, video, text)
            if not post:
                continue

            logger.info(f"  generated {len(post['content'])} chars in {post['language']}")
            if dry_run:
                logger.info("[DRY-RUN] skipping DB insert")
                logger.info(f"  content preview: {post['content'][:200]}")
                return video["id"]

            post_id = self._insert_post(account, video, post)
            if not post_id:
                continue

            # update state
            bot_state = state.get(bot_id, {})
            history = list(bot_state.get("last_video_ids", []))
            history.append(video["id"])
            history = history[-POST_HISTORY_LIMIT:]
            state[bot_id] = {
                "last_run_at": _now_ms(),
                "last_video_ids": history,
                "last_post_id": post_id,
            }
            self._save_state(state)
            self._record_health(
                "ok", f"bot={bot_id} posted {post_id}",
                {"bot_id": bot_id, "last_post_id": post_id},
            )
            return post_id

        detail = (
            f"bot={bot_id}: tried {min(len(candidates), MAX_VIDEO_ATTEMPTS)} candidates, "
            f"none produced a usable post (no transcript / generation failure)"
        )
        logger.warning(f"exhausted {MAX_VIDEO_ATTEMPTS} candidates without a usable post")
        self._record_health("exhausted", detail, {"bot_id": bot_id})
        self._alert("exhausted candidates without a post", detail)
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bot", help="Force a specific bot id (ignores cooldown)")
    parser.add_argument("--dry-run", action="store_true", help="Do not insert into Mongo")
    args = parser.parse_args()

    gen = YouTubePostGenerator()
    result = gen.run(force_bot=args.bot, dry_run=args.dry_run)
    if result:
        print(f"OK: {result}")
        return 0
    print("No post created")
    return 1


if __name__ == "__main__":
    sys.exit(main())
