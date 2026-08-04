"""
One-off: regenerate images for bot posts/articles whose image generation failed
2026-07-17 / 2026-07-18 because the dhyanapp-services /image_1/generate endpoint
was down — the Ollama moderation account had hit its weekly usage limit (429),
which aborted the request before OpenAI gpt-image-2 was ever reached.

The backend has since been patched to fall back to gpt-4o-mini for prompt
moderation, so the endpoint works again. This script re-derives each item's
original prompt (same style / language / source as the failed run) and re-sends
it via the relevant generator's generate_image(), then updates MongoDB.

The YouTube-pipeline video post from the same window is intentionally NOT
touched — video posts legitimately carry no generated image.

Run with the project venv:  .venv/bin/python regen_failed_images_last3d.py
"""

import logging

from gita_post_generator import GitaVersePostGenerator, GITA_IMAGE_STYLES
from scripture_post_generator import ScripturePostGenerator, SCRIPTURE_IMAGE_STYLES
from persona_post_generator import PersonaPostGenerator, IMAGE_STYLES as PERSONA_STYLES
from magazine_article_generator import (
    MagazineArticleGenerator, MAGAZINES, COVER_IMAGE_STYLES,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _pick_style(styles, name):
    return next((s for s in styles if s["name"] == name), styles[0])


def _update_post_image(gen, post_id, image_url, extra=None):
    fields = {"imageUrl": image_url, "imageUrls": [image_url]}
    if extra:
        fields.update(extra)
    r = gen.db["posts"].update_one({"_id": post_id}, {"$set": fields})
    logger.info(f"[{post_id}] posts updated: matched={r.matched_count} modified={r.modified_count}")


# ----------------------------------------------------------------------------
def regen_gita(gen, post_id, chapter, verse_num):
    post = gen.db["posts"].find_one({"_id": post_id})
    if not post:
        logger.error(f"[{post_id}] gita post not found; skipping."); return
    if post.get("imageUrl"):
        logger.info(f"[{post_id}] already has image; skipping."); return

    verse = gen.find_verse(chapter, verse_num)
    if verse is None:
        logger.error(f"[{post_id}] verse Ch{chapter}V{verse_num} not found; skipping."); return

    image_language = post.get("_imageLanguage", "english")
    style = _pick_style(GITA_IMAGE_STYLES, post.get("_imageStyle"))
    saying = (post.get("description") or "").split(" - ")[0].strip()

    assets = gen.generate_infographic_assets(verse, {"saying": saying}, image_language)
    prompt = gen.generate_infographic_prompt(verse, assets, image_language, style)
    logger.info(f"[{post_id}] GITA Ch{chapter}V{verse_num} lang={image_language} style={style['name']} ({len(prompt)} chars)")
    url = gen.generate_image(prompt, post_id)
    if not url:
        logger.error(f"[{post_id}] image gen failed again; DB unchanged."); return
    _update_post_image(gen, post_id, url)


# ----------------------------------------------------------------------------
def regen_scripture(gen, post_id):
    post = gen.db["posts"].find_one({"_id": post_id})
    if not post:
        logger.error(f"[{post_id}] scripture post not found; skipping."); return
    if post.get("imageUrl"):
        logger.info(f"[{post_id}] already has image; skipping."); return

    scripture_name = post.get("_scriptureName") or post.get("_scripture")
    chapter, verse_num = post.get("_chapter"), post.get("_verse")
    verse = gen.db["scripture_verses"].find_one({
        "scriptureTitle": scripture_name,
        "chapterNumber": {"$in": [chapter, str(chapter)]},
        "verseNumber": {"$in": [verse_num, str(verse_num)]},
    })
    if not verse:
        logger.error(f"[{post_id}] verse {scripture_name} Ch{chapter}V{verse_num} not found; skipping."); return
    verse.setdefault("scriptureName", scripture_name)

    scripture_type = post.get("_scriptureType", "narrative")
    image_language = post.get("_imageLanguage", "english")
    style = _pick_style(SCRIPTURE_IMAGE_STYLES, post.get("_imageStyle"))
    saying = (post.get("description") or "").split(" - ")[0].strip()

    assets = gen.generate_infographic_assets(verse, {"saying": saying}, scripture_type, image_language)
    prompt = gen.generate_infographic_prompt(verse, assets, scripture_type, style, image_language)
    logger.info(f"[{post_id}] SCRIPTURE {scripture_name} Ch{chapter}V{verse_num} type={scripture_type} style={style['name']} ({len(prompt)} chars)")
    url = gen.generate_image(prompt, post_id)
    if not url:
        logger.error(f"[{post_id}] image gen failed again; DB unchanged."); return
    _update_post_image(gen, post_id, url)


# ----------------------------------------------------------------------------
def regen_persona(gen, post_id):
    post = gen.db["posts"].find_one({"_id": post_id})
    if not post:
        logger.error(f"[{post_id}] persona post not found; skipping."); return
    if post.get("imageUrl"):
        logger.info(f"[{post_id}] already has image; skipping."); return

    content = post.get("content", "")
    style = _pick_style(PERSONA_STYLES, post.get("_imageStyle"))
    prompt = f"""Create a beautiful, serene image for a spiritual post.

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
    logger.info(f"[{post_id}] PERSONA style={style['name']} ({len(prompt)} chars)")
    url = gen.generate_image(prompt, post_id)
    if not url:
        logger.error(f"[{post_id}] image gen failed again; DB unchanged."); return
    _update_post_image(gen, post_id, url)


# ----------------------------------------------------------------------------
def regen_magazine(gen, article_id, slug, headline, style_name, image_language, category, month):
    doc = gen.db["article_files_v1"].find_one({"_id": article_id})
    if not doc:
        logger.error(f"[{article_id}] article not found; skipping."); return
    if doc.get("teaserImageURL"):
        logger.info(f"[{article_id}] already has image; skipping."); return

    mag_config = MAGAZINES[slug]
    mag_name = mag_config["name_hindi"] if image_language == "hindi" else mag_config["name"]
    label = f"{mag_name} · {month}" if month else mag_name
    style = _pick_style(COVER_IMAGE_STYLES, style_name)
    assets = {"label": label, "headline": headline}
    article = {"category": category}

    prompt = gen.generate_cover_prompt(article, assets, style, image_language, mag_config)
    logger.info(f"[{article_id}] MAGAZINE {slug} lang={image_language} style={style['name']} ({len(prompt)} chars)")
    url = gen.generate_image(prompt, article_id)
    if not url:
        logger.error(f"[{article_id}] image gen failed again; DB unchanged."); return
    r = gen.db["article_files_v1"].update_one(
        {"_id": article_id},
        {"$set": {"teaserImageURL": url, "backgroundImageURL": url}},
    )
    logger.info(f"[{article_id}] article_files_v1 updated: matched={r.matched_count} modified={r.modified_count}")


def main():
    # --- Gita + Scripture + Persona all live in the posts collection ---
    gita = GitaVersePostGenerator()
    assert gita.db is not None and gita.s3_client is not None and gita.services_password, "gita init failed"
    regen_gita(gita, "b8595009-8a9e-4203-aaf4-93cd48bd1d90", 4, 33)
    regen_gita(gita, "fc696009-7a64-4897-9d54-87fbd0174cc9", 4, 35)

    scripture = ScripturePostGenerator()
    assert scripture.db is not None and scripture.s3_client is not None and scripture.services_password, "scripture init failed"
    regen_scripture(scripture, "e8bfdaec-06c7-4930-b3f7-7d9ef5d7605b")

    persona = PersonaPostGenerator()
    assert persona.db is not None and persona.s3_client is not None and persona.services_password, "persona init failed"
    regen_persona(persona, "2e3daf98-813a-430a-8021-1f77304dddd4")
    regen_persona(persona, "dad51ec6-0d88-48e6-9ef5-f894eb719b42")

    # --- Magazine articles live in article_files_v1 (metadata taken from cron logs) ---
    mag = MagazineArticleGenerator()
    assert mag.db is not None and mag.s3_client is not None and mag.services_password, "magazine init failed"
    regen_magazine(mag, "35f76e26-e65d-40dc-b9c3-d2c7c0b9203e", "tattvaloka",
                   "विचार, शब्द और कर्म का संगम", "Cover Illustration Feature",
                   "hindi", "qna", "November 2025")
    regen_magazine(mag, "4d947ddb-8ed7-4c3f-bd43-865bdd1fef5b", "vedanta-kesari",
                   "Guide to Raising Healthy, Generous Kids", "Framed Art Plate Cover",
                   "english", "story", "December 2025")

    logger.info("Done.")


if __name__ == "__main__":
    main()
