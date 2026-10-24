"""Start the LORE multi-agent system: one public Chat-Protocol agent + four specialists.

    python run_agents.py                  # mailbox mode: connect "lore" to Agentverse, chat via ASI:One
    LORE_MAILBOX=0 python run_agents.py   # purely local

The public agent runs alone on LORE_PORT (default 8000) so the Agentverse inspector can
find it; the specialists share a Bureau on LORE_PORT+1. Both run in this one process.
"""

import asyncio
import os

from uagents import Bureau

from lore.agents.lore_agent import make_lore_agent
from lore.agents.net import LocalFirstResolver
from lore.agents.specialists import SPECS, address_of, make_specialist
from lore.engine import Lore

PORT = int(os.getenv("LORE_PORT", "8000"))
SPECIALIST_PORT = PORT + 1


def main():
    lore = Lore()
    if not lore.store.sources() and os.getenv("LORE_SEED_DEMO", "1") == "1":
        print("Empty memory: importing the sample repository (set LORE_SEED_DEMO=0 to skip)")
        lore.ingest_folder(os.path.join(os.path.dirname(__file__), "data", "sample_repo"))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    front_addr = address_of("lore")
    local = {front_addr: f"http://127.0.0.1:{PORT}/submit"}
    local |= {address_of(SPECS[k][0]): f"http://127.0.0.1:{SPECIALIST_PORT}/submit" for k in SPECS}
    resolver = LocalFirstResolver(local)

    specialists = {kind: make_specialist(kind, lore, resolve=resolver) for kind in SPECS}
    front = make_lore_agent(lore, {k: a.address for k, a in specialists.items()}, port=PORT,
                            resolve=resolver)
    front.update_loop(loop)

    print("\nLORE agents")
    print(f"  {front.name:<16} {front.address}   <- chat with this one (port {PORT})")
    for a in specialists.values():
        print(f"  {a.name:<16} {a.address}   (port {SPECIALIST_PORT})")
    if os.getenv("LORE_MAILBOX", "1") == "1":
        print(f"\nConnect the mailbox (once): https://agentverse.ai/inspect/"
              f"?uri=http%3A//127.0.0.1%3A{PORT}&address={front.address}")
    print()

    bureau = Bureau(agents=list(specialists.values()), port=SPECIALIST_PORT, loop=loop,
                    endpoint=[f"http://127.0.0.1:{SPECIALIST_PORT}/submit"])
    loop.create_task(front.run_async())
    bureau.run()


if __name__ == "__main__":
    main()
