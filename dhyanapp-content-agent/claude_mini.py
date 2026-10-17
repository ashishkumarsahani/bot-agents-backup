"""
Shared Claude Haiku helper — replacement for the old gpt-4o-mini chat calls.

Takes OpenAI-style chat `messages` (system/user/assistant, string or
content-part lists incl. `image_url` parts), converts them to the Anthropic
Messages API shape and calls `claude-haiku-5-5` through the official
`anthropic` SDK. Returns the reply text (or a cleaned JSON string when
`json_mode` is set) and records usage to `llm_usage` (provider "anthropic").

The API key is read from MongoDB `config` doc `{_id: "secrets"}` field
`ANTHROPIC_API_KEY` (same place the generators read OPENAI_API_KEY), with the
ANTHROPIC_API_KEY env var as fallback. The client is cached per process.
"""
import logging
import os
import re
import threading

import anthropic
from pymongo import MongoClient

from llm_usage_tracker import record_anthropic_response

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-5-5"
MIN_MAX_TOKENS = 4096  # adaptive thinking counts against max_tokens
LONG_MAX_TOKENS = 16000  # long articles / translations

MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb://dhyanadmin:Dhyan%40Mongo2026!@localhost:27017/dhyanapp?authSource=admin&replicaSet=rs0",
)

_client = None
_client_lock = threading.Lock()

_DATA_URI_RE = re.compile(r"^data:([^;,]+);base64,(.*)$", re.DOTALL)


class ClaudeMiniError(RuntimeError):
    """Raised when Claude returns no usable answer (refusal, truncation, empty)."""


def _load_api_key() -> str:
    key = ""
    try:
        mc = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        try:
            doc = mc["dhyanapp"]["config"].find_one({"_id": "secrets"}) or {}
            key = doc.get("ANTHROPIC_API_KEY", "") or ""
        finally:
            mc.close()
    except Exception as e:
        logger.warning(f"claude_mini: could not read secrets from MongoDB: {e}")
    return key or os.getenv("ANTHROPIC_API_KEY", "")


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            key = _load_api_key()
            if not key:
                raise ClaudeMiniError("ANTHROPIC_API_KEY not found in Mongo secrets or env")
            _client = anthropic.Anthropic(api_key=key, timeout=300.0, max_retries=3)
    return _client


def _convert_part(part):
    """OpenAI content part -> Anthropic content block (or None to drop)."""
    if isinstance(part, str):
        return {"type": "text", "text": part} if part else None
    ptype = part.get("type")
    if ptype == "text":
        text = part.get("text") or ""
        return {"type": "text", "text": text} if text else None
    if ptype == "image_url":
        img = part.get("image_url")
        url = img.get("url") if isinstance(img, dict) else img
        if not url:
            return None
        m = _DATA_URI_RE.match(url)
        if m:
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)},
            }
        return {"type": "image", "source": {"type": "url", "url": url}}
    if ptype in ("image", "document"):
        return part  # already Anthropic-shaped
    logger.warning(f"claude_mini: dropping unsupported content part type {ptype!r}")
    return None


def _content_blocks(content):
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    return [b for b in (_convert_part(p) for p in content) if b]


def convert_messages(messages):
    """Split OpenAI-style messages into (system_text, anthropic_messages)."""
    system_parts = []
    out = []
    for msg in messages or []:
        role = msg.get("role")
        content = msg.get("content")
        if role in ("system", "developer"):
            if isinstance(content, str):
                system_parts.append(content)
            else:
                system_parts.extend(
                    b["text"] for b in _content_blocks(content) if b.get("type") == "text"
                )
            continue
        role = "assistant" if role == "assistant" else "user"
        blocks = _content_blocks(content)
        if not blocks:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)  # merge consecutive same-role turns
        else:
            out.append({"role": role, "content": blocks})
    return "\n\n".join(p for p in system_parts if p), out


def extract_json(text: str, kind: str = "object") -> str:
    """Strip fences and return the substring from the first opening bracket to
    the last matching closing bracket. `kind` is "object" ({}) or "array" ([])."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    open_ch, close_ch = ("[", "]") if kind == "array" else ("{", "}")
    start = s.find(open_ch)
    end = s.rfind(close_ch)
    if start == -1 or end == -1 or end < start:
        raise ClaudeMiniError(f"no JSON {kind} found in Claude reply: {s[:200]!r}")
    return s[start:end + 1]


def chat(messages, *, max_tokens: int = MIN_MAX_TOKENS, service: str = None,
         json_mode=False, meta: dict = None, **_ignored) -> str:
    """Run one Claude Haiku call over OpenAI-style `messages`; return reply text.

    json_mode: False, True / "object" (expects a JSON object) or "array".
    When set, an instruction to return only JSON is appended and the returned
    string is the extracted JSON (ready for json.loads).
    Any OpenAI-only kwargs (temperature, top_p, response_format, ...) passed in
    `_ignored` are deliberately dropped. Raises on failure.
    """
    system, conv = convert_messages(messages)
    kind = None
    if json_mode:
        kind = "array" if json_mode == "array" else "object"
        instruction = (
            "Return ONLY a JSON array — no prose, no code fences."
            if kind == "array" else
            "Return ONLY a JSON object — no prose, no code fences."
        )
        if conv and conv[-1]["role"] == "user":
            conv[-1]["content"].append({"type": "text", "text": instruction})
        else:
            conv.append({"role": "user", "content": [{"type": "text", "text": instruction}]})

    kwargs = dict(
        model=MODEL,
        max_tokens=max(int(max_tokens or 0), MIN_MAX_TOKENS),
        messages=conv,
        output_config={"effort": "medium"},
    )
    if system:
        kwargs["system"] = system

    response = get_client().messages.create(**kwargs)
    record_anthropic_response(response, service=service or "claude_mini", meta=meta)

    if response.stop_reason in ("refusal", "max_tokens"):
        raise ClaudeMiniError(f"Claude stop_reason={response.stop_reason} (service={service})")
    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
    if not text:
        raise ClaudeMiniError(f"Claude returned empty text (service={service})")
    return extract_json(text, kind) if kind else text
