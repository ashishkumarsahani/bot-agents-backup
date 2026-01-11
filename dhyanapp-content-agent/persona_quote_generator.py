"""
Persona-Based Quote Generator Service for DhyanApp.

This service handles:
- Searching for authentic quotes from persona's saints/scriptures
- AI fallback generation when search yields no results
- Creating images with quote text overlay (language-specific fonts)
- Posting quotes in markdown format with persona commentary
- Triggering engagement from other bot accounts
"""

import os
import io
import json
import random
import logging
import uuid
import http.client
import requests
import time
import textwrap
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional, Tuple

from openai import OpenAI
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
IST = ZoneInfo("Asia/Kolkata")
BOT_ACCOUNTS_FILE = Path(__file__).parent / "bot_accounts.json"
ROTATION_STATE_FILE = Path(__file__).parent / "quote_rotation_state.json"
FONTS_DIR = Path(__file__).parent / "fonts"

# API Configuration
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "d85ad7c3297a1e315dd011b058b5d81c749fd07b")
DHYANAPP_SERVICES_URL = "https://dhyanapp-services.epilepto.com"

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore, storage

FIREBASE_CREDENTIALS_PATH = os.getenv(
    "FIREBASE_CREDENTIALS_PATH",
    os.path.join(os.path.dirname(__file__), "firebase_credentials.json")
)
FIREBASE_STORAGE_BUCKET = "dhyanapp-90de4.appspot.com"

# Font Configuration - Multiple options for variety
QUOTE_FONTS = {
    'hindi': [
        {
            'name': 'Noto Serif Devanagari',
            'quote': '/usr/share/fonts/truetype/noto/NotoSerifDevanagari-Bold.ttf',
            'attribution': '/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf',
            'style': 'elegant serif'
        },
        {
            'name': 'Noto Sans Devanagari',
            'quote': '/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf',
            'attribution': '/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf',
            'style': 'clean modern'
        },
        {
            'name': 'Noto Serif Devanagari SemiBold',
            'quote': '/usr/share/fonts/truetype/noto/NotoSerifDevanagari-SemiBold.ttf',
            'attribution': '/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf',
            'style': 'balanced serif'
        },
    ],
    'english': [
        {
            'name': 'Samarkan',
            'quote': str(FONTS_DIR / 'Samarkan.ttf'),
            'attribution': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            'style': 'Indian decorative',
            'size_adjust': 1.1  # Slightly larger
        },
        {
            'name': 'Cinzel',
            'quote': str(FONTS_DIR / 'Cinzel-Bold.ttf'),
            'attribution': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            'style': 'classical Roman',
            'size_adjust': 0.9
        },
        {
            'name': 'Great Vibes',
            'quote': str(FONTS_DIR / 'GreatVibes-Regular.ttf'),
            'attribution': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            'style': 'elegant script',
            'size_adjust': 1.2
        },
        {
            'name': 'Playfair Display',
            'quote': str(FONTS_DIR / 'PlayfairDisplay-Bold.ttf'),
            'attribution': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            'style': 'sophisticated serif',
            'size_adjust': 0.95
        },
        {
            'name': 'Cormorant Garamond',
            'quote': str(FONTS_DIR / 'CormorantGaramond-Bold.ttf'),
            'attribution': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            'style': 'elegant classic',
            'size_adjust': 1.0
        },
        {
            'name': 'Philosopher',
            'quote': str(FONTS_DIR / 'Philosopher-Bold.ttf'),
            'attribution': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            'style': 'thoughtful modern',
            'size_adjust': 0.95
        },
        {
            'name': 'Noto Serif Display',
            'quote': '/usr/share/fonts/truetype/noto/NotoSerifDisplay-Bold.ttf',
            'attribution': '/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf',
            'style': 'premium display',
            'size_adjust': 0.9
        },
        {
            'name': 'Gentium',
            'quote': '/usr/share/fonts/truetype/gentium/Gentium-R.ttf',
            'attribution': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            'style': 'scholarly classic',
            'size_adjust': 1.0
        },
    ]
}

# Fallback font config
FONT_FALLBACK = {
    'hindi': '/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf',
    'english': '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'
}

# Image styles for quote backgrounds
QUOTE_IMAGE_STYLES = [
    {
        "name": "Mystical Ethereal",
        "description": "Dreamlike, mystical atmosphere with soft glowing light, cosmic elements",
        "colors": "deep purples, celestial blues, soft gold glows, starlit blacks"
    },
    {
        "name": "Lotus Garden Serene",
        "description": "Peaceful lotus pond scenes with morning mist and natural tranquility",
        "colors": "soft pinks, white, jade green, morning gold, peaceful blues"
    },
    {
        "name": "Sacred Geometry",
        "description": "Yantras, mandalas, and Sri Chakra inspired designs with spiritual symbolism",
        "colors": "deep maroon, gold, white, with subtle gradient backgrounds"
    },
    {
        "name": "Himalayan Dawn",
        "description": "Mountain spirituality theme with snow peaks and golden sunrise atmospheres",
        "colors": "snow white, sunrise orange, sky blue, mountain purple, golden light"
    },
    {
        "name": "Temple Architecture",
        "description": "Ancient Indian temple carvings with intricate stone-like textures",
        "colors": "sandstone beige, granite grey, aged bronze, warm ambient lighting"
    },
    {
        "name": "Watercolor Spiritual",
        "description": "Soft, flowing watercolor style with gentle washes and ethereal quality",
        "colors": "soft pinks, lavender, sky blue, pale gold, and misty whites"
    },
    {
        "name": "Meditative Minimalist",
        "description": "Clean, minimal aesthetic with single focal point and zen-like simplicity",
        "colors": "warm whites, soft greys, single accent color (saffron or deep blue)"
    },
    {
        "name": "Oil Painting Classical",
        "description": "Rich textured brushstrokes emulating classical oil paintings with depth",
        "colors": "deep ochres, rich burgundies, golden highlights, earthy greens"
    }
]


class PersonaQuoteGenerator:
    """Service for generating persona-based quotes with images."""

    def __init__(self):
        """Initialize the persona quote generator."""
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.accounts = self._load_accounts()
        self.rotation_state = self._load_rotation_state()
        self._initialize_firebase()
        self.services_password = self._get_services_password()

    def _initialize_firebase(self):
        """Initialize Firebase."""
        try:
            if not firebase_admin._apps:
                if os.path.exists(FIREBASE_CREDENTIALS_PATH):
                    cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
                    firebase_admin.initialize_app(cred, {
                        'storageBucket': FIREBASE_STORAGE_BUCKET
                    })
            self.db = firestore.client()
            self.bucket = storage.bucket(FIREBASE_STORAGE_BUCKET)
            logger.info("[SUCCESS] Firebase initialized for quotes")
        except Exception as e:
            logger.error(f"[ERROR] Failed to initialize Firebase: {e}")
            self.db = None
            self.bucket = None

    def _get_services_password(self) -> str:
        """Get the services password from Firebase config."""
        try:
            if self.db:
                doc = self.db.collection("config").document("secrets").get()
                if doc.exists:
                    secrets = doc.to_dict()
                    return secrets.get("SERVICES_PASSWORD", "")
        except Exception as e:
            logger.error(f"[ERROR] Failed to get services password: {e}")
        return ""

    def _load_accounts(self) -> dict:
        """Load bot accounts from JSON file."""
        try:
            with open(BOT_ACCOUNTS_FILE, 'r') as f:
                data = json.load(f)
                return data.get('accounts', {})
        except Exception as e:
            logger.error(f"[ERROR] Failed to load bot accounts: {e}")
            return {}

    def _load_rotation_state(self) -> dict:
        """Load rotation state from file."""
        try:
            if ROTATION_STATE_FILE.exists():
                with open(ROTATION_STATE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"[ERROR] Failed to load rotation state: {e}")
        return {"last_date": None, "poster_index": 0}

    def _save_rotation_state(self):
        """Save rotation state to file."""
        try:
            with open(ROTATION_STATE_FILE, 'w') as f:
                json.dump(self.rotation_state, f, indent=2)
        except Exception as e:
            logger.error(f"[ERROR] Failed to save rotation state: {e}")

    def get_todays_posters(self) -> list[dict]:
        """Get today's poster accounts based on rotation."""
        account_keys = list(self.accounts.keys())
        today = date.today().isoformat()

        if self.rotation_state.get("last_date") != today:
            self.rotation_state["poster_index"] = (
                self.rotation_state.get("poster_index", 0) + 2
            ) % len(account_keys)
            self.rotation_state["last_date"] = today
            self._save_rotation_state()

        start_idx = self.rotation_state["poster_index"]
        posters = []
        for i in range(2):
            idx = (start_idx + i) % len(account_keys)
            key = account_keys[idx]
            account = self.accounts[key].copy()
            account['account_key'] = key
            posters.append(account)

        logger.info(f"Today's quote posters: {[p['name'] for p in posters]}")
        return posters

    def generate_quote_search_query(self, account: dict) -> Tuple[str, str]:
        """
        Generate a search query to find authentic quotes.

        Returns:
            Tuple of (search_query, source_name)
        """
        follows = account.get('follows', [])
        scriptures = account.get('scriptures', [])
        all_sources = follows + scriptures

        source = random.choice(all_sources) if all_sources else "spiritual wisdom"

        prompt = f"""Generate a web search query to find an authentic quote from {source}.

The query should help find actual quotes, sayings, or teachings.

Examples of good queries:
- "Ramana Maharshi quotes on self-inquiry"
- "Kabir Das famous dohe hindi"
- "Bhagavad Gita verse on duty karma"
- "Swami Vivekananda quotes on courage strength"
- "Rumi quotes on love soul"

Generate ONE specific search query for: {source}

Return ONLY the search query text, nothing else."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You generate focused search queries for finding spiritual quotes."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
                max_tokens=50
            )
            query = response.choices[0].message.content.strip().strip('"\'')
            logger.info(f"Generated quote search query: {query} (source: {source})")
            return query, source
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate search query: {e}")
            return f"{source} quotes", source

    def search_web(self, query: str, max_results: int = 5) -> list:
        """Search the web using SerperDev."""
        try:
            conn = http.client.HTTPSConnection("google.serper.dev")
            payload = json.dumps({"q": query, "gl": "in"})
            headers = {
                'X-API-KEY': SERPER_API_KEY,
                'Content-Type': 'application/json'
            }
            conn.request("POST", "/search", payload, headers)
            res = conn.getresponse()
            data = json.loads(res.read().decode("utf-8"))
            conn.close()

            results = []
            for r in data.get('organic', [])[:max_results]:
                results.append({
                    'title': r.get('title', ''),
                    'url': r.get('link', ''),
                    'snippet': r.get('snippet', ''),
                })
            logger.info(f"SerperDev returned {len(results)} results")
            return results
        except Exception as e:
            logger.error(f"SerperDev search failed: {e}")
            return []

    def search_authentic_quote(self, query: str, source: str) -> Optional[dict]:
        """
        Search for authentic quotes using SerperDev.

        Returns:
            Dictionary with quote, attribution, language or None
        """
        results = self.search_web(query)

        if not results:
            return None

        results_text = ""
        for i, r in enumerate(results[:4], 1):
            results_text += f"{i}. {r['title']}\n   {r['snippet']}\n\n"

        prompt = f"""From these search results, extract ONE authentic quote from or about {source}.

Search Results:
{results_text}

Extract a real quote (not a paraphrase or description). The quote should be:
1. An actual saying, teaching, or verse from {source}
2. Meaningful and complete (not a fragment)
3. 1-3 sentences long

Return JSON:
{{
    "quote": "The exact quote text",
    "attribution": "Name (e.g., '{source}')",
    "language": "hindi" or "english",
    "is_authentic": true if this is a real quote, false if paraphrased or not found
}}

If you cannot find a genuine quote in the results, set is_authentic to false.
Return ONLY valid JSON."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You extract authentic spiritual quotes from search results."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=300
            )

            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            quote_data = json.loads(content)

            if quote_data.get('is_authentic', False):
                logger.info(f"Found authentic quote: {quote_data['quote'][:50]}...")
                return quote_data
            else:
                logger.info("No authentic quote found in search results")
                return None

        except Exception as e:
            logger.error(f"[ERROR] Failed to extract quote: {e}")
            return None

    def generate_ai_quote(self, account: dict, source: str) -> dict:
        """Generate an AI quote when search fails."""
        follows = account.get('follows', [])
        scriptures = account.get('scriptures', [])
        topics = account.get('topics', [])
        languages = account.get('languages', ['english'])

        topic = random.choice(topics) if topics else "spiritual wisdom"
        language = "Hindi" if 'hindi' in languages and random.random() < 0.5 else "English"
        if languages == ['hindi']:
            language = "Hindi"

        prompt = f"""Generate a profound spiritual quote in the style and tradition of {source}.

Context:
- Tradition includes teachers like: {', '.join(follows[:3])}
- Related scriptures: {', '.join(scriptures[:3])}
- Topic: {topic}

Create a quote that:
1. Sounds authentic to the {source} tradition
2. Is 1-3 sentences long
3. Is inspiring, profound, and memorable
4. Relates to {topic}
5. Is written in {language}

Return JSON:
{{
    "quote": "The quote text in {language}",
    "attribution": "In the spirit of {source}",
    "language": "{language.lower()}",
    "topic": "{topic}"
}}

Return ONLY valid JSON."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"You create profound spiritual quotes inspired by {source}'s teachings."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.9,
                max_tokens=300
            )

            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            quote_data = json.loads(content)
            quote_data['is_ai_generated'] = True
            logger.info(f"Generated AI quote: {quote_data['quote'][:50]}...")
            return quote_data

        except Exception as e:
            logger.error(f"[ERROR] Failed to generate AI quote: {e}")
            return {
                "quote": "In stillness, we find the infinite.",
                "attribution": f"In the spirit of {source}",
                "language": "english",
                "is_ai_generated": True
            }

    def generate_persona_commentary(self, account: dict, quote: str, attribution: str) -> str:
        """Generate persona-specific reflection on the quote."""
        languages = account.get('languages', ['english'])
        language = "Hindi" if 'hindi' in languages and random.random() < 0.5 else "English"
        if languages == ['hindi']:
            language = "Hindi"

        prompt = f"""You are {account['name']} with this persona:
{account.get('persona', '')}

Conversational style: {account.get('conversational_style', '')}
Comment style: {account.get('comment_style', '')}
Teachers you follow: {', '.join(account.get('follows', [])[:3])}

Write a personal reflection (40-80 words) in {language} on this quote:
"{quote}" - {attribution}

Guidelines:
- Write in first person as {account['name']}
- Reference your own spiritual tradition naturally
- Make it feel personal and authentic, not generic
- Can include relevant dohas, shlokas, or teachings from your tradition
- End with an inspiring thought or question

Return ONLY the commentary text."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"You are {account['name']}, writing a personal reflection on a spiritual quote."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.85,
                max_tokens=200
            )
            commentary = response.choices[0].message.content.strip()
            return commentary
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate commentary: {e}")
            return "This wisdom resonates deeply with my spiritual journey."

    def generate_quote_background(self, quote_topic: str, post_id: str) -> Optional[bytes]:
        """Generate background image for quote."""
        if not self.services_password:
            logger.error("[ERROR] Services password not available")
            return None

        selected_style = random.choice(QUOTE_IMAGE_STYLES)

        prompt = f"""Create a beautiful, serene background image for a spiritual quote about "{quote_topic}".

ART STYLE: {selected_style['name']}
Style Description: {selected_style['description']}
Color Palette: {selected_style['colors']}

Requirements:
- NO TEXT whatsoever - purely visual background
- Leave space in the center for text overlay (darker/calmer center area)
- Subtle, not distracting from text that will be overlaid
- Spiritual, peaceful, meditative atmosphere
- Professional quality suitable for a meditation app

IMPORTANT: Do NOT include any text, letters, words, or typography."""

        try:
            response = requests.post(
                f"{DHYANAPP_SERVICES_URL}/image_1/generate",
                json={
                    "prompt": prompt,
                    "password": self.services_password,
                    "user_id": "quote_bot",
                    "size": "square",
                    "quality": "medium"
                },
                timeout=120
            )

            if response.status_code != 200:
                logger.error(f"[ERROR] Image generation failed: {response.status_code}")
                return None

            logger.info(f"[SUCCESS] Generated quote background ({selected_style['name']})")
            return response.content

        except Exception as e:
            logger.error(f"[ERROR] Failed to generate background: {e}")
            return None

    def _select_random_font(self, language: str) -> dict:
        """Select a random font configuration for the given language."""
        fonts = QUOTE_FONTS.get(language, QUOTE_FONTS['english'])

        # Filter to only fonts that exist
        available_fonts = []
        for font in fonts:
            if os.path.exists(font['quote']):
                available_fonts.append(font)

        if available_fonts:
            selected = random.choice(available_fonts)
            logger.info(f"Selected font: {selected['name']} ({selected['style']})")
            return selected

        # Fallback
        logger.warning(f"No fonts available for {language}, using fallback")
        return {
            'name': 'Fallback',
            'quote': FONT_FALLBACK.get(language, FONT_FALLBACK['english']),
            'attribution': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            'style': 'fallback',
            'size_adjust': 1.0
        }

    def _get_font(self, font_path: str, size: int) -> ImageFont.FreeTypeFont:
        """Load font from path with fallback."""
        if font_path and os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception as e:
                logger.warning(f"Failed to load font {font_path}: {e}")

        # Fallback to default
        logger.warning(f"Using default font")
        return ImageFont.load_default()

    def _wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
        """Wrap text to fit within max_width."""
        words = text.split()
        lines = []
        current_line = []

        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = font.getbbox(test_line)
            if bbox[2] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]

        if current_line:
            lines.append(' '.join(current_line))

        return '\n'.join(lines)

    def add_quote_text_overlay(self, image_bytes: bytes, quote: str,
                                attribution: str, language: str) -> tuple[bytes, str]:
        """Add quote text overlay with randomly selected language-specific fonts.

        Returns:
            Tuple of (image_bytes, font_name)
        """
        img = Image.open(io.BytesIO(image_bytes)).convert('RGBA')
        width, height = img.size

        # Create semi-transparent overlay for text readability
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Add gradient overlay in center area
        padding = 80
        text_area_top = int(height * 0.15)
        text_area_bottom = int(height * 0.85)
        draw.rectangle(
            [(padding, text_area_top), (width - padding, text_area_bottom)],
            fill=(0, 0, 0, 100)
        )

        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)

        # Select random font for this quote
        font_config = self._select_random_font(language)
        size_adjust = font_config.get('size_adjust', 1.0)

        # Get fonts with size adjustment
        base_quote_size = 44 if language == 'hindi' else 48
        quote_font_size = int(base_quote_size * size_adjust)
        attr_font_size = 28

        quote_font = self._get_font(font_config['quote'], quote_font_size)
        attr_font = self._get_font(font_config['attribution'], attr_font_size)

        # Wrap quote text
        max_text_width = width - (padding * 3)
        wrapped_quote = self._wrap_text(f'"{quote}"', quote_font, max_text_width)

        # Calculate quote position (centered)
        quote_bbox = draw.textbbox((0, 0), wrapped_quote, font=quote_font)
        quote_width = quote_bbox[2] - quote_bbox[0]
        quote_height = quote_bbox[3] - quote_bbox[1]

        quote_x = (width - quote_width) // 2
        quote_y = (height - quote_height) // 2 - 40

        # Draw quote with shadow
        shadow_offset = 3
        draw.text((quote_x + shadow_offset, quote_y + shadow_offset), wrapped_quote,
                  font=quote_font, fill=(0, 0, 0, 180))
        draw.text((quote_x, quote_y), wrapped_quote,
                  font=quote_font, fill=(255, 255, 255, 255))

        # Draw attribution below quote
        attr_text = f"- {attribution}"
        attr_bbox = draw.textbbox((0, 0), attr_text, font=attr_font)
        attr_width = attr_bbox[2] - attr_bbox[0]
        attr_x = (width - attr_width) // 2
        attr_y = quote_y + quote_height + 50

        draw.text((attr_x + 2, attr_y + 2), attr_text,
                  font=attr_font, fill=(0, 0, 0, 150))
        draw.text((attr_x, attr_y), attr_text,
                  font=attr_font, fill=(255, 255, 200, 230))

        # Convert to bytes
        output = io.BytesIO()
        img.convert('RGB').save(output, format='PNG', quality=95)
        return output.getvalue(), font_config['name']

    def upload_image_to_firebase(self, image_bytes: bytes, post_id: str) -> Optional[str]:
        """Upload image to Firebase Storage."""
        try:
            blob_path = f"Posts/images/bot_quotes/{post_id}.png"
            blob = self.bucket.blob(blob_path)

            blob.upload_from_string(image_bytes, content_type='image/png')
            blob.make_public()

            blob.metadata = {'firebaseStorageDownloadTokens': post_id}
            blob.patch()

            firebase_url = f"https://firebasestorage.googleapis.com/v0/b/{FIREBASE_STORAGE_BUCKET}/o/{blob_path.replace('/', '%2F')}?alt=media&token={post_id}"

            logger.info(f"[SUCCESS] Quote image uploaded to Firebase")
            return firebase_url

        except Exception as e:
            logger.error(f"[ERROR] Failed to upload image: {e}")
            return None

    def format_post_content(self, quote: str, commentary: str, attribution: str) -> str:
        """Format post content with italicized quote and double quotes."""
        return f"""*"{quote}"*

— {attribution}

{commentary}"""

    def push_quote_post(self, account: dict, quote_data: dict, commentary: str,
                        image_url: Optional[str], post_id: str) -> Optional[str]:
        """Push the quote post to Firestore."""
        if not self.db:
            logger.error("[ERROR] Firestore not connected")
            return None

        created_at_ms = int(datetime.now(IST).timestamp() * 1000)

        content = self.format_post_content(
            quote_data['quote'],
            commentary,
            quote_data['attribution']
        )

        doc_data = {
            "audioBackgroundUrl": None,
            "audioUrl": None,
            "commentCount": 0,
            "composition": "SEPARATE_CONTENT",
            "content": content,
            "createdAt": created_at_ms,
            "createdBy": account['user_id'],
            "creatorName": account['name'],
            "deleted": False,
            "deletedAt": None,
            "deletedByAdmin": False,
            "description": f"{quote_data.get('topic', 'Wisdom')} - {quote_data['attribution']}",
            "globallyHidden": False,
            "imageUrl": image_url,
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
            # Custom metadata
            "_botGenerated": True,
            "_isQuote": True,
            "_quoteSource": "ai_generated" if quote_data.get('is_ai_generated') else "web_search",
            "_quoteAttribution": quote_data['attribution'],
            "_language": quote_data.get('language', 'english'),
            "_fontUsed": quote_data.get('_font_used', ''),
        }

        try:
            self.db.collection("posts").document(post_id).set(doc_data)
            logger.info(f"[SUCCESS] Quote post pushed to Firestore: {post_id}")
            return post_id
        except Exception as e:
            logger.error(f"[ERROR] Failed to push quote post: {e}")
            return None

    def generate_and_post_quote(self, account: dict) -> Optional[str]:
        """Full pipeline: search/generate quote, create image, post."""
        logger.info(f"\n{'='*60}")
        logger.info(f"GENERATING QUOTE FOR: {account['name']}")
        logger.info(f"{'='*60}")

        # Step 1: Generate search query
        search_query, source = self.generate_quote_search_query(account)
        logger.info(f"Search query: {search_query}")

        # Step 2: Try to find authentic quote from web
        quote_data = self.search_authentic_quote(search_query, source)

        # Step 3: Fallback to AI generation if needed
        if not quote_data:
            logger.info("No authentic quote found, generating AI quote...")
            quote_data = self.generate_ai_quote(account, source)

        if not quote_data:
            logger.error("Failed to get quote data")
            return None

        logger.info(f"Quote: {quote_data['quote'][:60]}...")
        logger.info(f"Attribution: {quote_data['attribution']}")

        # Step 4: Generate persona commentary
        commentary = self.generate_persona_commentary(
            account, quote_data['quote'], quote_data['attribution']
        )
        logger.info(f"Commentary: {commentary[:60]}...")

        # Step 5: Generate post ID
        post_id = str(uuid.uuid4())

        # Step 6: Generate background image
        topic = quote_data.get('topic', source)
        logger.info(f"Generating background image for: {topic}")
        background_bytes = self.generate_quote_background(topic, post_id)

        image_url = None
        font_used = None
        if background_bytes:
            # Step 7: Add text overlay with random font
            language = quote_data.get('language', 'english')
            image_with_text, font_used = self.add_quote_text_overlay(
                background_bytes,
                quote_data['quote'],
                quote_data['attribution'],
                language
            )
            logger.info(f"Font used: {font_used}")

            # Step 8: Upload to Firebase
            image_url = self.upload_image_to_firebase(image_with_text, post_id)
            if image_url:
                logger.info(f"Image URL: {image_url[:60]}...")
        else:
            logger.warning("Posting quote without image")

        # Add font info to quote data
        quote_data['_font_used'] = font_used

        # Step 9: Push to Firestore
        doc_id = self.push_quote_post(account, quote_data, commentary, image_url, post_id)

        if doc_id:
            logger.info(f"[SUCCESS] Quote post created: {doc_id}")

        return doc_id

    def run_daily_quotes(self, enable_engagement: bool = True,
                         min_delay_minutes: int = 5, max_delay_minutes: int = 10,
                         test_mode: bool = False, single_post: bool = False) -> list[str]:
        """Run daily persona-based quote generation with engagement."""
        from engagement_service import get_engagement_service

        logger.info("=" * 60)
        logger.info("PERSONA-BASED QUOTE GENERATOR - DAILY RUN")
        logger.info(f"Date: {date.today()}")
        logger.info(f"Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
        if single_post:
            logger.info("Mode: SINGLE QUOTE")
        logger.info("=" * 60)

        post_ids = []
        posters = self.get_todays_posters()

        # If single_post mode, only use the first poster
        if single_post and posters:
            posters = [posters[0]]
            logger.info(f"Single post mode: Using {posters[0]['name']}")

        engagement_service = get_engagement_service() if enable_engagement else None

        for account in posters:
            try:
                post_id = self.generate_and_post_quote(account)
                if post_id:
                    post_ids.append(post_id)

                    if engagement_service:
                        logger.info(f"\nTriggering engagement for quote by {account['name']}...")
                        time.sleep(60)
                        engagement_service.engage_with_post(
                            post_id,
                            account['account_key'],
                            min_delay_minutes=min_delay_minutes,
                            max_delay_minutes=max_delay_minutes,
                            test_mode=test_mode
                        )

                    time.sleep(5)
            except Exception as e:
                logger.error(f"Error generating quote for {account['name']}: {e}")
                import traceback
                logger.error(traceback.format_exc())

        logger.info("=" * 60)
        logger.info(f"COMPLETED: Created {len(post_ids)} quote posts")
        logger.info("=" * 60)

        return post_ids


# Singleton instance
_generator = None


def get_persona_quote_generator() -> PersonaQuoteGenerator:
    """Get the singleton instance."""
    global _generator
    if _generator is None:
        _generator = PersonaQuoteGenerator()
    return _generator


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Persona-Based Quote Generator")
    parser.add_argument("--run-now", action="store_true", help="Run quote generation immediately")
    parser.add_argument("--single", action="store_true", help="Only post one quote from today's rotation")
    parser.add_argument("--test-account", type=str, help="Test with specific account key")
    parser.add_argument("--show-rotation", action="store_true", help="Show today's rotation")
    parser.add_argument("--no-engagement", action="store_true", help="Skip engagement")
    parser.add_argument("--test-mode", action="store_true", help="Use short delays for testing")

    args = parser.parse_args()

    generator = get_persona_quote_generator()

    if args.show_rotation:
        print("\n" + "=" * 60)
        print("TODAY'S QUOTE ROTATION")
        print("=" * 60)

        posters = generator.get_todays_posters()
        print("\nQuote Posters:")
        for p in posters:
            print(f"  - {p['name']} ({p['conversational_style']})")

    elif args.test_account:
        if args.test_account in generator.accounts:
            account = generator.accounts[args.test_account].copy()
            account['account_key'] = args.test_account
            post_id = generator.generate_and_post_quote(account)
            if post_id:
                print(f"\n[SUCCESS] Created quote post: {post_id}")

                # Trigger engagement unless --no-engagement flag
                if not args.no_engagement:
                    from engagement_service import get_engagement_service
                    engagement_service = get_engagement_service()
                    print("\nTriggering engagement from other bots...")
                    time.sleep(60)  # Wait 1 minute before engagement
                    engagement_service.engage_with_post(
                        post_id,
                        args.test_account,
                        min_delay_minutes=5,
                        max_delay_minutes=10,
                        test_mode=args.test_mode
                    )
            else:
                print("\n[ERROR] Failed to create quote post")
        else:
            print(f"[ERROR] Account '{args.test_account}' not found")
            print(f"Available accounts: {list(generator.accounts.keys())}")

    elif args.run_now:
        post_ids = generator.run_daily_quotes(
            enable_engagement=not args.no_engagement,
            test_mode=args.test_mode,
            single_post=args.single
        )
        print(f"\nCreated {len(post_ids)} quote posts")

    else:
        parser.print_help()
