"""The public LORE agent: Chat Protocol front door for ASI:One, routing to specialists."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (ChatAcknowledgement, ChatMessage, EndSessionContent,
                                                 StartSessionContent, TextContent, chat_protocol_spec)

from ..engine import Lore
from ..router import route
from .protocols import AskResponse, IngestResponse, OnboardResponse, ReviewResponse
from .specialists import seed_for

README = Path(__file__).resolve().parents[2] / "AGENT_README.md"
RESPONSE_TYPES = {"ask": AskResponse, "review": ReviewResponse, "onboard": OnboardResponse,
                  "ingest": IngestResponse}
TIMEOUTS = {"ask": 90, "review": 120, "onboard": 60, "ingest": 300}


def make_lore_agent(lore: Lore, specialists: dict[str, str], port: int = 8000,
                    mailbox: bool | None = None) -> Agent:
    """specialists maps kind ("ask", "review", ...) to that agent's address."""
    if mailbox is None:
        mailbox = os.getenv("LORE_MAILBOX", "1") == "1"
    agent = Agent(
        name="lore",
        seed=seed_for("lore"),
        port=port,
        mailbox=mailbox,
        handle=os.getenv("LORE_HANDLE") or None,
        description="LORE remembers why your team made its engineering decisions and checks new "
                    "code changes against them, with sources.",
        readme_path=str(README) if README.exists() else None,
        publish_agent_details=True,
    )
    chat = Protocol(spec=chat_protocol_spec)

    async def reply(ctx: Context, to: str, text: str):
        await ctx.send(to, ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                                       content=[TextContent(type="text", text=text), EndSessionContent(type="end-session")]))

    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc),
                                                   acknowledged_msg_id=msg.msg_id))
        text = " ".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
        if not text and any(isinstance(c, StartSessionContent) for c in msg.content):
            return
        ctx.logger.info(f"chat from {sender[:16]}…: {text[:80]}")

        async def call(kind: str, req):
            resp, status = await ctx.send_and_receive(specialists[kind], req, response_type=RESPONSE_TYPES[kind],
                                                      timeout=TIMEOUTS[kind])
            if resp is None:
                raise RuntimeError(f"{kind} agent did not answer ({status.detail})")
            return resp

        try:
            answer = await route(text, sender, call, lore)
        except Exception as exc:
            ctx.logger.exception("routing failed")
            answer = f"Sorry, LORE hit an error: {exc}"
        await reply(ctx, sender, answer)

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    agent.include(chat, publish_manifest=True)
    return agent
