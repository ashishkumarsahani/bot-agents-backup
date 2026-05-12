"""Quick smoke test: 3 random styles × 3 random chapters in parallel."""

import json
import random
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gita_post_generator as gpg

N = 4  # alternates english / hindi


def run_one(gen, style, verse, image_language):
    ch, vn = verse["_chapter_int"], verse["_verse_int"]
    t0 = time.time()
    try:
        post_data = gen.generate_post_from_verse(verse)
        if not post_data:
            return {"style": style["name"], "chapter": ch, "verse": vn,
                    "lang": image_language, "error": "post_data failed"}
        post_id = str(uuid.uuid4())
        assets = gen.generate_infographic_assets(verse, post_data, image_language)
        prompt = gen.generate_infographic_prompt(verse, assets, image_language, style)
        url = gen.generate_image(prompt, post_id)
        gen.push_post_to_db(post_data, url, post_id, verse, image_language, style["name"])
        return {
            "style": style["name"],
            "lang": image_language,
            "chapter": ch,
            "verse": vn,
            "post_id": post_id,
            "image_url": url,
            "saying": post_data.get("saying"),
            "headline": assets.get("headline"),
            "takeaway": assets.get("takeaway"),
            "content_excerpt": (post_data.get("content") or "")[:280],
            "seconds": round(time.time() - t0, 1),
        }
    except Exception as e:
        return {"style": style["name"], "lang": image_language,
                "chapter": ch, "verse": vn,
                "error": f"{type(e).__name__}: {e}"}


def main():
    gen = gpg.get_gita_post_generator()
    verses = gen._all_gita_verses_sorted()
    by_chapter = {}
    for v in verses:
        by_chapter.setdefault(v["_chapter_int"], []).append(v)

    chapters = random.sample(sorted(by_chapter.keys()), N)
    picks = [random.choice(by_chapter[c]) for c in chapters]
    styles = random.sample(gpg.GITA_IMAGE_STYLES, N)

    langs = ["english" if i % 2 == 0 else "hindi" for i in range(N)]

    print(f"Plan: {[(l, s['name'], v['_chapter_int'], v['_verse_int']) for l, s, v in zip(langs, styles, picks)]}",
          flush=True)

    results = [None] * N
    with ThreadPoolExecutor(max_workers=N) as ex:
        futs = {ex.submit(run_one, gen, s, v, l): i for i, (s, v, l) in enumerate(zip(styles, picks, langs))}
        for fut in as_completed(futs):
            i = futs[fut]
            results[i] = fut.result()
            print(f"[{i+1}/{N}] done: {results[i].get('image_url') or results[i].get('error')}",
                  flush=True)

    out = ROOT / "scripts" / "smoke_few_gita_styles_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nWrote {out}")
    for r in results:
        print(f"\n=== [{r['lang']}] {r['style']} | Ch{r['chapter']} V{r['verse']} ===")
        if "error" in r:
            print(f"  ERROR: {r['error']}")
        else:
            print(f"  URL: {r['image_url']}")
            print(f"  Headline: {r['headline']}")
            print(f"  Takeaway: {r['takeaway']}")


if __name__ == "__main__":
    main()
