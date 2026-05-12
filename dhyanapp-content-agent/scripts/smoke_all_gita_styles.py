"""One-off smoke test: render one Gita post per GITA_IMAGE_STYLES entry,
each on a different randomly chosen (chapter, verse). Writes results to
scripts/smoke_all_gita_styles_results.json and a markdown summary."""

import json
import random
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gita_post_generator as gpg

RESULTS_JSON = ROOT / "scripts" / "smoke_all_gita_styles_results.json"
RESULTS_MD = ROOT / "scripts" / "smoke_all_gita_styles_results.md"


def pick_random_verse_per_style(gen, n_styles):
    """Pick n_styles distinct (chapter, verse) pairs from diverse chapters."""
    verses = gen._all_gita_verses_sorted()
    by_chapter = {}
    for v in verses:
        by_chapter.setdefault(v["_chapter_int"], []).append(v)

    chapters = sorted(by_chapter.keys())
    random.shuffle(chapters)
    picks = []
    for ch in chapters:
        picks.append(random.choice(by_chapter[ch]))
        if len(picks) >= n_styles:
            break
    while len(picks) < n_styles:
        picks.append(random.choice(verses))
    return picks


def run():
    gen = gpg.get_gita_post_generator()
    styles = list(gpg.GITA_IMAGE_STYLES)
    verses = pick_random_verse_per_style(gen, len(styles))

    results = []
    for i, (style, verse) in enumerate(zip(styles, verses), start=1):
        ch, vn = verse["_chapter_int"], verse["_verse_int"]
        print(f"\n[{i}/{len(styles)}] STYLE={style['name']!r} Ch{ch} V{vn}", flush=True)
        t0 = time.time()
        entry = {
            "style": style["name"],
            "chapter": ch,
            "verse": vn,
        }
        try:
            # Force this style for this run
            gpg.GITA_IMAGE_STYLES = [style]

            post_data = gen.generate_post_from_verse(verse)
            if not post_data:
                entry["error"] = "post_data generation failed"
                results.append(entry)
                continue

            import uuid
            post_id = str(uuid.uuid4())
            image_language = "english"  # keep consistent for comparability
            assets = gen.generate_infographic_assets(verse, post_data, image_language)
            image_prompt = gen.generate_infographic_prompt(verse, assets, image_language, style)
            image_url = gen.generate_image(image_prompt, post_id)
            doc_id = gen.push_post_to_db(post_data, image_url, post_id, verse,
                                          image_language, style["name"])

            entry.update({
                "post_id": doc_id,
                "image_url": image_url,
                "saying": post_data.get("saying"),
                "description": post_data.get("description"),
                "headline": assets.get("headline"),
                "takeaway": assets.get("takeaway"),
                "content_excerpt": (post_data.get("content") or "")[:280],
                "seconds": round(time.time() - t0, 1),
            })
        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {e}"
            entry["trace"] = traceback.format_exc()
            print(f"  ERROR: {entry['error']}", flush=True)

        results.append(entry)
        RESULTS_JSON.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"  -> {entry.get('image_url')}", flush=True)

    # Markdown summary
    lines = ["# Gita image style smoke-test results", ""]
    for r in results:
        lines.append(f"## {r['style']} — Ch{r['chapter']} V{r['verse']}")
        if "error" in r:
            lines.append(f"- ERROR: `{r['error']}`")
        else:
            lines.append(f"- URL: {r['image_url']}")
            lines.append(f"- Saying: {r.get('saying')}")
            lines.append(f"- Headline (on image): {r.get('headline')}")
            lines.append(f"- Takeaway (on image): {r.get('takeaway')}")
            lines.append(f"- Time: {r.get('seconds')}s")
        lines.append("")
    RESULTS_MD.write_text("\n".join(lines))
    print(f"\nDone. Results: {RESULTS_JSON}\nSummary: {RESULTS_MD}")


if __name__ == "__main__":
    run()
