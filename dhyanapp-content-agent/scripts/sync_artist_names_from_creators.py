"""Sync `artistNames` on `shlokas` and `kirtan` docs from `creator_profiles.name`.

Many docs have `artistNames.en` polluted (e.g. "Sri M" pasted everywhere) and
its localized siblings stale relative to the linked creator. This script
walks every shloka/kirtan with a `creator_id`, looks up the creator profile,
and — when `artistNames.en` differs from `creator_profiles.name` — rewrites
`artistNames` to `{"en": <creator name>}` so the translation pipeline can
regenerate the localized variants cleanly.

Usage:
    python sync_artist_names_from_creators.py          # dry-run
    python sync_artist_names_from_creators.py --apply  # write changes
"""

import argparse
import os
import sys

from pymongo import MongoClient

MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb://dhyanadmin:Dhyan%40Mongo2026!@localhost:27017/dhyanapp?authSource=admin&replicaSet=rs0",
)
DB_NAME = "dhyanapp"
COLLECTIONS = ("shlokas", "kirtan")


def sync(apply_changes: bool) -> int:
    db = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000).get_database(DB_NAME)

    # Each creator: {"name": "...", "names": {"en": "...", "hi": "...", ...}}
    creators = {}
    for c in db.creator_profiles.find({}, {"name": 1, "names": 1}):
        name = (c.get("name") or "").strip()
        names_map = c.get("names") or {}
        # Always ensure the canonical English name is present.
        if name and not names_map.get("en"):
            names_map = {**names_map, "en": name}
        creators[c["_id"]] = {"name": name, "names": names_map}

    total_updated = 0
    for coll_name in COLLECTIONS:
        coll = db[coll_name]
        updated = skipped_no_cid = skipped_unknown = skipped_blank = matched = 0

        cursor = coll.find(
            {"creator_id": {"$exists": True, "$ne": ""}},
            {"creator_id": 1, "artistNames": 1, "primaryTitle": 1},
        )
        for doc in cursor:
            cid = doc.get("creator_id")
            if not cid:
                skipped_no_cid += 1
                continue
            creator = creators.get(cid)
            if creator is None:
                skipped_unknown += 1
                print(f"  [unknown creator] {coll_name}/{doc['_id']} creator_id={cid}")
                continue
            cname = creator["name"]
            cnames = creator["names"]
            if not cname:
                skipped_blank += 1
                continue

            cur = doc.get("artistNames") or {}
            if cur == cnames:
                matched += 1
                continue

            print(
                f"  [{coll_name}] {doc['_id']} '{doc.get('primaryTitle')}' "
                f"en={cur.get('en')!r} -> {cname!r} (locales: {len(cnames)})"
            )
            if apply_changes:
                coll.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"artistNames": cnames}},
                )
            updated += 1

        print(
            f"== {coll_name}: would_update={updated} matched={matched} "
            f"no_creator_id={skipped_no_cid} unknown_creator={skipped_unknown} "
            f"blank_name={skipped_blank} =="
        )
        total_updated += updated

    print(
        f"\n{'APPLIED' if apply_changes else 'DRY RUN'}: "
        f"{total_updated} docs {'updated' if apply_changes else 'would be updated'}."
    )
    return total_updated


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()
    sync(apply_changes=args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
