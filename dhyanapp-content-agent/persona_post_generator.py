"""
Persona-Based Post Generator Service for DhyanApp.

This service handles:
- Loading bot accounts from configuration
- Rotating accounts for daily posting
- Generating search queries based on persona
- Performing web search for content
- Generating posts/quotes from search results
- Creating image prompts and calling gpt-image endpoint
- Posting to MongoDB with persona-specific style
"""

import os
import json
import random
import logging
import uuid
import http.client
import requests
import time
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional, Tuple

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
IST = ZoneInfo("Asia/Kolkata")
ROTATION_STATE_FILE = Path(__file__).parent / "rotation_state.json"

from bot_personas_store import get_all_personas

# API Configuration
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "d85ad7c3297a1e315dd011b058b5d81c749fd07b")
DHYANAPP_SERVICES_URL = "https://dhyanapp-services.epilepto.com"

# MongoDB + MinIO
from pymongo import MongoClient

from llm_usage_tracker import record_openai_response
import boto3
from botocore.client import Config as BotoConfig

# MongoDB Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://dhyanadmin:Dhyan%40Mongo2026!@localhost:27017/dhyanapp?authSource=admin&replicaSet=rs0")

# MinIO Configuration
_minio_host = os.getenv("MINIO_ENDPOINT", "localhost")
_minio_port = os.getenv("MINIO_PORT", "9000")
MINIO_ENDPOINT = _minio_host if ":" in _minio_host else f"{_minio_host}:{_minio_port}"
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "dhyanapp-recordings")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "https://storage.dhyanapp.org")

# Image Style Options for variety in post images
IMAGE_STYLES = [
    {
        "name": "Traditional Indian Miniature",
        "description": "Inspired by Rajasthani and Mughal miniature paintings with intricate details, rich colors, flat perspective, and ornate borders",
        "colors": "rich reds, deep blues, gold accents, saffron, and emerald greens"
    },
    {
        "name": "Tanjore Painting Style",
        "description": "South Indian Tanjore art style with gold leaf textures, bold outlines, and vibrant jewel tones on dark backgrounds",
        "colors": "gold, ruby red, deep green, royal blue on maroon or black backgrounds"
    },
    {
        "name": "Watercolor Spiritual",
        "description": "Soft, flowing watercolor style with gentle washes, ethereal quality, and peaceful blending of colors",
        "colors": "soft pinks, lavender, sky blue, pale gold, and misty whites"
    },
    {
        "name": "Madhubani Folk Art",
        "description": "Traditional Bihar folk art with geometric patterns, nature motifs, fish, peacocks, and lotus designs with bold black outlines",
        "colors": "bright primary colors - red, yellow, blue, green with white backgrounds"
    },
    {
        "name": "Mystical Ethereal",
        "description": "Dreamlike, mystical atmosphere with soft glowing light, cosmic elements, and spiritual symbolism",
        "colors": "deep purples, celestial blues, soft gold glows, starlit blacks"
    },
    {
        "name": "Warli Art Style",
        "description": "Maharashtra tribal art with simple geometric shapes, stick figures, and circular motifs representing daily life and spirituality",
        "colors": "white figures on terracotta brown or deep red backgrounds"
    },
    {
        "name": "Temple Architecture",
        "description": "Inspired by ancient Indian temple carvings and sculptures with intricate stone-like textures and sacred geometry",
        "colors": "sandstone beige, granite grey, aged bronze, with warm ambient lighting"
    },
    {
        "name": "Lotus Garden Serene",
        "description": "Peaceful lotus pond scenes with morning mist, meditation imagery, and natural tranquility",
        "colors": "soft pinks, white, jade green, morning gold, peaceful blues"
    },
    {
        "name": "Sacred Geometry",
        "description": "Yantras, mandalas, and Sri Chakra inspired designs with precise geometric patterns and spiritual symbolism",
        "colors": "deep maroon, gold, white, with subtle gradient backgrounds"
    },
    {
        "name": "Himalayan Dawn",
        "description": "Mountain spirituality theme with snow peaks, ancient temples, and golden sunrise/sunset atmospheres",
        "colors": "snow white, sunrise orange, sky blue, mountain purple, golden light"
    },
    {
        "name": "Pattachitra Style",
        "description": "Odisha scroll painting style with mythological narratives, bold lines, and natural dye-inspired colors",
        "colors": "red, yellow, indigo blue, white, and black with intricate borders"
    },
    {
        "name": "Meditative Minimalist",
        "description": "Clean, minimal aesthetic with single focal point, vast negative space, and zen-like simplicity",
        "colors": "warm whites, soft greys, single accent color (saffron or deep blue)"
    },
    {
        "name": "Studio Ghibli Style",
        "description": "Whimsical, nostalgic aesthetic inspired by Studio Ghibli animations with soft hand-drawn quality, lush nature details, dreamy atmospheres, and gentle magical realism",
        "colors": "soft greens, sky blues, warm sunset oranges, gentle pastels, and earthy browns"
    },
    {
        "name": "Cartoon Style",
        "description": "Classic 2D animation style with clean lines, bold shapes, expressive characters, and vibrant flat colors reminiscent of modern adventure animations",
        "colors": "bright primary colors, bold outlines, saturated hues with clean backgrounds"
    },
    {
        "name": "Oil Painting",
        "description": "Rich textured brushstrokes emulating classical oil paintings with depth, luminosity, and the layered quality of traditional fine art masters",
        "colors": "deep ochres, rich burgundies, golden highlights, earthy greens, and warm amber glazes"
    },
    {
        "name": "Pixel Art",
        "description": "Retro 16-bit video game aesthetic with deliberate low resolution, visible pixels, limited color palette, and nostalgic digital charm",
        "colors": "limited palette of 16-32 colors, bold contrasts, retro game-inspired hues"
    },
    {
        "name": "Gothic Noir",
        "description": "Dark, moody atmosphere with dramatic chiaroscuro lighting, deep shadows, mysterious compositions, and cinematic intensity",
        "colors": "deep blacks, silver greys, midnight blues, with dramatic single light sources"
    },
    {
        "name": "Caricature Art",
        "description": "Playful exaggeration of features with bold expressive lines, dynamic poses, and whimsical distortions that capture essence and personality",
        "colors": "vibrant and bold colors, strong outlines, playful contrasts"
    },
    {
        "name": "Anime Style",
        "description": "Japanese animation aesthetic with large expressive elements, dynamic compositions, detailed backgrounds, and characteristic shading techniques",
        "colors": "vibrant saturated colors, soft gradients, dramatic lighting effects"
    },
    {
        "name": "Claymation Style",
        "description": "Stop-motion clay animation look with visible texture, handcrafted imperfections, rounded forms, and charming tactile quality",
        "colors": "muted earthy tones, plasticine textures, soft studio lighting"
    }
]


class PersonaPostGenerator:
    """Service for generating persona-based posts using web search and AI."""

    def __init__(self):
        """Initialize the persona post generator."""
        self.accounts = self._load_accounts()
        self.rotation_state = self._load_rotation_state()
        self._initialize_mongodb()
        self._initialize_minio()
        self._load_config_from_mongo()
        self.client = OpenAI(api_key=self.openai_api_key)
        self.services_password = self.secrets.get("SERVICES_PASSWORD", "")

    def _initialize_mongodb(self):
        """Initialize MongoDB connection."""
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
        """Initialize MinIO S3 client."""
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
        """Load secrets and API keys from MongoDB config collection."""
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

    def _load_accounts(self) -> dict:
        """Load bot accounts from MongoDB."""
        try:
            return get_all_personas()
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
        return {"last_date": None, "poster_index": 0, "commenter_index": 2}

    def _save_rotation_state(self):
        """Save rotation state to file."""
        try:
            with open(ROTATION_STATE_FILE, 'w') as f:
                json.dump(self.rotation_state, f, indent=2)
        except Exception as e:
            logger.error(f"[ERROR] Failed to save rotation state: {e}")

    def get_todays_festival(self) -> Optional[dict]:
        """
        Check if today (IST) is a festival or vrat day.

        Returns:
            Festival data dictionary if today is a festival, None otherwise
        """
        if self.db is None:
            return None

        try:
            # Get current date in IST
            now_ist = datetime.now(IST)
            current_year = str(now_ist.year)

            # Format: "January 10" (month day format)
            current_date_str = now_ist.strftime("%B %d").replace(" 0", " ")  # Remove leading zero from day

            logger.info(f"Checking for festivals on: {current_date_str}, {current_year}")

            # Query festivals from MongoDB
            festivals = self.db["Festivals"].find({"year": current_year})

            for data in festivals:
                festival_date = data.get('date', '')

                if festival_date.strip().lower() == current_date_str.strip().lower():
                    logger.info(f"[FESTIVAL] Today is: {data.get('name')}")
                    return {
                        'name': data.get('name', ''),
                        'date': festival_date,
                        'story': data.get('festivalStory', {}),
                        'significance': data.get('significance', ''),
                        'rituals': data.get('rituals', ''),
                        'celebrations': data.get('celebrations', ''),
                        'imageUrl': data.get('imageUrl', ''),
                        'selfID': data.get('selfID', '')
                    }

            logger.info("No festival today")
            return None

        except Exception as e:
            logger.error(f"[ERROR] Failed to check festivals: {e}")
            return None

    def generate_festival_post(self, account: dict, festival: dict) -> Optional[dict]:
        """
        Generate a post about today's festival.

        Args:
            account: Account dictionary with persona details
            festival: Festival data dictionary

        Returns:
            Dictionary with post content, description, etc.
        """
        # Get language preference
        languages = account.get('languages', ['english'])
        preferred_lang = "Hindi" if 'hindi' in languages and random.random() < 0.5 else "English"
        if languages == ['hindi']:
            preferred_lang = "Hindi"

        # Get festival story in preferred language
        story_dict = festival.get('story', {})
        festival_story = story_dict.get(preferred_lang, story_dict.get('English', ''))

        prompt = f"""Write a post about the festival "{festival['name']}" being celebrated today.

Festival Information:
- Name: {festival['name']}
- Significance: {festival.get('significance', '')}
- Story: {festival_story[:500] if festival_story else 'N/A'}
- Rituals: {festival.get('rituals', '')[:300]}

Account Persona: {account.get('persona', '')}
Conversational Style: {account.get('conversational_style', '')}
Teachers they follow: {', '.join(account.get('follows', [])[:3])}

Write a post in {preferred_lang} that:
1. Wishes everyone on the occasion of {festival['name']}
2. Shares the story or significance of this festival
3. Is written in the persona's unique voice and style
4. Is 100-200 words (substantial but engaging)
5. Connects the festival to spiritual teachings the persona follows
6. Ends with blessings or an inspiring message

Return JSON format:
{{
    "content": "The full post content with festival wishes, story, and blessings",
    "saying": "A 2-5 word festival greeting or theme",
    "description": "A 15-25 word summary",
    "source_topic": "{festival['name']}"
}}

Return ONLY valid JSON."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"You are {account['name']}, sharing festival wishes in your unique spiritual voice."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
                max_tokens=800
            )
            record_openai_response(response, service="persona_post.festival")

            content = response.choices[0].message.content.strip()

            # Clean JSON
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            post_data = json.loads(content)
            post_data['language'] = preferred_lang.lower()
            post_data['is_festival_post'] = True
            post_data['festival_name'] = festival['name']

            logger.info(f"Generated festival post: {post_data.get('saying', 'N/A')}")
            return post_data

        except Exception as e:
            logger.error(f"[ERROR] Failed to generate festival post: {e}")
            return None

    def get_todays_posters(self) -> list[dict]:
        """
        Get today's poster accounts based on rotation.

        Returns:
            List of 2 account dictionaries for today's posters
        """
        account_keys = list(self.accounts.keys())
        today = date.today().isoformat()

        # Check if we need to rotate (new day)
        if self.rotation_state.get("last_date") != today:
            # Advance the poster index
            self.rotation_state["poster_index"] = (
                self.rotation_state.get("poster_index", 0) + 2
            ) % len(account_keys)
            self.rotation_state["last_date"] = today
            self._save_rotation_state()

        # Get 2 posters
        start_idx = self.rotation_state["poster_index"]
        posters = []
        for i in range(2):
            idx = (start_idx + i) % len(account_keys)
            key = account_keys[idx]
            account = self.accounts[key].copy()
            account['account_key'] = key
            posters.append(account)

        logger.info(f"Today's posters: {[p['name'] for p in posters]}")
        return posters

    def get_todays_commenters(self) -> list[dict]:
        """
        Get today's commenter accounts (those not posting).

        Returns:
            List of account dictionaries for today's commenters
        """
        account_keys = list(self.accounts.keys())
        poster_keys = [p['account_key'] for p in self.get_todays_posters()]

        commenters = []
        for key in account_keys:
            if key not in poster_keys:
                account = self.accounts[key].copy()
                account['account_key'] = key
                commenters.append(account)

        # Return up to 3 commenters
        selected = commenters[:3] if len(commenters) >= 3 else commenters
        logger.info(f"Today's commenters: {[c['name'] for c in selected]}")
        return selected

    def generate_search_query(self, account: dict) -> str:
        """
        Generate a search query based on the account's persona.

        Args:
            account: Account dictionary with persona details

        Returns:
            Search query string
        """
        # Build context from account
        persona = account.get('persona', '')
        follows = account.get('follows', [])
        topics = account.get('topics', [])
        scriptures = account.get('scriptures', [])

        # Select random elements for variety
        selected_follows = random.sample(follows, min(2, len(follows))) if follows else []
        selected_topics = random.sample(topics, min(2, len(topics))) if topics else []

        selected_saint = random.choice(selected_follows) if selected_follows else random.choice(follows) if follows else ""

        prompt = f"""You are an expert on Indian spiritual traditions, especially the life and teachings of {selected_saint or 'great Indian saints'}.

First, think of a SPECIFIC and FASCINATING incident, story, or teaching. Consider:
- A pivotal moment in {selected_saint}'s life (meeting their guru, a moment of awakening, a test of faith)
- A specific dialogue or exchange with a disciple that reveals deep wisdom
- A miracle, transformation, or dramatic event from their life
- A lesser-known but powerful story that most people haven't heard
- A specific parable or teaching story they used to explain a concept
- An incident that shows their character (humility, devotion, fearlessness, compassion)
- Their encounters with rulers, skeptics, or other saints
- Stories from {', '.join(scriptures[:2]) if scriptures else 'sacred texts'} involving specific characters and events

Account Persona: {persona}
Teachers/Saints: {', '.join(follows)}
Topics: {', '.join(topics)}

Now generate a SPECIFIC web search query to find that particular story or incident.

AVOID generic queries like "teachings of {selected_saint}" or "{selected_saint} stories".
PREFER queries like "How {selected_saint} [specific event]" or "{selected_saint} and [person] [specific incident]".

Return ONLY the search query text, nothing else. Keep it under 15 words."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You generate focused search queries for finding spiritual stories and teachings."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.9,
                max_tokens=50
            )
            record_openai_response(response, service="persona_post.search_query")
            query = response.choices[0].message.content.strip()
            query = query.strip('"\'')
            logger.info(f"Generated search query: {query}")
            return query
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate search query: {e}")
            # Fallback query
            return f"{random.choice(follows) if follows else 'spiritual'} story teaching"

    def search_web(self, query: str, max_results: int = 5) -> Tuple[list, str]:
        """
        Search the web using SerperDev.

        Args:
            query: Search query string
            max_results: Maximum number of results

        Returns:
            Tuple of (results list, source name)
        """
        try:
            conn = http.client.HTTPSConnection("google.serper.dev")
            payload = json.dumps({"q": query, "gl": "in"})  # India
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
            return results, "SerperDev"
        except Exception as e:
            logger.error(f"SerperDev search failed: {e}")
            return [], "None"

    def generate_post_from_search(self, account: dict, query: str, search_results: list) -> Optional[dict]:
        """
        Generate a post from search results in the account's style.

        Args:
            account: Account dictionary with persona details
            query: Original search query
            search_results: List of search result dictionaries

        Returns:
            Dictionary with post content, description, saying, or None
        """
        if not search_results:
            logger.warning("No search results to generate post from")
            return None

        # Build context from search results
        results_text = ""
        for i, r in enumerate(search_results[:3], 1):
            results_text += f"{i}. {r['title']}\n   {r['snippet']}\n\n"

        # Get language preference
        languages = account.get('languages', ['english'])
        preferred_lang = "Hindi" if 'hindi' in languages and random.random() < 0.5 else "English"
        if languages == ['hindi']:
            preferred_lang = "Hindi"

        prompt = f"""Based on the search results below, write a spiritual post.

Search Query: {query}

Search Results:
{results_text}

Account Persona: {account.get('persona', '')}
Conversational Style: {account.get('conversational_style', '')}
Comment Style: {account.get('comment_style', '')}
Teachers they follow: {', '.join(account.get('follows', []))}

Write a post in {preferred_lang} that:
1. Tells a specific story, incident, or teaching found in the search results
2. Is written in the persona's unique voice and style
3. Is 100-200 words (substantial but engaging)
4. Ends with an inspiring takeaway or reflection
5. Feels authentic to the persona's spiritual tradition

Return JSON format:
{{
    "content": "The full post content with the story/teaching and reflection",
    "saying": "A 2-5 word theme or tagline",
    "description": "A 15-25 word summary",
    "source_topic": "What the post is about (for image generation)"
}}

Return ONLY valid JSON."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"You are {account['name']}, writing spiritual posts in your unique voice."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
                max_tokens=800
            )
            record_openai_response(response, service="persona_post.from_search")

            content = response.choices[0].message.content.strip()

            # Clean JSON
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            post_data = json.loads(content)
            post_data['language'] = preferred_lang.lower()
            post_data['search_query'] = query

            logger.info(f"Generated post: {post_data.get('saying', 'N/A')}")
            return post_data

        except Exception as e:
            logger.error(f"[ERROR] Failed to generate post: {e}")
            return None

    def generate_image_prompt(self, post_data: dict, account: dict) -> tuple[str, dict]:
        """
        Generate an image prompt based on the post content with random style selection.

        Args:
            post_data: Post data dictionary
            account: Account dictionary

        Returns:
            Tuple of (Image generation prompt, selected style dict)
        """
        content = post_data.get('content', '')
        source_topic = post_data.get('source_topic', post_data.get('saying', 'spirituality'))

        # Select a random style from the available styles
        selected_style = random.choice(IMAGE_STYLES)

        prompt = f"""Create a beautiful, serene image for a spiritual post.

POST CONTENT:
"{content[:500]}"

Based on this post's story and meaning, create a visual scene that captures its essence.

ART STYLE: {selected_style['name']}
Style Description: {selected_style['description']}
Color Palette: {selected_style['colors']}

Requirements:
- NO TEXT whatsoever - purely visual
- The image should visually depict the key scene, story, or teaching described in the post
- Can include: human faces, graceful female figures, nature scenes, Hindu imagery, Hindu gods and goddesses (Shiva, Krishna, Lakshmi, Saraswati, Ganesh, etc.), temples, lotus flowers, mandalas, meditating figures, spiritual symbols
- Peaceful, meditative mood
- Professional quality suitable for a meditation app

IMPORTANT: Do NOT include any text, letters, words, or typography in the image.
Strictly follow the {selected_style['name']} art style."""

        return prompt, selected_style

    def generate_image(self, prompt: str, post_id: str) -> Optional[str]:
        """
        Generate image using dhyanapp-services gpt-image endpoint.

        Args:
            prompt: Image generation prompt
            post_id: Post ID for naming

        Returns:
            MinIO public URL or None
        """
        if not self.services_password:
            logger.error("[ERROR] Services password not available")
            return None

        if not self.s3_client:
            logger.error("[ERROR] MinIO not initialized")
            return None

        try:
            # Call the gpt-image endpoint
            response = requests.post(
                f"{DHYANAPP_SERVICES_URL}/image_1/generate",
                json={
                    "prompt": prompt,
                    "password": self.services_password,
                    "size": "square",
                    "quality": "medium"
                },
                timeout=120
            )

            if response.status_code != 200:
                logger.error(f"[ERROR] Image generation failed: {response.status_code} - {response.text}")
                return None

            # Upload to MinIO
            image_bytes = response.content
            object_key = f"Posts/images/bot_posts/{post_id}.webp"
            self.s3_client.put_object(
                Bucket=MINIO_BUCKET,
                Key=object_key,
                Body=image_bytes,
                ContentType="image/webp",
            )

            base_url = MINIO_PUBLIC_URL if MINIO_PUBLIC_URL else f"http://{MINIO_ENDPOINT}"
            public_url = f"{base_url}/{MINIO_BUCKET}/{object_key}"

            logger.info(f"[SUCCESS] Image uploaded to MinIO")
            return public_url

        except Exception as e:
            logger.error(f"[ERROR] Failed to generate/upload image: {e}")
            return None

    def push_post_to_db(self, account: dict, post_data: dict, image_url: Optional[str], post_id: str) -> Optional[str]:
        """
        Push the generated post to MongoDB.

        Args:
            account: Account dictionary
            post_data: Post content dictionary
            image_url: MinIO URL for image
            post_id: Pre-generated post ID

        Returns:
            Document ID if successful
        """
        if self.db is None:
            logger.error("[ERROR] MongoDB not connected")
            return None

        created_at_ms = int(datetime.now(IST).timestamp() * 1000)

        doc_data = {
            "audioBackgroundUrl": None,
            "audioUrl": None,
            "commentCount": 0,
            "composition": "SEPARATE_CONTENT",
            "content": post_data['content'],
            "createdAt": created_at_ms,
            "createdBy": account['user_id'],
            "creatorName": account['name'],
            "deleted": False,
            "deletedAt": None,
            "deletedByAdmin": False,
            "description": f"{post_data.get('saying', '')} - {post_data.get('description', '')}",
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
            "_searchQuery": post_data.get('search_query', ''),
            "_language": post_data.get('language', 'english'),
            "_imageStyle": post_data.get('_image_style', ''),
            "_isFestivalPost": post_data.get('is_festival_post', False),
            "_festivalName": post_data.get('festival_name', ''),
        }

        try:
            doc_data["_id"] = post_id
            self.db["posts"].update_one(
                {"_id": post_id},
                {"$set": doc_data},
                upsert=True
            )
            logger.info(f"[SUCCESS] Post pushed to MongoDB: {post_id}")
            return post_id
        except Exception as e:
            logger.error(f"[ERROR] Failed to push post: {e}")
            return None

    def generate_and_post(self, account: dict, festival_override: dict = None) -> Optional[str]:
        """
        Full pipeline: Generate search query, search, create post, generate image, and post.
        If today is a festival/vrat day, generates a festival post instead.

        Args:
            account: Account dictionary
            festival_override: Optional festival dict to force festival post (for testing)

        Returns:
            Post ID if successful
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"GENERATING POST FOR: {account['name']}")
        logger.info(f"{'='*60}")

        # Check if today is a festival/vrat day
        festival = festival_override or self.get_todays_festival()

        if festival:
            # Generate festival-specific post
            logger.info(f"[FESTIVAL MODE] Generating post for: {festival['name']}")
            post_data = self.generate_festival_post(account, festival)
            if not post_data:
                logger.error("Failed to generate festival post, falling back to regular post")
                festival = None  # Fall back to regular post
            else:
                logger.info(f"Generated festival post: {post_data.get('saying', 'N/A')}")

        if not festival:
            # Regular post generation
            # Step 1: Generate search query
            search_query = self.generate_search_query(account)
            logger.info(f"Search query: {search_query}")

            # Step 2: Search the web
            results, source = self.search_web(search_query)
            if not results:
                logger.error("No search results found")
                return None
            logger.info(f"Found {len(results)} results from {source}")

            # Step 3: Generate post content
            post_data = self.generate_post_from_search(account, search_query, results)
            if not post_data:
                logger.error("Failed to generate post content")
                return None
            logger.info(f"Generated post: {post_data.get('saying', 'N/A')}")

        # Step 4: Generate post ID
        post_id = str(uuid.uuid4())

        # Step 5: Generate image with random style
        image_prompt, selected_style = self.generate_image_prompt(post_data, account)
        logger.info(f"Selected image style: {selected_style['name']}")
        logger.info("Generating image...")
        image_url = self.generate_image(image_prompt, post_id)
        if image_url:
            logger.info(f"Image URL: {image_url[:60]}...")
        else:
            logger.warning("Posting without image")

        # Add style info to post data for metadata
        post_data['_image_style'] = selected_style['name']

        # Step 6: Push to MongoDB
        doc_id = self.push_post_to_db(account, post_data, image_url, post_id)

        if doc_id:
            logger.info(f"[SUCCESS] Post created: {doc_id}")
            logger.info(f"Content preview: {post_data['content'][:100]}...")

        return doc_id

    def run_daily_posts(self, enable_engagement: bool = True,
                        min_delay_minutes: int = 5, max_delay_minutes: int = 10,
                        test_mode: bool = False, single_post: bool = False) -> list[str]:
        """
        Run the daily persona-based post generation with engagement.

        Args:
            enable_engagement: Whether to trigger bot engagement after posting
            min_delay_minutes: Minimum delay between comments (default 5 minutes)
            max_delay_minutes: Maximum delay between comments (default 10 minutes)
            test_mode: If True, use short delays for testing (10-30 seconds)
            single_post: If True, only post one item from today's rotation

        Returns:
            List of created post IDs
        """
        from engagement_service import get_engagement_service

        logger.info("=" * 60)
        logger.info("PERSONA-BASED POST GENERATOR - DAILY RUN")
        logger.info(f"Date: {date.today()}")
        logger.info(f"Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
        if single_post:
            logger.info("Mode: SINGLE POST")
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
                post_id = self.generate_and_post(account)
                if post_id:
                    post_ids.append(post_id)

                    # Trigger engagement from other bots
                    if engagement_service:
                        logger.info(f"\nTriggering engagement for post by {account['name']}...")
                        time.sleep(60)  # Wait 1 minute before starting engagement
                        engagement_service.engage_with_post(
                            post_id,
                            account['account_key'],
                            min_delay_minutes=min_delay_minutes,
                            max_delay_minutes=max_delay_minutes,
                            test_mode=test_mode
                        )

                    # Delay between posts
                    time.sleep(5)
            except Exception as e:
                logger.error(f"Error generating post for {account['name']}: {e}")
                import traceback
                logger.error(traceback.format_exc())

        logger.info("=" * 60)
        logger.info(f"COMPLETED: Created {len(post_ids)} posts with engagement")
        logger.info("=" * 60)

        return post_ids


# Singleton instance
_generator = None


def get_persona_post_generator() -> PersonaPostGenerator:
    """Get the singleton instance of the persona post generator."""
    global _generator
    if _generator is None:
        _generator = PersonaPostGenerator()
    return _generator


def run_persona_posts():
    """Main function to run persona-based posts."""
    generator = get_persona_post_generator()
    return generator.run_daily_posts()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Persona-Based Post Generator")
    parser.add_argument("--run-now", action="store_true", help="Run post generation immediately")
    parser.add_argument("--single", action="store_true", help="Only post one item from today's rotation")
    parser.add_argument("--test-account", type=str, help="Test with specific account key")
    parser.add_argument("--show-rotation", action="store_true", help="Show today's rotation")
    parser.add_argument("--check-festival", action="store_true", help="Check if today is a festival")
    parser.add_argument("--test-festival", type=str, help="Test with a specific festival name (e.g., 'Maha Shivaratri')")
    parser.add_argument("--no-engagement", action="store_true", help="Skip engagement")
    parser.add_argument("--test-mode", action="store_true", help="Use short delays for testing")

    args = parser.parse_args()

    generator = get_persona_post_generator()

    if args.check_festival:
        print("\n" + "=" * 60)
        print("FESTIVAL CHECK")
        print("=" * 60)
        festival = generator.get_todays_festival()
        if festival:
            print(f"\nToday is: {festival['name']}")
            print(f"Significance: {festival.get('significance', 'N/A')}")
        else:
            print("\nNo festival today")

            # Show upcoming festivals
            print("\nUpcoming festivals in 2026:")
            festivals = generator.db["Festivals"].find({"year": "2026"})
            for d in festivals:
                print(f"  - {d.get('date')}: {d.get('name')}")

    elif args.test_festival:
        # Find the festival by name and test
        print(f"\nTesting festival post for: {args.test_festival}")
        festivals = generator.db["Festivals"].find({"year": "2026"})
        festival_data = None
        for d in festivals:
            if d.get('name', '').lower() == args.test_festival.lower():
                festival_data = {
                    'name': d.get('name', ''),
                    'date': d.get('date', ''),
                    'story': d.get('festivalStory', {}),
                    'significance': d.get('significance', ''),
                    'rituals': d.get('rituals', ''),
                    'celebrations': d.get('celebrations', ''),
                    'imageUrl': d.get('imageUrl', ''),
                }
                break

        if festival_data:
            account_key = args.test_account or 'dhyani'
            if account_key in generator.accounts:
                account = generator.accounts[account_key].copy()
                account['account_key'] = account_key
                post_id = generator.generate_and_post(account, festival_override=festival_data)
                if post_id:
                    print(f"\n[SUCCESS] Created festival post: {post_id}")

                    # Trigger engagement unless --no-engagement flag
                    if not args.no_engagement:
                        from engagement_service import get_engagement_service
                        engagement_service = get_engagement_service()
                        print("\nTriggering engagement from other bots...")
                        time.sleep(60)  # Wait 1 minute before engagement
                        engagement_service.engage_with_post(
                            post_id,
                            account_key,
                            min_delay_minutes=5,
                            max_delay_minutes=10,
                            test_mode=args.test_mode
                        )
                else:
                    print("\n[ERROR] Failed to create festival post")
            else:
                print(f"[ERROR] Account '{account_key}' not found")
        else:
            print(f"[ERROR] Festival '{args.test_festival}' not found")

    elif args.show_rotation:
        print("\n" + "=" * 60)
        print("TODAY'S ROTATION")
        print("=" * 60)

        posters = generator.get_todays_posters()
        print("\nPosters:")
        for p in posters:
            print(f"  - {p['name']} ({p['conversational_style']})")

        commenters = generator.get_todays_commenters()
        print("\nCommenters:")
        for c in commenters:
            print(f"  - {c['name']} ({c['conversational_style']})")

    elif args.test_account:
        if args.test_account in generator.accounts:
            account = generator.accounts[args.test_account].copy()
            account['account_key'] = args.test_account
            post_id = generator.generate_and_post(account)
            if post_id:
                print(f"\n[SUCCESS] Created post: {post_id}")
            else:
                print("\n[ERROR] Failed to create post")
        else:
            print(f"[ERROR] Account '{args.test_account}' not found")
            print(f"Available accounts: {list(generator.accounts.keys())}")

    elif args.run_now:
        post_ids = generator.run_daily_posts(
            enable_engagement=not args.no_engagement,
            test_mode=args.test_mode,
            single_post=args.single
        )
        print(f"\nCreated {len(post_ids)} posts")

    else:
        parser.print_help()
