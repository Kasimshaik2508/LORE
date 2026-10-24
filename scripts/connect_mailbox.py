"""Connect the running "lore" agent to its Agentverse mailbox without the browser inspector.

Does exactly what the inspector's Connect -> Mailbox button does: POSTs your Agentverse
API key to the agent's local /connect endpoint, and the agent registers itself.

    1. Create an API key: https://agentverse.ai -> profile -> API Keys
    2. Put it in .env as AGENTVERSE_API_KEY=...
    3. With run_agents.py running:  python scripts/connect_mailbox.py
"""

import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lore  # noqa: E402,F401  (loads .env)

PORT = int(os.getenv("LORE_PORT", "8000"))


def main():
    key = os.getenv("AGENTVERSE_API_KEY")
    if not key:
        sys.exit("AGENTVERSE_API_KEY is not set. Add it to .env (see the docstring at the top of this file).")
    try:
        r = requests.post(f"http://127.0.0.1:{PORT}/connect",
                          json={"user_token": key, "agent_type": "mailbox"}, timeout=60)
    except requests.ConnectionError:
        sys.exit(f"Nothing is listening on port {PORT}. Start the agents first: python run_agents.py")
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
    if r.ok and isinstance(body, dict) and body.get("success"):
        print("Connected: lore is registered on Agentverse with a mailbox. It is now reachable from ASI:One.")
    else:
        sys.exit(f"Agentverse refused the connection ({r.status_code}): {body}")


if __name__ == "__main__":
    main()
