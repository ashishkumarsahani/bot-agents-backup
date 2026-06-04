"""
Tattvaloka Magazine Article Generator for DhyanApp.

Turns Tattvaloka magazine articles (MongoDB `source_magazine_articles`) into long-form
articles published to `article_files_v1` on an alternate-day schedule.

Cover image: portrait 1024×1536, magazine-cover style (full-bleed classical illustration
+ editorial title header). NOT an infographic poster.

State persisted in magazine_article_state.json beside this script:
  last_date, last_article_id, posted_article_ids, next_image_language
"""

import base64
import io
import os
import re
import json
import logging
import random
import uuid
import sys
import subprocess
import tempfile
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional

import requests as _requests
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
STATE_FILE = Path(__file__).parent / "magazine_article_state.json"
MAGAZINE_SLUG = "tattvaloka"

DHYANI_USER_ID = "7es9AYnaW7afNtMeOBtXl8Z2ILF3"
UPLOADED_BY = "Dhyani"
AUTHOR_NAME = "Dhyan"
AUTHOR_PROFILE_IMAGE_URL = "https://storage.dhyanapp.org/dhyanapp-recordings/avatars/DhyanApp_User_Profile_Icon_7.svg"
AUTHOR_BIO = (
    "Tattvaloka is the monthly journal of the Sringeri Sharada Peetham on "
    "Sanatana Dharma, Advaita Vedanta, and Indian culture."
)
AUTHOR_BIO_HINDI = (
    "तत्त्वलोक, श्रृंगेरी शारदा पीठम की मासिक पत्रिका है, जो सनातन धर्म, "
    "अद्वैत वेदांत और भारतीय संस्कृति पर केंद्रित है।"
)
AUTHOR_NAME_HINDI = "ध्यान"

ALLOWED_CATEGORIES = {"article", "discourse", "story", "subhashita", "poem", "qna"}

# Detect garbled PDF font encoding from legacy Indian fonts (Kruti Dev, Shivaji, etc.)
# Patterns: letter+$+letter (H$m), opening brace+letter ({anw), letter+©, letter+«$
_GARBLED_PATTERN = re.compile(
    r'[A-Za-z]\$[A-Za-z]'      # H$m, j_$m style
    r'|{[a-zA-Z]'               # {anw, {d^m — Kruti Dev brace artifacts
    r'|[A-Za-z]©'               # B© — combining char artifacts
    r'|[A-Za-z]«\$'             # H«$mo style
    r'|grVod|BË`m|VÁOm'         # known specific garbled strings
)

OPENAI_TTS_VOICE_ENGLISH = "nova"    # warm, smooth — suits spiritual content
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
SARVAM_TTS_VOICE_HINDI = "aditya"   # natural Indian male voice
SARVAM_TTS_MODEL = "bulbul:v3"

ARTICLE_IMAGE_MODEL = "gpt-image-2"
ARTICLE_IMAGE_SIZE = "1024x1536"   # portrait — magazine cover
ARTICLE_IMAGE_QUALITY = "medium"
DHYAN_LOGO_PATH = "/home/admin/dhyanapp-services/images/dhyan_logo.png"

MAGAZINE_CLOSERS = [
    "जय जगद्गुरु",
    "ॐ नमः शिवाय",
    "हर हर शंकर",
    "सत्यमेव जयते",
    "ॐ तत् सत्",
    "जय श्री शारदाम्बा",
]

# Classical magazine-cover illustration styles — portrait, image-led, NOT infographic.
COVER_IMAGE_STYLES = [
    {
        "name": "Cover Illustration Feature",
        "description": (
            "A tall portrait magazine cover: a large, dignified classical Indian devotional "
            "illustration fills roughly two-thirds of the frame. A slim maroon-and-gold header "
            "band at the very TOP carries the kicker line and feature title in elegant serif. "
            "Below the header the illustration flows to the bottom edge. Image-dominant, "
            "minimal text — like a premium Tattvaloka cover."
        ),
        "colors": "warm cream, deep maroon, antique gold, and soft sepia",
    },
    {
        "name": "Hero Portrait Cover",
        "description": (
            "Full-bleed portrait painting of the central deity, sage, or sacred scene, "
            "richly rendered in classical Indian style. A clean white-ivory editorial strip "
            "at the TOP carries the small kicker and large feature title. The art bleeds to "
            "the left, right, and bottom edges — cinematic and devotional."
        ),
        "colors": "ivory, deep maroon, gold leaf, and warm devotional tones",
    },
    {
        "name": "Framed Art Plate Cover",
        "description": (
            "A tall portrait art plate: the subject rendered as a painterly classical "
            "illustration centered within an ornate gold-and-maroon border. The feature title "
            "appears in elegant serif at the top inside the border, a single short kicker above "
            "it. Mostly image — refined like a collectible magazine plate."
        ),
        "colors": "antique gold, deep maroon, ivory, and rich painterly tones",
    },
    {
        "name": "Sringeri Temple Scene Cover",
        "description": (
            "A serene tall portrait illustration of the Sringeri Sharada temple by the Tunga "
            "river, or a sacred landscape fitting the article — as the dominant visual filling "
            "most of the frame. The feature title sits in a calm overlaid editorial band near "
            "the top. Atmospheric and image-led."
        ),
        "colors": "soft sandalwood, ivory, muted indigo, antique gold, and maroon",
    },
    {
        "name": "Deity Portrait Cover",
        "description": (
            "A refined tall portrait painting of the relevant deity, sage, or Adi Shankara — "
            "head-and-shoulders to three-quarter length — as the focal image filling the frame. "
            "Small maroon kicker and large serif feature title at the top, the rest is pure art. "
            "Portrait-dominant, very sparse text."
        ),
        "colors": "deep maroon, gold, ivory, and warm devotional tones",
    },
    {
        "name": "Lamp-lit Contemplative Cover",
        "description": (
            "A tall portrait atmospheric scene lit by oil lamps or soft divine light — evoking "
            "the mood of the article — filling almost the entire frame. The feature title "
            "appears in a single elegant serif line near the top against the scene. "
            "Mood-driven, very little text."
        ),
        "colors": "deep indigo, warm amber glow, gold, maroon, and ivory",
    },
    {
        "name": "Sacred Symbol Cover",
        "description": (
            "One large central sacred motif — Om, Goddess Sharada's veena, a lotus, or the "
            "article's key symbol — rendered as elegant tall-format focal art filling the frame, "
            "the feature title beneath it in serif and a thin gold rule above. "
            "Symbol-dominant, minimal words."
        ),
        "colors": "ivory, antique gold, deep maroon, lotus white, and muted blue",
    },
    {
        "name": "Manuscript Art Cover",
        "description": (
            "An aged-parchment tall portrait with a single fine classical illustration of the "
            "subject as the centerpiece filling most of the frame, a calligraphic-style serif "
            "title and kicker at the top; subtle palm-leaf texture at the edges. "
            "Balanced art-and-title, not text-filled."
        ),
        "colors": "aged parchment, sepia, deep maroon, faded gold, and ink black",
    },
]


def _flip_image_language(lang: str) -> str:
    return "hindi" if lang == "english" else "english"


def _sanitize_hindi_text(text: str) -> str:
    """Remove stray Cyrillic/Greek/other scripts from Hindi text, keep Devanagari + ASCII."""
    result = []
    for ch in text:
        cp = ord(ch)
        if (0x20 <= cp <= 0x7E) or (0x0900 <= cp <= 0x097F) or cp in (0x200C, 0x200D, 0x0964, 0x0965, 0x0A, 0x0D, 0x09):
            result.append(ch)
    return "".join(result)



def _strip_markdown_for_tts(text: str) -> str:
    """Remove markdown syntax before sending to TTS."""
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)   # headings
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)                  # bold
    text = re.sub(r'\*(.+?)\*', r'\1', text)                       # italic
    text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)       # bullet lists
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)      # numbered lists
    text = re.sub(r'\n---+\n', '\n', text)                         # hr
    text = re.sub(r'\n{3,}', '\n\n', text)                        # excess blank lines
    return text.strip()


def _get_audio_duration_ms(audio_bytes: bytes) -> int:
    """Get duration of MP3 bytes using ffprobe."""
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', tmp_path],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)
        duration_s = float(data['format']['duration'])
        return int(duration_s * 1000)
    except Exception as e:
        logger.warning(f"ffprobe duration failed: {e}")
        return 0
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


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


class MagazineArticleGenerator:
    """Generates articles from Tattvaloka magazine content, posting on alternate days."""

    def __init__(self):
        self.state = self._load_state()
        self._initialize_mongodb()
        self._initialize_minio()
        self._load_config_from_mongo()
        self.client = OpenAI(api_key=self.openai_api_key)
        self._load_watermark_logo()
        self._articles_cache: Optional[list] = None

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
            image.paste(logo, (w - ww - px, py), logo)
            return image
        except Exception as e:
            logger.warning(f"Watermark apply failed: {e}")
            return image

    # ----- state -----

    def _default_state(self) -> dict:
        return {
            "last_date": None,
            "last_article_id": None,
            "posted_article_ids": [],
            "next_image_language": "english",
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

    # ----- article selection -----

    def _get_all_articles(self) -> list:
        if self._articles_cache is not None:
            return self._articles_cache
        if self.db is None:
            return []
        try:
            cursor = self.db["source_magazine_articles"].find(
                {
                    "magazineSlug": MAGAZINE_SLUG,
                    "category": {"$in": list(ALLOWED_CATEGORIES)},
                }
            )
            articles = []
            skipped = 0
            for a in cursor:
                if not (a.get("body") or a.get("summary")):
                    continue
                if _GARBLED_PATTERN.search(a.get("body", "")):
                    skipped += 1
                    continue
                articles.append(a)
            if skipped:
                logger.info(f"Skipped {skipped} articles with garbled PDF encoding")
            self._articles_cache = articles
            logger.info(f"Loaded {len(articles)} curated Tattvaloka articles from MongoDB")
            return articles
        except Exception as e:
            logger.error(f"[ERROR] Failed to load magazine articles: {e}")
            return []

    def _select_random_article(self) -> Optional[dict]:
        all_articles = self._get_all_articles()
        if not all_articles:
            return None

        posted_ids = set(str(a) for a in self.state.get("posted_article_ids", []))
        available = [a for a in all_articles if str(a["_id"]) not in posted_ids]

        if not available:
            logger.info("[POOL] All articles posted. Resetting posted list.")
            self.state["posted_article_ids"] = []
            self._save_state()
            available = all_articles

        article = random.choice(available)
        logger.info(
            f"Selected: [{article.get('category')}] {article.get('title')} "
            f"({article.get('month')})"
        )
        return article

    # ----- LLM: generate article from source -----

    def generate_article_from_source(self, article: dict) -> Optional[dict]:
        """
        Distil a Tattvaloka source article into a long-form Markdown article
        with an explanatory title, subtitle, short description, and full body.
        """
        title = (article.get("title") or "").strip()
        author = (article.get("author") or "").strip()
        category = (article.get("category") or "article").strip()
        month = (article.get("month") or "").strip()
        summary = (article.get("summary") or "").strip()
        body = (article.get("body") or "").strip()[:5000]
        tags = article.get("tags") or []
        tags_str = ", ".join(tags) if tags else ""

        category_guidance = {
            "story": (
                "This is a story or episode. Retell it faithfully — name the characters, "
                "setting, action, and the spiritual insight it conveys. Use narrative prose "
                "with clear sections."
            ),
            "discourse": (
                "This is a discourse or teaching. Distil the teaching into clearly labelled "
                "sections covering the core idea, supporting arguments, and practical "
                "application. Stay faithful to the text."
            ),
            "article": (
                "This is an essay. Organise it into titled sections that cover the central "
                "argument, key supporting ideas, and a reflective conclusion. Faithful to "
                "the source body."
            ),
            "subhashita": (
                "This is a subhashita (wisdom verse). Present the verse or its idea in full, "
                "then explain its meaning and significance across several sections. If a "
                "Devanagari shloka appears in the body, quote it verbatim."
            ),
            "poem": (
                "This is a devotional poem. Convey its imagery, emotion, and devotional "
                "message across sections — verse context, meaning, and how to carry it into "
                "practice."
            ),
            "qna": (
                "This is a Q&A piece. State the question clearly as an opening section, then "
                "expand the answer into well-labelled sections covering the full reasoning."
            ),
        }
        guidance = category_guidance.get(category, category_guidance["article"])
        attribution = f"From Tattvaloka, {month}" if month else "From Tattvaloka"
        if author:
            attribution += f" — {author}"

        prompt = f"""You are writing a long-form article for DhyanApp based on a Tattvaloka magazine piece.

Source article:
Original title: {title}
Category: {category}
Month: {month}
{f'Tags: {tags_str}' if tags_str else ''}
Attribution: {attribution}

Summary (reference only):
{summary}

Article body (PRIMARY source — be faithful, invent nothing):
{body}

{guidance}

Write a well-structured ENGLISH article in Markdown format, 400-700 words.

STRUCTURE REQUIREMENTS:
- Use `##` for section headings (2-4 sections)
- Use bullet points or numbered lists where appropriate
- Bold key terms or phrases with **bold**
- No IAST transliteration; Devanagari script is fine if quoted verbatim from source
- End with a short reflective section (## Reflection or ## In Practice)
- Do NOT add a byline, header label, or attribution line inside the body — those are stored separately

Return ONLY valid JSON:
{{
  "title": "clear explanatory title (says exactly what the article is about)",
  "sub_title": "15-20 word subtitle / tagline that complements the title",
  "description": "2-3 sentence summary of what this article covers and what the reader will learn",
  "full_text": "complete Markdown article body (400-700 words)"
}}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a writer for DhyanApp, adapting Tattvaloka magazine articles "
                            "into clear, faithful long-form pieces. Always return valid JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=1800,
            )
            record_openai_response(response, service="magazine_article.generate")
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            data = json.loads(content)

            # Backfill missing fields
            if not (data.get("title") or "").strip():
                data["title"] = title
            if not (data.get("description") or "").strip():
                data["description"] = summary[:200].rstrip() if summary else data["title"]
            if not (data.get("sub_title") or "").strip():
                data["sub_title"] = f"From the Tattvaloka {month} edition" if month else "From Tattvaloka"
            return data
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate article: {e}")
            return None

    # ----- cover image assets -----

    def generate_cover_assets(
        self, article: dict, article_data: dict, image_language: str = "english"
    ) -> dict:
        """Produce label / headline / sub_title strings for the cover image."""
        month = (article.get("month") or "").strip()
        category = (article.get("category") or "article").strip()
        title = article_data.get("title") or article.get("title") or ""
        sub_title = article_data.get("sub_title", "")

        if image_language == "hindi":
            lang_instruction = (
                "All strings MUST be in Hindi using Devanagari script. "
                "Do not use English words except digits."
            )
            label_default = f"तत्त्वलोक · {month}" if month else "तत्त्वलोक"
        else:
            lang_instruction = "All strings MUST be in clear, simple English."
            label_default = f"Tattvaloka · {month}" if month else "Tattvaloka"

        prompt = f"""Prepare cover text for a Tattvaloka magazine cover image.

Article title (reference): {title}
Category: {category}
Subtitle (reference): {sub_title}

{lang_instruction}

Return ONLY valid JSON with exactly these keys:
{{
  "label": "short magazine label e.g. '{label_default}'",
  "headline": "3-7 word cover title (clear and descriptive, says what the article is about)"
}}

Keep text short enough to render cleanly on a magazine cover. No quotation marks inside values."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You craft concise cover text for magazine covers. Always return valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                max_tokens=200,
            )
            record_openai_response(response, service="magazine_article.cover_assets")
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            data = json.loads(content)
            return {
                "label": label_default,  # always use the deterministic label
                "headline": data.get("headline") or title,
            }
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate cover assets: {e}")
            return {
                "label": label_default,
                "headline": title,
            }

    def generate_cover_prompt(
        self, article: dict, assets: dict, style: dict, image_language: str = "english"
    ) -> str:
        label = assets["label"].replace('"', "'")
        headline = assets["headline"].replace('"', "'")
        category = (article.get("category") or "article").strip()

        scene_hints = {
            "story": (
                "Depict the key moment of the story — the characters, setting, and action — "
                "as a beautiful, dignified classical Indian illustration."
            ),
            "discourse": (
                "Show a serene sacred scene fitting the teaching — a sage or guru in a calm "
                "temple or natural setting, or the Sringeri Sharada temple by the Tunga river."
            ),
            "article": (
                "Show one strong, evocative classical illustration of the article's central "
                "subject — the deity, sage, place, or idea."
            ),
            "subhashita": (
                "Show an elegant symbolic illustration of the verse's image — a lamp, lotus, "
                "river, or sage — calm and refined."
            ),
            "poem": (
                "Show a soft, lyrical devotional scene evoking the poem's imagery — "
                "light, lotus, flame, or the divine."
            ),
            "qna": (
                "Show a serene seeker-and-sage scene — two figures in calm dialogue "
                "in a sacred setting."
            ),
        }
        scene_hint = scene_hints.get(category, scene_hints["article"])
        title_typography = (
            "elegant Devanagari Hindi typography" if image_language == "hindi"
            else "an elegant editorial serif typeface"
        )

        return (
            f"A premium PORTRAIT magazine cover for \"Tattvaloka\", the refined print journal "
            f"of the Sringeri Sharada Peetham on Advaita Vedanta and Sanatana Dharma, "
            f"in the \"{style['name']}\" style: {style['description']} "
            f"Color palette: {style['colors']}. "

            f"BALANCE: this is a PORTRAIT cover — tall format, image-dominant. "
            f"A strong, beautiful classical Indian devotional illustration fills roughly "
            f"two-thirds to three-quarters of the frame. "
            f"It must feel like a real Tattvaloka magazine cover — dignified, painterly, "
            f"devotional — NOT a flat infographic, NOT folk or tribal art, NOT a poster with "
            f"bullet points or text columns. "

            f"MAIN ILLUSTRATION (the focal point): {scene_hint} "
            f"Render it richly and elegantly, with classical Indian devotional art sensibility. "

            f"TEXT — render EXACTLY these two lines of text, clearly legible, in {title_typography}: "
            f"(1) The word \"TATTVALOKA\" in small caps or a refined serif, at the very top — this MUST be visible and readable; "
            f"(2) the feature title in large prominent serif directly below, reading: {headline}. "
            f"The word TATTVALOKA must appear on the cover — do not omit it. "
            f"Do NOT add any body text, bullet points, key points, summary lines, captions, "
            f"page numbers, or any other text. Only those two lines. "

            f"LAYOUT: the kicker and title sit in a clean editorial band at the very TOP. "
            f"The illustration fills the rest of the frame below, flowing to the bottom and "
            f"side edges. "
            f"Leave a small empty area in the UPPER-RIGHT corner of the header free of text "
            f"and imagery so a brand logo fits without overlap. "

            f"Overall feel: dignified, painterly, premium, contemplative — a quality spiritual "
            f"magazine cover. "
            f"Do NOT include any transliteration or Latin-script romanization of Sanskrit."
        )

    # ----- Hindi translation -----

    def generate_hindi_content(self, article_data: dict) -> Optional[dict]:
        """Translate title, sub_title, description and fullText to Hindi using the LLM."""
        title = article_data.get("title", "")
        sub_title = article_data.get("sub_title", "")
        description = article_data.get("description", "")
        full_text = article_data.get("full_text", "")

        prompt = f"""Translate the following article content into Hindi using ONLY Devanagari script.
Preserve the Markdown structure exactly (## headings, **bold**, bullet points, numbered lists).
Do not translate proper nouns, Sanskrit terms, or names — keep them in their original form.
CRITICAL: Use ONLY Devanagari script for Hindi words. Do NOT use Cyrillic, Greek, or any other non-Latin script. English proper nouns may remain in Latin script.

Title: {title}
Subtitle: {sub_title}
Description: {description}

Article body:
{full_text}

Return ONLY valid JSON:
{{
  "title": "Hindi title in Devanagari",
  "sub_title": "Hindi subtitle in Devanagari",
  "description": "Hindi description in Devanagari (2-3 sentences)",
  "full_text": "Hindi Markdown body in Devanagari"
}}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a Hindi translator. Translate faithfully preserving Markdown. Return valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=2500,
            )
            record_openai_response(response, service="magazine_article.hindi_translation")
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            return json.loads(content)
        except Exception as e:
            logger.error(f"[ERROR] Hindi translation failed: {e}")
            return None

    def generate_english_audio(self, text: str) -> Optional[bytes]:
        """Generate English MP3 using Sarvam bulbul:v3 (aditya, en-IN).
        Fallback to OpenAI TTS if Sarvam fails after 3 attempts.
        """
        import time
        clean_text = _strip_markdown_for_tts(text)
        if not clean_text:
            return None

        sarvam_key = self.secrets.get("SARVAM_API_KEY", os.getenv("SARVAM_API_KEY", ""))

        if sarvam_key:
            for attempt in range(1, 4):
                try:
                    result = self._sarvam_tts_attempt_lang(clean_text, sarvam_key, "en-IN")
                    if result:
                        logger.info(f"Sarvam English TTS succeeded on attempt {attempt}")
                        return result
                except Exception as e:
                    logger.warning(f"Sarvam English attempt {attempt}/3 failed: {e}")
                    if attempt < 3:
                        time.sleep(5)
            logger.warning("All 3 Sarvam English attempts failed — falling back to OpenAI TTS")
        else:
            logger.warning("SARVAM_API_KEY not found — falling back to OpenAI TTS for English")

        # Fallback: OpenAI TTS
        try:
            chunks = []
            remaining = clean_text
            while len(remaining) > 4096:
                idx = remaining.rfind('.', 0, 4096)
                if idx == -1:
                    idx = remaining.rfind(' ', 0, 4096)
                if idx == -1:
                    idx = 4096
                chunks.append(remaining[:idx + 1].strip())
                remaining = remaining[idx + 1:].strip()
            if remaining:
                chunks.append(remaining)
            segments = []
            for chunk in chunks:
                response = self.client.audio.speech.create(
                    model="gpt-4o-mini-tts",
                    voice=OPENAI_TTS_VOICE_ENGLISH,
                    input=chunk,
                    response_format="mp3",
                )
                segments.append(response.content)
            combined = io.BytesIO()
            for seg in segments:
                combined.write(seg)
            logger.info("English audio generated via OpenAI TTS fallback")
            return combined.getvalue()
        except Exception as e:
            logger.error(f"[ERROR] OpenAI English TTS fallback also failed: {e}")
            return None

    def _sarvam_tts_attempt_lang(self, clean_text: str, sarvam_key: str, lang_code: str) -> Optional[bytes]:
        """Sarvam TTS for any language code (en-IN, hi-IN, etc.)."""
        chunks = []
        remaining = clean_text
        while len(remaining) > 1500:
            idx = remaining.rfind('.', 0, 1500)
            if idx == -1:
                idx = remaining.rfind(' ', 0, 1500)
            if idx == -1:
                idx = 1500
            chunks.append(remaining[:idx + 1].strip())
            remaining = remaining[idx + 1:].strip()
        if remaining:
            chunks.append(remaining)

        wav_buffers = []
        for chunk in chunks:
            resp = _requests.post(
                SARVAM_TTS_URL,
                json={
                    "text": chunk,
                    "target_language_code": lang_code,
                    "model": SARVAM_TTS_MODEL,
                    "speaker": SARVAM_TTS_VOICE_HINDI,
                    "speech_sample_rate": 22050,
                    "output_audio_codec": "wav",
                },
                headers={
                    "api-subscription-key": sarvam_key,
                    "Content-Type": "application/json",
                },
                timeout=180,
            )
            resp.raise_for_status()
            for b64 in resp.json().get("audios", []):
                wav_buffers.append(base64.b64decode(b64))

        if not wav_buffers:
            return None

        import shutil
        tmp_dir = tempfile.mkdtemp()
        try:
            wav_paths = []
            for i, wav in enumerate(wav_buffers):
                p = os.path.join(tmp_dir, f"chunk_{i}.wav")
                with open(p, "wb") as f:
                    f.write(wav)
                wav_paths.append(p)
            concat_list = os.path.join(tmp_dir, "concat.txt")
            with open(concat_list, "w") as f:
                for p in wav_paths:
                    f.write(f"file '{p}'\n")
            mp3_path = os.path.join(tmp_dir, "output.mp3")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", concat_list, "-c:a", "libmp3lame", "-q:a", "2", mp3_path],
                capture_output=True, check=True,
            )
            with open(mp3_path, "rb") as f:
                return f.read()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _sarvam_tts_attempt(self, clean_text: str, sarvam_key: str) -> Optional[bytes]:
        """Single attempt at Sarvam TTS. Returns MP3 bytes or None on failure."""
        chunks = []
        remaining = clean_text
        while len(remaining) > 1500:
            idx = remaining.rfind('.', 0, 1500)
            if idx == -1:
                idx = remaining.rfind(' ', 0, 1500)
            if idx == -1:
                idx = 1500
            chunks.append(remaining[:idx + 1].strip())
            remaining = remaining[idx + 1:].strip()
        if remaining:
            chunks.append(remaining)

        wav_buffers = []
        for chunk in chunks:
            resp = _requests.post(
                SARVAM_TTS_URL,
                json={
                    "text": chunk,
                    "target_language_code": "hi-IN",
                    "model": SARVAM_TTS_MODEL,
                    "speaker": SARVAM_TTS_VOICE_HINDI,
                    "speech_sample_rate": 22050,
                    "output_audio_codec": "wav",
                },
                headers={
                    "api-subscription-key": sarvam_key,
                    "Content-Type": "application/json",
                },
                timeout=180,
            )
            resp.raise_for_status()
            for b64 in resp.json().get("audios", []):
                wav_buffers.append(base64.b64decode(b64))

        if not wav_buffers:
            return None

        # Convert WAV chunks → single MP3 via ffmpeg concat
        import shutil
        tmp_dir = tempfile.mkdtemp()
        try:
            wav_paths = []
            for i, wav in enumerate(wav_buffers):
                p = os.path.join(tmp_dir, f"chunk_{i}.wav")
                with open(p, "wb") as f:
                    f.write(wav)
                wav_paths.append(p)

            concat_list = os.path.join(tmp_dir, "concat.txt")
            with open(concat_list, "w") as f:
                for p in wav_paths:
                    f.write(f"file '{p}'\n")

            mp3_path = os.path.join(tmp_dir, "output.mp3")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", concat_list, "-c:a", "libmp3lame", "-q:a", "2", mp3_path],
                capture_output=True, check=True,
            )
            with open(mp3_path, "rb") as f:
                return f.read()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def generate_hindi_audio(self, text: str) -> Optional[bytes]:
        """Generate Hindi MP3.
        Primary: Sarvam bulbul:v3 (aditya) — 3 attempts with 5s waits.
        Fallback: OpenAI TTS (nova) if all Sarvam attempts fail.
        """
        import time
        clean_text = _strip_markdown_for_tts(text)
        if not clean_text:
            return None

        sarvam_key = self.secrets.get("SARVAM_API_KEY", os.getenv("SARVAM_API_KEY", ""))

        if sarvam_key:
            for attempt in range(1, 4):
                try:
                    result = self._sarvam_tts_attempt_lang(clean_text, sarvam_key, "hi-IN")
                    if result:
                        logger.info(f"Sarvam Hindi TTS succeeded on attempt {attempt}")
                        return result
                except Exception as e:
                    logger.warning(f"Sarvam attempt {attempt}/3 failed: {e}")
                    if attempt < 3:
                        time.sleep(5)
            logger.warning("All 3 Sarvam attempts failed — falling back to OpenAI TTS for Hindi")
        else:
            logger.warning("SARVAM_API_KEY not found — falling back to OpenAI TTS for Hindi")

        # Fallback: OpenAI TTS
        try:
            chunks = []
            remaining = clean_text
            while len(remaining) > 4096:
                idx = remaining.rfind('.', 0, 4096)
                if idx == -1:
                    idx = remaining.rfind(' ', 0, 4096)
                if idx == -1:
                    idx = 4096
                chunks.append(remaining[:idx + 1].strip())
                remaining = remaining[idx + 1:].strip()
            if remaining:
                chunks.append(remaining)

            segments = []
            for chunk in chunks:
                response = self.client.audio.speech.create(
                    model="gpt-4o-mini-tts",
                    voice=OPENAI_TTS_VOICE_ENGLISH,
                    input=chunk,
                    response_format="mp3",
                )
                segments.append(response.content)
            combined = io.BytesIO()
            for seg in segments:
                combined.write(seg)
            logger.info("Hindi audio generated via OpenAI TTS fallback")
            return combined.getvalue()
        except Exception as e:
            logger.error(f"[ERROR] OpenAI Hindi TTS fallback also failed: {e}")
            return None

    def upload_audio(self, audio_bytes: bytes, object_key: str) -> Optional[str]:
        """Upload MP3 bytes to MinIO and return public URL."""
        if not self.s3_client:
            return None
        try:
            self.s3_client.put_object(
                Bucket=MINIO_BUCKET,
                Key=object_key,
                Body=audio_bytes,
                ContentType="audio/mpeg",
            )
            base_url = MINIO_PUBLIC_URL if MINIO_PUBLIC_URL else f"http://{MINIO_ENDPOINT}"
            return f"{base_url}/{MINIO_BUCKET}/{object_key}"
        except Exception as e:
            logger.error(f"[ERROR] Audio upload failed: {e}")
            return None

    # ----- image -----

    def generate_image(self, prompt: str, article_id: str) -> Optional[str]:
        if not self.s3_client:
            logger.error("[ERROR] MinIO not initialized")
            return None
        try:
            response = self.client.images.generate(
                model=ARTICLE_IMAGE_MODEL,
                prompt=prompt,
                size=ARTICLE_IMAGE_SIZE,
                quality=ARTICLE_IMAGE_QUALITY,
                n=1,
            )
            _img_price = {"low": 0.02, "medium": 0.07, "high": 0.28}
            try:
                record_usage(
                    "openai", ARTICLE_IMAGE_MODEL, "magazine_article.generate_image",
                    images=1,
                    cost_usd=_img_price.get(ARTICLE_IMAGE_QUALITY, 0.07),
                    meta={"size": ARTICLE_IMAGE_SIZE, "quality": ARTICLE_IMAGE_QUALITY},
                )
            except Exception as track_err:
                logger.warning(f"Failed to record image usage: {track_err}")

            raw_bytes = base64.b64decode(response.data[0].b64_json)
            image = Image.open(io.BytesIO(raw_bytes))
            image = self._apply_watermark_top_right(image)
            buf = io.BytesIO()
            image.save(buf, format="WEBP", lossless=True)

            object_key = f"Knowledge/ArticleBot/{article_id}/poster_image.webp"
            self.s3_client.put_object(
                Bucket=MINIO_BUCKET,
                Key=object_key,
                Body=buf.getvalue(),
                ContentType="image/webp",
            )
            base_url = MINIO_PUBLIC_URL if MINIO_PUBLIC_URL else f"http://{MINIO_ENDPOINT}"
            public_url = f"{base_url}/{MINIO_BUCKET}/{object_key}"
            logger.info("[SUCCESS] Cover image uploaded to MinIO")
            return public_url
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate/upload image: {e}")
            return None

    # ----- DB write -----

    def push_article_to_db(
        self,
        article_data: dict,
        image_url: Optional[str],
        article_id: str,
        source_article: dict,
        image_style: str,
        image_language: str = "english",
        hindi_data: Optional[dict] = None,
        english_audio_url: Optional[str] = None,
        english_duration_ms: int = 0,
        hindi_audio_url: Optional[str] = None,
    ) -> Optional[str]:
        if self.db is None:
            logger.error("[ERROR] MongoDB not connected")
            return None

        month = (source_article.get("month") or "").strip()
        category = (source_article.get("category") or "article").strip()
        full_text = article_data.get("full_text") or ""
        created_at_ms = int(datetime.now(IST).timestamp() * 1000)

        # Prepend Tattvaloka attribution to article body
        attribution_line = f"**Tattvaloka — {month}**" if month else "**Tattvaloka**"
        full_text = f"{attribution_line}\n\n{full_text}"

        # Build alternateAudio, alternateText, alternateTitle
        alternate_audio = {}
        alternate_text = {}
        alternate_title = {}

        if english_audio_url:
            alternate_audio["English"] = english_audio_url
        alternate_text["English"] = full_text
        alternate_title["English"] = article_data.get("title", "")

        if hindi_data:
            if hindi_audio_url:
                alternate_audio["Hindi"] = hindi_audio_url
            if hindi_data.get("full_text"):
                alternate_text["Hindi"] = hindi_data["full_text"]
            if hindi_data.get("title"):
                alternate_title["Hindi"] = hindi_data["title"]

        # Localized maps — English + Hindi only
        en_title = article_data.get("title", "")
        hi_title = (hindi_data or {}).get("title", "")
        en_subtitle = f"Tattvaloka · {month} · {category.capitalize()}" if month else f"Tattvaloka · {category.capitalize()}"
        hi_subtitle = (hindi_data or {}).get("sub_title", en_subtitle)
        en_desc = article_data.get("description", "")
        hi_desc = (hindi_data or {}).get("description", "")

        primary_titles = {"English": en_title}
        sub_titles = {"English": en_subtitle}
        short_descriptions = {"English": en_desc}
        original_author_names = {"English": AUTHOR_NAME, "Hindi": AUTHOR_NAME_HINDI}
        sound_artist_names = {"English": AUTHOR_NAME, "Hindi": AUTHOR_NAME_HINDI}
        author_short_bios = {"English": AUTHOR_BIO, "Hindi": AUTHOR_BIO_HINDI}

        if hi_title:
            primary_titles["Hindi"] = hi_title
        if hi_subtitle:
            sub_titles["Hindi"] = hi_subtitle
        if hi_desc:
            short_descriptions["Hindi"] = hi_desc

        doc = {
            "_id": article_id,
            "selfID": article_id,
            "primaryTitle": en_title,
            "subTitle": en_subtitle,   # e.g. "Tattvaloka · July 2025 · Article"
            "shortDescription": en_desc,
            "fullText": full_text,
            "teaserImageURL": image_url or "",
            "backgroundImageURL": image_url or "",
            "originalAuthorName": AUTHOR_NAME,
            "originalAuthorURL": "",
            "AuthorProfileImageURL": AUTHOR_PROFILE_IMAGE_URL,
            "AuthorShortBio": AUTHOR_BIO,
            "soundArtistName": AUTHOR_NAME,
            "ArticleCategory": "Spirituality",
            "articleType": "original",
            "primaryLanguage": "English",
            "tags": source_article.get("tags") or [],
            "multiMediaType": "originalTextArticle",
            "uploadedBy": UPLOADED_BY,
            "creator_id": DHYANI_USER_ID,
            "wordCount": len(full_text.split()),
            "AIGeneratedText": True,
            "AIGeneratedAudio": bool(english_audio_url),
            "availableOnWebsite": True,
            "availableOnPhone": True,
            "availableOnWatch": False,
            "audioURL": english_audio_url or "",
            "audioLengthMilliSeconds": english_duration_ms,
            "videoURL": "",
            "backgroundMusicSupported": [],
            "alternateAudio": alternate_audio,
            "alternateText": alternate_text,
            "alternateTitle": alternate_title,
            "primaryTitles": primary_titles,
            "subTitles": sub_titles,
            "shortDescriptions": short_descriptions,
            "originalAuthorNames": original_author_names,
            "soundArtistNames": sound_artist_names,
            "authorShortBios": author_short_bios,
            "creationTimeEpoch": created_at_ms,
            "likedBy": [],
            "replayedBy": [],
            "premiumSettings": "general",
        }

        try:
            self.db["article_files_v1"].update_one(
                {"_id": article_id},
                {"$set": doc},
                upsert=True,
            )
            logger.info(f"[SUCCESS] Article pushed to article_files_v1: {article_id}")
            return article_id
        except Exception as e:
            logger.error(f"[ERROR] Failed to push article: {e}")
            return None

    # ----- orchestration -----

    def generate_and_publish(
        self, *, advance_state: bool = True, override_image_lang: Optional[str] = None
    ) -> Optional[str]:
        source_article = self._select_random_article()
        if source_article is None:
            logger.error("[ERROR] No article available")
            return None

        category = source_article.get("category", "?")
        month = source_article.get("month", "?")
        image_language = override_image_lang or self.state.get("next_image_language", "english")

        logger.info(f"\n{'='*60}")
        logger.info(f"GENERATING TATTVALOKA ARTICLE: [{category}] {source_article.get('title')} ({month}) (image: {image_language})")
        logger.info(f"{'='*60}")

        article_data = self.generate_article_from_source(source_article)
        if not article_data:
            logger.error("Failed to generate article content")
            return None
        logger.info(f"Title: {article_data.get('title', 'N/A')}")

        article_id = str(uuid.uuid4())

        assets = self.generate_cover_assets(source_article, article_data, image_language)
        logger.info(f"Cover headline: {assets.get('headline', '')}")

        selected_style = random.choice(COVER_IMAGE_STYLES)
        logger.info(f"Cover style: {selected_style['name']}")

        image_prompt = self.generate_cover_prompt(source_article, assets, selected_style, image_language)
        logger.info("Generating cover image...")
        image_url = self.generate_image(image_prompt, article_id)
        if image_url:
            logger.info(f"Image URL: {image_url[:80]}...")
        else:
            logger.warning("Publishing article without image")

        # ----- Hindi translation -----
        logger.info("Generating Hindi translation...")
        hindi_data = self.generate_hindi_content(article_data)
        if hindi_data:
            logger.info("Hindi translation done")
        else:
            logger.warning("Hindi translation failed — continuing without Hindi content")

        # ----- Audio generation -----
        logger.info("Generating English audio (OpenAI nova)...")
        english_audio = self.generate_english_audio(article_data.get("full_text", ""))
        english_audio_url = None
        english_duration_ms = 0
        if english_audio:
            english_audio_url = self.upload_audio(
                english_audio, f"Knowledge/ArticleBot/{article_id}/audio.mp3"
            )
            english_duration_ms = _get_audio_duration_ms(english_audio)
            logger.info(f"English audio: {english_duration_ms}ms")
        else:
            logger.warning("English audio generation failed")

        hindi_audio_url = None
        if hindi_data and hindi_data.get("full_text"):
            logger.info("Generating Hindi audio (Sarvam bulbul:v3 aditya)...")
            hindi_audio = self.generate_hindi_audio(_sanitize_hindi_text(hindi_data["full_text"]))
            if hindi_audio:
                hindi_audio_url = self.upload_audio(
                    hindi_audio, f"Knowledge/ArticleBot/{article_id}/Hindi.mp3"
                )
                logger.info("Hindi audio uploaded")
            else:
                logger.warning("Hindi audio generation failed")

        doc_id = self.push_article_to_db(
            article_data, image_url, article_id, source_article,
            selected_style["name"], image_language,
            hindi_data=hindi_data,
            english_audio_url=english_audio_url,
            english_duration_ms=english_duration_ms,
            hindi_audio_url=hindi_audio_url,
        )
        if not doc_id:
            return None

        if advance_state:
            self.state["last_date"] = date.today().isoformat()
            self.state["last_article_id"] = doc_id
            self.state["next_image_language"] = _flip_image_language(image_language)
            self.state.setdefault("posted_article_ids", []).append(str(source_article["_id"]))
            self._save_state()
            logger.info(
                f"State saved. Next image language: {self.state['next_image_language']}. "
                f"Published {len(self.state['posted_article_ids'])} articles so far."
            )

        logger.info(f"[SUCCESS] Article created: {doc_id}")
        return doc_id

    def run_daily(self) -> Optional[str]:
        today_iso = date.today().isoformat()
        logger.info("=" * 60)
        logger.info("TATTVALOKA MAGAZINE ARTICLE GENERATOR")
        logger.info(f"Date: {today_iso}")
        logger.info(f"Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
        logger.info("=" * 60)

        if not self._should_post_today():
            return None

        return self.generate_and_publish(advance_state=True)


# Singleton
_generator: Optional[MagazineArticleGenerator] = None


def get_magazine_article_generator() -> MagazineArticleGenerator:
    global _generator
    if _generator is None:
        _generator = MagazineArticleGenerator()
    return _generator


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Tattvaloka Magazine Article Generator")
    parser.add_argument("--run-now", action="store_true",
                        help="Run daily publish (respects alternate-day schedule)")
    parser.add_argument("--test", action="store_true",
                        help="Generate one article without advancing state")
    parser.add_argument("--show-state", action="store_true",
                        help="Print current state")
    parser.add_argument("--reset-state", action="store_true",
                        help="Reset state to defaults (requires --yes-i-am-sure)")
    parser.add_argument("--yes-i-am-sure", action="store_true",
                        help="Confirm --reset-state")
    parser.add_argument("--list-articles", action="store_true",
                        help="List available curated Tattvaloka articles by category")
    parser.add_argument("--image-language", choices=["english", "hindi"],
                        help="Override cover image language for this run")

    args = parser.parse_args()

    if args.reset_state:
        if not args.yes_i_am_sure:
            print("[ABORT] --reset-state requires --yes-i-am-sure")
            sys.exit(1)
        state = {
            "last_date": None,
            "last_article_id": None,
            "posted_article_ids": [],
            "next_image_language": "english",
        }
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
                print("TATTVALOKA MAGAZINE ARTICLE STATE")
                print("=" * 60)
                print(f"Last date:          {state.get('last_date')}")
                print(f"Last article ID:    {state.get('last_article_id')}")
                print(f"Articles published: {len(state.get('posted_article_ids', []))}")
                print(f"Next image lang:    {state.get('next_image_language')}")
            else:
                print("No state file found.")
        except Exception as e:
            print(f"Error reading state: {e}")
        sys.exit(0)

    if args.list_articles:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client["dhyanapp"]
        pipeline = [
            {"$match": {"magazineSlug": MAGAZINE_SLUG, "category": {"$in": list(ALLOWED_CATEGORIES)}}},
            {"$group": {"_id": "$category", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        print("\nAvailable Tattvaloka articles (curated categories):")
        print(f"{'Category':<20} {'Count':>7}")
        print("-" * 30)
        total = 0
        for doc in db["source_magazine_articles"].aggregate(pipeline):
            print(f"{str(doc['_id']):<20} {doc['count']:>7}")
            total += doc["count"]
        print("-" * 30)
        print(f"{'TOTAL':<20} {total:>7}")
        sys.exit(0)

    if args.test:
        gen = get_magazine_article_generator()
        article_id = gen.generate_and_publish(
            advance_state=False, override_image_lang=args.image_language
        )
        if article_id:
            print(f"\n[SUCCESS] Test article created (state NOT advanced): {article_id}")
        else:
            print("\n[ERROR] Failed to create test article")
        sys.exit(0 if article_id else 1)

    if args.run_now:
        gen = get_magazine_article_generator()
        article_id = gen.run_daily()
        if article_id:
            print(f"\nCreated article: {article_id}")
        sys.exit(0)

    parser.print_help()
