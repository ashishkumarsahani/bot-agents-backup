"""YouTube-sourced post generator.

Each bot persona has a list of source YouTube channels (stored in
`dhyanapp.bot_personas.<id>.youtube_channels`). On each run we pick one
eligible bot (cooldown = 3 days), list recent shorts from its channels via
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
DHYANAPP_SERVICES_URL = "https://dhyanapp-services.epilepto.com"
TRANSCRIPT_URL = f"{DHYANAPP_SERVICES_URL}/youtube/transcript"

YT_DLP = "/home/admin/.local/bin/yt-dlp"
SHORTS_LIST_LIMIT = 15
MAX_VIDEO_ATTEMPTS = 6
COOLDOWN_DAYS = 3
STATE_ID = "youtube_post_state"
POST_HISTORY_LIMIT = 60
GPT_MODEL = "gpt-5-mini"


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _list_channel_shorts(channel_handle: str) -> list[dict]:
    """Return [{id,title}, ...] of recent shorts from a channel.

    channel_handle may be '@handle' or a full URL.
    """
    handle = channel_handle.lstrip("@")
    url = f"https://www.youtube.com/@{handle}/shorts"
    try:
        result = subprocess.run(
            [
                YT_DLP,
                "--flat-playlist",
                "--print",
                "%(id)s\t%(title)s",
                "--playlist-end",
                str(SHORTS_LIST_LIMIT),
                url,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"[yt-dlp] timeout listing {url}")
        return []
    if result.returncode != 0:
        logger.warning(
            f"[yt-dlp] failed listing {url}: {result.stderr.strip().splitlines()[-1:]}"
        )
        return []
    out = []
    for line in result.stdout.strip().splitlines():
        if "\t" not in line:
            continue
        vid, title = line.split("\t", 1)
        if len(vid) == 11:
            out.append({"id": vid, "title": title})
    return out


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
        self.openai = OpenAI(api_key=api_key)

    # ---- state ----

    def _load_state(self) -> dict:
        doc = _db()["bot_config"].find_one({"_id": STATE_ID}) or {}
        return doc.get("bots", {})

    def _save_state(self, state: dict) -> None:
        _db()["bot_config"].update_one(
            {"_id": STATE_ID},
            {"$set": {"bots": state, "updated_at": datetime.utcnow()}},
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

    def _collect_candidates(self, bot_id: str, account: dict, posted_ids: set) -> list[dict]:
        channels = list(account.get("youtube_channels") or [])
        random.shuffle(channels)
        candidates: list[dict] = []
        for handle in channels:
            vids = _list_channel_shorts(handle)
            if not vids:
                continue
            for v in vids:
                if v["id"] in posted_ids:
                    continue
                candidates.append({**v, "channel": handle})
            if len(candidates) >= MAX_VIDEO_ATTEMPTS * 2:
                break
        random.shuffle(candidates)
        return candidates

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
                response_format={"type": "json_object"},
            )
        except Exception as e:
            logger.warning(f"[openai] generation failed: {e}")
            return None
        try:
            data = json.loads(resp.choices[0].message.content)
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
        candidates = self._collect_candidates(bot_id, account, posted_ids)
        if not candidates:
            logger.warning(f"no candidate videos for {bot_id}")
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
            return post_id

        logger.warning(f"exhausted {MAX_VIDEO_ATTEMPTS} candidates without a usable post")
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
