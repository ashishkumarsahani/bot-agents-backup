"""
Bhagavad Gita Daily Verse Post Generator for DhyanApp.

Posts one Gita verse per day in strict sequence (Ch1V1 -> Ch18V78) from the
`scripture_verses` collection. The post body is always English; only the
infographic image's rendered text alternates English / Hindi day by day.

State is persisted in `gita_post_state.json` beside this script:
  - last_date, last_posted_chapter, last_posted_verse
  - next_image_language, last_post_id, completed
"""

import base64
import io
import os
import json
import logging
import random
import uuid
import sys
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional

from PIL import Image
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
STATE_FILE = Path(__file__).parent / "gita_post_state.json"
GITA_ACCOUNT_KEY = "gita"
GITA_SCRIPTURE_ID = "BhagwadGita"
GITA_SCRIPTURE_TITLE_FIELD = "BhagwadGita"  # value of scripture_verses.scriptureTitle


GITA_IMAGE_MODEL = "gpt-image-2"
GITA_IMAGE_SIZE = "1024x1024"
GITA_IMAGE_QUALITY = "medium"
DHYAN_LOGO_PATH = "/home/admin/dhyanapp-services/images/dhyan_logo.png"

from bot_personas_store import get_persona

from pymongo import MongoClient

from llm_usage_tracker import record_openai_response, record_usage
import boto3
from botocore.client import Config as BotoConfig

MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb://dhyanadmin:Dhyan%40Mongo2026!@localhost:27017/dhyanapp?authSource=admin&replicaSet=rs0",
)

_minio_host = os.getenv("MINIO_ENDPOINT", "localhost")
_minio_port = os.getenv("MINIO_PORT", "9000")
MINIO_ENDPOINT = _minio_host if ":" in _minio_host else f"{_minio_host}:{_minio_port}"
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "dhyanapp-recordings")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "https://storage.dhyanapp.org")


GITA_IMAGE_STYLES = [
    {
        "name": "Shloka Breakdown Infographic",
        "description": "Clean educational infographic style with clear section blocks for shloka, transliteration, meaning, and key takeaway, using icons, dividers, and balanced visual hierarchy",
        "colors": "ivory, saffron, deep blue, muted gold, and charcoal grey"
    },
    {
        "name": "Karma Yoga Infographic",
        "description": "Modern infographic poster style explaining concepts like karma, duty, detachment, and action through simple flow diagrams, symbolic icons, and structured content cards",
        "colors": "warm white, saffron orange, navy blue, soft gold, and earthy brown"
    },
    {
        "name": "Gita Concept Map",
        "description": "Knowledge-map infographic style with interconnected nodes for themes like dharma, bhakti, jnana, karma yoga, and moksha, arranged in a visually organized educational layout",
        "colors": "cream, maroon, indigo, gold, and sage green"
    },
    {
        "name": "Verse Meaning Card Infographic",
        "description": "Social-media-friendly infographic card with bold heading, short verse excerpt, concise meaning, and 3 to 4 key learning points in a neat structured layout",
        "colors": "off-white, deep maroon, peacock blue, saffron, and light beige"
    },
    {
        "name": "Krishna Teaching Diagram",
        "description": "Instructional infographic style showing Krishna's teachings through labeled sections, symbolic arrows, icons like chakra, lotus, and conch, and a clear teacher-student visual flow",
        "colors": "soft gold, royal blue, ivory, muted red, and bronze"
    },
    {
        "name": "Chapter Summary Infographic",
        "description": "Editorial infographic layout for summarizing one Gita chapter with title, central theme, core ideas, practical lesson, and highlighted keywords in clean visual blocks",
        "colors": "parchment beige, dark blue, saffron, maroon, and antique gold"
    },
    {
        "name": "Spiritual Comparison Infographic",
        "description": "Split-panel infographic style useful for comparing ideas such as action versus inaction, ego versus surrender, attachment versus detachment, with elegant labels and sacred accents",
        "colors": "ivory, deep teal, saffron, maroon, and subtle gold"
    },
    {
        "name": "Timeline Wisdom Infographic",
        "description": "Chronological infographic style for showing progression of spiritual understanding, inner conflict, guidance, realization, and peace using a refined sacred timeline layout",
        "colors": "warm white, dusty blue, saffron gold, rose brown, and charcoal"
    },
    {
        "name": "Minimal Data Card Infographic",
        "description": "Very clean modern infographic style with icon-led content cards, short insight bullets, high readability, and premium whitespace for educational Gita posts",
        "colors": "white, ash grey, saffron accent, navy blue, and muted gold"
    },
    {
        "name": "Wheel of Dharma Infographic",
        "description": "Circular infographic style inspired by dharma chakra, with each segment explaining one principle or lesson from the Gita in a visually structured sacred diagram",
        "colors": "deep blue, gold, cream, saffron, and reddish brown"
    },
    {
        "name": "Sacred Geometry Infographic",
        "description": "Yantra and mandala-inspired infographic style with concentric layouts, geometric grids holding the verse, meaning, and reflection in sacred symmetry",
        "colors": "deep maroon, antique gold, ivory, indigo, and burnt orange"
    },
    {
        "name": "Lotus Petal Infographic",
        "description": "Lotus-petal layout with each petal carrying a teaching point — verse, transliteration, meaning, key insight — around a central glowing emblem of Krishna or Om",
        "colors": "rose pink, jade green, ivory, saffron, and soft gold"
    },
    {
        "name": "Devotional Scroll Infographic",
        "description": "Aged parchment-scroll layout with ornamental top header, vertical sections for shloka and meaning, and decorative side borders evoking ancient manuscripts",
        "colors": "parchment beige, sepia brown, deep maroon, antique gold, and dusty navy"
    }
]


def _flip_image_language(lang: str) -> str:
    return "hindi" if lang == "english" else "english"


def _parse_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


class GitaVersePostGenerator:
    """Single-purpose generator that posts Bhagavad Gita verses sequentially."""

    def __init__(self):
        self.account = self._load_account()
        self.state = self._load_state()
        self._initialize_mongodb()
        self._initialize_minio()
        self._load_config_from_mongo()
        self.client = OpenAI(api_key=self.openai_api_key)
        self._load_watermark_logo()
        self._gita_scripture_cache: Optional[dict] = None
        self._gita_verses_cache: Optional[list] = None

    # ----- init helpers -----

    def _initialize_mongodb(self):
        try:
            self.mongo_client = MongoClient(
                MONGODB_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
            )
            self.mongo_client.admin.command("ping")
            self.db = self.mongo_client["dhyanapp"]
            logger.info("[SUCCESS] MongoDB initialized")
        except Exception as e:
            logger.error(f"[ERROR] Failed to initialize MongoDB: {e}")
            self.db = None

    def _load_watermark_logo(self):
        try:
            if os.path.exists(DHYAN_LOGO_PATH):
                self.watermark_logo = Image.open(DHYAN_LOGO_PATH).convert("RGBA")
                logger.info(f"Watermark logo loaded from {DHYAN_LOGO_PATH}")
            else:
                logger.warning(f"Watermark logo missing at {DHYAN_LOGO_PATH}")
                self.watermark_logo = None
        except Exception as e:
            logger.warning(f"Failed to load watermark logo: {e}")
            self.watermark_logo = None

    def _apply_watermark(self, image):
        if self.watermark_logo is None:
            return image
        try:
            if image.mode != "RGBA":
                image = image.convert("RGBA")
            w, h = image.size
            ww = int(w * 0.10)
            logo = self.watermark_logo.copy()
            ratio = logo.size[1] / logo.size[0]
            wh = int(ww * ratio)
            logo = logo.resize((ww, wh), Image.Resampling.LANCZOS)
            px, py = int(w * 0.02), int(h * 0.02)
            image.paste(logo, (w - ww - px, h - wh - py), logo)
            return image
        except Exception as e:
            logger.warning(f"Watermark apply failed: {e}")
            return image

    def _initialize_minio(self):
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

    def _load_config_from_mongo(self):
        self.secrets = {}
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        try:
            if self.db is not None:
                config_doc = self.db["config"].find_one({"_id": "secrets"})
                if config_doc:
                    self.secrets = config_doc
                    self.openai_api_key = config_doc.get("OPENAI_API_KEY", self.openai_api_key)
                    logger.info("[SUCCESS] Loaded config from MongoDB")
        except Exception as e:
            logger.error(f"[ERROR] Failed to load config from MongoDB: {e}")

    def _load_account(self) -> dict:
        try:
            persona = get_persona(GITA_ACCOUNT_KEY)
            if not persona:
                raise RuntimeError(f"Persona '{GITA_ACCOUNT_KEY}' not found in bot_personas")
            persona["account_key"] = GITA_ACCOUNT_KEY
            return persona
        except Exception as e:
            logger.error(f"[ERROR] Failed to load gita account: {e}")
            raise

    # ----- state -----

    def _default_state(self) -> dict:
        return {
            "last_date": None,
            "last_posted_chapter": 0,
            "last_posted_verse": 0,
            "last_checked_chapter": 0,
            "last_checked_verse": 0,
            "next_image_language": "english",
            "last_post_id": None,
            "completed": False,
        }

    def _load_state(self) -> dict:
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, "r") as f:
                    loaded = json.load(f)
                merged = self._default_state()
                merged.update(loaded)
                return merged
        except Exception as e:
            logger.error(f"[ERROR] Failed to load state: {e}")
        return self._default_state()

    def _save_state(self):
        try:
            tmp = STATE_FILE.with_suffix(".json.tmp")
            with open(tmp, "w") as f:
                json.dump(self.state, f, indent=2)
            os.replace(tmp, STATE_FILE)
        except Exception as e:
            logger.error(f"[ERROR] Failed to save state: {e}")

    # ----- data access -----

    def get_bhagavad_gita_scripture(self) -> Optional[dict]:
        if self._gita_scripture_cache is not None:
            return self._gita_scripture_cache
        if self.db is None:
            return None
        try:
            doc = self.db["scriptures"].find_one({"_id": GITA_SCRIPTURE_ID})
            self._gita_scripture_cache = doc
            return doc
        except Exception as e:
            logger.error(f"[ERROR] Failed to load Gita scripture metadata: {e}")
            return None

    def _all_gita_verses_sorted(self) -> list:
        """Fetch all Gita verses, drop malformed ones, sort by (chapter, verse)."""
        if self._gita_verses_cache is not None:
            return self._gita_verses_cache
        if self.db is None:
            return []
        try:
            cursor = self.db["scripture_verses"].find(
                {"scriptureTitle": GITA_SCRIPTURE_TITLE_FIELD}
            )
            verses = []
            for v in cursor:
                ch = _parse_int(v.get("chapterNumber"))
                vn = _parse_int(v.get("verseNumber"))
                if ch is None or vn is None:
                    continue
                v["_chapter_int"] = ch
                v["_verse_int"] = vn
                verses.append(v)
            verses.sort(key=lambda d: (d["_chapter_int"], d["_verse_int"]))
            self._gita_verses_cache = verses
            logger.info(f"Loaded {len(verses)} Gita verses from MongoDB")
            return verses
        except Exception as e:
            logger.error(f"[ERROR] Failed to load Gita verses: {e}")
            return []

    def get_next_gita_verse(self, after_chapter: int = None, after_verse: int = None) -> Optional[dict]:
        """Return the verse strictly after (after_chapter, after_verse). None if none left."""
        if after_chapter is None:
            after_chapter = int(self.state.get("last_posted_chapter") or 0)
        if after_verse is None:
            after_verse = int(self.state.get("last_posted_verse") or 0)
        verses = self._all_gita_verses_sorted()
        for v in verses:
            if (v["_chapter_int"], v["_verse_int"]) > (after_chapter, after_verse):
                return v
        return None

    def find_verse(self, chapter: int, verse: int) -> Optional[dict]:
        for v in self._all_gita_verses_sorted():
            if v["_chapter_int"] == chapter and v["_verse_int"] == verse:
                return v
        return None

    # ----- LLM generation -----

    def generate_post_from_verse(self, verse: dict) -> Optional[dict]:
        """Always-English post body from a Gita verse, written in the gita persona voice."""
        chapter = verse["_chapter_int"]
        verse_num = verse["_verse_int"]
        sanskrit = (verse.get("verseText") or "").strip()
        translation = (verse.get("translationText") or "").strip()
        commentary = (verse.get("commentary") or "").strip()[:1200]

        persona = (self.account.get("persona") or "").strip()
        conv_style = (self.account.get("conversational_style") or "").strip()
        translation_author = (verse.get("translationAuthor") or "Shri Purohit Swami").strip()
        commentary_author = (verse.get("commentaryAuthor") or "Swami Sivananda").strip()

        deeplink = f"https://dhyanapp.org/scriptureChaptersListScreen/{GITA_SCRIPTURE_ID}"

        prompt = f"""You are writing a daily Bhagavad Gita post in the voice of a devoted student of the Gita.

Persona: {persona}
Voice: {conv_style}

Today's verse — Bhagavad Gita, Chapter {chapter}, Verse {verse_num}.

Sanskrit (Devanagari):
{sanskrit}

English translation (by {translation_author}):
{translation}

Commentary excerpt (by {commentary_author}) — this is your PRIMARY source for the reflection. Do not invent ideas outside it; draw the takeaway from the commentary's own line of thought:
{commentary}

Write the post body in ENGLISH only, 130-200 words, in this exact structure:

1. Header line, on its own: "Bhagavad Gita · Chapter {chapter} · Verse {verse_num}"
2. The full Devanagari shloka exactly as given above, on its own lines.
3. The translation rendered in clear modern English, 1-2 sentences. You may smooth the wording but do not change meaning.
4. A reflection of 3-5 sentences, grounded in the commentary above. Write in first person ("I", "we", "us"). Quietly devotional, never preachy. May reference Krishna or Arjuna by name where natural. Do NOT use cliché phrases like "fast-paced lives", "journey not the destination", or generic self-help framing.
5. End with a single short contemplative question or a soft devotional closer (one short line). Examples: "Where in my day can I act without grasping?" or "जय श्री कृष्ण."
6. On a new line after the closing, write a natural invitation to read the chapter in the DhyanApp — for example: "Explore this chapter: [Bhagavad Gita Chapter {chapter}]({deeplink})" or "Read this in DhyanApp: [Chapter {chapter} · Bhagavad Gita]({deeplink})". Vary the phrasing naturally. Use the exact URL verbatim: {deeplink}. Do not add any other links.

Do NOT include any IAST or Latin-script transliteration of the Sanskrit. Devanagari shloka and English translation only.

Return ONLY valid JSON:
{{
  "content": "the full post body exactly as structured above, with real newlines between sections",
  "saying": "a 3-6 word evocative title rooted in this verse (not generic)",
  "description": "a 15-25 word summary of THIS verse's specific teaching",
  "source_topic": "Bhagavad Gita Chapter {chapter} Verse {verse_num}"
}}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You write devotional, commentary-grounded English reflections on Bhagavad Gita verses in a warm first-person voice. Always return valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
                max_tokens=1100,
            )
            record_openai_response(response, service="gita_post.from_verse")
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            return json.loads(content)
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate post from verse: {e}")
            return None

    def detect_krishna_verses_batch(self, verses: list) -> list:
        """
        Single LLM call: send up to KRISHNA_SEARCH_LOOKAHEAD verses and identify which are spoken by Krishna.
        Returns a list of dicts, one per input verse:
          [{"index": 0, "chapter": 1, "verse": 1, "speaker": "Sanjaya", "is_krishna_speaking": false, "reason": "..."}, ...]
        Returns [] on total failure.
        """
        if not verses:
            return []

        verse_blocks = []
        for i, v in enumerate(verses):
            ch = v["_chapter_int"]
            vn = v["_verse_int"]
            sanskrit = (v.get("verseText") or "").strip()
            translation = (v.get("translationText") or "").strip()
            commentary = (v.get("commentary") or "").strip()[:200]
            verse_blocks.append(
                f"[{i}] Chapter {ch}, Verse {vn}\n"
                f"Sanskrit: {sanskrit}\n"
                f"Translation: {translation}\n"
                f"Commentary excerpt: {commentary}"
            )

        prompt = (
            "You are a Bhagavad Gita scholar. Below are verses from the Bhagavad Gita. "
            "The Gita has multiple speakers: Lord Krishna, Arjuna, Sanjaya (narrator), "
            "Dhritarashtra, and occasionally others.\n\n"
            "For EACH verse, identify who is speaking and whether it is Lord Krishna.\n\n"
            "CRITICAL RULE: 'is_krishna_speaking' must be true ONLY if Lord Krishna himself "
            "is the one UTTERING these words as direct speech. If Sanjaya, Arjuna, "
            "Dhritarashtra, or any narrator is speaking — even if they are describing "
            "Krishna's actions or quoting him — set is_krishna_speaking to false. "
            "A verse where Sanjaya says 'Krishna blew his conch' is NOT Krishna speaking.\n\n"
            + "\n\n".join(verse_blocks)
            + "\n\nReturn ONLY a valid JSON array with one object per verse, in the same order:\n"
            '[\n'
            '  {"index": 0, "chapter": <int>, "verse": <int>, "speaker": "<name>", '
            '"is_krishna_speaking": <true|false>, "reason": "<one sentence>"},\n'
            "  ...\n"
            "]"
        )

        for attempt in range(1, 3):
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a Bhagavad Gita scholar. Always return valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=2000,
                )
                record_openai_response(response, service="gita_post.detect_speaker_batch")
                content = response.choices[0].message.content.strip()
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                    content = content.strip()
                return json.loads(content)
            except Exception as e:
                logger.warning(f"[SPEAKER-DETECT] Attempt {attempt}/2 failed: {e}")

        logger.error("[SPEAKER-DETECT] All retries exhausted for batch call")
        return []

    def _fetch_verses_after(self, after_chapter: int, after_verse: int, limit: int) -> list:
        """
        Fetch up to `limit` verses strictly after (after_chapter, after_verse) using
        an aggregation pipeline so numeric sort works even when chapterNumber/verseNumber
        are stored as strings in MongoDB.
        """
        if self.db is None:
            return []
        try:
            pipeline = [
                {"$match": {"scriptureTitle": GITA_SCRIPTURE_TITLE_FIELD}},
                {"$addFields": {
                    "_chapter_int": {"$toInt": "$chapterNumber"},
                    "_verse_int":   {"$toInt": "$verseNumber"},
                }},
                {"$match": {"$expr": {"$or": [
                    {"$gt": ["$_chapter_int", after_chapter]},
                    {"$and": [
                        {"$eq": ["$_chapter_int", after_chapter]},
                        {"$gt": ["$_verse_int", after_verse]},
                    ]},
                ]}}},
                {"$sort": {"_chapter_int": 1, "_verse_int": 1}},
                {"$limit": limit},
            ]
            return list(self.db["scripture_verses"].aggregate(pipeline))
        except Exception as e:
            logger.error(f"[FETCH] MongoDB aggregation failed: {e}")
            return []

    def find_next_krishna_verse(
        self,
        after_chapter: int,
        after_verse: int,
    ) -> tuple:
        """
        Stage 1: fetch and check the single next verse from DB. If Krishna, return it.
        Stage 2+: fetch rolling batches of 5 from DB until a Krishna verse is found.
        Returns (verse_to_post, last_checked_chapter, last_checked_verse).
        Returns (None, after_chapter, after_verse) if nothing found.
        """
        BATCH_SIZE = 5

        # Stage 1: check the single next verse
        first_batch = self._fetch_verses_after(after_chapter, after_verse, limit=1)
        if not first_batch:
            logger.info(f"[SEARCH] No verses found after Ch{after_chapter}V{after_verse}")
            return None, after_chapter, after_verse

        first_verse = first_batch[0]
        first_ch, first_v = first_verse["_chapter_int"], first_verse["_verse_int"]
        logger.info(f"[SEARCH] Stage 1 — checking Ch{first_ch}V{first_v} individually")
        stage1 = self.detect_krishna_verses_batch([first_verse])
        if stage1:
            entry = stage1[0]
            speaker = entry.get("speaker", "Unknown")
            is_krishna_flag = entry.get("is_krishna_speaking", False)
            reason = entry.get("reason", "")
            is_krishna = is_krishna_flag and "krishna" in speaker.lower()
            accepted = "✓ ACCEPTED" if is_krishna else "✗ REJECTED"
            logger.info(f"[SEARCH] Ch{first_ch}V{first_v} | Speaker: {speaker} | {accepted} | {reason}")
            if is_krishna:
                logger.info(f"[SEARCH] Krishna verse found in Stage 1: Ch{first_ch}V{first_v}")
                return first_verse, first_ch, first_v
        else:
            logger.warning(f"[SEARCH] Stage 1 LLM call failed for Ch{first_ch}V{first_v}")

        # Stage 2+: rolling batches of 5, starting after the first verse
        current_ch, current_v = first_ch, first_v
        while True:
            batch = self._fetch_verses_after(current_ch, current_v, limit=BATCH_SIZE)
            if not batch:
                break

            start = batch[0]
            end = batch[-1]
            last_ch, last_v = end["_chapter_int"], end["_verse_int"]
            logger.info(
                f"[SEARCH] Checking batch Ch{start['_chapter_int']}V{start['_verse_int']}"
                f" → Ch{last_ch}V{last_v}"
            )

            results = self.detect_krishna_verses_batch(batch)
            if results:
                verse_index = {(v["_chapter_int"], v["_verse_int"]): v for v in batch}
                for entry in results:
                    ch = entry.get("chapter")
                    vn = entry.get("verse")
                    speaker = entry.get("speaker", "Unknown")
                    is_krishna_flag = entry.get("is_krishna_speaking", False)
                    reason = entry.get("reason", "")
                    is_krishna = is_krishna_flag and "krishna" in speaker.lower()
                    accepted = "✓ ACCEPTED" if is_krishna else "✗ REJECTED"
                    logger.info(f"[SEARCH] Ch{ch}V{vn} | Speaker: {speaker} | {accepted} | {reason}")
                    if is_krishna:
                        verse = verse_index.get((ch, vn))
                        if verse:
                            logger.info(f"[SEARCH] Krishna verse found: Ch{ch}V{vn}")
                            return verse, ch, vn
            else:
                logger.warning(f"[SEARCH] LLM call failed for batch ending Ch{last_ch}V{last_v}")

            current_ch, current_v = last_ch, last_v

        logger.info(f"[SEARCH] No Krishna verse found in remaining verses after Ch{after_chapter}V{after_verse}")
        return None, after_chapter, after_verse

    def generate_infographic_assets(self, verse: dict, post_data: dict, image_language: str) -> dict:
        """Produce label/headline/takeaway strings for the infographic in the chosen language."""
        chapter = verse["_chapter_int"]
        verse_num = verse["_verse_int"]
        translation = (verse.get("translationText") or "").strip()
        saying = post_data.get("saying", "")

        if image_language == "hindi":
            lang_instruction = (
                "All three strings MUST be in Hindi using Devanagari script. "
                "Do not use English words except for the digits in the chapter/verse label."
            )
            label_default = f"भगवद् गीता · अध्याय {chapter} · श्लोक {verse_num}"
        else:
            lang_instruction = "All three strings MUST be in clear, simple English."
            label_default = f"Bhagavad Gita · Chapter {chapter} · Verse {verse_num}"

        prompt = f"""You are preparing TEXT that will be rendered onto a square infographic poster
for Bhagavad Gita Chapter {chapter}, Verse {verse_num}.

English translation (reference):
{translation}

Post headline (reference): {saying}

{lang_instruction}

Return ONLY valid JSON with exactly these three keys:
{{
  "label": "the chapter/verse reference label, e.g. '{label_default}'",
  "headline": "a 3 to 6 word evocative title for this verse",
  "takeaway": "the verse's core teaching in 12-20 words, plain and readable"
}}

Keep text short enough to render cleanly on a poster. No quotation marks inside values."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You craft concise poster text for spiritual infographics. Always return valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
                max_tokens=300,
            )
            record_openai_response(response, service="gita_post.infographic_assets")
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            data = json.loads(content)
            return {
                "label": data.get("label") or label_default,
                "headline": data.get("headline") or saying or ("भगवद् गीता" if image_language == "hindi" else "Bhagavad Gita"),
                "takeaway": data.get("takeaway") or "",
            }
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate infographic assets: {e}")
            return {
                "label": label_default,
                "headline": saying or ("भगवद् गीता" if image_language == "hindi" else "Bhagavad Gita"),
                "takeaway": (translation[:120] if image_language == "english" else ""),
            }

    def generate_infographic_prompt(self, verse: dict, assets: dict, image_language: str,
                                    style: dict) -> str:
        label = assets["label"].replace('"', "'")
        headline = assets["headline"].replace('"', "'")
        takeaway = assets["takeaway"].replace('"', "'")

        raw_shloka = (verse.get("verseText") or "").strip()
        shloka_text = raw_shloka.replace('"', "'")

        translation = (verse.get("translationText") or "").strip()
        translation_clean = translation.replace('"', "'")

        verse_theme = headline
        if takeaway:
            verse_theme += f". {takeaway}"
        if translation:
            verse_theme += f" ({translation[:160].rstrip()})"

        script_phrase = (
            "elegant Devanagari Hindi typography"
            if image_language == "hindi"
            else "clean modern English typography"
        )

        return (
            f"A premium square Bhagavad Gita infographic poster rendered in the "
            f"\"{style['name']}\" visual style: {style['description']}. "
            f"Color palette: {style['colors']}. "

            f"VERSE THEME for visual imagery: {verse_theme}. "
            f"All visual elements — background scenes, icons, symbolic illustrations, decorative accents — "
            f"must directly reflect this specific verse's teaching. "
            f"Do NOT fall back to generic lotus, Om symbol, or mandala imagery unless they directly relate to this verse. "
            f"Choose scene, characters, and symbols that are uniquely meaningful for this verse's message. "

            f"Create the poster in a clear infographic format, similar to a spiritual flow-chart poster. "
            f"The content should be divided into visually separated sections/cards/steps, arranged in a clean flow-based layout. "
            f"Use numbered cards, connected arrows, icons, symbolic illustrations, or circular flow elements to show progression. "
            f"The design should feel informative, structured, and easy to understand at first glance, not just decorative artwork. "

            f"Balance image and text evenly. "

            f"On-image text must be minimal, prominent, and readable, rendered in {script_phrase}. "
            f"Include exactly these content elements: "
            f"(1) a small chapter/verse label reading {label}, "
            f"(2) a short headline reading {headline}, "
            f"(3) the full Sanskrit shloka reading {shloka_text}, "
            f"(4) a takeaway line reading {takeaway}, "
            f"(5) the verse meaning reading {translation_clean}. "

            f"Present the meaning in infographic style using visual sections, icons, arrows, or step cards, "
            f"but do not add long paragraphs, bullet lists, comparison tables, captions, or extra labels. "
            f"The poster should look like a premium spiritual infographic poster, not a dense study sheet and not a plain devotional painting. "

            f"Use clear visual hierarchy: small label at top, large headline, full shloka in a dedicated card, takeaway highlighted, and meaning below. "
            f"Use subtle dividers, elegant borders, glowing accents, and enough breathing space. "
            f"Keep the layout clean, premium, devotional, meditative, and visually polished. "

            f"Leave a small clean empty area in the lower-right corner free of text and primary visual elements "
            f"so a brand logo can be placed there without overlap. "

            f"Sharp readable lettering, balanced editorial poster quality, no clutter, no extra words."
        )

    # ----- image -----

    def generate_image(self, prompt: str, post_id: str) -> Optional[str]:
        if not self.s3_client:
            logger.error("[ERROR] MinIO not initialized")
            return None
        try:
            response = self.client.images.generate(
                model=GITA_IMAGE_MODEL,
                prompt=prompt,
                size=GITA_IMAGE_SIZE,
                quality=GITA_IMAGE_QUALITY,
                n=1,
            )
            _img_price = {"low": 0.01, "medium": 0.04, "high": 0.17, "auto": 0.04}
            try:
                record_usage(
                    "openai", GITA_IMAGE_MODEL, "gita_post.generate_image",
                    images=1,
                    cost_usd=_img_price.get(GITA_IMAGE_QUALITY, 0.04),
                    meta={"size": GITA_IMAGE_SIZE, "quality": GITA_IMAGE_QUALITY},
                )
            except Exception as track_err:
                logger.warning(f"Failed to record image usage: {track_err}")

            raw_bytes = base64.b64decode(response.data[0].b64_json)
            image = Image.open(io.BytesIO(raw_bytes))
            image = self._apply_watermark(image)
            buf = io.BytesIO()
            image.save(buf, format="WEBP", lossless=True)
            image_bytes = buf.getvalue()

            object_key = f"Posts/images/bot_gita/{post_id}.webp"
            self.s3_client.put_object(
                Bucket=MINIO_BUCKET,
                Key=object_key,
                Body=image_bytes,
                ContentType="image/webp",
            )
            base_url = MINIO_PUBLIC_URL if MINIO_PUBLIC_URL else f"http://{MINIO_ENDPOINT}"
            public_url = f"{base_url}/{MINIO_BUCKET}/{object_key}"
            logger.info("[SUCCESS] Image uploaded to MinIO")
            return public_url
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate/upload image: {e}")
            return None

    # ----- DB write -----

    def push_post_to_db(self, post_data: dict, image_url: Optional[str], post_id: str,
                        verse: dict, image_language: str, image_style: str) -> Optional[str]:
        if self.db is None:
            logger.error("[ERROR] MongoDB not connected")
            return None

        created_at_ms = int(datetime.now(IST).timestamp() * 1000)

        doc_data = {
            "audioBackgroundUrl": None,
            "audioUrl": None,
            "commentCount": 0,
            "composition": "SEPARATE_CONTENT",
            "content": post_data["content"],
            "createdAt": created_at_ms,
            "createdBy": self.account["user_id"],
            "creatorName": self.account["name"],
            "deleted": False,
            "deletedAt": None,
            "deletedByAdmin": False,
            "description": f"{post_data.get('saying', '')} - {post_data.get('description', '')}",
            "globallyHidden": False,
            "imageUrl": image_url,
            "imageUrls": [image_url] if image_url else [],
            "isAudioBackgroundFromGallery": False,
            "isLikedByCurrentUser": None,
            "isReportedByCurrentUserStatus": None,
            "isViewedByCurrentUser": None,
            "isYouTubeVideo": False,
            "lastEditedAt": None,
            "likeCount": 0,
            "location": "",
            "selfID": post_id,
            "videoUrl": None,
            "viewCount": 0,
            # Bot metadata
            "_botGenerated": True,
            "_generatorType": "gita_daily_verse",
            "_language": "english",
            "_imageLanguage": image_language,
            "_scripture": "Bhagavad Gita",
            "_chapter": verse["_chapter_int"],
            "_verse": verse["_verse_int"],
            "_imageStyle": image_style,
        }

        try:
            doc_data["_id"] = post_id
            self.db["posts"].update_one(
                {"_id": post_id},
                {"$set": doc_data},
                upsert=True,
            )
            logger.info(f"[SUCCESS] Post pushed to MongoDB: {post_id}")
            return post_id
        except Exception as e:
            logger.error(f"[ERROR] Failed to push post: {e}")
            return None

    # ----- orchestration -----

    def generate_and_post(self, *, advance_state: bool = True,
                          override_image_lang: Optional[str] = None,
                          override_ch_v: Optional[tuple] = None) -> Optional[str]:
        if override_ch_v is not None:
            ch, vn = override_ch_v
            verse = self.find_verse(ch, vn)
            if verse is None:
                logger.error(f"[ERROR] Verse Ch{ch}V{vn} not found")
                return None
        else:
            verse = self.get_next_gita_verse()
            if verse is None:
                logger.info("[DONE] Gita sequence completed. No more verses to post.")
                if advance_state:
                    self.state["completed"] = True
                    self._save_state()
                return None

        chapter = verse["_chapter_int"]
        verse_num = verse["_verse_int"]
        image_language = override_image_lang or self.state.get("next_image_language", "english")

        logger.info(f"\n{'='*60}")
        logger.info(f"GENERATING GITA POST: Ch{chapter} V{verse_num} (image: {image_language})")
        logger.info(f"{'='*60}")

        post_data = self.generate_post_from_verse(verse)
        if not post_data:
            logger.error("Failed to generate post content")
            return None
        logger.info(f"Saying: {post_data.get('saying', 'N/A')}")

        post_id = str(uuid.uuid4())

        assets = self.generate_infographic_assets(verse, post_data, image_language)
        logger.info(f"Infographic headline: {assets.get('headline', '')}")

        selected_style = random.choice(GITA_IMAGE_STYLES)
        logger.info(f"Image style: {selected_style['name']}")

        image_prompt = self.generate_infographic_prompt(verse, assets, image_language, selected_style)
        logger.info("Generating infographic image...")
        image_url = self.generate_image(image_prompt, post_id)
        if image_url:
            logger.info(f"Image URL: {image_url[:80]}...")
        else:
            logger.warning("Posting without image")

        doc_id = self.push_post_to_db(post_data, image_url, post_id, verse, image_language,
                                       selected_style["name"])
        if not doc_id:
            return None

        if advance_state:
            self.state["last_date"] = date.today().isoformat()
            self.state["last_posted_chapter"] = chapter
            self.state["last_posted_verse"] = verse_num
            self.state["next_image_language"] = _flip_image_language(image_language)
            self.state["last_post_id"] = doc_id
            self.state["completed"] = False
            self._save_state()
            logger.info(f"State advanced. Next image language: {self.state['next_image_language']}")

        logger.info(f"[SUCCESS] Gita post created: {doc_id}")
        return doc_id

    def run_daily_post(self) -> Optional[str]:
        today_iso = date.today().isoformat()
        logger.info("=" * 60)
        logger.info("GITA DAILY VERSE POST GENERATOR")
        logger.info(f"Date: {today_iso}")
        logger.info(f"Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
        logger.info("=" * 60)

        if self.state.get("completed"):
            logger.info("Gita sequence already completed. Use --reset-state to restart.")
            return None

        if self.state.get("last_date") == today_iso:
            logger.info(f"Already posted today ({today_iso}). Skipping.")
            return None

        last_posted_ch = int(self.state.get("last_posted_chapter") or 0)
        last_posted_v = int(self.state.get("last_posted_verse") or 0)
        last_checked_ch = int(self.state.get("last_checked_chapter") or last_posted_ch)
        last_checked_v = int(self.state.get("last_checked_verse") or last_posted_v)

        if (last_checked_ch, last_checked_v) > (last_posted_ch, last_posted_v):
            search_from_ch, search_from_v = last_checked_ch, last_checked_v
            logger.info(f"[SEARCH] Resuming from last checked position: Ch{search_from_ch}V{search_from_v}")
        else:
            search_from_ch, search_from_v = last_posted_ch, last_posted_v
            logger.info(f"[SEARCH] Starting from last posted position: Ch{search_from_ch}V{search_from_v}")

        verse, last_ch, last_v = self.find_next_krishna_verse(search_from_ch, search_from_v)

        self.state["last_checked_chapter"] = last_ch
        self.state["last_checked_verse"] = last_v

        if verse is None:
            logger.info(
                f"[SKIP] No Krishna verse found in lookahead. "
                f"Saving search position Ch{last_ch}V{last_v}. No post today."
            )
            self._save_state()
            return None

        return self.generate_and_post(
            advance_state=True,
            override_ch_v=(verse["_chapter_int"], verse["_verse_int"]),
        )


# Singleton
_generator: Optional[GitaVersePostGenerator] = None


def get_gita_post_generator() -> GitaVersePostGenerator:
    global _generator
    if _generator is None:
        _generator = GitaVersePostGenerator()
    return _generator


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Bhagavad Gita Daily Verse Post Generator")
    parser.add_argument("--run-now", action="store_true", help="Run the daily post (idempotent per day)")
    parser.add_argument("--test", action="store_true", help="Generate a post without advancing state")
    parser.add_argument("--advance", action="store_true",
                        help="With --chapter/--verse or --image-language: also advance state")
    parser.add_argument("--show-state", action="store_true", help="Print current state and next verse")
    parser.add_argument("--reset-state", action="store_true", help="Reset state to defaults (requires --yes-i-am-sure)")
    parser.add_argument("--yes-i-am-sure", action="store_true", help="Confirmation for --reset-state")
    parser.add_argument("--chapter", type=int, help="Override chapter (with --test or --advance)")
    parser.add_argument("--verse", type=int, help="Override verse (with --test or --advance)")
    parser.add_argument("--image-language", choices=["english", "hindi"],
                        help="Override infographic language for this run")

    args = parser.parse_args()

    if args.reset_state:
        if not args.yes_i_am_sure:
            print("[ABORT] --reset-state requires --yes-i-am-sure")
            sys.exit(1)
        gen = get_gita_post_generator()
        gen.state = gen._default_state()
        gen._save_state()
        print("[OK] State reset to defaults.")
        sys.exit(0)

    if args.show_state:
        gen = get_gita_post_generator()
        print("\n" + "=" * 60)
        print("GITA POST STATE")
        print("=" * 60)
        print(json.dumps(gen.state, indent=2))
        last_posted_ch = int(gen.state.get("last_posted_chapter") or 0)
        last_posted_v = int(gen.state.get("last_posted_verse") or 0)
        last_checked_ch = int(gen.state.get("last_checked_chapter") or last_posted_ch)
        last_checked_v = int(gen.state.get("last_checked_verse") or last_posted_v)
        print(f"\nLast posted:  Ch{last_posted_ch} V{last_posted_v}")
        print(f"Last checked: Ch{last_checked_ch} V{last_checked_v}")
        nxt = gen.get_next_gita_verse(last_checked_ch, last_checked_v)
        if nxt:
            print(f"Next search start: Ch{nxt['_chapter_int']} V{nxt['_verse_int']}")
            print(f"Next image language: {gen.state.get('next_image_language')}")
        else:
            print("\nNo more verses to search (sequence complete).")
        sys.exit(0)

    if args.test or ((args.chapter or args.verse) and not args.advance):
        gen = get_gita_post_generator()
        override_ch_v = None
        if args.chapter is not None and args.verse is not None:
            override_ch_v = (args.chapter, args.verse)
        elif args.chapter is not None or args.verse is not None:
            print("[ERROR] --chapter and --verse must be provided together")
            sys.exit(1)
        post_id = gen.generate_and_post(
            advance_state=False,
            override_image_lang=args.image_language,
            override_ch_v=override_ch_v,
        )
        if post_id:
            print(f"\n[SUCCESS] Created test post (state NOT advanced): {post_id}")
        else:
            print("\n[ERROR] Failed to create test post")
        sys.exit(0 if post_id else 1)

    if args.advance and (args.chapter is not None or args.image_language is not None):
        gen = get_gita_post_generator()
        override_ch_v = None
        if args.chapter is not None and args.verse is not None:
            override_ch_v = (args.chapter, args.verse)
        elif args.chapter is not None or args.verse is not None:
            print("[ERROR] --chapter and --verse must be provided together")
            sys.exit(1)
        post_id = gen.generate_and_post(
            advance_state=True,
            override_image_lang=args.image_language,
            override_ch_v=override_ch_v,
        )
        sys.exit(0 if post_id else 1)

    if args.run_now:
        gen = get_gita_post_generator()
        post_id = gen.run_daily_post()
        if post_id:
            print(f"\nCreated post: {post_id}")
        sys.exit(0)

    parser.print_help()