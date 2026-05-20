"""
One-off test: generate 3 image variants for 2 Krishna verses.
Variant A: takeaway only
Variant B: takeaway + full meaning
Variant C: meaning only
"""
import random
import copy
from gita_post_generator import get_gita_post_generator, GITA_IMAGE_STYLES

TEST_VERSES = [(2, 11), (6, 5)]

gen = get_gita_post_generator()
style = random.choice(GITA_IMAGE_STYLES)
print(f"Style: {style['name']}\n")

results = []

for ch, vn in TEST_VERSES:
    verse = gen.find_verse(ch, vn)
    if not verse:
        print(f"[SKIP] Ch{ch}V{vn} not found")
        continue

    translation = (verse.get("translationText") or "").strip()
    post_data = {"saying": f"Bhagavad Gita Ch{ch}V{vn}"}
    assets_base = gen.generate_infographic_assets(verse, post_data, "english")
    takeaway = assets_base["takeaway"]

    variants = {
        "A_takeaway_only":      {**assets_base, "takeaway": takeaway},
        "B_takeaway_meaning":   {**assets_base, "takeaway": f"{takeaway}\n{translation}"},
        "C_meaning_only":       {**assets_base, "takeaway": translation},
    }

    for variant_name, assets in variants.items():
        test_id = f"test_ch{ch}v{vn}_{variant_name}"
        prompt = gen.generate_infographic_prompt(verse, assets, "english", style)
        url = gen.generate_image(prompt, test_id)
        label = f"Ch{ch}V{vn} — {variant_name}"
        print(f"{label}:\n  {url}\n")
        results.append((label, url))

print("\n=== ALL URLS ===")
for label, url in results:
    print(f"{label}:\n  {url}")
