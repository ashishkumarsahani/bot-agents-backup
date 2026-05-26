"""
Scripture Daily Post Generator for DhyanApp — Aditya Karn Bot.

Posts one verse per run from non-Gita Hindu scriptures (Upanishads, Valmiki Ramayana,
Yoga Sutras, Bhakti Sutras, etc.), selected randomly from scripture_verses collection.
Posts on alternate days only (skips if last post was < 2 days ago).

Two-level LLM pipeline:
  Level 1 (temp=0.1): classify scripture_type from verse content
  Level 2 (temp=0.8): generate post in tone matching scripture_type

State persisted in scripture_post_state.json beside this script:
  last_date, last_post_id, posted_verse_ids
"""

import base64
import io
import os
import json
import logging
import random
import uuid
import sys
import urllib.parse
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
STATE_FILE = Path(__file__).parent / "scripture_post_state.json"
SCRIPTURE_ACCOUNT_KEY = "adityakarn"
SCRIPTURE_BOT_USER_ID = "UQqox6yuW5f8mylYoImiHwSxPm52"

SCRIPTURE_IMAGE_MODEL = "gpt-image-2"
SCRIPTURE_IMAGE_SIZE = "1024x1024"
SCRIPTURE_IMAGE_QUALITY = "medium"
DHYAN_LOGO_PATH = "/home/admin/dhyanapp-services/images/dhyan_logo.png"

# Bhagavad Gita in all variants must never be posted by this bot
EXCLUDED_SCRIPTURE_TITLES = {
    "BhagwadGita",
    "श्रीमद्भगवद्गीता ( हिंदी व्याख्या )",
    "aG7FtUyPPTdi3sXUP4Sh",  # unidentified, excluded for safety
}

VALID_SCRIPTURE_TYPES = {"narrative", "philosophical", "devotional", "mantra", "wisdom"}

SCRIPTURE_IMAGE_STYLES = [
    # --- Art-style infographics: traditional Indian art aesthetic + structured layout ---
    {
        "name": "Tanjore Gold Infographic",
        "description": "Structured content cards rendered in Tanjore painting style with gold-leaf borders, jewel-tone panels, and divine motifs as section dividers in an educational poster layout",
        "colors": "gold, ruby red, deep green, royal blue, and ivory on rich dark backgrounds"
    },
    {
        "name": "Rajasthani Miniature Infographic",
        "description": "Flat-perspective infographic with ornate Rajasthani miniature-style borders, peacock and floral accents, content arranged in richly decorated panels inspired by royal court art",
        "colors": "rich reds, deep blues, saffron, emerald greens, and gold borders"
    },
    {
        "name": "Pattachitra Scroll Infographic",
        "description": "Scroll-style infographic with bold Pattachitra outlines framing verse, meaning, and insight in distinct sections with mythological motifs and intricate patterned borders",
        "colors": "red, yellow, indigo blue, white, and black with patterned scroll borders"
    },
    {
        "name": "Madhubani Wisdom Card",
        "description": "Infographic with Madhubani geometric borders and folk nature motifs — fish, lotus, peacock — framing structured content blocks in traditional Bihar folk art style",
        "colors": "bright primary colors, red, yellow, blue, green on cream or white background"
    },
    {
        "name": "Temple Fresco Infographic",
        "description": "Stone-texture background with fresco-style content panels and carved-look dividers, like sacred teachings inscribed directly onto ancient temple walls in structured blocks",
        "colors": "sandstone beige, granite grey, ochre, terracotta, and warm amber lighting"
    },
    {
        "name": "Warli Flow Infographic",
        "description": "Infographic using Warli geometric stick-figure icons and circular tribal motifs to illustrate the flow and progression of a teaching in structured steps",
        "colors": "white figures and patterns on deep terracotta brown or russet red background"
    },
    # --- Pure infographic layouts: clean structured, sacred feel ---
    {
        "name": "Verse Breakdown Card",
        "description": "Clean educational infographic with clearly separated sections for original verse, transliteration, meaning, and key insight using elegant dividers and balanced visual hierarchy",
        "colors": "ivory, saffron, deep blue, antique gold, and charcoal"
    },
    {
        "name": "Scripture Story Flow",
        "description": "Narrative panel infographic showing sequence of events or teachings in 3 to 4 connected visual steps with icons, arrows, and brief labels in a story-flow layout",
        "colors": "warm parchment, maroon, saffron, forest green, and earthy brown"
    },
    {
        "name": "Teacher-Student Dialogue",
        "description": "Split-panel layout showing the seeker's question and the sage's answer with symbolic icons for each voice in a structured sacred teaching dialogue format",
        "colors": "cream, deep teal, saffron, dusty rose, and muted gold"
    },
    {
        "name": "Concept Tree Infographic",
        "description": "Branching tree diagram rooting one central teaching into sub-ideas, ideal for philosophical texts, with elegant labeled nodes and flowing connecting lines",
        "colors": "ivory, indigo, sage green, antique gold, and terracotta"
    },
    {
        "name": "Mantra Meaning Breakdown",
        "description": "Word-by-word infographic dissecting a verse or mantra into component meanings with phonetic and semantic labels in clean structured sections",
        "colors": "deep maroon, ivory, saffron, lotus pink, and soft gold"
    },
    {
        "name": "Wisdom Comparison Card",
        "description": "Split layout contrasting two states or ideas such as ignorance versus knowledge or bondage versus liberation with elegant sacred labels and balanced panels",
        "colors": "ivory, deep teal, saffron, maroon, and subtle gold"
    },
    {
        "name": "Sacred Symbol Explainer",
        "description": "Infographic built around a central sacred symbol — Om, lotus, trishul, or chakra — with meaning-labeled sections radiating outward in a structured spiritual layout",
        "colors": "deep indigo, gold, cream, burnt orange, and dusty white"
    },
    {
        "name": "Pillar of Teaching Infographic",
        "description": "Vertical stacked-block layout with each block holding one principle or step, like pillars of wisdom building upward in a structured sacred poster design",
        "colors": "sandstone beige, maroon, saffron, ivory, and bronze"
    },
    {
        "name": "Lotus Wisdom Infographic",
        "description": "Lotus petal layout with each petal holding a teaching point from the passage, centered on a glowing Om or deity emblem in an elegant sacred structured design",
        "colors": "rose pink, jade green, ivory, saffron, and soft gold"
    },
    {
        "name": "Devotional Scroll Card",
        "description": "Ornate parchment scroll layout with header, verse in a dedicated panel, meaning below, and decorative side borders evoking ancient sacred manuscripts and palm-leaf texts",
        "colors": "parchment beige, sepia brown, deep maroon, antique gold, and dusty navy"
    },
    {
        "name": "Wheel of Dharma Infographic",
        "description": "Circular spoke diagram with each segment holding one principle or teaching from the passage, arranged in a visually structured sacred wheel or chakra layout",
        "colors": "deep blue, gold, cream, saffron, and reddish brown"
    },
    {
        "name": "Ancient Manuscript Grid",
        "description": "Editorial grid infographic evoking aged palm-leaf manuscripts with structured content blocks, Sanskrit script accents, and a subtle aged texture throughout",
        "colors": "aged ochre, sepia, dark maroon, faded gold, and charcoal"
    },
]

SCRIPTURE_TYPE_CLOSERS = {
    "narrative": ["जय श्री राम", "Where in this story do I find myself today?", "हर हर महादेव", "राम राम"],
    "philosophical": ["ॐ तत् सत्", "What does this passage ask of me right now?", "सोऽहम्", "ॐ"],
    "devotional": ["जय श्री कृष्ण", "ॐ नमः शिवाय", "हरि ॐ", "जय माँ"],
    "mantra": ["ॐ", "ॐ शान्तिः शान्तिः शान्तिः", "May this mantra find its home in your heart."],
    "wisdom": ["What does this wisdom ask of me today?", "सत्यमेव जयते", "How can I live this teaching today?"],
}

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


class ScripturePostGenerator:
    """Generates posts from non-Gita Hindu scriptures, posting on alternate days."""

    def __init__(self):
        self.account = self._load_account()
        self.state = self._load_state()
        self._initialize_mongodb()
        self._initialize_minio()
        self._load_config_from_mongo()
        self.client = OpenAI(api_key=self.openai_api_key)
        self._load_watermark_logo()
        self._verses_cache: Optional[list] = None

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
            persona = get_persona(SCRIPTURE_ACCOUNT_KEY)
            if not persona:
                raise RuntimeError(
                    f"Persona '{SCRIPTURE_ACCOUNT_KEY}' not found in bot_personas. "
                    f"Run: python scripture_post_generator.py --setup-persona"
                )
            persona["account_key"] = SCRIPTURE_ACCOUNT_KEY
            return persona
        except Exception as e:
            logger.error(f"[ERROR] Failed to load account: {e}")
            raise

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

    def _apply_watermark_top_right(self, image: Image.Image) -> Image.Image:
        """Dhyan logo at top-right — different from Gita bot's bottom-right placement."""
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
            image.paste(logo, (w - ww - px, py), logo)  # top-right
            return image
        except Exception as e:
            logger.warning(f"Watermark apply failed: {e}")
            return image

    # ----- state -----

    def _default_state(self) -> dict:
        return {
            "last_date": None,
            "last_post_id": None,
            "posted_verse_ids": [],
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

    def _should_post_today(self) -> bool:
        """Alternate-day gate: post only when last post was 2+ days ago."""
        last_date_str = self.state.get("last_date")
        if not last_date_str:
            return True
        try:
            last_date = date.fromisoformat(last_date_str)
            days_since = (date.today() - last_date).days
            if days_since == 0:
                logger.info("Already posted today. Skipping.")
                return False
            if days_since == 1:
                logger.info("Rest day (alternate-day schedule). Skipping.")
                return False
            return True
        except Exception:
            return True

    # ----- verse selection -----

    def _get_all_non_gita_verses(self) -> list:
        """Fetch all non-Gita scripture verses from MongoDB. Cached per run."""
        if self._verses_cache is not None:
            return self._verses_cache
        if self.db is None:
            return []
        try:
            cursor = self.db["scripture_verses"].find(
                {"scriptureTitle": {"$nin": list(EXCLUDED_SCRIPTURE_TITLES)}}
            )
            verses = []
            for v in cursor:
                title = (v.get("scriptureTitle") or "").strip()
                if not title:
                    continue
                if not v.get("verseText") and not v.get("translationText"):
                    continue
                v["_title_clean"] = title
                verses.append(v)
            self._verses_cache = verses
            logger.info(f"Loaded {len(verses)} non-Gita verses from MongoDB")
            return verses
        except Exception as e:
            logger.error(f"[ERROR] Failed to load scripture verses: {e}")
            return []

    def _select_random_verse(self) -> Optional[dict]:
        """Pick a random unposted verse. Resets the pool when all verses are exhausted."""
        all_verses = self._get_all_non_gita_verses()
        if not all_verses:
            return None

        posted_ids = set(str(v) for v in self.state.get("posted_verse_ids", []))
        available = [v for v in all_verses if str(v["_id"]) not in posted_ids]

        if not available:
            logger.info("[POOL] All verses posted. Resetting posted list and restarting.")
            self.state["posted_verse_ids"] = []
            self._save_state()
            available = all_verses

        verse = random.choice(available)
        logger.info(
            f"Selected: {verse.get('_title_clean')} "
            f"Ch{verse.get('chapterNumber', '?')} V{verse.get('verseNumber', '?')}"
        )
        return verse

    # ----- Level 1 LLM: classify scripture_type (low temperature) -----

    def classify_scripture_type(self, verse: dict) -> str:
        """
        Single low-temperature call to classify the passage type.
        Returns one of: narrative / philosophical / devotional / mantra / wisdom
        """
        scripture_name = (
            verse.get("scriptureName") or verse.get("_title_clean") or ""
        ).strip()
        verse_text = (verse.get("verseText") or "")[:300].strip()
        translation = (verse.get("translationText") or "")[:200].strip()

        prompt = (
            "Classify this scripture passage into ONE of these types:\n"
            "narrative / philosophical / devotional / mantra / wisdom\n\n"
            f"Scripture: {scripture_name}\n"
            f"Original text: {verse_text}\n"
            f"Translation: {translation}\n\n"
            "Return ONLY one word from the list above. Nothing else."
        )

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a Hindu scripture scholar. Classify the passage. Return exactly one word.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=10,
            )
            record_openai_response(response, service="scripture_post.classify_type")
            result = response.choices[0].message.content.strip().lower()
            if result in VALID_SCRIPTURE_TYPES:
                logger.info(f"Scripture type classified: {result}")
                return result
            logger.warning(f"Unexpected classification '{result}', defaulting to 'philosophical'")
            return "philosophical"
        except Exception as e:
            logger.error(f"[ERROR] Classification failed: {e}")
            return "philosophical"

    # ----- Level 2 LLM: generate post (high temperature) -----

    def generate_post_from_verse(self, verse: dict, scripture_type: str) -> Optional[dict]:
        """
        High-temperature post generation. Tone is locked by scripture_type from Level 1.
        Voice is Aditya Karn's — exploratory seeker, not the devoted-student style of Gita bot.
        """
        chapter = verse.get("chapterNumber", "")
        verse_num = verse.get("verseNumber", "")
        scripture_title = verse.get("_title_clean", verse.get("scriptureTitle", "")).strip()
        scripture_name = (verse.get("scriptureName") or scripture_title).strip()
        verse_text = (verse.get("verseText") or "").strip()
        translation = (verse.get("translationText") or "").strip()
        commentary = (verse.get("commentary") or "").strip()[:1200]
        translation_author = (verse.get("translationAuthor") or "").strip()
        commentary_author = (verse.get("commentaryAuthor") or "").strip()

        persona = (self.account.get("persona") or "").strip()
        conv_style = (self.account.get("conversational_style") or "").strip()

        section_label = scripture_name
        if chapter:
            section_label += f" · Chapter {chapter}"
        if verse_num:
            section_label += f" · Verse {verse_num}"

        deeplink = (
            f"https://dhyanapp.org/scriptureChaptersListScreen/"
            f"{urllib.parse.quote(scripture_title)}"
        )

        tone_instructions = {
            "narrative": (
                "Tell what happened and why it matters. Name characters naturally. "
                "Write with the warmth of a storyteller — vivid, immediate, present. "
                "Let the reader feel they are inside the story, not observing it."
            ),
            "philosophical": (
                "Explain the concept in clear, simple terms. Use 'I' and 'we'. "
                "Ground the abstract in the felt sense of lived experience. "
                "Be quietly inquiring, not definitive. Let the question linger."
            ),
            "devotional": (
                "Write with warmth and surrender. Name the deity naturally if appropriate. "
                "Let the reflection feel like an offering, not a lesson. "
                "Quietly devotional, never performative or preachy."
            ),
            "mantra": (
                "Explain what the sound or word means and what it invokes within. "
                "Connect the mantra syllables to an inner experience or quality. "
                "Let the reader feel the resonance of the words, not just their meaning."
            ),
            "wisdom": (
                "Be practical and grounded. Connect directly to lived experience today. "
                "The wisdom should feel applicable right now, not abstract or distant. "
                "Write with the simplicity of someone who has lived the teaching."
            ),
        }
        tone = tone_instructions.get(scripture_type, tone_instructions["philosophical"])
        closer = random.choice(SCRIPTURE_TYPE_CLOSERS.get(scripture_type, ["ॐ"]))

        commentary_block = ""
        if commentary:
            author_line = f" (by {commentary_author})" if commentary_author else ""
            commentary_block = (
                f"\nCommentary{author_line} — PRIMARY source for your reflection:\n{commentary}"
            )

        translation_author_line = f" (by {translation_author})" if translation_author else ""

        prompt = f"""You are writing a daily scripture post for a spiritual social app in the voice of a seeker who explores the full breadth of Hindu sacred texts.

Persona: {persona}
Voice: {conv_style}

Today's passage — {section_label}.

Original text:
{verse_text}

Translation{translation_author_line}:
{translation}
{commentary_block}

Scripture type: {scripture_type}
Tone instruction: {tone}

Write the post in ENGLISH, 130–200 words, in this exact structure:

1. Header line on its own: "{section_label}"
2. The original verse/passage exactly as given above, on its own lines.
3. The translation in 1–2 clear modern English sentences. Smooth the wording, do not change meaning.
4. A reflection of 3–5 sentences. Follow the tone instruction above strictly.
   Write in first person.{' Ground reflection in the commentary above.' if commentary else ''}
   Do NOT use clichés like "fast-paced modern life", "journey not the destination", or generic self-help framing.
5. End with this exact closing line (do not modify): {closer}
6. A new line with a natural invitation to read in DhyanApp. Vary the phrasing. Use the exact URL verbatim: {deeplink}
   Example: "Explore this passage: [{section_label}]({deeplink})"

Do NOT include IAST transliteration. Original verse and English translation only.

Return ONLY valid JSON:
{{
  "content": "full post body with real newlines between sections",
  "saying": "3–6 word evocative title rooted in this specific passage (not generic)",
  "description": "15–25 word summary of this passage's specific teaching",
  "source_topic": "{scripture_name} {chapter} {verse_num}",
  "scripture_type": "{scripture_type}"
}}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a seeker writing daily scripture posts. "
                            "Your tone shifts with the text — narrative for epics, philosophical for Upanishads, "
                            "devotional for bhakti texts, precise for Yoga Sutras. "
                            "Always return valid JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
                max_tokens=1100,
            )
            record_openai_response(response, service="scripture_post.generate")
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            return json.loads(content)
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate post: {e}")
            return None

    # ----- infographic assets -----

    def generate_infographic_assets(
        self, verse: dict, post_data: dict, scripture_type: str
    ) -> dict:
        """Produce label / headline / takeaway strings for the infographic renderer."""
        scripture_name = (verse.get("scriptureName") or verse.get("_title_clean") or "").strip()
        chapter = verse.get("chapterNumber", "")
        verse_num = verse.get("verseNumber", "")
        translation = (verse.get("translationText") or "").strip()
        saying = post_data.get("saying", "")

        label_parts = [p for p in [
            scripture_name,
            f"Ch. {chapter}" if chapter else "",
            f"V. {verse_num}" if verse_num else "",
        ] if p]
        label_default = " · ".join(label_parts)

        prompt = f"""Prepare text to render onto a scripture infographic poster.

Scripture: {scripture_name}, Chapter {chapter}, Verse {verse_num}
Scripture type: {scripture_type}
Translation (reference): {translation}
Post headline (reference): {saying}

All strings MUST be in clear, simple English.

Return ONLY valid JSON with exactly these three keys:
{{
  "label": "reference label e.g. '{label_default}'",
  "headline": "3–6 word evocative title for this specific passage",
  "takeaway": "core teaching of this passage in 12–20 plain readable words"
}}

Keep text short enough to render cleanly on a poster. No quotation marks inside values."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You craft concise poster text for scripture infographics. Always return valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
                max_tokens=300,
            )
            record_openai_response(response, service="scripture_post.infographic_assets")
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            data = json.loads(content)
            return {
                "label": data.get("label") or label_default,
                "headline": data.get("headline") or saying or scripture_name,
                "takeaway": data.get("takeaway") or "",
            }
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate infographic assets: {e}")
            return {
                "label": label_default,
                "headline": saying or scripture_name,
                "takeaway": translation[:120],
            }

    def generate_infographic_prompt(
        self, verse: dict, assets: dict, scripture_type: str, style: dict
    ) -> str:
        label = assets["label"].replace('"', "'")
        headline = assets["headline"].replace('"', "'")
        takeaway = assets["takeaway"].replace('"', "'")
        verse_text = (verse.get("verseText") or "").strip().replace('"', "'")
        translation = (verse.get("translationText") or "").strip().replace('"', "'")

        verse_theme = headline
        if takeaway:
            verse_theme += f". {takeaway}"
        if translation:
            verse_theme += f" ({translation[:160].rstrip()})"

        visual_hints = {
            "narrative": (
                "The background scene should depict the key moment in the story — characters, setting, action. "
                "Make it vivid and narrative, like a frame from an epic tale being told."
            ),
            "philosophical": (
                "The background should evoke the concept — vast open sky, deep stillness, "
                "light emerging from darkness, or sacred geometry. Contemplative and spacious."
            ),
            "devotional": (
                "The background should feel like an offering — soft light, a divine presence, lotus, flame, "
                "or a deity motif appropriate to this scripture. Warm and surrendered in mood."
            ),
            "mantra": (
                "The background should evoke sound, vibration, and cosmic resonance — "
                "sacred syllables dissolving into light, ripples of energy, or a deep meditative space."
            ),
            "wisdom": (
                "The background should feel practical and grounded — nature, a calm everyday scene, "
                "a sage in quiet dialogue, or a simple image that holds the wisdom naturally."
            ),
        }
        visual_hint = visual_hints.get(scripture_type, visual_hints["philosophical"])

        return (
            f"A premium square scripture infographic poster rendered in the "
            f"\"{style['name']}\" visual style: {style['description']}. "
            f"Color palette: {style['colors']}. "

            f"PASSAGE THEME for all visual imagery: {verse_theme}. "
            f"{visual_hint} "
            f"All visual elements — background scenes, icons, symbolic illustrations, decorative accents — "
            f"must directly reflect this specific passage's teaching. "

            f"Create the poster in a clear infographic format with visually separated content sections "
            f"arranged in a structured, flow-based layout. "
            f"Use icons, symbolic illustrations, or structured cards to show the teaching's structure. "
            f"The design should feel informative, structured, spiritually premium, and easy to read at first glance. "

            f"On-image text must be minimal, prominent, and readable in clean modern English typography. "
            f"Include exactly these content elements: "
            f"(1) a small scripture/verse label reading: {label}, "
            f"(2) a short headline reading: {headline}, "
            f"(3) the original verse text: {verse_text}, "
            f"(4) a highlighted takeaway line reading: {takeaway}, "
            f"(5) the meaning across the full bottom section reading: {translation}. "

            f"LAYOUT RULES: "
            f"The MEANING (element 5) must occupy the FULL bottom section of the poster — "
            f"give it generous space, no crowding below it. "
            f"Leave a small clean empty area in the UPPER-RIGHT corner free of text and visual elements "
            f"so a brand logo can be placed there without overlap. "

            f"Use clear visual hierarchy: label small at top-left, large headline, "
            f"verse in a dedicated card, takeaway highlighted, meaning filling the full bottom. "
            f"Subtle dividers, elegant borders, glowing accents, breathing space. "
            f"Spiritual, calm, premium, meditative. No clutter. No extra words."
        )

    # ----- image -----

    def generate_image(self, prompt: str, post_id: str) -> Optional[str]:
        if not self.s3_client:
            logger.error("[ERROR] MinIO not initialized")
            return None
        try:
            response = self.client.images.generate(
                model=SCRIPTURE_IMAGE_MODEL,
                prompt=prompt,
                size=SCRIPTURE_IMAGE_SIZE,
                quality=SCRIPTURE_IMAGE_QUALITY,
                n=1,
            )
            _img_price = {"low": 0.01, "medium": 0.04, "high": 0.17}
            try:
                record_usage(
                    "openai", SCRIPTURE_IMAGE_MODEL, "scripture_post.generate_image",
                    images=1,
                    cost_usd=_img_price.get(SCRIPTURE_IMAGE_QUALITY, 0.04),
                    meta={"size": SCRIPTURE_IMAGE_SIZE, "quality": SCRIPTURE_IMAGE_QUALITY},
                )
            except Exception as track_err:
                logger.warning(f"Failed to record image usage: {track_err}")

            raw_bytes = base64.b64decode(response.data[0].b64_json)
            image = Image.open(io.BytesIO(raw_bytes))
            image = self._apply_watermark_top_right(image)
            buf = io.BytesIO()
            image.save(buf, format="WEBP", lossless=True)

            object_key = f"Posts/images/bot_scripture/{post_id}.webp"
            self.s3_client.put_object(
                Bucket=MINIO_BUCKET,
                Key=object_key,
                Body=buf.getvalue(),
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

    def push_post_to_db(
        self,
        post_data: dict,
        image_url: Optional[str],
        post_id: str,
        verse: dict,
        scripture_type: str,
        image_style: str,
    ) -> Optional[str]:
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
            "_generatorType": "scripture_daily_verse",
            "_language": "english",
            "_scripture": verse.get("_title_clean", verse.get("scriptureTitle", "")),
            "_scriptureName": verse.get("scriptureName", ""),
            "_chapter": verse.get("chapterNumber", ""),
            "_verse": verse.get("verseNumber", ""),
            "_scriptureType": scripture_type,
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

    def generate_and_post(self, *, advance_state: bool = True) -> Optional[str]:
        verse = self._select_random_verse()
        if verse is None:
            logger.error("[ERROR] No verse available to post")
            return None

        scripture_title = verse.get("_title_clean", "unknown")
        chapter = verse.get("chapterNumber", "?")
        verse_num = verse.get("verseNumber", "?")

        logger.info(f"\n{'='*60}")
        logger.info(f"GENERATING SCRIPTURE POST: {scripture_title} Ch{chapter} V{verse_num}")
        logger.info(f"{'='*60}")

        # Level 1: classify at low temperature
        scripture_type = self.classify_scripture_type(verse)
        logger.info(f"Scripture type: {scripture_type}")

        # Level 2: generate post at high temperature, guided by scripture_type
        post_data = self.generate_post_from_verse(verse, scripture_type)
        if not post_data:
            logger.error("Failed to generate post content")
            return None
        logger.info(f"Saying: {post_data.get('saying', 'N/A')}")

        post_id = str(uuid.uuid4())

        assets = self.generate_infographic_assets(verse, post_data, scripture_type)
        logger.info(f"Infographic headline: {assets.get('headline', '')}")

        selected_style = random.choice(SCRIPTURE_IMAGE_STYLES)
        logger.info(f"Image style: {selected_style['name']}")

        image_prompt = self.generate_infographic_prompt(verse, assets, scripture_type, selected_style)
        logger.info("Generating infographic image...")
        image_url = self.generate_image(image_prompt, post_id)
        if image_url:
            logger.info(f"Image URL: {image_url[:80]}...")
        else:
            logger.warning("Posting without image")

        doc_id = self.push_post_to_db(
            post_data, image_url, post_id, verse, scripture_type, selected_style["name"]
        )
        if not doc_id:
            return None

        if advance_state:
            self.state["last_date"] = date.today().isoformat()
            self.state["last_post_id"] = doc_id
            self.state.setdefault("posted_verse_ids", []).append(str(verse["_id"]))
            self._save_state()
            logger.info(
                f"State saved. Posted {len(self.state['posted_verse_ids'])} verses so far."
            )

        logger.info(f"[SUCCESS] Scripture post created: {doc_id}")
        return doc_id

    def run_daily_post(self) -> Optional[str]:
        today_iso = date.today().isoformat()
        logger.info("=" * 60)
        logger.info("SCRIPTURE DAILY POST GENERATOR (Aditya Karn)")
        logger.info(f"Date: {today_iso}")
        logger.info(f"Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
        logger.info("=" * 60)

        if not self._should_post_today():
            return None

        return self.generate_and_post(advance_state=True)


# Singleton
_generator: Optional[ScripturePostGenerator] = None


def get_scripture_post_generator() -> ScripturePostGenerator:
    global _generator
    if _generator is None:
        _generator = ScripturePostGenerator()
    return _generator


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scripture Daily Post Generator (Aditya Karn)")
    parser.add_argument("--run-now", action="store_true",
                        help="Run daily post (respects alternate-day schedule)")
    parser.add_argument("--test", action="store_true",
                        help="Generate one post without advancing state")
    parser.add_argument("--show-state", action="store_true",
                        help="Print current state")
    parser.add_argument("--reset-state", action="store_true",
                        help="Reset state to defaults (requires --yes-i-am-sure)")
    parser.add_argument("--yes-i-am-sure", action="store_true",
                        help="Confirm --reset-state")
    parser.add_argument("--setup-persona", action="store_true",
                        help="Insert/update the Aditya Karn persona in bot_personas collection")
    parser.add_argument("--list-scriptures", action="store_true",
                        help="List available non-Gita scriptures and verse counts")

    args = parser.parse_args()

    if args.setup_persona:
        persona = get_persona(SCRIPTURE_ACCOUNT_KEY)
        if persona:
            print(f"[OK] Persona '{SCRIPTURE_ACCOUNT_KEY}' already exists in DB:")
            print(f"     name={persona.get('name')}")
            print(f"     user_id={persona.get('user_id')}")
        else:
            print(f"[ERROR] Persona '{SCRIPTURE_ACCOUNT_KEY}' not found in DB. Insert it manually into bot_personas collection.")
        sys.exit(0)

    if args.reset_state:
        if not args.yes_i_am_sure:
            print("[ABORT] --reset-state requires --yes-i-am-sure")
            sys.exit(1)
        state = {"last_date": None, "last_post_id": None, "posted_verse_ids": []}
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        print("[OK] State reset to defaults.")
        sys.exit(0)

    if args.show_state:
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE) as f:
                    state = json.load(f)
                print("\n" + "=" * 60)
                print("SCRIPTURE POST STATE (Aditya Karn)")
                print("=" * 60)
                print(f"Last date:     {state.get('last_date')}")
                print(f"Last post ID:  {state.get('last_post_id')}")
                print(f"Verses posted: {len(state.get('posted_verse_ids', []))}")
            else:
                print("No state file found.")
        except Exception as e:
            print(f"Error reading state: {e}")
        sys.exit(0)

    if args.list_scriptures:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client["dhyanapp"]
        pipeline = [
            {"$match": {"scriptureTitle": {"$nin": list(EXCLUDED_SCRIPTURE_TITLES)}}},
            {"$group": {"_id": "$scriptureTitle", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        print("\nAvailable non-Gita scriptures:")
        print(f"{'Scripture':<45} {'Verses':>7}")
        print("-" * 55)
        total = 0
        for doc in db["scripture_verses"].aggregate(pipeline):
            print(f"{str(doc['_id']):<45} {doc['count']:>7}")
            total += doc["count"]
        print("-" * 55)
        print(f"{'TOTAL':<45} {total:>7}")
        sys.exit(0)

    if args.test:
        gen = get_scripture_post_generator()
        post_id = gen.generate_and_post(advance_state=False)
        if post_id:
            print(f"\n[SUCCESS] Test post created (state NOT advanced): {post_id}")
        else:
            print("\n[ERROR] Failed to create test post")
        sys.exit(0 if post_id else 1)

    if args.run_now:
        gen = get_scripture_post_generator()
        post_id = gen.run_daily_post()
        if post_id:
            print(f"\nCreated post: {post_id}")
        sys.exit(0)

    parser.print_help()
