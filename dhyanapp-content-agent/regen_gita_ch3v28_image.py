"""
One-off: regenerate the infographic image for the Bhagavad Gita Ch3 V28 post
(post_id 7421c6ce-2df2-4e3a-87a6-200be59dee64) whose image generation failed on
2026-06-27 with a prompt-moderation rejection
("Contains excessive detailed instructions and formatting requests unsuitable
for a prompt.").

The original generate_infographic_prompt() is very long and clause-heavy, which
trips the image model's "excessive detailed instructions" moderation. This
script rebuilds a trimmed, simpler prompt with the same content elements and
re-sends it via the same /image_1/generate path, then updates the MongoDB post
with the new imageUrl.
"""

import logging
from gita_post_generator import GitaVersePostGenerator as GitaPostGenerator, GITA_IMAGE_STYLES

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

POST_ID = "7421c6ce-2df2-4e3a-87a6-200be59dee64"
CHAPTER, VERSE = 3, 28
STYLE_NAME = "Shloka Breakdown Infographic"


def build_simplified_prompt(verse: dict, style: dict) -> str:
    shloka = (verse.get("verseText") or "").strip().replace('"', "'")
    translation = (verse.get("translationText") or "").strip().replace('"', "'")
    translation_short = translation[:160].rstrip()

    label = f"Bhagavad Gita · Chapter {CHAPTER} · Verse {VERSE}"
    headline = "Seeing Beyond Action's Veil"
    takeaway = ("The awakened Self does not act and is not bound — it simply watches "
                "the qualities acting upon one another.")

    # Trimmed, single coherent description — far fewer formatting directives than
    # generate_infographic_prompt(), to avoid the "excessive detailed instructions"
    # moderation rejection while keeping the same on-image content elements.
    return (
        f"A premium square Bhagavad Gita infographic poster in a clean educational "
        f"infographic style with clear section blocks and balanced visual hierarchy. "
        f"Color palette: {style['colors']}. "
        f"Theme: {headline} — {takeaway}. "
        f"Show minimal, prominent, readable clean modern English typography with exactly "
        f"these elements: a small label reading {label}; a short headline reading "
        f"{headline}; the Sanskrit shloka reading {shloka}; a takeaway line reading "
        f"{takeaway}; and the verse meaning reading {translation_short}. "
        f"Arrange them as a clean infographic flow with simple icons and dividers — "
        f"premium, devotional, meditative feel, no clutter, no extra words. "
        f"Leave a small empty area in the lower-right corner free of text and main "
        f"visuals so a logo can be placed there."
    )


def build_minimal_fallback_prompt(verse: dict, style: dict) -> str:
    """Even shorter fallback if the simplified prompt is still rejected."""
    translation = (verse.get("translationText") or "").strip().replace('"', "'")[:140]
    return (
        f"A serene square spiritual infographic poster, {style['name']} style, "
        f"colors {style['colors']}. "
        f"Theme: seeing beyond action — the true Self watches the qualities act "
        f"and is not bound by them. "
        f"Minimal clean English typography: a heading 'Seeing Beyond Action's Veil', "
        f"a short meaning line: {translation}. "
        f"Calm devotional mood, clean layout, no clutter. Leave the lower-right "
        f"corner empty for a logo."
    )


def main():
    gen = GitaPostGenerator()
    if gen.db is None or gen.s3_client is None:
        logger.error("MongoDB or MinIO not initialized; aborting.")
        return
    if not gen.services_password:
        logger.error("SERVICES_PASSWORD missing; aborting.")
        return

    verse = gen.find_verse(CHAPTER, VERSE)
    if verse is None:
        logger.error(f"Verse Ch{CHAPTER}V{VERSE} not found; aborting.")
        return

    style = next((s for s in GITA_IMAGE_STYLES if s["name"] == STYLE_NAME), GITA_IMAGE_STYLES[0])

    # Confirm the target post still exists and is still image-less.
    post = gen.db["posts"].find_one({"_id": POST_ID}, {"imageUrl": 1, "_imageStyle": 1, "_chapter": 1, "_verse": 1})
    if not post:
        logger.error(f"Post {POST_ID} not found in MongoDB; aborting.")
        return
    logger.info(f"Target post found: _imageStyle={post.get('_imageStyle')} "
                f"Ch{post.get('_chapter')}V{post.get('_verse')} imageUrl={post.get('imageUrl')}")

    prompt = build_simplified_prompt(verse, style)
    logger.info(f"Sending simplified prompt ({len(prompt)} chars) to image service...")
    url = gen.generate_image(prompt, POST_ID)

    if not url:
        logger.warning("Simplified prompt failed; trying minimal fallback prompt...")
        prompt2 = build_minimal_fallback_prompt(verse, style)
        logger.info(f"Fallback prompt ({len(prompt2)} chars).")
        url = gen.generate_image(prompt2, POST_ID)

    if not url:
        logger.error("Both prompts failed; no image generated. MongoDB left unchanged.")
        return

    logger.info(f"Image generated and uploaded: {url}")

    result = gen.db["posts"].update_one(
        {"_id": POST_ID},
        {"$set": {"imageUrl": url, "imageUrls": [url]}},
    )
    logger.info(f"MongoDB updated: matched={result.matched_count} modified={result.modified_count}")
    logger.info(f"[SUCCESS] Post {POST_ID} now has image {url}")


if __name__ == "__main__":
    main()