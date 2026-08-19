"""YouTube Community-post reposter.

Each bot persona has a list of source YouTube channels whose *Community/Posts*
tab we mirror (`dhyanapp.bot_personas.<id>.community_channels`). On each run we
pick one eligible bot (cooldown = 3 days), scrape the newest community post that
has image(s) via YouTube's InnerTube API, re-host the image(s) on MinIO, and
write a multi-image DhyanApp post that copies the original text verbatim with a
`via @channel` attribution line.

yt-dlp has no community-post extractor, so this uses InnerTube (youtubei/v1)
directly — pure JSON HTTP, no browser, no JS runtime.
"""

import argparse
import http.cookiejar
import io
import json
import logging
import os
import random
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import boto3
import requests
from botocore.client import Config as BotoConfig
from dotenv import load_dotenv
from PIL import Image
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

# ---- MinIO (S3-compatible) image hosting — same config as scripture_post_generator ----
_minio_host = os.getenv("MINIO_ENDPOINT", "localhost")
_minio_port = os.getenv("MINIO_PORT", "9000")
MINIO_ENDPOINT = _minio_host if ":" in _minio_host else f"{_minio_host}:{_minio_port}"
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "dhyanapp-recordings")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "https://storage.dhyanapp.org")

# ---- InnerTube ----
INNERTUBE_BASE = "https://www.youtube.com/youtubei/v1"
INNERTUBE_BROWSE = f"{INNERTUBE_BASE}/browse"
INNERTUBE_RESOLVE = f"{INNERTUBE_BASE}/navigation/resolve_url"
INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"  # public web-client key
INNERTUBE_CLIENT_VERSION = "2.20240101.00.00"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ---- anti-block config (env-first, then Mongo config/secrets) ----
YT_PROXY = os.getenv("YT_DLP_PROXY", "").strip()
YT_COOKIES = os.getenv("YT_DLP_COOKIES", "").strip()  # path to cookies.txt
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "").strip()

COOLDOWN_DAYS = 3
STATE_ID = "youtube_community_state"
HEALTH_ID = "youtube_community_health"
POST_HISTORY_LIMIT = 120
POSTS_PER_CHANNEL = 20  # newest N posts scanned per channel
MAX_IMAGES = 10         # cap images per repost
WEBP_QUALITY = 85


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


# ======================================================================
#  InnerTube scraper (module-level; takes a requests.Session)
# ======================================================================

def _context() -> dict:
    return {"client": {"clientName": "WEB", "clientVersion": INNERTUBE_CLIENT_VERSION, "hl": "en", "gl": "US"}}


def _browse(sess: requests.Session, browse_id: str, params: Optional[str] = None) -> dict:
    body = {"context": _context(), "browseId": browse_id}
    if params:
        body["params"] = params
    r = sess.post(
        INNERTUBE_BROWSE,
        params={"key": INNERTUBE_KEY, "prettyPrint": "false"},
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _resolve_url(sess: requests.Session, url: str) -> dict:
    r = sess.post(
        INNERTUBE_RESOLVE,
        params={"key": INNERTUBE_KEY, "prettyPrint": "false"},
        json={"context": _context(), "url": url},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("endpoint", {}) or {}


def resolve_channel_id(sess: requests.Session, handle: str) -> Optional[str]:
    """@handle (or legacy custom URL) -> canonical UC... browseId via resolve_url.

    Scraping the channel HTML is unreliable (the page references linked/featured
    channels, so a naive regex grabs the wrong UC id). Legacy vanity handles
    resolve to a urlEndpoint redirect first, so we follow one hop.
    """
    h = handle.lstrip("@")
    endpoint = _resolve_url(sess, f"https://www.youtube.com/@{h}")
    browse = endpoint.get("browseEndpoint") or {}
    if browse.get("browseId"):
        return browse["browseId"]
    redirect = (endpoint.get("urlEndpoint") or {}).get("url")
    if redirect:
        endpoint = _resolve_url(sess, redirect)
        return (endpoint.get("browseEndpoint") or {}).get("browseId")
    return None


def find_posts_tab_params(sess: requests.Session, channel_id: str) -> Optional[str]:
    """Discover the Posts/Community tab's browse params dynamically."""
    data = _browse(sess, channel_id)
    tabs = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
    for t in tabs:
        tr = t.get("tabRenderer") or {}
        if (tr.get("title") or "").lower() in ("posts", "community"):
            return (tr.get("endpoint") or {}).get("browseEndpoint", {}).get("params")
    return None


def _find_all(obj, key):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            else:
                yield from _find_all(v, key)
    elif isinstance(obj, list):
        for item in obj:
            yield from _find_all(item, key)


def _full_res(url: str) -> str:
    """Force Google image URLs to original size (drop any =sNNN-... suffix)."""
    return re.sub(r"=[sw]\d.*$", "=s0", url) if "=" in url.rsplit("/", 1)[-1] else url


def _best_thumb(image_renderer: dict) -> Optional[str]:
    thumbs = (((image_renderer or {}).get("image") or {}).get("thumbnails")) or []
    if not thumbs:
        return None
    best = max(thumbs, key=lambda t: (t.get("width", 0) * t.get("height", 0)))
    url = best.get("url")
    return _full_res(url) if url else None


def _extract_images(post: dict) -> list:
    att = post.get("backstageAttachment") or {}
    urls = []
    if "backstageImageRenderer" in att:
        u = _best_thumb(att["backstageImageRenderer"])
        if u:
            urls.append(u)
    for img in (att.get("postMultiImageRenderer") or {}).get("images", []):
        u = _best_thumb(img.get("backstageImageRenderer") or {})
        if u:
            urls.append(u)
    return urls


def _post_text(post: dict) -> str:
    runs = (post.get("contentText") or {}).get("runs") or []
    return "".join(run.get("text", "") for run in runs).strip()


def _published(post: dict) -> str:
    pt = post.get("publishedTimeText") or {}
    if "runs" in pt:
        return "".join(r.get("text", "") for r in pt["runs"])
    return pt.get("simpleText", "")


def _looks_like_block(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(m in s for m in ("403", "429", "consent", "captcha", "too many requests"))


def scrape_posts_with_images(sess: requests.Session, handle: str):
    """Return (posts, error). posts newest-first, each with image(s).

    error is None on success; on failure a short string, prefixed "BLOCK:" when
    it looks like bot-detection / rate limiting.
    """
    try:
        channel_id = resolve_channel_id(sess, handle)
        if not channel_id:
            return [], "resolve failed"
        params = find_posts_tab_params(sess, channel_id)
        if not params:
            return [], "no posts/community tab"
        data = _browse(sess, channel_id, params=params)
    except requests.RequestException as e:
        prefix = "BLOCK:" if _looks_like_block(e) else ""
        return [], f"{prefix}{str(e)[:160]}"

    out = []
    for post in list(_find_all(data, "backstagePostRenderer"))[:POSTS_PER_CHANNEL]:
        images = _extract_images(post)
        if not images:
            continue
        pid = post.get("postId")
        if not pid:
            continue
        out.append({
            "post_id": pid,
            "text": _post_text(post),
            "images": images[:MAX_IMAGES],
            "published": _published(post),
            "source_url": f"https://www.youtube.com/post/{pid}",
        })
    return out, None


# ======================================================================
#  Generator
# ======================================================================

class YouTubeCommunityPostGenerator:
    def __init__(self) -> None:
        self.accounts = get_all_personas()
        self._init_mongo()
        self._init_minio()
        self._load_settings()

    def _init_mongo(self) -> None:
        self.mongo_client = MongoClient(
            MONGODB_URI, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000
        )
        self.mongo_client.admin.command("ping")
        self.db = self.mongo_client["dhyanapp"]
        logger.info("[SUCCESS] MongoDB initialized for community posts")

    def _init_minio(self) -> None:
        try:
            protocol = "https" if MINIO_SECURE else "http"
            self.s3_client = boto3.client(
                "s3",
                endpoint_url=f"{protocol}://{MINIO_ENDPOINT}",
                aws_access_key_id=MINIO_ACCESS_KEY,
                aws_secret_access_key=MINIO_SECRET_KEY,
                config=BotoConfig(signature_version="s3v4"),
                region_name="us-east-1",
            )
            logger.info("[SUCCESS] MinIO initialized")
        except Exception as e:
            logger.error(f"[ERROR] Failed to initialize MinIO: {e}")
            self.s3_client = None

    def _load_settings(self) -> None:
        """Resolve proxy/cookies/webhook: env first, then Mongo config/secrets."""
        self.yt_proxy = YT_PROXY
        self.yt_cookies = YT_COOKIES
        self.alert_webhook = ALERT_WEBHOOK_URL
        try:
            secrets = self.db["config"].find_one({"_id": "secrets"}) or {}
        except Exception as e:
            logger.warning(f"[config] could not load secrets from Mongo: {e}")
            secrets = {}
        self.yt_proxy = self.yt_proxy or (secrets.get("YT_DLP_PROXY") or "").strip()
        self.yt_cookies = self.yt_cookies or (secrets.get("YT_DLP_COOKIES") or "").strip()
        self.alert_webhook = self.alert_webhook or (secrets.get("ALERT_WEBHOOK_URL") or "").strip()
        logger.info(
            f"[innertube] proxy={'yes' if self.yt_proxy else 'no'} "
            f"cookies={'yes' if self.yt_cookies else 'no'}"
        )

    def _make_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        # SOCS/CONSENT cookies skip the consent interstitial that otherwise blanks data.
        s.cookies.set("SOCS", "CAI", domain=".youtube.com")
        s.cookies.set("CONSENT", "YES+cb", domain=".youtube.com")
        if self.yt_cookies and os.path.exists(self.yt_cookies):
            try:
                cj = http.cookiejar.MozillaCookieJar()
                cj.load(self.yt_cookies, ignore_discard=True, ignore_expires=True)
                s.cookies.update(cj)
            except Exception as e:
                logger.warning(f"[cookies] failed to load {self.yt_cookies}: {e}")
        if self.yt_proxy:
            s.proxies.update({"http": self.yt_proxy, "https": self.yt_proxy})
        return s

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
            if not acc.get("community_channels"):
                continue
            last_run = state.get(bot_id, {}).get("last_run_at", 0)
            if last_run <= cutoff_ms:
                eligible.append((bot_id, last_run))
        if not eligible:
            logger.info("no bot eligible (all within cooldown or no community_channels)")
            return None
        eligible.sort(key=lambda x: x[1])
        return eligible[0][0]

    def _already_posted_ids(self, bot_id: str, state: dict) -> set:
        ids = set(state.get(bot_id, {}).get("last_post_ids", []))
        try:
            cursor = self.db["posts"].find(
                {"_source": "youtube_community"}, {"_sourcePostId": 1}
            )
            for d in cursor:
                if d.get("_sourcePostId"):
                    ids.add(d["_sourcePostId"])
        except Exception as e:
            logger.warning(f"[dedup] posts scan failed: {e}")
        return ids

    # ---- candidate selection ----

    def _collect_candidates(self, account: dict, posted_ids: set):
        sess = self._make_session()
        channels = list(account.get("community_channels") or [])
        random.shuffle(channels)
        candidates = []
        stats = {"channels": len(channels), "channels_ok": 0, "errors": [], "blocked": False}
        for handle in channels:
            posts, err = scrape_posts_with_images(sess, handle)
            if err:
                stats["errors"].append(f"{handle}: {err}")
                if err.startswith("BLOCK:"):
                    stats["blocked"] = True
                continue
            stats["channels_ok"] += 1
            for p in posts:
                if p["post_id"] in posted_ids:
                    continue
                candidates.append({**p, "channel": handle})
        return candidates, stats, sess

    # ---- image pipeline ----

    def _download_and_upload_images(self, sess: requests.Session, post_id: str, image_urls: list) -> list:
        """Download each source image, re-encode WEBP, upload to MinIO. Returns public URLs."""
        if not self.s3_client:
            logger.error("[minio] not initialized; cannot upload images")
            return []
        out = []
        for i, url in enumerate(image_urls):
            try:
                r = sess.get(url, timeout=45)
                if r.status_code != 200 or not r.content:
                    logger.warning(f"[img {i}] download {r.status_code}")
                    continue
                img = Image.open(io.BytesIO(r.content))
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="WEBP", quality=WEBP_QUALITY, method=6)
                object_key = f"Posts/images/bot_community/{post_id}_{i}.webp"
                self.s3_client.put_object(
                    Bucket=MINIO_BUCKET,
                    Key=object_key,
                    Body=buf.getvalue(),
                    ContentType="image/webp",
                )
                base_url = MINIO_PUBLIC_URL if MINIO_PUBLIC_URL else f"http://{MINIO_ENDPOINT}"
                out.append(f"{base_url}/{MINIO_BUCKET}/{object_key}")
            except Exception as e:
                logger.warning(f"[img {i}] failed: {e}")
        return out

    # ---- content + insert ----

    @staticmethod
    def _build_content(text: str, channel: str) -> str:
        text = (text or "").strip()
        handle = channel if channel.startswith("@") else f"@{channel}"
        credit = f"via {handle} on YouTube"
        return f"{text}\n\n{credit}" if text else credit

    def _insert_post(self, account: dict, candidate: dict, image_urls: list) -> Optional[str]:
        post_id = str(uuid.uuid4())
        now_ms = int(datetime.now(IST).timestamp() * 1000)
        content = self._build_content(candidate["text"], candidate["channel"])
        doc = {
            "_id": post_id,
            "selfID": post_id,
            "content": content,
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
            "isYouTubeVideo": False,
            "videoUrl": None,
            "imageUrl": image_urls[0] if image_urls else None,
            "imageUrls": image_urls,
            "thumbnailUrl": None,
            "audioUrl": None,
            "audioBackgroundUrl": None,
            "isAudioBackgroundFromGallery": False,
            "_botGenerated": True,
            "_source": "youtube_community",
            "_sourceChannel": candidate["channel"],
            "_sourcePostId": candidate["post_id"],
            "_sourceUrl": candidate["source_url"],
        }
        self.db["posts"].insert_one(doc)
        logger.info(
            f"[SUCCESS] Inserted community post {post_id} for {account['name']} "
            f"({len(image_urls)} image(s), source {candidate['post_id']})"
        )
        return post_id

    # ---- health / alerts ----

    def _record_health(self, status: str, detail: str, extra: Optional[dict] = None) -> None:
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
        logger.error(f"[ALERT] YouTube community bot: {subject} — {detail}")
        if not self.alert_webhook:
            return
        try:
            requests.post(
                self.alert_webhook,
                json={"text": f":warning: YouTube community bot: {subject}\n{detail}"},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"[alert] webhook post failed: {e}")

    # ---- main ----

    def run(self, force_bot: Optional[str] = None, dry_run: bool = False) -> Optional[str]:
        state = self._load_state()
        bot_id = self._pick_eligible_bot(state, force_bot)
        if not bot_id:
            return None
        account = self.accounts[bot_id]
        logger.info(f"Selected bot: {bot_id} ({account['name']})")

        posted_ids = self._already_posted_ids(bot_id, state)
        candidates, stats, sess = self._collect_candidates(account, posted_ids)
        logger.info(
            f"[scan] channels={stats['channels']} ok={stats['channels_ok']} "
            f"candidates={len(candidates)} errors={len(stats['errors'])}"
        )
        if not candidates:
            if stats["blocked"] or (stats["channels"] and stats["channels_ok"] == 0):
                detail = (
                    f"bot={bot_id}: all {stats['channels']} channel scrapes failed "
                    f"(blocked={stats['blocked']}); errors: {'; '.join(stats['errors'][:5])}"
                )
                self._record_health("blocked", detail, {"bot_id": bot_id, "errors": stats["errors"][:10]})
                self._alert("community scrape blocked / failing", detail)
            else:
                logger.warning(f"no new community posts for {bot_id}")
                self._record_health(
                    "no_candidates",
                    f"bot={bot_id}: scrapes ok but no new posts with images",
                    {"bot_id": bot_id},
                )
            return None

        candidate = candidates[0]  # newest unseen (channels scanned newest-first)
        logger.info(
            f"Selected post {candidate['post_id']} from {candidate['channel']} "
            f"({candidate['published']}, {len(candidate['images'])} image(s))"
        )

        if dry_run:
            logger.info("[DRY-RUN] skipping image upload + DB insert")
            logger.info(f"  content preview: {self._build_content(candidate['text'], candidate['channel'])[:240]}")
            return candidate["post_id"]

        image_urls = self._download_and_upload_images(sess, candidate["post_id"], candidate["images"])
        if not image_urls:
            detail = f"bot={bot_id}: post {candidate['post_id']} had images but none uploaded"
            logger.error(detail)
            self._record_health("image_fail", detail, {"bot_id": bot_id})
            self._alert("image download/upload failed", detail)
            return None

        post_id = self._insert_post(account, candidate, image_urls)
        if not post_id:
            return None

        bot_state = state.get(bot_id, {})
        history = list(bot_state.get("last_post_ids", []))
        history.append(candidate["post_id"])
        history = history[-POST_HISTORY_LIMIT:]
        state[bot_id] = {
            "last_run_at": _now_ms(),
            "last_post_ids": history,
            "last_post_id": post_id,
        }
        self._save_state(state)
        self._record_health(
            "ok", f"bot={bot_id} posted {post_id}",
            {"bot_id": bot_id, "last_post_id": post_id},
        )
        return post_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bot", help="Force a specific bot id (ignores cooldown)")
    parser.add_argument("--dry-run", action="store_true", help="Do not upload/insert")
    args = parser.parse_args()

    gen = YouTubeCommunityPostGenerator()
    result = gen.run(force_bot=args.bot, dry_run=args.dry_run)
    if result:
        print(f"OK: {result}")
        return 0
    print("No post created")
    return 1


if __name__ == "__main__":
    sys.exit(main())
