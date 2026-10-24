"""Address resolution for running LORE's agents on two local ports.

The public agent needs its own port so the Agentverse inspector can find it; the
specialists share a Bureau on another. Known LORE agents resolve to localhost directly,
everything else (ASI:One users, other agents) goes through the normal global resolver."""

from __future__ import annotations

from uagents.resolver import GlobalResolver, Resolver
from uagents_core.identity import parse_identifier


class LocalFirstResolver(Resolver):
    def __init__(self, local: dict[str, str]):
        self.local = local  # address -> http://127.0.0.1:<port>/submit
        self.fallback = GlobalResolver()

    async def resolve(self, destination: str) -> tuple[str | None, list[str]]:
        _, _, address = parse_identifier(destination)
        if address in self.local:
            return address, [self.local[address]]
        return await self.fallback.resolve(destination)
