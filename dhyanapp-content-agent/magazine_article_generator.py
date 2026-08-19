"""
Tattvaloka Magazine Article Generator for DhyanApp.

Turns Tattvaloka magazine articles (MongoDB `source_magazine_articles`) into long-form
articles published to `article_files_v1` on an alternate-day schedule.

Cover image: landscape 1536×1024, magazine-cover style (full-bleed classical illustration
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

# Every magazine the bot may draw from. The daily run picks TWO at random from
# whichever of these currently have articles (see run_daily), so a magazine with
# no articles yet (e.g. freshly-added Chandamama before it's OCR'd/processed) is
# simply skipped until it has content.
MAGAZINE_ROTATION = [
    "tattvaloka", "vedanta-kesari", "kalyan", "prabuddha-bharati",
    "chandamama",
]

MAGAZINES = {
    "tattvaloka": {
        "slug": "tattvaloka",
        "name": "Tattvaloka",
        "name_hindi": "तत्त्वलोक",
        "bio": (
            "Tattvaloka is the monthly journal of the Sringeri Sharada Peetham on "
            "Sanatana Dharma, Advaita Vedanta, and Indian culture."
        ),
        "bio_hindi": (
            "तत्त्वलोक, श्रृंगेरी शारदा पीठम की मासिक पत्रिका है, जो सनातन धर्म, "
            "अद्वैत वेदांत और भारतीय संस्कृति पर केंद्रित है।"
        ),
        "cover_journal_desc": (
            "the refined print journal of the Sringeri Sharada Peetham on Advaita Vedanta "
            "and Sanatana Dharma"
        ),
        "creator_id_fallback": "30JNWvp12Wxk4V8KfDBA",
        "profile_image_url_fallback": "https://storage.dhyanapp.org/dhyanapp-recordings/creator-profiles/30JNWvp12Wxk4V8KfDBA.jpg",
    },
    "vedanta-kesari": {
        "slug": "vedanta-kesari",
        "name": "Vedanta Kesari",
        "name_hindi": "वेदान्त केसरी",
        "bio": (
            "Vedanta Kesari is the monthly journal of Sri Ramakrishna Math on "
            "Vedanta, Indian culture, and spiritual wisdom."
        ),
        "bio_hindi": (
            "वेदान्त केसरी, श्री रामकृष्ण मठ की मासिक पत्रिका है, जो वेदांत, "
            "भारतीय संस्कृति और आध्यात्मिक ज्ञान पर केंद्रित है।"
        ),
        "cover_journal_desc": (
            "the monthly journal of Sri Ramakrishna Math on Vedanta, Indian culture, "
            "and spiritual wisdom"
        ),
        "creator_id_fallback": "7144ff02f4844d58b657b49df660",
        "profile_image_url_fallback": "https://storage.dhyanapp.org/dhyanapp-recordings/creator-profiles/7144ff02f4844d58b657b49df660.png",
    },
    "kalyan": {
        "slug": "kalyan",
        "name": "Kalyan",
        "name_hindi": "कल्याण",
        "bio": (
            "Kalyan is the monthly Hindi spiritual magazine of Gita Press, Gorakhpur, "
            "published since 1926, covering Sanatana Dharma, Vedanta, and Indian culture."
        ),
        "bio_hindi": (
            "कल्याण गीता प्रेस, गोरखपुर की मासिक हिंदी पत्रिका है, जो 1926 से प्रकाशित है और "
            "सनातन धर्म, वेदांत तथा भारतीय संस्कृति पर केंद्रित है।"
        ),
        "cover_journal_desc": (
            "the monthly Hindi spiritual magazine of Gita Press, Gorakhpur"
        ),
        "creator_id_fallback": "21TbwsVF3YuH10Qd5fTm",
        "profile_image_url_fallback": "https://archive.org/services/img/PCGc_kalyan-issue-no.-11-vol.-53-november-1979-gita-press",
    },
    "prabuddha-bharati": {
        "slug": "prabuddha-bharati",
        "name": "Prabuddha Bharata",
        "name_hindi": "प्रबुद्ध भारत",
        "bio": (
            "Prabuddha Bharata is the monthly English journal of Advaita Ashrama, "
            "Ramakrishna Math, on Vedanta, spiritual life, and Indian culture, "
            "published since 1896."
        ),
        "bio_hindi": (
            "प्रबुद्ध भारत, अद्वैत आश्रम (रामकृष्ण मठ) की मासिक अंग्रेज़ी पत्रिका है, जो 1896 से "
            "प्रकाशित है और वेदांत, आध्यात्मिक जीवन तथा भारतीय संस्कृति पर केंद्रित है।"
        ),
        "cover_journal_desc": (
            "the monthly English journal of Advaita Ashrama, Ramakrishna Math, on Vedanta "
            "and spiritual life"
        ),
        "creator_id_fallback": "7dbfcYZjHyBlzebJU8eI",
        "profile_image_url_fallback": "https://advaitaashrama.org/wp-content/uploads/PB-January-2023-Complete-for-Online-1-1.png",
    },
    # Newer magazines. They have no articles until their issues are OCR'd and
    # processed in Creator-Tools-Web; until then run_daily's pool filter skips
    # them. creator_id/profile resolve from creator_profiles (auto-created by the
    # CTW process step) — the fallbacks below are only a last resort.
    "chandamama": {
        "slug": "chandamama",
        "name": "Chandamama",
        "name_hindi": "चंदामामा",
        "bio": (
            "Chandamama is the classic Indian children's magazine (1947–2013), "
            "celebrated for its folklore, mythology, and moral tales in Hindi and English."
        ),
        "bio_hindi": (
            "चंदामामा एक प्रसिद्ध भारतीय बाल पत्रिका (1947–2013) है, जो अपनी लोककथाओं, "
            "पौराणिक कथाओं और नैतिक कहानियों के लिए जानी जाती है।"
        ),
        "cover_journal_desc": (
            "the classic Indian children's magazine of folklore, mythology, and moral tales"
        ),
        "creator_id_fallback": "8Pnzmjlhkbdp1dzn6Kso",
        "profile_image_url_fallback": "https://archive.org/services/img/Chandamama-English-1980-11",
    },
}

ALLOWED_CATEGORIES = {"article", "discourse", "story", "subhashita", "poem", "qna"}

# Script detectors for language-purity enforcement (English must have no
# Devanagari; Hindi must have no Latin word-runs).
_DEVANAGARI_RE = re.compile(r'[ऀ-ॿ]')
_LATIN_RUN_RE = re.compile(r'[A-Za-z]{3,}')

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

DHYANAPP_SERVICES_URL = "https://services.dhyanapp.org"

# The /cover/generate-localized service returns localized_teaserImage keyed by
# lowercase language NAME ("hindi", "bengali", ...). The app resolves images by ISO
# locale (see primary_titles/sub_titles below and AppLanguage in DhyanApp
# core/common/.../locale/LocaleManager.kt), so a name-keyed map is never found. Convert
# to ISO codes before storing. Covers every AppLanguage entry; extras/unknowns pass
# through lowercased so the map is also idempotent on already-coded input.
_TEASER_LANG_NAME_TO_CODE = {
    "assamese": "as", "bengali": "bn", "english": "en", "gujarati": "gu",
    "hindi": "hi", "kannada": "kn", "malayalam": "ml", "marathi": "mr",
    "odia": "or", "punjabi": "pa", "tamil": "ta", "telugu": "te",
    "spanish": "es", "french": "fr", "italian": "it",
}


def _teaser_map_to_iso(localized: Optional[dict]) -> dict:
    """Re-key a localized_teaserImage map from language name to ISO code.

    Idempotent: an already-coded key ("en") isn't in the map and passes through
    unchanged. Blank URLs are dropped."""
    out: dict = {}
    for name, url in (localized or {}).items():
        key = str(name).strip().lower()
        if not key or not url:
            continue
        out[_TEASER_LANG_NAME_TO_CODE.get(key, key)] = url
    return out

# Local AI TTS — free, offline, uses cloned voices via local-ai-tools
LOCAL_AI_TTS_URL = os.getenv("LOCAL_AI_TTS_URL", "http://localhost:8507")
LOCAL_AI_PASSWORD = os.getenv("LOCAL_AI_PASSWORD", "admin@6553")
USE_LOCAL_AUDIO = os.getenv("USE_LOCAL_AUDIO", "true").lower() == "true"

# Cloned voice profiles — one is chosen randomly per article for both EN + HI.
# Each voice is used for both languages (cloned timbre, not language-specific).
LOCAL_AI_VOICES = [
    ("eba63537", "Swami Atmashraddhananda"),
    ("73feaaa1", "Sw Suddhidhananda"),
    ("49bd830a", "S Vishwanath"),
    ("22f3ec30", "Ashish Sahani"),
    ("87dd47b5", "Rituparna"),
    ("d339aa34", "Ajay Chahal"),
]
ARTICLE_IMAGE_MODEL = "gpt-image-2"
ARTICLE_IMAGE_SIZE = "1536x1024"   # landscape — magazine cover
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

# Classical magazine-cover illustration styles — landscape, image-led, NOT infographic.
COVER_IMAGE_STYLES = [
    {
        "name": "Cover Illustration Feature",
        "description": (
            "A wide landscape magazine cover: a large, dignified classical Indian devotional "
            "illustration fills roughly two-thirds of the frame. A slim maroon-and-gold header "
            "band at the very TOP carries the kicker line and feature title in elegant serif. "
            "Below the header the illustration flows to the bottom edge. Image-dominant, "
            "minimal text — like a premium spiritual magazine cover."
        ),
        "colors": "warm cream, deep maroon, antique gold, and soft sepia",
    },
    {
        "name": "Hero Portrait Cover",
        "description": (
            "Full-bleed landscape painting of the central deity, sage, or sacred scene, "
            "richly rendered in classical Indian style. A clean white-ivory editorial strip "
            "at the TOP carries the small kicker and large feature title. The art bleeds to "
            "the left, right, and bottom edges — cinematic and devotional."
        ),
        "colors": "ivory, deep maroon, gold leaf, and warm devotional tones",
    },
    {
        "name": "Framed Art Plate Cover",
        "description": (
            "A wide landscape art plate: the subject rendered as a painterly classical "
            "illustration centered within an ornate gold-and-maroon border. The feature title "
            "appears in elegant serif at the top inside the border, a single short kicker above "
            "it. Mostly image — refined like a collectible magazine plate."
        ),
        "colors": "antique gold, deep maroon, ivory, and rich painterly tones",
    },
    {
        "name": "Sringeri Temple Scene Cover",
        "description": (
            "A serene wide landscape illustration of the Sringeri Sharada temple by the Tunga "
            "river, or a sacred landscape fitting the article — as the dominant visual filling "
            "most of the frame. The feature title sits in a calm overlaid editorial band near "
            "the top. Atmospheric and image-led."
        ),
        "colors": "soft sandalwood, ivory, muted indigo, antique gold, and maroon",
    },
    {
        "name": "Deity Portrait Cover",
        "description": (
            "A refined wide landscape painting of the relevant deity, sage, or Adi Shankara — "
            "head-and-shoulders to three-quarter length, positioned off-center — as the focal "
            "image filling the frame. Small maroon kicker and large serif feature title at the "
            "top, the rest is pure art. Image-dominant, very sparse text."
        ),
        "colors": "deep maroon, gold, ivory, and warm devotional tones",
    },
    {
        "name": "Lamp-lit Contemplative Cover",
        "description": (
            "A wide landscape atmospheric scene lit by oil lamps or soft divine light — evoking "
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
            "article's key symbol — rendered as elegant wide-format focal art filling the frame, "
            "the feature title beneath it in serif and a thin gold rule above. "
            "Symbol-dominant, minimal words."
        ),
        "colors": "ivory, antique gold, deep maroon, lotus white, and muted blue",
    },
    {
        "name": "Manuscript Art Cover",
        "description": (
            "An aged-parchment wide landscape with a single fine classical illustration of the "
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
    """Remove markdown syntax before sending to TTS.
    Ensures every line ends with a full stop or daṇḍa so the TTS engine
    inserts a natural pause at line breaks."""
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)   # headings
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)                  # bold
    text = re.sub(r'\*(.+?)\*', r'\1', text)                       # italic
    text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)       # bullet lists
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)      # numbered lists
    text = re.sub(r'\n---+\n', '\n', text)                         # hr
    text = re.sub(r'\n{3,}', '\n\n', text)                        # excess blank lines

    # Ensure each line ends with sentence-ending punctuation for TTS pauses.
    # Convert Devanagari daṇḍa/double-daṇḍa to periods — XTTS
    # doesn't recognise ।/॥ as sentence boundaries, so they produce no pause.
    text = text.replace("॥", ".").replace("।", ".")
    lines = []
    for line in text.split('\n'):
        line = line.rstrip()
        if not line:
            lines.append('')
            continue
        # Check if line already ends with . ! ? or :
        if line[-1] in '.!?:;—':
            lines.append(line)
        else:
            lines.append(line + '.')
    text = '\n'.join(lines)
    # Collapse newlines into period+space — XTTS treats \n as whitespace and
    # reads across line breaks without pausing. A period forces a sentence break.
    # Paragraph breaks (\n\n) get a double period (. . ) for a longer pause
    # so the TTS creates a clear break between title and body.
    text = re.sub(r'\n\n+', '. . ', text)
    text = re.sub(r'\n+', '. ', text)
    text = re.sub(r'\. \. ', '. ', text)  # clean up ". . " from empty lines
    text = re.sub(r'\.{2,}', '. ', text)  # collapse multiple periods
    text = re.sub(r'\.  +', '. ', text)   # collapse ".  " (double space) → ". "
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


def _wav_bytes_to_mp3(wav_bytes: bytes) -> Optional[bytes]:
    """Transcode WAV bytes to MP3 via ffmpeg (local TTS returns WAV;
    the pipeline stores/plays MP3). Returns None on failure."""
    wav_path = mp3_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            f.write(wav_bytes)
            wav_path = f.name
        mp3_path = wav_path[:-4] + '.mp3'
        subprocess.run(
            ['ffmpeg', '-y', '-i', wav_path, '-codec:a', 'libmp3lame', '-qscale:a', '2', mp3_path],
            check=True, capture_output=True, timeout=180,
        )
        with open(mp3_path, 'rb') as f:
            return f.read()
    except Exception as e:
        logger.warning(f"[tts] wav->mp3 conversion failed: {e}")
        return None
    finally:
        for p in (wav_path, mp3_path):
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass


def _sentence_chunks(text: str, max_len: int = 800) -> list:
    """Split text into <= max_len chunks at sentence/space boundaries."""
    chunks, remaining = [], text.strip()
    while len(remaining) > max_len:
        idx = remaining.rfind('.', 0, max_len)
        if idx == -1:
            idx = remaining.rfind(' ', 0, max_len)
        if idx == -1:
            idx = max_len
        chunks.append(remaining[:idx + 1].strip())
        remaining = remaining[idx + 1:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _concat_wavs_to_mp3(wav_buffers: list) -> Optional[bytes]:
    """Concatenate WAV byte-buffers into one MP3 via ffmpeg (concat demuxer)."""
    if not wav_buffers:
        return None
    if len(wav_buffers) == 1:
        return _wav_bytes_to_mp3(wav_buffers[0])
    import shutil
    tmp = tempfile.mkdtemp()
    try:
        paths = []
        for i, w in enumerate(wav_buffers):
            p = os.path.join(tmp, f"chunk_{i}.wav")
            with open(p, "wb") as f:
                f.write(w)
            paths.append(p)
        lst = os.path.join(tmp, "concat.txt")
        with open(lst, "w") as f:
            for p in paths:
                f.write(f"file '{p}'\n")
        mp3 = os.path.join(tmp, "out.mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
             "-c:a", "libmp3lame", "-q:a", "2", mp3],
            capture_output=True, check=True,
        )
        with open(mp3, "rb") as f:
            return f.read()
    except Exception as e:
        logger.warning(f"[tts] wav concat failed: {e}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
    """Generates articles from Tattvaloka, Vedanta Kesari, Kalyan, and Prabuddha
    Bharata, rotating one magazine per day (round-robin through MAGAZINE_ROTATION)."""

    def __init__(self):
        self.state = self._load_state()
        self._initialize_mongodb()
        self._initialize_minio()
        self._load_config_from_mongo()
        self.client = OpenAI(api_key=self.openai_api_key)
        self.services_password = self.secrets.get("SERVICES_PASSWORD", "")
        self._load_watermark_logo()
        self._articles_cache: dict = {}

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

    def _load_creator_profile(self, magazine_slug: str):
        """Resolve the magazine's creator profile from DB by magazineSlug."""
        mag = MAGAZINES[magazine_slug]
        self.creator_id = mag["creator_id_fallback"]
        self.author_name = mag["name"]
        self.author_profile_image_url = mag["profile_image_url_fallback"]
        try:
            if self.db is not None:
                prof = self.db["creator_profiles"].find_one({"magazineSlug": magazine_slug})
                if prof:
                    self.creator_id = prof.get("selfId") or prof.get("_id") or self.creator_id
                    self.author_name = prof.get("name") or self.author_name
                    self.author_profile_image_url = (
                        prof.get("profileImageUrl") or self.author_profile_image_url
                    )
                    logger.info(
                        f"[creator] Resolved magazineSlug='{magazine_slug}' -> "
                        f"{self.creator_id} ({self.author_name})"
                    )
                else:
                    logger.warning(
                        f"[creator] No creator_profiles for magazineSlug='{magazine_slug}', "
                        f"using fallback {self.creator_id}"
                    )
        except Exception as e:
            logger.warning(f"[creator] Lookup failed, using fallback {self.creator_id}: {e}")

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
            "posted_article_ids_tattvaloka": [],
            "posted_article_ids_vedanta-kesari": [],
            "posted_article_ids_kalyan": [],
            "posted_article_ids_prabuddha-bharati": [],
            "next_magazine": "tattvaloka",
            "next_image_language": "english",
        }

    def _load_state(self) -> dict:
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, "r") as f:
                    loaded = json.load(f)
                merged = self._default_state()
                merged.update(loaded)
                # Migrate legacy posted_article_ids into tattvaloka bucket
                if "posted_article_ids" in merged:
                    merged["posted_article_ids_tattvaloka"] = merged.pop("posted_article_ids")
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
            return True
        except Exception:
            return True

    # ----- article selection -----

    def _get_all_articles(self, magazine_slug: str) -> list:
        if magazine_slug in self._articles_cache:
            return self._articles_cache[magazine_slug]
        if self.db is None:
            return []
        try:
            cursor = self.db["source_magazine_articles"].find(
                {
                    "magazineSlug": magazine_slug,
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
            self._articles_cache[magazine_slug] = articles
            logger.info(f"Loaded {len(articles)} curated {MAGAZINES[magazine_slug]['name']} articles from MongoDB")
            return articles
        except Exception as e:
            logger.error(f"[ERROR] Failed to load magazine articles: {e}")
            return []

    def _select_random_article(self, magazine_slug: str) -> Optional[dict]:
        all_articles = self._get_all_articles(magazine_slug)
        if not all_articles:
            return None

        state_key = f"posted_article_ids_{magazine_slug}"
        posted_ids = set(str(a) for a in self.state.get(state_key, []))
        available = [a for a in all_articles if str(a["_id"]) not in posted_ids]

        if not available:
            logger.info(f"[POOL] All {MAGAZINES[magazine_slug]['name']} articles posted. Resetting posted list.")
            self.state[state_key] = []
            self._save_state()
            available = all_articles

        article = random.choice(available)
        logger.info(
            f"Selected: [{article.get('category')}] {article.get('title')} "
            f"({article.get('month')})"
        )
        return article

    # ----- LLM: generate article from source -----

    def _purify_language(self, text: str, target_lang: str) -> str:
        """Safety net: ensure `text` is purely in target_lang ('English' or
        'Hindi'). Regex-gated — only when foreign script is actually present does
        it spend one LLM pass to rewrite it, preserving Markdown + meaning."""
        if not text or not text.strip():
            return text
        if target_lang == "English":
            if not _DEVANAGARI_RE.search(text):
                return text
            instruction = (
                "Rewrite the following text so it contains NO Devanagari, while preserving all content. "
                "For any Sanskrit verse or quoted scripture in Devanagari, CONVERT it to IAST (Roman "
                "diacritic transliteration) and keep it (you may add an English translation in parentheses). "
                "For ordinary Hindi prose in Devanagari, translate it into English. Leave existing English "
                "text and the Markdown structure unchanged. Output ONLY the corrected text — no commentary, "
                "no code fences."
            )
        else:  # Hindi
            scan = re.sub(r'https?://\S+', '', text)
            if not _LATIN_RUN_RE.search(scan):
                return text
            instruction = (
                "नीचे दिए गए पाठ को शुद्ध हिन्दी (केवल देवनागरी लिपि) में फिर से लिखें। सभी अंग्रेज़ी/रोमन "
                "शब्दों का हिन्दी में अनुवाद करें या उन्हें देवनागरी में लिप्यंतरित करें। Markdown संरचना और "
                "अर्थ को अक्षरशः बनाए रखें। केवल सुधारा हुआ पाठ लौटाएँ — कोई टिप्पणी नहीं, कोई code fence नहीं।"
            )
        try:
            resp = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You rewrite text into a single target language/script, preserving Markdown and meaning."},
                    {"role": "user", "content": f"{instruction}\n\n---\n{text}"},
                ],
                temperature=0.2, max_tokens=2500,
            )
            record_openai_response(resp, service="magazine_article.purify")
            out = (resp.choices[0].message.content or "").strip()
            if out.startswith("```"):
                parts = out.split("```")
                out = parts[1] if len(parts) > 1 else out
                out = re.sub(r'^(markdown|md|text)\n', '', out.strip())
            logger.info(f"[purity] repaired {target_lang} text ({len(text)}→{len(out)} chars)")
            return out.strip() or text
        except Exception as e:
            logger.warning(f"[purity] {target_lang} repair failed: {e}")
            return text

    def generate_article_from_source(self, article: dict, magazine_config: dict) -> Optional[dict]:
        """
        Distil a magazine source article into a long-form Markdown article
        with an explanatory title, subtitle, short description, and full body.
        """
        magazine_name = magazine_config["name"]
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
        attribution = f"From {magazine_name}, {month}" if month else f"From {magazine_name}"
        if author:
            attribution += f" — {author}"

        prompt = f"""You are writing a long-form article for DhyanApp based on a {magazine_name} magazine piece.

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
- Write all prose in English. A Sanskrit verse or a short scriptural quotation MAY be included, but render it in IAST (Roman diacritic transliteration) — NOT Devanagari — and you may follow it with an English translation. Do NOT put ordinary Hindi prose in Devanagari; the English article must contain no Devanagari characters (verses appear as IAST).
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
                            f"You are a writer for DhyanApp, adapting {magazine_name} magazine articles "
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
                data["sub_title"] = f"From the {magazine_name} {month} edition" if month else f"From {magazine_name}"
            # Enforce pure-English output (no Devanagari verses leaking through).
            for k in ("title", "sub_title", "description", "full_text"):
                data[k] = self._purify_language(data.get(k, ""), "English")
            return data
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate article: {e}")
            return None

    # ----- cover image assets -----

    def generate_cover_assets(
        self, article: dict, article_data: dict, image_language: str = "english",
        magazine_config: dict = None
    ) -> dict:
        """Produce label / headline / sub_title strings for the cover image."""
        if magazine_config is None:
            magazine_config = MAGAZINES["tattvaloka"]
        magazine_name = magazine_config["name"]
        magazine_name_hindi = magazine_config["name_hindi"]
        month = (article.get("month") or "").strip()
        category = (article.get("category") or "article").strip()
        title = article_data.get("title") or article.get("title") or ""
        sub_title = article_data.get("sub_title", "")

        if image_language == "hindi":
            lang_instruction = (
                "All strings MUST be in Hindi using Devanagari script. "
                "Do not use English words except digits."
            )
            label_default = f"{magazine_name_hindi} · {month}" if month else magazine_name_hindi
        else:
            lang_instruction = "All strings MUST be in clear, simple English."
            label_default = f"{magazine_name} · {month}" if month else magazine_name

        prompt = f"""Prepare cover text for a {magazine_name} magazine cover image.

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
        self, article: dict, assets: dict, style: dict, image_language: str = "english",
        magazine_config: dict = None
    ) -> str:
        if magazine_config is None:
            magazine_config = MAGAZINES["tattvaloka"]
        magazine_name = magazine_config["name"]
        label = assets["label"].replace('"', "'")
        headline = assets["headline"].replace('"', "'")
        category = (article.get("category") or "article").strip()

        scene_hints = {
            "story": (
                "A serene cinematic scene depicting the key moment of the story — the characters, "
                "setting, and mood — rendered with classical Indian devotional sensibility."
            ),
            "discourse": (
                "A serene sacred scene fitting the teaching — a sage or guru in a calm temple "
                "or natural setting, or a sacred landscape with mountains and calm water."
            ),
            "article": (
                "A serene cinematic scene visually representing the article's central subject — "
                "the deity, sage, place, or idea — with soft mist, natural light, and spiritual symbolism."
            ),
            "subhashita": (
                "An elegant symbolic scene — a lamp, lotus, river, or sage — calm and refined, "
                "with soft natural lighting and subtle ornamental details."
            ),
            "poem": (
                "A soft, lyrical devotional scene evoking the poem's imagery — light, lotus, "
                "flame, or the divine — with gentle mist and warm sunrise light."
            ),
            "qna": (
                "A serene seeker-and-sage scene — two figures in calm dialogue in a sacred "
                "natural setting with soft light and subtle Indian ornamental patterns."
            ),
        }
        scene_hint = scene_hints.get(category, scene_hints["article"])

        title_typography = (
            "elegant Devanagari Hindi serif typography"
            if image_language == "hindi"
            else "elegant, refined serif typography"
        )

        return (
            f'Create a premium 16:9 landscape editorial cover image for a spiritual, devotional, '
            f'meditation, yoga, philosophy, or self-development article.\n'
            f'Use a minimalist Zen-inspired aesthetic with a soft warm cream/off-white background, '
            f'a subtle bluish atmospheric tint, muted gold accents, deep navy typography, gentle '
            f'natural lighting, and elegant vintage Indian ornamental details.\n\n'
            f'Text layout:\n'
            f'Show ONLY the article title as text.\n'
            f'Place the title prominently in the left/center area using {title_typography}.\n'
            f'Place a thin vintage ornamental gold line above the title, with a small subtle '
            f'lotus/Indian decorative motif in the center.\n'
            f'Place another matching vintage ornamental gold line below the title.\n'
            f'Do not add category names, subtitles, descriptions, quotes, dates, logos, buttons, '
            f'badges, or other text.\n\n'
            f'Visual composition:\n'
            f'Keep the left side spacious and highly readable for the title. On the right side, '
            f'create a serene cinematic scene that visually represents the article topic — '
            f'such as meditation, nature, temple architecture, Krishna, Shiva, yoga, wisdom, '
            f'self-development, books, mountains, rivers, prayer, or spiritual symbolism.\n'
            f'Use soft mist, mountains, calm water, sunrise/sunset light, subtle clouds, birds, '
            f'foliage, stone textures, and delicate Indian ornamental patterns where appropriate. '
            f'Keep these elements understated and sophisticated.\n\n'
            f'The overall result should feel premium, timeless, peaceful, spiritual, Indian, '
            f'editorial, and slightly vintage, rather than like a commercial poster or stock '
            f'photograph.\n\n'
            f'No category label. No extra text. No subtitle. Only the article title.\n'
            f'Article Title: {headline}\n'
            f'Visual Concept: {scene_hint}'
        )

    # ----- Hindi translation -----

    def generate_hindi_content(self, article_data: dict) -> Optional[dict]:
        """Translate title, sub_title, description and fullText to Hindi using the LLM."""
        title = article_data.get("title", "")
        sub_title = article_data.get("sub_title", "")
        description = article_data.get("description", "")
        full_text = article_data.get("full_text", "")

        prompt = f"""Translate the following article content into PURE Hindi, written entirely in Devanagari script.
Preserve the Markdown structure exactly (## headings, **bold**, bullet points, numbered lists).
Translate EVERY English word into Hindi. Proper nouns, names and Sanskrit terms must be written in Devanagari (transliterate them into Devanagari — do NOT leave them in Latin/Roman letters).
CRITICAL: The Hindi output MUST contain NO Latin/Roman letters and no other non-Devanagari script (no Cyrillic/Greek). Every word must be in Devanagari; only digits and Markdown symbols (#, *, -) may be non-Devanagari.

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
            hindi = json.loads(content)
            # Enforce pure-Hindi output (no stray English words in Devanagari text).
            for k in ("title", "sub_title", "description", "full_text"):
                if k in hindi:
                    hindi[k] = self._purify_language(hindi.get(k, ""), "Hindi")
            return hindi
        except Exception as e:
            logger.error(f"[ERROR] Hindi translation failed: {e}")
            return None

    def _local_tts(self, text: str, voice_id: str, language: str) -> Optional[bytes]:
        """Generate audio via local-ai-tools TTS (free, offline).

        Uses cloned voice profiles — Ashish Sahani for English, Rituparna for Hindi.
        Returns MP3 bytes or None on failure.
        """
        import time
        clean_text = _strip_markdown_for_tts(text)
        if not clean_text:
            return None

        # local-ai-tools TTS via /tts/speak (subprocess tts-venv on MPS)
        # — the working path for the cloned voices. It 500s on very long inputs,
        # so we CHUNK the text (like the Sarvam path), synthesize each chunk with
        # the same clone voice, and concatenate the WAVs into one MP3 (keeping the
        # pipeline's mp3 contract). (The old /v1/audio/speech route forwards to the
        # No OmniVoice app dependency — runs the model directly as subprocess.)
        chunks = _sentence_chunks(clean_text, 800)
        wav_buffers = []
        for ci, chunk in enumerate(chunks):
            got = None
            for attempt in range(1, 4):
                try:
                    response = _requests.post(
                        f"{LOCAL_AI_TTS_URL}/tts/speak",
                        json={"text": chunk, "voice": voice_id, "language": language, "speed": 1.0},
                        headers={"Content-Type": "application/json", "X-Service-Password": LOCAL_AI_PASSWORD},
                        timeout=300,
                    )
                    if response.status_code == 200 and len(response.content) > 100:
                        got = response.content
                        break
                    logger.warning(f"Local AI TTS chunk {ci+1}/{len(chunks)} attempt {attempt}/3: HTTP {response.status_code}")
                except Exception as e:
                    logger.warning(f"Local AI TTS chunk {ci+1}/{len(chunks)} attempt {attempt}/3 failed: {e}")
                if attempt < 3:
                    time.sleep(3)
            if got is None:
                logger.warning(f"Local AI TTS: chunk {ci+1}/{len(chunks)} failed after retries — giving up")
                return None
            wav_buffers.append(got)

        mp3 = _concat_wavs_to_mp3(wav_buffers)
        if mp3:
            logger.info(f"Local AI TTS ({voice_id}) succeeded: {len(chunks)} chunk(s) → {len(mp3)} bytes mp3")
            return mp3
        logger.warning("Local AI TTS: wav→mp3 concat failed")
        return None

    def generate_english_audio(self, text: str) -> Optional[bytes]:
        """Generate English MP3.

        Priority: Local AI (random cloned voice) → Sarvam → OpenAI TTS fallback.
        The chosen voice is stored in self._current_voice for reuse in Hindi.
        """
        if USE_LOCAL_AUDIO:
            voice_id, voice_name = random.choice(LOCAL_AI_VOICES)
            self._current_voice = (voice_id, voice_name)
            logger.info(f"Trying local AI TTS ({voice_name}) for English...")
            audio = self._local_tts(text, voice_id, "en")
            if audio:
                return audio
            logger.warning("Local AI TTS failed — falling back to Sarvam/OpenAI")
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

        Priority: Local AI (same voice as English) → Sarvam → OpenAI TTS fallback.
        Reuses the voice chosen during generate_english_audio for consistency.
        """
        if USE_LOCAL_AUDIO:
            voice_id, voice_name = getattr(self, '_current_voice', random.choice(LOCAL_AI_VOICES))
            logger.info(f"Trying local AI TTS ({voice_name}) for Hindi...")
            audio = self._local_tts(text, voice_id, "hi")
            if audio:
                return audio
            logger.warning("Local AI TTS failed — falling back to Sarvam/OpenAI")
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
        if not self.services_password:
            logger.error("[ERROR] SERVICES_PASSWORD not available")
            return None
        # The image endpoint (gpt-image via services.dhyanapp.org) can take
        # >120s under load; a single slow call used to silently drop the cover
        # and the article went out image-less. Retry once on timeout/error and
        # allow up to 180s per attempt (matches the OpenAI calls below).
        response = None
        for attempt in (1, 2):
            try:
                response = _requests.post(
                    f"{DHYANAPP_SERVICES_URL}/image_1/generate",
                    json={"prompt": prompt, "password": self.services_password, "size": "landscape", "quality": "medium"},
                    timeout=180,
                )
                break
            except Exception as e:
                logger.warning(f"[WARN] Image request attempt {attempt} failed: {e}")
                response = None
                if attempt == 2:
                    logger.error("[ERROR] Image generation failed after 2 attempts")
                    return None

        if response is None or response.status_code != 200:
            status = response.status_code if response is not None else "no-response"
            logger.error(f"[ERROR] Image generation failed: {status} - {(response.text[:200] if response is not None else '')}")
            return None

        try:
            buf = io.BytesIO(response.content)

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

    # Per-category serene scene hints (text-free) for the localized cover art.
    _COVER_SCENE_HINTS = {
        "story":      "a serene cinematic scene depicting the key moment of the story — figures, setting, and mood, in a classical Indian devotional style",
        "discourse":  "a sage or guru in a calm temple or a sacred landscape with soft mountains and still water",
        "article":    "a serene scene representing the article's central subject — a deity, sage, sacred place, or idea — with soft mist and natural light",
        "subhashita": "an elegant symbolic scene — a lamp, lotus, river, or sage — calm and refined with subtle ornamental detail",
        "poem":       "a soft, lyrical devotional scene — light, lotus, or flame — with gentle mist and warm sunrise light",
        "qna":        "a serene seeker-and-sage scene in a sacred natural setting with soft light",
    }

    def generate_localized_cover(self, title: str, category: str = "article"):
        """Generate the localized Zen cover set via dhyanapp-services
        POST /cover/generate-localized (ONE shared scene, per-language titles).

        Returns (teaser_url_english, {language: url}) or (None, {}) on failure so
        the caller can fall back to the legacy single-cover path."""
        if not self.services_password:
            logger.error("[cover] SERVICES_PASSWORD not available")
            return None, {}
        if not (title or "").strip():
            return None, {}
        hint = self._COVER_SCENE_HINTS.get(category, self._COVER_SCENE_HINTS["article"])
        concept = f"{hint}. Evoke the theme of: {title}."
        try:
            resp = _requests.post(
                f"{DHYANAPP_SERVICES_URL}/cover/generate-localized",
                json={
                    "title": title,
                    "visual_concept": concept,
                    "password": self.services_password,
                    "size": "landscape",
                    "quality": "medium",
                },
                timeout=300,
            )
            if resp.status_code != 200:
                logger.error(f"[cover] localized endpoint HTTP {resp.status_code}: {resp.text[:200]}")
                return None, {}
            data = resp.json()
            return data.get("teaserImageURL") or None, (data.get("localized_teaserImage") or {})
        except Exception as e:
            logger.error(f"[cover] localized cover generation failed: {e}")
            return None, {}

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
        magazine_config: dict = None,
        localized_teaser: dict = None,
    ) -> Optional[str]:
        if self.db is None:
            logger.error("[ERROR] MongoDB not connected")
            return None
        if magazine_config is None:
            magazine_config = MAGAZINES["tattvaloka"]
        magazine_name = magazine_config["name"]

        month = (source_article.get("month") or "").strip()
        category = (source_article.get("category") or "article").strip()
        full_text = article_data.get("full_text") or ""
        created_at_ms = int(datetime.now(IST).timestamp() * 1000)

        attribution_line = f"**{magazine_name} — {month}**" if month else f"**{magazine_name}**"
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
        en_subtitle = f"{magazine_name} · {month} · {category.capitalize()}" if month else f"{magazine_name} · {category.capitalize()}"
        hi_subtitle = (hindi_data or {}).get("sub_title", en_subtitle)
        en_desc = article_data.get("description", "")
        hi_desc = (hindi_data or {}).get("description", "")

        # These display maps MUST be keyed by ISO code (en/hi), not language name.
        # The app + home/recommended-sessions resolve titles by ISO locale; a
        # name-keyed map ("English"/"Hindi") renders with a blank title.
        # (alternate_audio/text/title above are intentionally name-keyed.)
        primary_titles = {"en": en_title}
        sub_titles = {"en": en_subtitle}
        short_descriptions = {"en": en_desc}
        original_author_names = {"en": self.author_name, "hi": magazine_config["name_hindi"]}
        sound_artist_names = {"en": self.author_name, "hi": magazine_config["name_hindi"]}
        author_short_bios = {"en": magazine_config["bio"], "hi": magazine_config["bio_hindi"]}

        if hi_title:
            primary_titles["hi"] = hi_title
        if hi_subtitle:
            sub_titles["hi"] = hi_subtitle
        if hi_desc:
            short_descriptions["hi"] = hi_desc

        doc = {
            "_id": article_id,
            "selfID": article_id,
            "primaryTitle": en_title,
            "subTitle": en_subtitle,   # e.g. "Tattvaloka · July 2025 · Article"
            "shortDescription": en_desc,
            "fullText": full_text,
            "teaserImageURL": image_url or "",
            "backgroundImageURL": image_url or "",
            "localized_teaserImage": _teaser_map_to_iso(localized_teaser),
            "originalAuthorName": self.author_name,
            "originalAuthorURL": "",
            "AuthorProfileImageURL": self.author_profile_image_url,
            "AuthorShortBio": magazine_config["bio"],
            "soundArtistName": self.author_name,
            "ArticleCategory": "Spirituality",
            "articleType": "original",
            "primaryLanguage": "English",
            "tags": source_article.get("tags") or [],
            "multiMediaType": "originalTextArticle",
            "uploadedBy": self.author_name,
            "creator_id": self.creator_id,
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
        self, *, advance_state: bool = True, override_image_lang: Optional[str] = None,
        magazine_slug: Optional[str] = None
    ) -> Optional[str]:
        magazine_slug = magazine_slug or self.state.get("next_magazine", "tattvaloka")
        magazine_config = MAGAZINES[magazine_slug]
        self._load_creator_profile(magazine_slug)

        source_article = self._select_random_article(magazine_slug)
        if source_article is None:
            logger.error(f"[ERROR] No article available for {magazine_config['name']}")
            return None

        category = source_article.get("category", "?")
        month = source_article.get("month", "?")
        image_language = override_image_lang or self.state.get("next_image_language", "english")

        logger.info(f"\n{'='*60}")
        logger.info(f"GENERATING {magazine_config['name'].upper()} ARTICLE: [{category}] {source_article.get('title')} ({month}) (image: {image_language})")
        logger.info(f"{'='*60}")

        article_data = self.generate_article_from_source(source_article, magazine_config)
        if not article_data:
            logger.error("Failed to generate article content")
            return None
        logger.info(f"Title: {article_data.get('title', 'N/A')}")

        article_id = str(uuid.uuid4())

        # Localized Zen cover set (ONE shared artwork, per-language titles) via
        # the dhyanapp-services /cover/generate-localized endpoint.
        #   teaserImageURL        = English cover
        #   localized_teaserImage = {language: url} for every language
        logger.info("Generating localized cover set...")
        category = source_article.get("category", "article")
        image_url, localized_teaser = self.generate_localized_cover(
            article_data.get("title", ""), category
        )
        if image_url:
            selected_style = {"name": "Zen Editorial Cover"}
            logger.info(f"Cover teaser: {image_url[:70]}... ({len(localized_teaser)} localized languages)")
        else:
            # Fallback to the legacy single-cover path so the article still ships.
            logger.warning("Localized cover failed — falling back to legacy cover")
            assets = self.generate_cover_assets(source_article, article_data, image_language, magazine_config)
            selected_style = random.choice(COVER_IMAGE_STYLES)
            image_prompt = self.generate_cover_prompt(source_article, assets, selected_style, image_language, magazine_config)
            image_url = self.generate_image(image_prompt, article_id)
            localized_teaser = {}
            if not image_url:
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
            magazine_config=magazine_config,
            localized_teaser=localized_teaser,
        )
        if not doc_id:
            return None

        try:
            self.db["latest_content"].insert_one({
                "_id": doc_id,
                "contentId": doc_id,
                "contentType": "ARTICLES",
                "timeOfAddition": int(datetime.now().timestamp() * 1000),
            })
            logger.info(f"[latest_content] Entry created for article {doc_id}")
        except Exception as e:
            logger.warning(f"[latest_content] Insert failed (non-fatal): {e}")

        if advance_state:
            self.state["last_date"] = date.today().isoformat()
            self.state["last_article_id"] = doc_id
            self.state["next_image_language"] = _flip_image_language(image_language)
            state_key = f"posted_article_ids_{magazine_slug}"
            self.state.setdefault(state_key, []).append(str(source_article["_id"]))
            current_idx = MAGAZINE_ROTATION.index(magazine_slug)
            self.state["next_magazine"] = MAGAZINE_ROTATION[(current_idx + 1) % len(MAGAZINE_ROTATION)]
            self._save_state()
            logger.info(
                f"State saved. Next magazine: {self.state['next_magazine']}. "
                f"Next image language: {self.state['next_image_language']}. "
                f"Published {len(self.state[state_key])} {magazine_config['name']} articles so far."
            )

        logger.info(f"[SUCCESS] Article created: {doc_id}")
        return doc_id

    def _magazines_with_articles(self) -> list:
        """Slugs from MAGAZINE_ROTATION that currently have at least one source
        article — the eligible pool for the day. Magazines not yet OCR'd/processed
        (no articles) are skipped automatically."""
        pool = []
        for slug in MAGAZINE_ROTATION:
            try:
                if self._get_all_articles(slug):
                    pool.append(slug)
            except Exception as e:
                logger.warning(f"[pool] {slug} availability check failed: {e}")
        return pool

    def run_daily(self) -> Optional[str]:
        today_iso = date.today().isoformat()
        logger.info("=" * 60)
        logger.info("MAGAZINE ARTICLE GENERATOR — 2 random magazines/day")
        logger.info(f"Date: {today_iso}")
        logger.info(f"Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
        logger.info("=" * 60)

        if not self._should_post_today():
            return None

        pool = self._magazines_with_articles()
        if not pool:
            logger.warning("No magazine has any articles available — nothing to publish today.")
            return None

        # Two random magazines per day (or one if only one has content).
        picks = random.sample(pool, min(2, len(pool)))
        logger.info(f"Today's magazines ({len(picks)} of {len(pool)} eligible): {picks}")

        first_doc_id = None
        published = 0
        for slug in picks:
            try:
                doc_id = self.generate_and_publish(advance_state=True, magazine_slug=slug)
                if doc_id:
                    published += 1
                    first_doc_id = first_doc_id or doc_id
            except Exception as e:
                logger.error(f"[{slug}] article generation failed: {e}", exc_info=True)

        logger.info(f"[DONE] Published {published}/{len(picks)} article(s) today.")
        return first_doc_id


# Singleton
_generator: Optional[MagazineArticleGenerator] = None


def get_magazine_article_generator() -> MagazineArticleGenerator:
    global _generator
    if _generator is None:
        _generator = MagazineArticleGenerator()
    return _generator


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Magazine Article Generator (Tattvaloka / Vedanta Kesari / Kalyan / Prabuddha Bharata)")
    parser.add_argument("--run-now", action="store_true",
                        help="Run daily publish (posts every day, alternates magazine)")
    parser.add_argument("--test", action="store_true",
                        help="Generate one article without advancing state")
    parser.add_argument("--show-state", action="store_true",
                        help="Print current state")
    parser.add_argument("--reset-state", action="store_true",
                        help="Reset state to defaults (requires --yes-i-am-sure)")
    parser.add_argument("--yes-i-am-sure", action="store_true",
                        help="Confirm --reset-state")
    parser.add_argument("--list-articles", action="store_true",
                        help="List available articles by magazine and category")
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
            "posted_article_ids_tattvaloka": [],
            "posted_article_ids_vedanta-kesari": [],
            "posted_article_ids_kalyan": [],
            "posted_article_ids_prabuddha-bharati": [],
            "next_magazine": "tattvaloka",
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
                print("MAGAZINE ARTICLE GENERATOR STATE")
                print("=" * 60)
                print(f"Last date:                  {state.get('last_date')}")
                print(f"Last article ID:            {state.get('last_article_id')}")
                print(f"Next magazine:              {state.get('next_magazine')}")
                print(f"Next image lang:            {state.get('next_image_language')}")
                for slug in MAGAZINE_ROTATION:
                    key = f"posted_article_ids_{slug}"
                    print(f"Articles ({slug}): {len(state.get(key, []))}")
            else:
                print("No state file found.")
        except Exception as e:
            print(f"Error reading state: {e}")
        sys.exit(0)

    if args.list_articles:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client["dhyanapp"]
        for slug in MAGAZINE_ROTATION:
            pipeline = [
                {"$match": {"magazineSlug": slug, "category": {"$in": list(ALLOWED_CATEGORIES)}}},
                {"$group": {"_id": "$category", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ]
            print(f"\nAvailable {MAGAZINES[slug]['name']} articles (curated categories):")
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
