"""Daily self-healing sweep for bot images that failed generation.

Scans the last N days (default 5) for bot posts / magazine articles whose image
generation failed (empty imageUrl / teaserImageURL) and regenerates them, with
retry + backoff to ride over transient upstream 502/5xx blips and stochastic
output-moderation flakiness.

Failure classes seen in practice (see investigation 2026-08-13):
  1. Transient infra  — Cloudflare 502 / gateway blips.        -> retry fixes it.
  2. Output moderation — OpenAI flags the *generated* image.    -> retry often fixes it (stochastic).
  3. Input moderation  — OpenAI blocks the *prompt*, e.g.
     category 'public-figure' (real names like Gandhi).        -> retry canNOT fix; needs prompt fix.
The backend currently masks all of these as a generic HTTP 500, so we classify
by outcome: anything still missing after all retries is reported as NEEDS-ATTENTION.

Idempotent: skips any item that already has an image. Never deletes.

Usage:  .venv/bin/python heal_failed_images.py [--days 5] [--attempts 3] [--dry-run]
"""
import argparse
import logging
import time
from datetime import datetime

from regen_failed_images_last3d import (
    regen_gita, regen_scripture, regen_persona, regen_magazine,
)
from gita_post_generator import GitaVersePostGenerator
from scripture_post_generator import ScripturePostGenerator
from persona_post_generator import PersonaPostGenerator
from magazine_article_generator import MagazineArticleGenerator, MAGAZINES

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("heal_images")

BACKOFF = [10, 30, 60]  # seconds between attempts


def _missing(v):
    return v in (None, "")


def _post_has_image(db, pid):
    d = db["posts"].find_one({"_id": pid}, {"imageUrl": 1})
    return bool(d and d.get("imageUrl"))


def _article_has_image(db, aid):
    d = db["article_files_v1"].find_one({"_id": aid}, {"teaserImageURL": 1})
    return bool(d and d.get("teaserImageURL"))


def _derive_magazine_args(doc):
    """Best-effort reconstruction of regen_magazine() args from the stored doc."""
    sub = doc.get("subTitle") or ""            # e.g. "Tattvaloka · November 2025 · Article"
    parts = [p.strip() for p in sub.split("·")]
    mag_name = parts[0] if parts else ""
    month = parts[1] if len(parts) > 1 else ""
    slug = next((k for k, v in MAGAZINES.items()
                 if mag_name.lower() in (v.get("name", "").lower(), v.get("name_hindi", "").lower())),
                None)
    lang = "hindi" if (doc.get("primaryLanguage", "").lower() == "hindi") else "english"
    return {
        "slug": slug,
        "headline": doc.get("primaryTitle") or "",
        "style_name": doc.get("_imageStyle"),        # may be None -> _pick_style falls back
        "image_language": lang,
        "category": (doc.get("ArticleCategory") or "story").lower(),
        "month": month,
    }


def heal_item(kind, ident, regen_call, has_image, attempts, dry_run):
    """Run regen_call() with retries until the item has an image or attempts run out."""
    label = f"[{kind}:{ident}]"
    if has_image():
        logger.info(f"{label} already has image; skip.")
        return "ok"
    if dry_run:
        logger.info(f"{label} DRY-RUN would regenerate.")
        return "dry"
    for attempt in range(1, attempts + 1):
        logger.info(f"{label} attempt {attempt}/{attempts}")
        try:
            regen_call()
        except Exception as e:
            logger.error(f"{label} regen raised: {e}")
        if has_image():
            logger.info(f"{label} HEALED on attempt {attempt}.")
            return "healed"
        if attempt < attempts:
            wait = BACKOFF[min(attempt - 1, len(BACKOFF) - 1)]
            logger.info(f"{label} still missing; waiting {wait}s before retry.")
            time.sleep(wait)
    logger.warning(f"{label} NEEDS-ATTENTION — still missing after {attempts} attempts "
                   f"(likely input-moderation block, e.g. public-figure; retry cannot fix).")
    return "needs_attention"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now_ms = int(datetime.now().timestamp() * 1000)
    cutoff_ms = now_ms - args.days * 24 * 60 * 60 * 1000
    logger.info(f"=== Healing sweep: last {args.days} days, up to {args.attempts} attempts/item, "
                f"dry_run={args.dry_run} ===")

    gita = GitaVersePostGenerator()
    scripture = ScripturePostGenerator()
    persona = PersonaPostGenerator()
    magazine = MagazineArticleGenerator()
    for g, name in [(gita, "gita"), (scripture, "scripture"), (persona, "persona"), (magazine, "magazine")]:
        assert g.db is not None and g.s3_client is not None and g.services_password, f"{name} init failed"
    db = persona.db  # posts live in the same 'dhyanapp' db for every generator

    summary = {"healed": 0, "needs_attention": 0, "ok": 0, "dry": 0}

    # ---- posts (gita / scripture / persona) ----
    posts_q = {
        "_botGenerated": True,
        "createdAt": {"$gte": cutoff_ms},
        "$or": [{"imageUrl": {"$in": [None, ""]}}, {"imageUrl": {"$exists": False}}],
        "deleted": {"$ne": True},
        "isYouTubeVideo": {"$ne": True},
        "videoUrl": {"$in": [None, ""]},
    }
    posts = list(db["posts"].find(posts_q))
    logger.info(f"posts needing image: {len(posts)}")
    for p in posts:
        pid = p["_id"]
        gtype = p.get("_generatorType", "")
        if gtype == "gita_daily_verse":
            ch, v = p.get("_chapter"), p.get("_verse")
            call = lambda pid=pid, ch=ch, v=v: regen_gita(gita, pid, ch, v)
        elif gtype == "scripture_daily_verse":
            call = lambda pid=pid: regen_scripture(scripture, pid)
        else:  # persona / quote / festival posts
            call = lambda pid=pid: regen_persona(persona, pid)
        res = heal_item("post", pid, call, lambda pid=pid: _post_has_image(db, pid),
                        args.attempts, args.dry_run)
        summary[res] = summary.get(res, 0) + 1

    # ---- magazine articles ----
    art_q = {
        "AIGeneratedText": True,
        "creationTimeEpoch": {"$gte": cutoff_ms},
        "$or": [{"teaserImageURL": {"$in": [None, ""]}}, {"teaserImageURL": {"$exists": False}}],
    }
    arts = list(db["article_files_v1"].find(art_q))
    logger.info(f"magazine articles needing image: {len(arts)}")
    for a in arts:
        aid = a["_id"]
        m = _derive_magazine_args(a)
        if not m["slug"]:
            logger.warning(f"[article:{aid}] cannot resolve magazine slug from subTitle; skipping.")
            summary["needs_attention"] += 1
            continue
        call = lambda aid=aid, m=m: regen_magazine(
            magazine, aid, m["slug"], m["headline"], m["style_name"],
            m["image_language"], m["category"], m["month"])
        res = heal_item("article", aid, call, lambda aid=aid: _article_has_image(db, aid),
                        args.attempts, args.dry_run)
        summary[res] = summary.get(res, 0) + 1

    logger.info(f"=== Sweep done. healed={summary['healed']} "
                f"needs_attention={summary['needs_attention']} "
                f"already_ok={summary['ok']} dry={summary['dry']} ===")
    if summary["needs_attention"]:
        logger.warning(f"{summary['needs_attention']} item(s) NEED MANUAL ATTENTION "
                       f"(persistent moderation block).")


if __name__ == "__main__":
    main()
