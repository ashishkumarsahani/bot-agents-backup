"""MongoDB-backed bot persona store.

Personas live in `dhyanapp.bot_personas`, keyed by `_id = account_id`.
Global config blocks (daily_rotation, engagement_config, comment_guidelines)
live in `dhyanapp.bot_config` as singleton docs keyed by `_id = <block>`.
"""

import os
import time
from datetime import datetime
from typing import Optional

from pymongo import MongoClient

MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb://dhyanadmin:Dhyan%40Mongo2026!@localhost:27017/dhyanapp?authSource=admin&replicaSet=rs0",
)
DB_NAME = "dhyanapp"
PERSONAS_COLL = "bot_personas"
CONFIG_COLL = "bot_config"
CACHE_TTL_SECONDS = 60

_client: Optional[MongoClient] = None
_personas_cache: tuple[float, dict] | None = None


def _db():
    global _client
    if _client is None:
        _client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
    return _client[DB_NAME]


def _strip_id(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in ("_id", "updated_at")}


def get_all_personas() -> dict:
    """Return `{account_id: persona_dict}` shaped like the legacy JSON `accounts` map."""
    global _personas_cache
    now = time.monotonic()
    if _personas_cache and now - _personas_cache[0] < CACHE_TTL_SECONDS:
        return _personas_cache[1]
    docs = _db()[PERSONAS_COLL].find()
    out = {doc["_id"]: _strip_id(doc) for doc in docs}
    _personas_cache = (now, out)
    return out


def get_persona(account_id: str) -> Optional[dict]:
    doc = _db()[PERSONAS_COLL].find_one({"_id": account_id})
    return _strip_id(doc) if doc else None


def save_persona(account_id: str, persona: dict) -> None:
    payload = {**persona, "updated_at": datetime.utcnow()}
    _db()[PERSONAS_COLL].update_one(
        {"_id": account_id}, {"$set": payload}, upsert=True
    )
    _invalidate_cache()


def save_personas(personas: dict) -> int:
    coll = _db()[PERSONAS_COLL]
    now = datetime.utcnow()
    count = 0
    for account_id, persona in personas.items():
        coll.update_one(
            {"_id": account_id},
            {"$set": {**persona, "updated_at": now}},
            upsert=True,
        )
        count += 1
    _invalidate_cache()
    return count


def get_bot_config(key: str) -> Optional[dict]:
    doc = _db()[CONFIG_COLL].find_one({"_id": key})
    return _strip_id(doc) if doc else None


def save_bot_config(key: str, value: dict) -> None:
    _db()[CONFIG_COLL].update_one(
        {"_id": key},
        {"$set": {**value, "updated_at": datetime.utcnow()}},
        upsert=True,
    )


def _invalidate_cache() -> None:
    global _personas_cache
    _personas_cache = None
