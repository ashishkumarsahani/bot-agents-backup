"""
Local mirror of dhyanapp-services llm_usage_tracker.

Writes one document per OpenAI API call to MongoDB collection `llm_usage`
in the same `dhyanapp` database used elsewhere in this repo. Schema and
pricing tables match dhyanapp-services/utils/llm_usage_tracker.py so usage
from this repo aggregates with the rest of the platform.

All recording is best-effort and swallows exceptions.
"""
import logging
import os
from datetime import datetime, timezone

from pymongo import MongoClient

logger = logging.getLogger(__name__)

MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb://dhyanadmin:Dhyan%40Mongo2026!@localhost:27017/dhyanapp?authSource=admin&replicaSet=rs0",
)

_client = None
_coll = None


def _collection():
    global _client, _coll
    if _coll is not None:
        return _coll
    try:
        _client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=3000)
        _client.admin.command("ping")
        _coll = _client["dhyanapp"]["llm_usage"]
        return _coll
    except Exception:
        logger.exception("llm_usage: failed to connect to MongoDB")
        return None


OPENAI_PRICING = {
    "gpt-4o":                  {"input": 2.50,  "output": 10.00},
    "gpt-4o-2024-08-06":       {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":             {"input": 0.15,  "output": 0.60},
    "gpt-4o-mini-2024-07-18":  {"input": 0.15,  "output": 0.60},
    "gpt-4.1":                 {"input": 2.00,  "output": 8.00},
    "gpt-4.1-mini":            {"input": 0.40,  "output": 1.60},
    "gpt-4.1-nano":            {"input": 0.10,  "output": 0.40},
    "gpt-5":                   {"input": 1.25,  "output": 10.00},
    "gpt-5-mini":              {"input": 0.25,  "output": 2.00},
    "o1":                      {"input": 15.00, "output": 60.00},
    "o1-mini":                 {"input": 1.10,  "output": 4.40},
    "o3":                      {"input": 2.00,  "output": 8.00},
    "o3-mini":                 {"input": 1.10,  "output": 4.40},
    "text-embedding-3-small":  {"input": 0.02,  "output": 0.0},
    "text-embedding-3-large":  {"input": 0.13,  "output": 0.0},
    "text-embedding-ada-002":  {"input": 0.10,  "output": 0.0},
    "gpt-image-1":             {"per_image": 0.04},
    "dall-e-3":                {"per_image": 0.04},
    "dall-e-2":                {"per_image": 0.02},
}


def _pricing_for(model):
    if not model:
        return {}
    if model in OPENAI_PRICING:
        return OPENAI_PRICING[model]
    candidates = [k for k in OPENAI_PRICING if model.startswith(k)]
    if candidates:
        return OPENAI_PRICING[max(candidates, key=len)]
    return {}


def _calc_cost(pricing, prompt_tokens, completion_tokens, images):
    cost = 0.0
    if "input" in pricing or "output" in pricing:
        cost += (prompt_tokens or 0) / 1_000_000.0 * pricing.get("input", 0.0)
        cost += (completion_tokens or 0) / 1_000_000.0 * pricing.get("output", 0.0)
    if images and "per_image" in pricing:
        cost += images * pricing["per_image"]
    return cost


def record_usage(
    provider,
    model,
    service,
    *,
    prompt_tokens=0,
    completion_tokens=0,
    images=0,
    cost_usd=None,
    meta=None,
):
    """Insert one usage doc into `llm_usage`. Never raises."""
    try:
        coll = _collection()
        if coll is None:
            return
        pricing = _pricing_for(model) if provider == "openai" else {}
        if cost_usd is None:
            cost_usd = _calc_cost(pricing, prompt_tokens, completion_tokens, images)

        ts = datetime.now(timezone.utc)
        doc = {
            "ts": ts,
            "date": ts.strftime("%Y-%m-%d"),
            "provider": provider,
            "model": model or "unknown",
            "service": service or "unknown",
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "total_tokens": int((prompt_tokens or 0) + (completion_tokens or 0)),
            "chars": 0,
            "seconds": 0.0,
            "images": int(images or 0),
            "pages": 0,
            "cost_usd": float(cost_usd or 0.0),
            "meta": meta or {},
        }
        coll.insert_one(doc)
    except Exception:
        logger.exception(
            "llm_usage record failed (provider=%s model=%s service=%s)",
            provider, model, service,
        )


def record_openai_response(response, *, service, meta=None):
    """Pull `.usage` off an OpenAI chat/completions response and log it."""
    try:
        if response is None:
            return
        usage = getattr(response, "usage", None)
        model = getattr(response, "model", "unknown")
        if usage is None:
            return
        record_usage(
            "openai", model, service,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            meta=meta,
        )
    except Exception:
        logger.exception("record_openai_response failed (service=%s)", service)


def record_openai_image(*, model, service, n=1, meta=None):
    """Log an OpenAI image generation call (priced per image)."""
    record_usage("openai", model, service, images=n, meta=meta)
