"""Specialist uAgents. Each owns one job and speaks a typed request/response protocol."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from uagents import Agent, Context, Protocol
from uagents.resolver import Resolver
from uagents_core.identity import Identity

from ..engine import Lore
from ..router import HANDLERS
from .protocols import (AskRequest, AskResponse, IngestRequest, IngestResponse, OnboardRequest,
                        OnboardResponse, ReviewRequest, ReviewResponse)

SEED_FILE = Path(__file__).resolve().parents[2] / "data" / ".agent_seed"

SPECS = {
    "ingest": ("lore-extractor", IngestRequest, IngestResponse,
               "Imports repository history and extracts evidence-backed engineering memories."),
    "ask": ("lore-retriever", AskRequest, AskResponse,
            "Answers questions about a codebase's decisions with sources and impact analysis."),
    "review": ("lore-reviewer", ReviewRequest, ReviewResponse,
               "Checks proposed changes against recorded decisions, rules and incidents."),
    "onboard": ("lore-onboarding", OnboardRequest, OnboardResponse,
                "Builds a briefing for new developers from the project's memory."),
}


def seed_for(name: str) -> str:
    """Stable per-install seed so agent addresses survive restarts but differ between installs."""
    base = os.getenv("LORE_SEED")
    if not base:
        SEED_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not SEED_FILE.exists():
            SEED_FILE.write_text(secrets.token_hex(32))
        base = SEED_FILE.read_text().strip()
    return f"{base}/{name}"


def address_of(name: str) -> str:
    return Identity.from_seed(seed_for(name), 0).address


def make_specialist(kind: str, lore: Lore, port: int | None = None, resolve: Resolver | None = None) -> Agent:
    name, req_t, resp_t, description = SPECS[kind]
    agent = Agent(name=name, seed=seed_for(name), port=port, description=description,
                  publish_agent_details=False, resolve=resolve)
    proto = Protocol(name=name, version="0.1.0")
    handler = HANDLERS[kind]

    @proto.on_message(req_t, replies=resp_t)
    async def on_request(ctx: Context, sender: str, msg):
        ctx.logger.info(f"{kind} request from {sender[:16]}…")
        await ctx.send(sender, handler(lore, msg))

    agent.include(proto)

    if kind == "ingest" and os.getenv("LORE_WATCH_REPO"):
        repo = os.environ["LORE_WATCH_REPO"]
        every = float(os.getenv("LORE_WATCH_SECONDS", "900"))

        @agent.on_interval(period=every)
        async def watch(ctx: Context):
            """Event-driven mode: pick up newly merged PRs and extract memories."""
            since = ctx.storage.get("since") or ""
            try:
                s = lore.ingest_github(repo, limit=20, since=since)
            except Exception as exc:
                ctx.logger.warning(f"watch {repo} failed: {exc}")
                return
            if s["latest_merge"]:
                ctx.storage.set("since", max(since, s["latest_merge"]))
            if s["memories_created"]:
                ctx.logger.info(f"watch {repo}: +{s['memories_created']} memories")

    return agent
