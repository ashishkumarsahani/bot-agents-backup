"""One-time migration: seed Mongo `bot_personas` + `bot_config` from bot_accounts.json.

Idempotent — safe to re-run. Reads the JSON file living next to the content agent,
upserts each account into `dhyanapp.bot_personas` keyed by account id, and upserts
the three global blocks (daily_rotation, engagement_config, comment_guidelines)
into `dhyanapp.bot_config` as singleton docs.
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot_personas_store import (  # noqa: E402
    get_all_personas,
    save_bot_config,
    save_personas,
)

BOT_ACCOUNTS_JSON = Path(__file__).resolve().parent.parent / "bot_accounts.json"
CONFIG_KEYS = ("daily_rotation", "engagement_config", "comment_guidelines")


def main() -> int:
    if not BOT_ACCOUNTS_JSON.exists():
        print(f"ERROR: {BOT_ACCOUNTS_JSON} not found")
        return 1

    data = json.loads(BOT_ACCOUNTS_JSON.read_text())
    accounts = data.get("accounts", {})
    if not accounts:
        print("ERROR: no accounts in JSON")
        return 1

    print(f"Seeding {len(accounts)} personas into dhyanapp.bot_personas...")
    count = save_personas(accounts)
    print(f"  upserted {count} personas")

    for key in CONFIG_KEYS:
        block = data.get(key)
        if block is None:
            print(f"  skip {key} (absent in JSON)")
            continue
        save_bot_config(key, block)
        print(f"  upserted bot_config/{key}")

    print("\nVerification — reading back personas:")
    stored = get_all_personas()
    print(f"  found {len(stored)} docs in bot_personas")
    for account_id in sorted(stored.keys()):
        name = stored[account_id].get("name", "?")
        print(f"    - {account_id}: {name}")

    missing = set(accounts.keys()) - set(stored.keys())
    if missing:
        print(f"\nERROR: missing personas after upsert: {missing}")
        return 1

    print("\nMigration complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
