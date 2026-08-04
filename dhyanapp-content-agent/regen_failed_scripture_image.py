"""
One-off: regenerate the infographic image for the scripture post that failed
image generation on 2026-06-30 due to a prompt-moderation rejection (before
the moderation model was switched from gpt-4.1-nano to gemma4:31b-cloud —
see dhyanapp-services/utils/image_utils_1.py).

The verse text/translation is reconstructed from the post's own `content`
field (no separate verse lookup needed), then the same
generate_infographic_prompt() is re-sent via generate_image(), and the post's
imageUrl/imageUrls is updated in MongoDB.
"""

import logging
from scripture_post_generator import ScripturePostGenerator, SCRIPTURE_IMAGE_STYLES

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

POST_ID = "9cbd80a5-76fb-4152-b3ce-a1cfd285caa5"


def main():
    gen = ScripturePostGenerator()
    if gen.db is None or gen.s3_client is None:
        logger.error("MongoDB or MinIO not initialized; aborting.")
        return
    if not gen.services_password:
        logger.error("SERVICES_PASSWORD missing; aborting.")
        return

    post = gen.db["posts"].find_one({"_id": POST_ID})
    if not post:
        logger.error(f"Post {POST_ID} not found; aborting.")
        return
    if post.get("imageUrl"):
        logger.info(f"Post {POST_ID} already has an image; nothing to do.")
        return

    verse = {
        "scriptureName": post.get("_scriptureName", ""),
        "chapterNumber": post.get("_chapter", ""),
        "verseNumber": post.get("_verse", ""),
        "verseText": (
            "रुद्राणां शङ्करश्चास्मि वित्तेशो यक्षरक्षसाम्।\n"
            "वसूनां पावकश्चास्मि मेरुः शिखरिणामहम्।।10.23।।"
        ),
        "translationText": (
            "Among the Rudras, I am Shankara; among the Yakshas and Rakshasas, "
            "I am the wealth-god Kubera; among the Vasus, I am Fire; and among "
            "mountains, I am Meru."
        ),
    }

    description = post.get("description", "")
    saying = description.split(" - ")[0].strip() if description else ""
    post_data = {"saying": saying}

    scripture_type = post.get("_scriptureType", "philosophical")
    image_language = post.get("_imageLanguage", "english")
    style_name = post.get("_imageStyle") or SCRIPTURE_IMAGE_STYLES[0]["name"]
    style = next((s for s in SCRIPTURE_IMAGE_STYLES if s["name"] == style_name), SCRIPTURE_IMAGE_STYLES[0])

    assets = gen.generate_infographic_assets(verse, post_data, scripture_type, image_language)
    prompt = gen.generate_infographic_prompt(verse, assets, scripture_type, style, image_language)
    logger.info(f"[{POST_ID}] Sending infographic prompt ({len(prompt)} chars, lang={image_language}, style={style_name})...")
    image_url = gen.generate_image(prompt, POST_ID)

    if not image_url:
        logger.error(f"[{POST_ID}] Image generation failed again; leaving DB unchanged.")
        return

    result = gen.db["posts"].update_one(
        {"_id": POST_ID},
        {"$set": {"imageUrl": image_url, "imageUrls": [image_url]}},
    )
    logger.info(
        f"[{POST_ID}] MongoDB updated: matched={result.matched_count} "
        f"modified={result.modified_count} url={image_url}"
    )


if __name__ == "__main__":
    main()
