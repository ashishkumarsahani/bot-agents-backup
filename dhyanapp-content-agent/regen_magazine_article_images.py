"""
One-off: regenerate cover images for Tattvaloka articles whose image generation
failed on 2026-06-29 and 2026-07-03 with prompt-moderation rejections
("too long/detailed for a single image-generation request"), from before the
moderation model was switched from gpt-4.1-nano to gemma4:31b-cloud
(see utils/image_utils_1.py). Re-sends the same cover prompt via
generate_cover_prompt() -> generate_image(), then updates article_files_v1
with the new teaserImageURL/backgroundImageURL.

latest_content already has entries for both articles (contentId points at the
same _id) — no image field lives there, so no update needed there.
"""

import logging
from magazine_article_generator import (
    MagazineArticleGenerator, MAGAZINES, COVER_IMAGE_STYLES,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TARGETS = [
    {
        # 2026-07-24: cover image timed out (read timeout=120) at 05:32 IST;
        # article published image-less. Regenerate now with the new retry/180s path.
        "article_id": "84a37af1-a293-4ea2-95e9-20ca5de66110",
        "month": "February 2026",
        "headline": "चतु: श्लोकी मनुस्मृति का वैज्ञानिक विश्लेषण",
        "style_name": "Hero Portrait Cover",
    },
]

IMAGE_LANGUAGE = "hindi"
MAGAZINE_SLUG = "tattvaloka"


def main():
    gen = MagazineArticleGenerator()
    if gen.db is None or gen.s3_client is None:
        logger.error("MongoDB or MinIO not initialized; aborting.")
        return
    if not gen.services_password:
        logger.error("SERVICES_PASSWORD missing; aborting.")
        return

    magazine_config = MAGAZINES[MAGAZINE_SLUG]
    magazine_name_hindi = magazine_config["name_hindi"]

    for t in TARGETS:
        article_id = t["article_id"]
        doc = gen.db["article_files_v1"].find_one(
            {"_id": article_id}, {"teaserImageURL": 1, "backgroundImageURL": 1, "primaryTitle": 1}
        )
        if not doc:
            logger.error(f"Article {article_id} not found; skipping.")
            continue
        if doc.get("teaserImageURL"):
            logger.info(f"Article {article_id} already has an image; skipping.")
            continue

        label = f"{magazine_name_hindi} · {t['month']}"
        assets = {"label": label, "headline": t["headline"]}
        style = next((s for s in COVER_IMAGE_STYLES if s["name"] == t["style_name"]), COVER_IMAGE_STYLES[0])
        source_article = {"category": "article"}

        prompt = gen.generate_cover_prompt(source_article, assets, style, IMAGE_LANGUAGE, magazine_config)
        logger.info(f"[{article_id}] Sending cover prompt ({len(prompt)} chars) to image service...")
        image_url = gen.generate_image(prompt, article_id)

        if not image_url:
            logger.error(f"[{article_id}] Image generation failed again; leaving DB unchanged.")
            continue

        result = gen.db["article_files_v1"].update_one(
            {"_id": article_id},
            {"$set": {"teaserImageURL": image_url, "backgroundImageURL": image_url}},
        )
        logger.info(
            f"[{article_id}] MongoDB updated: matched={result.matched_count} "
            f"modified={result.modified_count} url={image_url}"
        )

        lc = gen.db["latest_content"].find_one({"_id": article_id})
        logger.info(f"[{article_id}] latest_content entry present: {bool(lc)}")


if __name__ == "__main__":
    main()
