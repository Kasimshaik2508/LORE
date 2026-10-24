"""Memory Extraction Agent logic: source record -> structured, evidence-backed memories."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import llm
from .store import Memory

REF = re.compile(r"\b(?:MR|PR|INC|ISSUE)-\d+\b")

MARKERS = {
    "decision": "architecture_decision",
    "rule": "rule",
    "commitment": "commitment",
    "root cause": "incident",
}

EXTRACTION_PROMPT = """You are the Memory Extraction Agent for LORE, an engineering knowledge system.

Analyze ONE software project record (issue, commit, merge request, review comments, incident or doc).
Extract only information explicitly supported by the record:
1. Architecture and technical decisions, and the reasoning behind them.
2. Bugs and incidents with their root causes.
3. Security rules, engineering rules and commitments (including reviewer feedback that sets a reusable rule).
4. Files, services and components affected.

Return a JSON list. Each item:
{"memory_type": "architecture_decision|rule|incident|commitment",
 "title": short title,
 "statement": the decision/rule in one sentence,
 "rationale": why, or "" if the record does not say,
 "affected_components": [file paths or service names named in the record],
 "quote": an EXACT verbatim substring of the record that supports the statement,
 "supersedes": [record ids this explicitly replaces],
 "caused_by": [record ids of incidents that caused it],
 "confidence": 0.0-1.0}

Rules:
- Never invent context. Never present an inference as a decision.
- Suggestions, questions and opinions ("maybe", "should we", "just a thought") are NOT decisions.
- Keep contradictory decisions as separate items; do not merge them.
- The quote must be copied character-for-character from the record.
- Return [] if nothing reliable can be extracted."""


@dataclass
class Extracted:
    memory: Memory
    supersedes: list[str] = field(default_factory=list)
    caused_by: list[str] = field(default_factory=list)


def record_text(rec: dict) -> str:
    parts = [f"[{rec['id']}] {rec.get('type', '')}: {rec.get('title', '')}", rec.get("body", "")]
    for c in rec.get("comments", []):
        parts.append(f"Comment by {c.get('author', '?')}:\n{c.get('body', '')}")
    return "\n\n".join(p for p in parts if p)


def _blocks(rec: dict):
    """Yield (author, text, is_review_comment) for body and each comment."""
    yield rec.get("author", ""), rec.get("body", ""), False
    for c in rec.get("comments", []):
        yield c.get("author", ""), c.get("body", ""), True


def _split_list(value: str) -> list[str]:
    return [v.strip().rstrip(".") for v in re.split(r",|;", value) if v.strip()]


def heuristic_extract(rec: dict) -> list[Extracted]:
    """Parse ADR-style markers (Decision:/Rule:/Why:/Affects:/Supersedes:/Caused by:).
    Deterministic and conservative: no markers, no memory."""
    out: list[Extracted] = []
    for author, text, is_comment in _blocks(rec):
        if not text:
            continue
        fields: dict[str, str] = {}
        items: list[tuple[str, str, str]] = []  # (memory_type, statement, quote line)
        for line in text.splitlines():
            m = re.match(r"\s*([A-Za-z ]{2,14}):\s*(.+)$", line)
            if not m:
                continue
            key, val = m.group(1).strip().lower(), m.group(2).strip()
            if key in MARKERS:
                items.append((MARKERS[key], val, line.strip()))
            else:
                fields[key] = val
        for mtype, statement, quote in items:
            components = _split_list(fields.get("affects", "")) or list(rec.get("files", []))
            mem = Memory(
                id="",
                type=mtype,
                title=rec.get("title", "") if mtype == "incident" else statement.rstrip(".")[:90],
                statement=statement,
                rationale=fields.get("why", fields.get("because", "")),
                components=components,
                source_id=rec["id"],
                source_url=rec.get("url", ""),
                timestamp=rec.get("date", ""),
                confidence=0.85 if is_comment else 0.9,
                extracted_by="heuristic",
                quote=quote,
            )
            out.append(Extracted(
                mem,
                supersedes=REF.findall(fields.get("supersedes", "")),
                caused_by=REF.findall(fields.get("caused by", "")),
            ))
    return out


def llm_extract(rec: dict) -> list[Extracted] | None:
    text = record_text(rec)
    data = llm.chat_json(EXTRACTION_PROMPT, f"Record:\n{text}\n\nMetadata: {json.dumps({k: rec.get(k) for k in ('id', 'date', 'url', 'files')})}")
    if data is None:
        return None
    if isinstance(data, dict):
        data = data.get("memories", [])
    flat = re.sub(r"\s+", " ", text)
    out = []
    for item in data if isinstance(data, list) else []:
        quote = (item.get("quote") or "").strip()
        statement = (item.get("statement") or "").strip()
        # Verification gate: every memory must be grounded in a verbatim quote.
        if not statement or not quote or re.sub(r"\s+", " ", quote) not in flat:
            continue
        mtype = item.get("memory_type", "rule")
        if mtype not in MARKERS.values():
            mtype = "rule"
        out.append(Extracted(
            Memory(
                id="",
                type=mtype,
                title=(item.get("title") or statement)[:90],
                statement=statement,
                rationale=item.get("rationale", "") or "",
                components=[str(c) for c in item.get("affected_components", [])] or list(rec.get("files", [])),
                source_id=rec["id"],
                source_url=rec.get("url", ""),
                timestamp=rec.get("date", ""),
                confidence=max(0.0, min(1.0, float(item.get("confidence", 0.6)))),
                extracted_by=f"asi1:{llm.MODEL}",
                quote=quote,
            ),
            supersedes=[s for s in item.get("supersedes", []) if isinstance(s, str)],
            caused_by=[s for s in item.get("caused_by", []) if isinstance(s, str)],
        ))
    return out


def extract(rec: dict) -> list[Extracted]:
    """Explicit markers are always honoured; the LLM adds what free text implies."""
    found = heuristic_extract(rec)
    if llm.available():
        extra = llm_extract(rec) or []
        quotes = [f.memory.quote for f in found]
        found += [e for e in extra
                  if not any(q in e.memory.quote or e.memory.quote in q for q in quotes)]
    return found
