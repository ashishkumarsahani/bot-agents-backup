"""
Tattvaloka Magazine Post Generator for DhyanApp.

Turns Tattvaloka magazine articles (MongoDB `source_magazine_articles`) into infographic
social posts on an alternate-day schedule (skips if last post was < 2 days ago).

Publishes under the Gita bot's user_id but with its own display name "Tattvaloka"
(persona key "tattvaloka" in bot_personas).

LLM pipeline (gpt-4o-mini):
  1. generate_post_from_article (temp=0.7): distil the article into a structured post +
     a clear, EXPLANATORY title that tells the reader what the article is about.
  2. generate_infographic_assets (temp=0.6): poster label / headline / key points / takeaway.

State persisted in magazine_post_state.json beside this script:
  last_date, last_post_id, posted_article_ids, next_image_language
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
STATE_FILE = Path(__file__).parent / "magazine_post_state.json"
MAGAZINE_ACCOUNT_KEY = "tattvaloka"
MAGAZINE_SLUG = "tattvaloka"
MAGAZINE_DISPLAY_NAME = "Tattvaloka"
GITA_BOT_USER_ID = "LHjuJnXcexRHVigsLlOSZlSVGPC3"  # reused per product decision

# Curated spiritual subset — exclude news, health, puzzle, other.
ALLOWED_CATEGORIES = {"article", "discourse", "story", "subhashita", "poem", "qna"}

MAGAZINE_IMAGE_MODEL = "gpt-image-2"
MAGAZINE_IMAGE_SIZE = "1024x1024"
MAGAZINE_IMAGE_QUALITY = "medium"
DHYAN_LOGO_PATH = "/home/admin/dhyanapp-services/images/dhyan_logo.png"

# Devotional closers fitting the Sringeri Sharada Peetham / Advaita tone of Tattvaloka.
MAGAZINE_CLOSERS = [
    "जय जगद्गुरु",
    "ॐ नमः शिवाय",
    "हर हर शंकर",
    "सत्यमेव जयते",
    "ॐ तत् सत्",
    "जय श्री शारदाम्बा",
]

# Tattvaloka is a refined PRINT JOURNAL of the Sringeri Sharada Peetham (Advaita
# Vedanta, Adi Shankara, Goddess Sharada). These styles are IMAGE-LED magazine
# feature openers: a strong classical illustration carries the page, balanced by a
# clean, minimal text area (kicker + feature title + one short line) — like a real
# Tattvaloka article opener. Distinct from the Gita devotional poster and the
# Scripture folk-art card, and deliberately NOT text-heavy.
MAGAZINE_IMAGE_STYLES = [
    {
        "name": "Cover Illustration Feature",
        "description": "A slim maroon-and-gold header band at the TOP carries the kicker and feature title; a large, dignified classical illustration of the subject fills the center beneath it — like a Tattvaloka cover/feature opener. Image dominant, text minimal",
        "colors": "warm cream, deep maroon, antique gold, and soft sepia",
    },
    {
        "name": "Hero Image with Title Header",
        "description": "A clean header at the TOP holds the kicker and feature title; one serene, painterly devotional illustration fills the center as the hero image, with a slim full-width summary band at the bottom. Balanced like a printed magazine feature",
        "colors": "ivory, deep maroon, gold leaf, and gentle earth tones",
    },
    {
        "name": "Framed Art Plate",
        "description": "A painterly art plate of the subject centered within an ornate gold-and-maroon border, the feature title in elegant serif above the plate and one short line below — like a classical magazine art plate. Mostly image",
        "colors": "antique gold, deep maroon, ivory, and rich painterly tones",
    },
    {
        "name": "Sringeri Temple Scene",
        "description": "A serene illustrated scene — the Sringeri Sharada temple by the Tunga river, or a calm sacred setting fitting the subject — as the dominant image, with the feature title in an elegant overlaid band. Atmospheric, image-led",
        "colors": "soft sandalwood, ivory, muted indigo, antique gold, and maroon",
    },
    {
        "name": "Deity Portrait Feature",
        "description": "A refined classical portrait illustration of the relevant deity, sage, or Adi Shankara as the focal image, with a small maroon nameplate kicker and the feature title in serif. Portrait dominant, text sparse",
        "colors": "deep maroon, gold, ivory, and warm devotional tones",
    },
    {
        "name": "Lamp-lit Contemplative Feature",
        "description": "An atmospheric devotional scene lit by oil lamps or soft divine light, evoking the article's mood, with a single elegant serif title and one short line in a calm corner. Mood and image lead, very little text",
        "colors": "deep indigo, warm amber glow, gold, maroon, and ivory",
    },
    {
        "name": "Sacred Symbol Hero",
        "description": "One large central sacred motif — Om, Goddess Sharada's veena, or a lotus — rendered as elegant focal art, with the feature title beneath in serif and a thin gold rule. Symbol dominant, minimal words",
        "colors": "ivory, antique gold, deep maroon, lotus white, and muted blue",
    },
    {
        "name": "Manuscript Art Plate",
        "description": "An aged-paper page with a single fine painterly illustration of the subject as the centerpiece and a short calligraphic-style serif title; subtle palm-leaf texture at the edges. Balanced art-and-title, not text-filled",
        "colors": "aged parchment, sepia, deep maroon, faded gold, and ink black",
    },
]


def _flip_image_language(lang: str) -> str:
    return "hindi" if lang == "english" else "english"


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


class MagazinePostGenerator:
    """Generates posts from Tattvaloka magazine articles, posting on alternate days."""

    def __init__(self):
        self.account = self._load_account()
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

    def _load_account(self) -> dict:
        try:
            persona = get_persona(MAGAZINE_ACCOUNT_KEY)
            if not persona:
                raise RuntimeError(
                    f"Persona '{MAGAZINE_ACCOUNT_KEY}' not found in bot_personas. "
                    f"Run: python magazine_post_generator.py --setup-persona"
                )
            persona["account_key"] = MAGAZINE_ACCOUNT_KEY
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
        """Dhyan logo at top-right, matching the scripture bot's placement."""
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

    # ----- article selection -----

    def _get_all_articles(self) -> list:
        """Fetch all curated-category Tattvaloka articles from MongoDB. Cached per run."""
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
            for a in cursor:
                if not (a.get("body") or a.get("summary")):
                    continue
                articles.append(a)
            self._articles_cache = articles
            logger.info(f"Loaded {len(articles)} curated Tattvaloka articles from MongoDB")
            return articles
        except Exception as e:
            logger.error(f"[ERROR] Failed to load magazine articles: {e}")
            return []

    def _select_random_article(self) -> Optional[dict]:
        """Pick a random unposted article. Resets the pool when all are exhausted."""
        all_articles = self._get_all_articles()
        if not all_articles:
            return None

        posted_ids = set(str(a) for a in self.state.get("posted_article_ids", []))
        available = [a for a in all_articles if str(a["_id"]) not in posted_ids]

        if not available:
            logger.info("[POOL] All articles posted. Resetting posted list and restarting.")
            self.state["posted_article_ids"] = []
            self._save_state()
            available = all_articles

        article = random.choice(available)
        logger.info(
            f"Selected: [{article.get('category')}] {article.get('title')} "
            f"({article.get('month')})"
        )
        return article

    # ----- LLM: generate post from article -----

    def generate_post_from_article(self, article: dict) -> Optional[dict]:
        """
        Distil a Tattvaloka article into a structured post with a clear, EXPLANATORY title.
        The title must tell the reader what the article actually explains — not a poetic teaser.
        """
        title = (article.get("title") or "").strip()
        author = (article.get("author") or "").strip()
        category = (article.get("category") or "article").strip()
        month = (article.get("month") or "").strip()
        summary = (article.get("summary") or "").strip()
        body = (article.get("body") or "").strip()[:4000]
        tags = article.get("tags") or []
        tags_str = ", ".join(tags) if tags else ""

        persona = (self.account.get("persona") or "").strip()
        conv_style = (self.account.get("conversational_style") or "").strip()

        header_label = f"Tattvaloka · {month} · {category.capitalize()}" if month else f"Tattvaloka · {category.capitalize()}"
        attribution = f"From Tattvaloka, {month}" if month else "From Tattvaloka"
        if author:
            attribution += f" — {author}"

        category_guidance = {
            "story": "This is a story/episode. Retell its arc briefly and faithfully — name the characters, what happened, and the spiritual point it makes.",
            "discourse": "This is a discourse/teaching. Distil the core teaching into 2-4 clear key insights, faithful to the text.",
            "article": "This is an essay. Distil its central argument into 2-4 clear key insights, faithful to the text.",
            "subhashita": "This is a subhashita (wisdom verse). Present the verse's idea and its meaning. If a Devanagari shloka appears in the body, you may quote it verbatim.",
            "poem": "This is a devotional poem. Convey its imagery and feeling, and the devotional point it expresses.",
            "qna": "This is a question-and-answer piece. State the question clearly, then the essence of the answer.",
        }
        guidance = category_guidance.get(category, category_guidance["article"])
        closer = random.choice(MAGAZINE_CLOSERS)

        prompt = f"""You are the curator voice of Tattvaloka, the Sringeri Sharada Peetham monthly on Sanatana Dharma, writing a daily post for a spiritual social app.

Persona: {persona}
Voice: {conv_style}

Today's article (from Tattvaloka, {month}):
Original magazine title: {title}
Category: {category}
{f'Tags: {tags_str}' if tags_str else ''}

Summary (reference):
{summary}

Article body (your PRIMARY source — be faithful, invent nothing):
{body}

{guidance}

Write a post in ENGLISH, 150-230 words, in this EXACT structure (use real newlines between sections):

1. Header line on its own: "{header_label}"
2. An EXPLANATORY title on its own line — a clear, informative title that tells the reader exactly what this article is about and what they will learn from it. It should explain the content, NOT be a vague poetic teaser. (You may keep the spirit of the original title but make it clearly descriptive.)
3. "What it's about": 1-2 sentences orienting the reader to the article's subject.
4. The core: 2-4 distilled key insights or a tight faithful retelling per the category guidance above. Stay true to the body; do not add facts that are not in it.
5. A reflection of 2-3 sentences in first person — how to carry this teaching into daily life. No clichés like "fast-paced modern life" or generic self-help framing.
6. End with this exact closing line (do not modify): {closer}
7. A final line of attribution (do not add any link): {attribution}

Do NOT include IAST transliteration. If the body contains a Devanagari shloka, you may quote it verbatim; otherwise do not invent one.

Return ONLY valid JSON:
{{
  "content": "full post body with real newlines between sections",
  "title": "the explanatory title from section 2 (clear and descriptive)",
  "description": "15-25 word summary of what this article explains",
  "key_points": ["2-4 short key insight phrases drawn from the article"],
  "source_topic": "Tattvaloka {month} {category}"
}}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are the curator of Tattvaloka magazine. You distil sacred-text articles "
                            "into clear, faithful posts with explanatory titles. You never invent facts "
                            "beyond the article. Always return valid JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=1200,
            )
            record_openai_response(response, service="magazine_post.generate")
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            data = json.loads(content)
            # The model occasionally omits title/description — backfill so the
            # stored description field and logs are never blank.
            if not (data.get("title") or "").strip():
                body_lines = [l.strip() for l in (data.get("content") or "").splitlines() if l.strip()]
                # line 0 is the header ("Tattvaloka · ..."), line 1 is the explanatory title
                data["title"] = body_lines[1] if len(body_lines) > 1 else title
            if not (data.get("description") or "").strip():
                data["description"] = summary[:160].rstrip() if summary else data["title"]
            return data
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate post: {e}")
            return None

    # ----- infographic assets -----

    def generate_infographic_assets(
        self, article: dict, post_data: dict, image_language: str = "english"
    ) -> dict:
        """Produce label / headline / key_points / takeaway strings for the infographic renderer."""
        month = (article.get("month") or "").strip()
        category = (article.get("category") or "article").strip()
        title = post_data.get("title") or article.get("title") or ""
        description = post_data.get("description", "")
        key_points = post_data.get("key_points") or []
        key_points_str = " | ".join(str(p) for p in key_points)[:300]

        if image_language == "hindi":
            lang_instruction = (
                "All strings (label, headline, key_points, takeaway) MUST be in Hindi using Devanagari script, "
                "translated faithfully from the English reference text. Do not use English words except digits."
            )
            label_default = f"तत्त्वलोक · {month}" if month else "तत्त्वलोक"
        else:
            lang_instruction = "All strings MUST be in clear, simple English."
            label_default = f"Tattvaloka · {month}" if month else "Tattvaloka"

        prompt = f"""Prepare text to render onto a Tattvaloka magazine infographic poster.

Article title (reference): {title}
Category: {category}
Summary (reference): {description}
Key points (reference): {key_points_str}

{lang_instruction}

Return ONLY valid JSON with exactly these keys:
{{
  "label": "short magazine label e.g. '{label_default}'",
  "headline": "3-7 word explanatory title for this article (says what it is about)",
  "key_points": ["2-3 very short phrases, max 6 words each, capturing the main points"],
  "takeaway": "core teaching of this article in 12-20 plain readable words"
}}

Keep text short enough to render cleanly on a poster. No quotation marks inside values."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You craft concise poster text for magazine infographics. Always return valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
                max_tokens=400,
            )
            record_openai_response(response, service="magazine_post.infographic_assets")
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            data = json.loads(content)
            pts = data.get("key_points") or key_points
            return {
                # label is set deterministically from the real month — the model
                # tends to hallucinate the date, so we never trust its label.
                "label": label_default,
                "headline": data.get("headline") or title,
                "key_points": [str(p) for p in pts][:3],
                "takeaway": data.get("takeaway") or description,
            }
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate infographic assets: {e}")
            return {
                "label": label_default,
                "headline": title,
                "key_points": [str(p) for p in key_points][:3],
                "takeaway": description[:120],
            }

    def generate_infographic_prompt(
        self, article: dict, assets: dict, style: dict, image_language: str = "english"
    ) -> str:
        label = assets["label"].replace('"', "'")
        headline = assets["headline"].replace('"', "'")
        takeaway = assets["takeaway"].replace('"', "'")
        category = (article.get("category") or "article").strip()

        theme = headline
        if takeaway:
            theme += f". {takeaway}"

        scene_hints = {
            "story": (
                "Depict the key moment of the story — the characters, setting, and action — as a beautiful, "
                "dignified classical illustration that fills most of the page."
            ),
            "discourse": (
                "Show a serene sacred scene fitting the teaching — a sage or guru in a calm temple or natural setting, "
                "or the Sringeri Sharada temple by the Tunga river — as a rich, atmospheric illustration."
            ),
            "article": (
                "Show one strong, evocative classical illustration of the article's central subject "
                "(the deity, sage, place, or idea) as the dominant image."
            ),
            "subhashita": (
                "Show an elegant symbolic illustration of the verse's image (a lamp, lotus, river, or sage) "
                "as the focal art, calm and refined."
            ),
            "poem": (
                "Show a soft, lyrical devotional scene evoking the poem's imagery — light, lotus, flame, or the divine — "
                "as the dominant, atmospheric illustration."
            ),
            "qna": (
                "Show a serene seeker-and-sage scene as the focal illustration — two figures in calm dialogue "
                "in a sacred setting."
            ),
        }
        scene_hint = scene_hints.get(category, scene_hints["article"])

        return (
            f"A premium SQUARE magazine feature opener for \"Tattvaloka\", the refined print journal of the Sringeri "
            f"Sharada Peetham on Advaita Vedanta and Sanatana Dharma, in the \"{style['name']}\" style: {style['description']}. "
            f"Color palette: {style['colors']}. "

            f"BALANCE: this is an IMAGE-LED magazine page — a strong, beautiful classical illustration carries the page, "
            f"paired with a small, clean text area. Roughly two-thirds image, one-third text. "
            f"It must feel like a real Tattvaloka article opener — dignified, painterly, and devotional — "
            f"NOT a flat poster, NOT folk or tribal art, NOT an icon-and-bullet infographic. "

            f"MAIN ILLUSTRATION (the focal point of the page): {scene_hint} "
            f"Subject for the illustration: {theme}. "
            f"Render it richly and elegantly, with classical Indian devotional art sensibility. "

            f"TEXT — render ONLY these few short lines, cleanly, in "
            f"{'elegant Devanagari Hindi typography' if image_language == 'hindi' else 'an elegant editorial serif typeface'}: "
            f"(1) a small kicker line reading: {label}, "
            f"(2) the feature title, large and prominent, reading: {headline}, "
            f"(3) a summary line at a clearly legible, comfortable reading size (NOT tiny, NOT decorative) "
            f"reading exactly: {takeaway}. "
            f"This summary line must be fully readable and never clipped or shrunk into illegibility. "
            f"Do NOT add any body paragraphs, text columns, drop caps, marginalia, captions, page numbers, "
            f"or any extra/placeholder/lorem text. Those three lines are the only text. "

            f"LAYOUT (top-to-bottom, like a classical magazine article opener): "
            f"TOP — a clean header band holding the small kicker (element 1) and, directly below it, the large feature "
            f"title (element 2), both at the top of the page. "
            f"MIDDLE — the main illustration sits below the header as the central focal area of the page. "
            f"BOTTOM — the summary line (element 3) spans the full width of a clean band across the bottom, centered, "
            f"tall enough to display the complete line comfortably and never clipped. "
            f"Keep the kicker and title strictly at the TOP and the summary strictly at the BOTTOM. "
            f"Leave a small clean empty area in the UPPER-RIGHT corner of the header free of text and imagery so a brand logo fits without overlap. "

            f"Overall feel: dignified, painterly, premium, contemplative — a quality spiritual magazine feature. "
            f"Do NOT include any transliteration or Latin-script romanization of Sanskrit."
        )

    # ----- image -----

    def generate_image(self, prompt: str, post_id: str) -> Optional[str]:
        if not self.s3_client:
            logger.error("[ERROR] MinIO not initialized")
            return None
        try:
            response = self.client.images.generate(
                model=MAGAZINE_IMAGE_MODEL,
                prompt=prompt,
                size=MAGAZINE_IMAGE_SIZE,
                quality=MAGAZINE_IMAGE_QUALITY,
                n=1,
            )
            _img_price = {"low": 0.01, "medium": 0.04, "high": 0.17}
            try:
                record_usage(
                    "openai", MAGAZINE_IMAGE_MODEL, "magazine_post.generate_image",
                    images=1,
                    cost_usd=_img_price.get(MAGAZINE_IMAGE_QUALITY, 0.04),
                    meta={"size": MAGAZINE_IMAGE_SIZE, "quality": MAGAZINE_IMAGE_QUALITY},
                )
            except Exception as track_err:
                logger.warning(f"Failed to record image usage: {track_err}")

            raw_bytes = base64.b64decode(response.data[0].b64_json)
            image = Image.open(io.BytesIO(raw_bytes))
            image = self._apply_watermark_top_right(image)
            buf = io.BytesIO()
            image.save(buf, format="WEBP", lossless=True)

            object_key = f"Posts/images/bot_magazine/{post_id}.webp"
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
        article: dict,
        image_style: str,
        image_language: str = "english",
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
            "description": f"{post_data.get('title', '')} - {post_data.get('description', '')}",
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
            "_generatorType": "magazine_article",
            "_language": "english",
            "_imageLanguage": image_language,
            "_imageStyle": image_style,
            "_magazineSlug": MAGAZINE_SLUG,
            "_magazineMonth": article.get("month", ""),
            "_magazineCategory": article.get("category", ""),
            "_articleId": str(article.get("_id", "")),
            "_issueId": str(article.get("issueId", "")),
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

    def generate_and_post(
        self, *, advance_state: bool = True, override_image_lang: Optional[str] = None
    ) -> Optional[str]:
        article = self._select_random_article()
        if article is None:
            logger.error("[ERROR] No article available to post")
            return None

        category = article.get("category", "?")
        month = article.get("month", "?")
        image_language = override_image_lang or self.state.get("next_image_language", "english")

        logger.info(f"\n{'='*60}")
        logger.info(f"GENERATING MAGAZINE POST: [{category}] {article.get('title')} ({month}) (image: {image_language})")
        logger.info(f"{'='*60}")

        post_data = self.generate_post_from_article(article)
        if not post_data:
            logger.error("Failed to generate post content")
            return None
        logger.info(f"Title: {post_data.get('title', 'N/A')}")

        post_id = str(uuid.uuid4())

        assets = self.generate_infographic_assets(article, post_data, image_language)
        logger.info(f"Infographic headline: {assets.get('headline', '')}")

        selected_style = random.choice(MAGAZINE_IMAGE_STYLES)
        logger.info(f"Image style: {selected_style['name']}")

        image_prompt = self.generate_infographic_prompt(article, assets, selected_style, image_language)
        logger.info("Generating infographic image...")
        image_url = self.generate_image(image_prompt, post_id)
        if image_url:
            logger.info(f"Image URL: {image_url[:80]}...")
        else:
            logger.warning("Posting without image")

        doc_id = self.push_post_to_db(
            post_data, image_url, post_id, article, selected_style["name"], image_language
        )
        if not doc_id:
            return None

        if advance_state:
            self.state["last_date"] = date.today().isoformat()
            self.state["last_post_id"] = doc_id
            self.state["next_image_language"] = _flip_image_language(image_language)
            self.state.setdefault("posted_article_ids", []).append(str(article["_id"]))
            self._save_state()
            logger.info(
                f"State saved. Next image language: {self.state['next_image_language']}. "
                f"Posted {len(self.state['posted_article_ids'])} articles so far."
            )

        logger.info(f"[SUCCESS] Magazine post created: {doc_id}")
        return doc_id

    def run_daily_post(self) -> Optional[str]:
        today_iso = date.today().isoformat()
        logger.info("=" * 60)
        logger.info("TATTVALOKA MAGAZINE POST GENERATOR")
        logger.info(f"Date: {today_iso}")
        logger.info(f"Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
        logger.info("=" * 60)

        if not self._should_post_today():
            return None

        return self.generate_and_post(advance_state=True)


# Singleton
_generator: Optional[MagazinePostGenerator] = None


def get_magazine_post_generator() -> MagazinePostGenerator:
    global _generator
    if _generator is None:
        _generator = MagazinePostGenerator()
    return _generator


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Tattvaloka Magazine Post Generator")
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
                        help="Insert/update the Tattvaloka persona in bot_personas collection")
    parser.add_argument("--list-articles", action="store_true",
                        help="List available curated Tattvaloka articles by category")
    parser.add_argument("--image-language", choices=["english", "hindi"],
                        help="Override infographic language for this run")

    args = parser.parse_args()

    if args.setup_persona:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client["dhyanapp"]
        existing = db["bot_personas"].find_one({"_id": MAGAZINE_ACCOUNT_KEY})
        persona_doc = {
            "name": MAGAZINE_DISPLAY_NAME,
            "user_id": GITA_BOT_USER_ID,
            "persona": (
                "Curator of Tattvaloka, the Sringeri Sharada Peetham monthly on Sanatana Dharma. "
                "Distils each article into a clear, faithful summary for daily readers."
            ),
            "conversational_style": (
                "Dignified, lucid, reverent. Explains first, never preaches. "
                "Leads with what the piece is about."
            ),
            "comment_style": (
                "Replies briefly and warmly. Points readers to the relevant article or teaching. "
                "Never debates."
            ),
            "topics": [],
            "scriptures": [],
            "follows": [],
            "languages": [],
            "updated_at": datetime.now(IST).isoformat(),
        }
        db["bot_personas"].update_one(
            {"_id": MAGAZINE_ACCOUNT_KEY},
            {"$set": persona_doc},
            upsert=True,
        )
        action = "Updated" if existing else "Created"
        print(f"[OK] {action} persona '{MAGAZINE_ACCOUNT_KEY}':")
        print(f"     name={persona_doc['name']}")
        print(f"     user_id={persona_doc['user_id']}")
        sys.exit(0)

    if args.reset_state:
        if not args.yes_i_am_sure:
            print("[ABORT] --reset-state requires --yes-i-am-sure")
            sys.exit(1)
        state = {
            "last_date": None,
            "last_post_id": None,
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
                print("TATTVALOKA MAGAZINE POST STATE")
                print("=" * 60)
                print(f"Last date:        {state.get('last_date')}")
                print(f"Last post ID:     {state.get('last_post_id')}")
                print(f"Articles posted:  {len(state.get('posted_article_ids', []))}")
                print(f"Next image lang:  {state.get('next_image_language')}")
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
        gen = get_magazine_post_generator()
        post_id = gen.generate_and_post(advance_state=False, override_image_lang=args.image_language)
        if post_id:
            print(f"\n[SUCCESS] Test post created (state NOT advanced): {post_id}")
        else:
            print("\n[ERROR] Failed to create test post")
        sys.exit(0 if post_id else 1)

    if args.run_now:
        gen = get_magazine_post_generator()
        post_id = gen.run_daily_post()
        if post_id:
            print(f"\nCreated post: {post_id}")
        sys.exit(0)

    parser.print_help()
