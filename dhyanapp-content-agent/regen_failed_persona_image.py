"""
One-off: regenerate the image for the persona post that failed image
generation on 2026-07-02. First attempt was rejected by OpenAI's own
image-safety system with `moderation_blocked` / category `public-figure`
(the prompt named real historical figures — Gandhi and Rajagopalachari —
requesting a photorealistic likeness). Retrying with a stylized cartoon /
papercut illustration style instead of a realistic depiction, since
non-photorealistic renderings of historical scenes are far less likely to
trip the public-figure classifier.
"""

import logging
from persona_post_generator import PersonaPostGenerator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

POST_ID = "d9570d0c-8069-4f73-b677-f050ae8bf3e6"

STYLIZED_STYLE = {
    "name": "Papercut Storybook",
    "description": "Flat, layered papercut / cut-paper illustration style with soft shadows, simple shapes, and warm storybook charm — clearly stylized and non-photorealistic, not a realistic likeness of any person",
    "colors": "warm cream, muted saffron, dusty blue, soft brown, and gentle gold",
}


def main():
    gen = PersonaPostGenerator()
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

    content = post.get("content", "")

    prompt = f"""Create a beautiful, stylized illustration for a spiritual/historical storytelling post.

POST CONTENT (for scene context only):
"{content[:500]}"

Depict the general scene and mood of this moment — a quiet railway-station conversation about truth and non-violence — WITHOUT rendering any specific person's realistic likeness or facial identity. Use anonymous, generic silhouetted or simplified cartoon-like figures (no recognizable facial features of any real historical individual), a vintage Indian railway station setting, soft early-morning light.

ART STYLE: {STYLIZED_STYLE['name']}
Style Description: {STYLIZED_STYLE['description']}
Color Palette: {STYLIZED_STYLE['colors']}

Requirements:
- NO TEXT whatsoever - purely visual
- Clearly a stylized illustration, not a photorealistic image, and not a recognizable likeness of any real person
- Peaceful, reflective, historical-storybook mood
- Professional quality suitable for a meditation app

IMPORTANT: Do NOT include any text, letters, words, or typography in the image. Do NOT attempt to render the specific facial likeness of any named historical figure — keep any human figures simplified, silhouetted, or stylized."""

    logger.info(f"[{POST_ID}] Sending stylized image prompt ({len(prompt)} chars, style={STYLIZED_STYLE['name']})...")
    image_url = gen.generate_image(prompt, POST_ID)

    if not image_url:
        logger.error(f"[{POST_ID}] Image generation failed again; leaving DB unchanged.")
        return

    result = gen.db["posts"].update_one(
        {"_id": POST_ID},
        {"$set": {"imageUrl": image_url, "imageUrls": [image_url], "_imageStyle": STYLIZED_STYLE["name"]}},
    )
    logger.info(
        f"[{POST_ID}] MongoDB updated: matched={result.matched_count} "
        f"modified={result.modified_count} url={image_url}"
    )


if __name__ == "__main__":
    main()
