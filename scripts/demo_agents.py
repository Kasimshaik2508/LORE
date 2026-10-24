"""End-to-end demo over real uAgents messaging (no Agentverse needed).

A scripted "developer" agent chats with LORE using the Chat Protocol; LORE routes each
message to its specialist agents with typed messages and replies. This is the judge story:
import history -> memory -> conflicting change -> evidence-backed BLOCK -> override.

    python scripts/demo_agents.py
"""

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LORE_DB", os.path.join(tempfile.mkdtemp(), "demo.db"))

from uagents import Agent, Bureau, Context, Protocol  # noqa: E402
from uagents_core.contrib.protocols.chat import (ChatAcknowledgement, ChatMessage,  # noqa: E402
                                                 TextContent, chat_protocol_spec)

from lore.agents.lore_agent import make_lore_agent  # noqa: E402
from lore.agents.specialists import SPECS, make_specialist  # noqa: E402
from lore.engine import Lore  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = [
    f"ingest {ROOT / 'data' / 'sample_repo'}",
    "Why did we choose PostgreSQL instead of MongoDB?",
    "Can I replace our payment service's database?",
    "review: add a 5 minute Redis cache to verify_token in auth_service/verify.py to cut auth latency",
    "review: add a 5 minute Redis cache to verify_token in auth_service/verify.py "
    "override: only enabled in the load-test environment, tokens there are never revoked",
    "show MEM-007",
    "onboard",
]

PORT = int(os.getenv("LORE_DEMO_PORT", "8010"))


def main():
    lore = Lore()
    specialists = {k: make_specialist(k, lore) for k in SPECS}
    front = make_lore_agent(lore, {k: a.address for k, a in specialists.items()}, mailbox=False)
    dev = Agent(name="developer", seed=f"lore-demo-developer-{uuid4()}", publish_agent_details=False)
    proto = Protocol(spec=chat_protocol_spec)
    state = {"i": 0}

    async def send_next(ctx: Context):
        if state["i"] >= len(SCRIPT):
            print("\n=== demo complete ===", flush=True)
            os._exit(0)
        text = SCRIPT[state["i"]]
        state["i"] += 1
        print(f"\n\033[1;36m>>> developer: {text}\033[0m\n")
        await ctx.send(front.address, ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                                                  content=[TextContent(type="text", text=text)]))

    @proto.on_message(ChatMessage)
    async def on_reply(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc),
                                                   acknowledged_msg_id=msg.msg_id))
        print("\n".join(c.text for c in msg.content if isinstance(c, TextContent)))
        await send_next(ctx)

    @proto.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    dev.include(proto)

    @dev.on_event("startup")
    async def start(ctx: Context):
        await asyncio.sleep(2)
        await send_next(ctx)

    Bureau(agents=[front, dev, *specialists.values()], port=PORT,
           endpoint=[f"http://127.0.0.1:{PORT}/submit"], log_level="WARNING").run()


if __name__ == "__main__":
    main()
