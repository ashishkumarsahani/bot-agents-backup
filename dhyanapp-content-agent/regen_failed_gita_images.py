"""
One-off: regenerate infographic images for Gita posts that failed image
generation between 2026-06-28 and 2026-07-02 due to prompt-moderation
rejections (before the moderation model was switched from gpt-4.1-nano to
gemma4:31b-cloud — see dhyanapp-services/utils/image_utils_1.py).

Re-derives infographic assets from the verse + stored post description, then
re-sends the same generate_infographic_prompt() via generate_image(), and
updates the post's imageUrl/imageUrls in MongoDB.
"""

import logging
from gita_post_generator import GitaVersePostGenerator, GITA_IMAGE_STYLES

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TARGETS = [
    {"post_id": "9d0f17e0-fbdb-4dae-ab46-67ad4d1101b5", "chapter": 3, "verse": 30},
    {"post_id": "3cdfea7c-cb4c-4af2-8535-b2c0a153d917", "chapter": 3, "verse": 31},
    {"post_id": "5b6496d5-7eb4-4141-a32c-cfad534ab3bc", "chapter": 3, "verse": 32},
    {"post_id": "05464643-4224-4f32-b299-b02020be9a6e", "chapter": 3, "verse": 37},
    {"post_id": "b4b5cf49-15c8-41d5-8f10-c5fc06ed60aa", "chapter": 3, "verse": 41},
]


def main():
    gen = GitaVersePostGenerator()
    if gen.db is None or gen.s3_client is None:
        logger.error("MongoDB or MinIO not initialized; aborting.")
        return
    if not gen.services_password:
        logger.error("SERVICES_PASSWORD missing; aborting.")
        return

    for t in TARGETS:
        post_id = t["post_id"]
        post = gen.db["posts"].find_one(
            {"_id": post_id}, {"imageUrl": 1, "_imageStyle": 1, "_imageLanguage": 1, "description": 1}
        )
        if not post:
            logger.error(f"[{post_id}] Not found; skipping.")
            continue
        if post.get("imageUrl"):
            logger.info(f"[{post_id}] Already has an image; skipping.")
            continue

        verse = gen.find_verse(t["chapter"], t["verse"])
        if verse is None:
            logger.error(f"[{post_id}] Verse Ch{t['chapter']}V{t['verse']} not found; skipping.")
            continue

        image_language = post.get("_imageLanguage", "english")
        style_name = post.get("_imageStyle") or GITA_IMAGE_STYLES[0]["name"]
        style = next((s for s in GITA_IMAGE_STYLES if s["name"] == style_name), GITA_IMAGE_STYLES[0])

        description = post.get("description", "")
        saying = description.split(" - ")[0].strip() if description else ""
        post_data = {"saying": saying}

        assets = gen.generate_infographic_assets(verse, post_data, image_language)
        prompt = gen.generate_infographic_prompt(verse, assets, image_language, style)
        logger.info(f"[{post_id}] Sending infographic prompt ({len(prompt)} chars, lang={image_language}, style={style_name})...")
        image_url = gen.generate_image(prompt, post_id)

        if not image_url:
            logger.error(f"[{post_id}] Image generation failed again; leaving DB unchanged.")
            continue

        result = gen.db["posts"].update_one(
            {"_id": post_id},
            {"$set": {"imageUrl": image_url, "imageUrls": [image_url]}},
        )
        logger.info(
            f"[{post_id}] MongoDB updated: matched={result.matched_count} "
            f"modified={result.modified_count} url={image_url}"
        )


if __name__ == "__main__":
    main()
