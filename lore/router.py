"""Router: turns a chat message into an intent, dispatches it to a specialist agent,
and handles memory-maintenance replies (show/challenge/reaffirm/remember) itself."""

from __future__ import annotations

import json
import os
import re
from typing import Awaitable, Callable

from . import render
from .agents.protocols import (AskRequest, AskResponse, IngestRequest, IngestResponse,
                               OnboardRequest, OnboardResponse, ReviewRequest, ReviewResponse)
from .engine import Lore

# call(kind, request) -> response, where kind is "ask" | "review" | "onboard" | "ingest"
Dispatch = Callable[[str, object], Awaitable[object]]

MEM_ID = re.compile(r"\bMEM-\d{3,}\b", re.I)


MENTION = re.compile(r"(?:^|\s)@[\w.-]+")


def classify(text: str) -> tuple[str, dict]:
    # ASI:One includes "@agent1q…" mentions in the message text.
    t = MENTION.sub(" ", text).strip()
    low = t.lower()
    if not t or low in {"help", "hi", "hello", "hey", "start", "?"} \
            or re.fullmatch(r"(lore)?\s*(engineering memory|agent)?[.!?]*", low):
        return "help", {}
    if low in {"status", "stats"}:
        return "status", {}
    m = re.match(r"(show|explain|memory)\s+(MEM-\d+)\b", t, re.I)
    if m:
        return "show", {"id": m.group(2).upper()}
    m = re.match(r"(challenge|dispute|reaffirm)\s+(MEM-\d+)\s*[:,-]?\s*(.*)", t, re.I | re.S)
    if m:
        return m.group(1).lower().replace("dispute", "challenge"), {"id": m.group(2).upper(),
                                                                       "reason": m.group(3).strip()}
    m = re.match(r"remember\s*:?\s*(.+)", t, re.I | re.S)
    if m:
        body = m.group(1)
        parts = re.split(r"\s+affects?\s*:?\s+", body, maxsplit=1, flags=re.I)
        comps = [c.strip() for c in parts[1].split(",")] if len(parts) > 1 else []
        stmt, why = parts[0], ""
        because = re.split(r"\s+(?:because|since)\s+", parts[0], maxsplit=1, flags=re.I)
        if len(because) == 2:
            stmt, why = because
        sup = MEM_ID.search(body)
        return "remember", {"statement": stmt.strip().rstrip("."), "rationale": why.strip(),
                            "components": comps, "supersedes": sup.group(0).upper() if sup else ""}
    m = re.match(r"(?:import|ingest)\s+(github\s+|folder\s+)?(\S+)\s*$", t, re.I)
    if m:
        kind, target = (m.group(1) or "").strip().lower(), m.group(2)
        # owner/repo means GitHub unless it is a folder that exists here.
        if kind == "github" or (kind != "folder" and re.fullmatch(r"[\w.-]+/[\w.-]+", target)
                                and not os.path.isdir(target)):
            return "ingest", {"source": "github", "target": target}
        return "ingest", {"source": "folder", "target": target}
    if re.match(r"(onboard|onboarding|briefing|i'?m new|new here)\b", low):
        focus = re.sub(r"^(onboard(ing)?|briefing|i'?m new( here)?|new here)\s*(me)?\s*(on|about|for)?\s*", "", low)
        return "onboard", {"focus": focus.strip(" ?.")}
    if (re.match(r"(review|check|propose|proposal|pr|mr)\b\s*:?", low) or "diff --git" in t
            or re.search(r"^\+\+\+ ", t, re.M)):
        change = re.sub(r"^(review|check|propose|proposal|pr|mr)\b\s*(this|my)?\s*(change)?\s*:?\s*", "", t, flags=re.I)
        just = ""
        jm = re.search(r"\b(?:override|justification)\s*:\s*(.+)$", change, re.I | re.S)
        if jm:
            just, change = jm.group(1).strip(), change[: jm.start()].strip()
        return "review", {"change": change, "justification": just}
    return "ask", {"question": t}


async def route(text: str, actor: str, call: Dispatch, lore: Lore) -> str:
    intent, args = classify(text)
    if intent == "help":
        return render.HELP
    if intent == "status":
        return render.stats(lore.stats())
    if intent == "show":
        m = lore.store.memory(args["id"])
        if not m:
            return f"No memory {args['id']}."
        return render.memory(m.to_dict(), lore.store.events(m.id), lore.evidence(m)["links"])
    if intent in ("challenge", "reaffirm"):
        if not args["reason"]:
            return f"Please give a reason: `{intent} {args['id']}: <evidence>`."
        fn = lore.challenge if intent == "challenge" else lore.reaffirm
        m = fn(args["id"], args["reason"], actor)
        if not m:
            return f"No memory {args['id']}."
        verb = "marked **disputed** — it no longer blocks reviews until reaffirmed" if intent == "challenge" \
            else "reaffirmed as **active**"
        return f"[{m.id}] {m.statement}\n\n{verb}. Reason recorded in the audit log: “{args['reason']}”"
    if intent == "remember":
        if not args["statement"]:
            return "Usage: `remember: <decision> because <reason> affects <component, ...>`"
        m = lore.remember(args["statement"], args["rationale"], args["components"], actor, args["supersedes"])
        extra = f" It supersedes {args['supersedes']}." if args["supersedes"] else ""
        return (f"Recorded **[{m.id}]** {m.statement} (source {m.source_id}, attributed to `{actor[:16]}…`, "
                f"confidence {m.confidence:.2f}).{extra}")
    if intent == "ingest":
        r: IngestResponse = await call("ingest", IngestRequest(**args))
        return r.summary
    if intent == "onboard":
        r: OnboardResponse = await call("onboard", OnboardRequest(**args))
        return r.report_md
    if intent == "review":
        r: ReviewResponse = await call("review", ReviewRequest(actor=actor, **args))
        return r.report_md
    r: AskResponse = await call("ask", AskRequest(**args))
    return r.answer_md


# --- specialist handlers: pure functions shared by the agents, the CLI and tests ---

def handle_ingest(lore: Lore, req: IngestRequest) -> IngestResponse:
    try:
        if req.source == "github":
            s = lore.ingest_github(req.target, limit=req.limit)
        else:
            s = lore.ingest_folder(req.target)
    except Exception as exc:
        return IngestResponse(ok=False, summary=f"Import failed: {exc}")
    return IngestResponse(ok=True, created=s["memories_created"],
                          summary=f"Imported {s['records']} records from `{req.target}` "
                                  f"({s['new_records']} new) and extracted {s['memories_created']} memories.\n\n"
                                  + render.stats(lore.stats()))


def handle_ask(lore: Lore, req: AskRequest) -> AskResponse:
    r = lore.ask(req.question)
    return AskResponse(answer_md=render.ask(r), evidence_json=json.dumps(r["evidence"], default=str),
                       impact_json=json.dumps(r["impact"]) if r["impact"] else "")


def handle_review(lore: Lore, req: ReviewRequest) -> ReviewResponse:
    r = lore.review(req.change, req.files, req.justification, req.actor or "developer")
    return ReviewResponse(status=r["status"], report_md=render.review(r),
                          findings_json=json.dumps(r["findings"], default=str))


def handle_onboard(lore: Lore, req: OnboardRequest) -> OnboardResponse:
    return OnboardResponse(report_md=render.onboard(lore.onboard(req.focus)))


HANDLERS = {"ingest": handle_ingest, "ask": handle_ask, "review": handle_review, "onboard": handle_onboard}


def local_dispatch(lore: Lore) -> Dispatch:
    """Dispatch straight to handlers in-process (CLI, tests, dashboard)."""
    async def call(kind: str, req):
        return HANDLERS[kind](lore, req)
    return call
