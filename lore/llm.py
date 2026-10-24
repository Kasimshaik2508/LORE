"""ASI:One client (OpenAI-compatible). Every caller has a deterministic fallback,
so LORE still works, more conservatively, when no key is configured."""

from __future__ import annotations

import json
import logging
import os
import re

import requests

log = logging.getLogger("lore.llm")

BASE_URL = os.getenv("ASI1_BASE_URL", "https://api.asi1.ai/v1")
MODEL = os.getenv("ASI1_MODEL", "asi1")


def api_key() -> str | None:
    return os.getenv("ASI1_API_KEY") or None


def available() -> bool:
    return bool(api_key()) and os.getenv("LORE_OFFLINE", "") != "1"


def chat(system: str, user: str, temperature: float = 0.1, max_tokens: int = 1500) -> str | None:
    """Return the model's text, or None on any failure (callers then fall back)."""
    if not available():
        return None
    try:
        r = requests.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as exc:  # network, auth, quota, schema
        log.warning("ASI:One call failed, using fallback: %s", exc)
        return None


def chat_json(system: str, user: str, **kw):
    """Like chat() but parses the first JSON object/array in the reply."""
    text = chat(system, user + "\n\nRespond with JSON only.", **kw)
    if text is None:
        return None
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = m.group(1) if m else text
    start = min([i for i in (body.find("{"), body.find("[")) if i >= 0], default=-1)
    if start < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(body[start:])[0]
    except json.JSONDecodeError:
        log.warning("ASI:One returned unparseable JSON")
        return None
