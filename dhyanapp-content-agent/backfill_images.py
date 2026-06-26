"""
Backfill images for bot-generated posts that were created without images
due to DNS failures with dhyanapp-services.epilepto.com.

Finds all posts where _botGenerated=True and imageUrl is None,
generates an image for each using the post content, and updates MongoDB.
"""

import os
import random
import logging
import requests
import boto3
from botocore.client import Config as BotoConfig
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MongoDB
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://dhyanadmin:Dhyan%40Mongo2026!@localhost:27017/dhyanapp?authSource=admin&replicaSet=rs0")

# MinIO
_minio_host = os.getenv("MINIO_ENDPOINT", "localhost")
_minio_port = os.getenv("MINIO_PORT", "9000")
MINIO_ENDPOINT = _minio_host if ":" in _minio_host else f"{_minio_host}:{_minio_port}"
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "dhyanapp-recordings")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "https://storage.dhyanapp.org")

DHYANAPP_SERVICES_URL = "https://services.dhyanapp.org"

IMAGE_STYLES = [
    {"name": "Traditional Indian Miniature", "description": "Inspired by Rajasthani and Mughal miniature paintings with intricate details, rich colors, flat perspective, and ornate borders", "colors": "rich reds, deep blues, gold accents, saffron, and emerald greens"},
    {"name": "Tanjore Painting Style", "description": "South Indian Tanjore art style with gold leaf textures, bold outlines, and vibrant jewel tones on dark backgrounds", "colors": "gold, ruby red, deep green, royal blue on maroon or black backgrounds"},
    {"name": "Watercolor Spiritual", "description": "Soft, flowing watercolor style with gentle washes, ethereal quality, and peaceful blending of colors", "colors": "soft pinks, lavender, sky blue, pale gold, and misty whites"},
    {"name": "Mystical Ethereal", "description": "Dreamlike, mystical atmosphere with soft glowing light, cosmic elements, and spiritual symbolism", "colors": "deep purples, celestial blues, soft gold glows, starlit blacks"},
    {"name": "Sacred Geometry", "description": "Yantras, mandalas, and Sri Chakra inspired designs with precise geometric patterns and spiritual symbolism", "colors": "deep maroon, gold, white, with subtle gradient backgrounds"},
    {"name": "Anime Style", "description": "Japanese animation aesthetic with large expressive elements, dynamic compositions, detailed backgrounds, and characteristic shading techniques", "colors": "vibrant saturated colors, soft gradients, dramatic lighting effects"},
    {"name": "Lotus Garden Serene", "description": "Peaceful lotus pond scenes with morning mist, meditation imagery, and natural tranquility", "colors": "soft pinks, white, jade green, morning gold, peaceful blues"},
]


def build_image_prompt(content: str, image_style: str) -> str:
    style = next((s for s in IMAGE_STYLES if s["name"] == image_style), random.choice(IMAGE_STYLES))
    return f"""Create a beautiful, serene image for a spiritual post.

POST CONTENT:
"{content[:500]}"

Based on this post's story and meaning, create a visual scene that captures its essence.

ART STYLE: {style['name']}
Style Description: {style['description']}
Color Palette: {style['colors']}

Requirements:
- NO TEXT whatsoever - purely visual
- The image should visually depict the key scene, story, or teaching described in the post
- Can include: human faces, graceful female figures, nature scenes, Hindu imagery, Hindu gods and goddesses (Shiva, Krishna, Lakshmi, Saraswati, Ganesh, etc.), temples, lotus flowers, mandalas, meditating figures, spiritual symbols
- Peaceful, meditative mood
- Professional quality suitable for a meditation app

IMPORTANT: Do NOT include any text, letters, words, or typography in the image.
Strictly follow the {style['name']} art style."""


def generate_image(s3_client, services_password: str, prompt: str, post_id: str) -> str | None:
    try:
        response = requests.post(
            f"{DHYANAPP_SERVICES_URL}/image_1/generate",
            json={"prompt": prompt, "password": services_password, "size": "square", "quality": "medium"},
            timeout=120
        )
        if response.status_code != 200:
            logger.error(f"Image generation failed: {response.status_code} - {response.text[:200]}")
            return None

        image_bytes = response.content
        object_key = f"Posts/images/bot_posts/{post_id}.webp"
        s3_client.put_object(
            Bucket=MINIO_BUCKET,
            Key=object_key,
            Body=image_bytes,
            ContentType="image/webp",
        )
        base_url = MINIO_PUBLIC_URL if MINIO_PUBLIC_URL else f"http://{MINIO_ENDPOINT}"
        return f"{base_url}/{MINIO_BUCKET}/{object_key}"

    except Exception as e:
        logger.error(f"Failed to generate/upload image: {e}")
        return None


def main():
    # Connect to MongoDB
    mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    db = mongo_client["dhyanapp"]
    logger.info("Connected to MongoDB")

    # Connect to MinIO
    s3_client = boto3.client(
        "s3",
        endpoint_url=f"{'https' if MINIO_SECURE else 'http'}://{MINIO_ENDPOINT}",
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=BotoConfig(signature_version="s3v4"),
        region_name="us-east-1",
    )
    logger.info("Connected to MinIO")

    # Load services password from MongoDB config
    config_doc = db["config"].find_one({"_id": "secrets"}) or {}
    services_password = config_doc.get("SERVICES_PASSWORD", "")
    if not services_password:
        logger.error("SERVICES_PASSWORD not found in MongoDB config")
        return

    # Find all bot posts without images
    query = {
        "_botGenerated": True,
        "$or": [
            {"imageUrl": None},
            {"imageUrl": {"$exists": False}},
            {"imageUrls": []},
        ]
    }
    posts = list(db["posts"].find(query, {"_id": 1, "content": 1, "_imageStyle": 1}))
    logger.info(f"Found {len(posts)} posts without images")

    if not posts:
        logger.info("Nothing to backfill.")
        return

    success = 0
    failed = 0

    for post in posts:
        post_id = post["_id"]
        content = post.get("content", "")
        image_style = post.get("_imageStyle", "")

        logger.info(f"Processing post {post_id} (style: {image_style or 'random'})")

        prompt = build_image_prompt(content, image_style)
        image_url = generate_image(s3_client, services_password, prompt, post_id)

        if image_url:
            db["posts"].update_one(
                {"_id": post_id},
                {"$set": {"imageUrl": image_url, "imageUrls": [image_url]}}
            )
            logger.info(f"[SUCCESS] Updated post {post_id}")
            success += 1
        else:
            logger.warning(f"[FAILED] Could not generate image for post {post_id}")
            failed += 1

    logger.info("=" * 60)
    logger.info(f"Backfill complete: {success} updated, {failed} failed")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
