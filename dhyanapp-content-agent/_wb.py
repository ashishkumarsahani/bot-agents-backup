"""Write agent-produced Hindi translations into scripture_verses.translationTexts.hi

Validates before writing: every output entry must correspond to an input entry in
the same batch, the counts must match, and the text must actually be Devanagari.
A batch that fails validation is skipped whole rather than partially applied --
a half-written batch is far harder to reason about later than an unwritten one.

Usage:  writeback.py [--apply] [batch numbers...]
Without --apply it reports what it would do and changes nothing.
"""
import glob, json, os, re, sys

sys.path.insert(0, "/Users/epilepto/bot_agents/dhyanapp-content-agent")
from dotenv import load_dotenv
load_dotenv("/Users/epilepto/bot_agents/dhyanapp-content-agent/.env")
from pymongo import MongoClient, UpdateOne

SP = os.path.dirname(os.path.abspath(__file__))
APPLY = "--apply" in sys.argv
only = [a for a in sys.argv[1:] if a.isdigit()]

DEVA = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]{3,}")

client = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=8000)
col = client["dhyanapp"]["scripture_verses"]

total_ok = total_skip = total_written = 0
report = []

for outf in sorted(glob.glob(f"{SP}/out/out_*.json")):
    num = os.path.basename(outf).split("_")[1].split(".")[0]
    if only and num.lstrip("0") not in [o.lstrip("0") for o in only]:
        continue
    inf = f"{SP}/batches/batch_{num}.json"
    if not os.path.exists(inf):
        report.append((num, "SKIP", "no matching input batch")); total_skip += 1; continue
    try:
        src = json.load(open(inf, encoding="utf-8"))
        out = json.load(open(outf, encoding="utf-8"))
    except Exception as e:
        report.append((num, "SKIP", f"unreadable json: {e}")); total_skip += 1; continue

    if len(out) != len(src):
        report.append((num, "SKIP", f"count mismatch: {len(out)} out vs {len(src)} in"))
        total_skip += 1; continue

    src_ids = [r["id"] for r in src]
    out_ids = [r.get("id") for r in out]
    if src_ids != out_ids:
        report.append((num, "SKIP", "id order/content mismatch")); total_skip += 1; continue

    ops, bad = [], 0
    for s, o in zip(src, out):
        hi = (o.get("hi") or "").strip()
        if not s["en"].strip():
            continue
        if not hi or not DEVA.search(hi):
            bad += 1; continue
        if LATIN.search(hi):          # stray English left in the output
            bad += 1; continue
        ops.append(UpdateOne({"_id": s["id"]}, {"$set": {"translationTexts.hi": hi}}))

    if bad > len(src) * 0.05:
        report.append((num, "SKIP", f"{bad}/{len(src)} entries failed script check"))
        total_skip += 1; continue

    if APPLY and ops:
        res = col.bulk_write(ops, ordered=False)
        total_written += res.modified_count
        report.append((num, "WROTE", f"{res.modified_count} modified, {bad} rejected"))
    else:
        report.append((num, "DRY", f"{len(ops)} ready, {bad} rejected"))
    total_ok += 1

for num, status, msg in report:
    print(f"  batch {num}: {status:5s} {msg}")
print(f"\n  batches ok={total_ok} skipped={total_skip} docs_written={total_written}")
if not APPLY:
    print("  (dry run - pass --apply to write)")
