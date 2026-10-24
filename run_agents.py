"""Start the LORE multi-agent system: one public Chat-Protocol agent + four specialists.

    python run_agents.py            # mailbox mode: connect "lore" to Agentverse, chat via ASI:One
    LORE_MAILBOX=0 python run_agents.py   # purely local (use scripts/chat_client.py)
"""

import os

from uagents import Bureau

from lore.agents.lore_agent import make_lore_agent
from lore.agents.specialists import SPECS, make_specialist
from lore.engine import Lore

PORT = int(os.getenv("LORE_PORT", "8000"))


def main():
    lore = Lore()
    if not lore.store.sources() and os.getenv("LORE_SEED_DEMO", "1") == "1":
        print("Empty memory: importing the sample repository (set LORE_SEED_DEMO=0 to skip)")
        lore.ingest_folder(os.path.join(os.path.dirname(__file__), "data", "sample_repo"))

    specialists = {kind: make_specialist(kind, lore) for kind in SPECS}
    front = make_lore_agent(lore, {k: a.address for k, a in specialists.items()}, port=PORT)

    print("\nLORE agents")
    print(f"  {front.name:<16} {front.address}   <- chat with this one")
    for a in specialists.values():
        print(f"  {a.name:<16} {a.address}")
    if os.getenv("LORE_MAILBOX", "1") == "1":
        print(f"\nConnect the mailbox (once): https://agentverse.ai/inspect/"
              f"?uri=http%3A//127.0.0.1%3A{PORT}&address={front.address}")
    print()

    bureau = Bureau(agents=[front, *specialists.values()], port=PORT,
                    endpoint=[f"http://127.0.0.1:{PORT}/submit"])
    bureau.run()


if __name__ == "__main__":
    main()
