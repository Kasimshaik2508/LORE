"""Command line interface: python -m lore <command>."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from . import render
from .engine import Lore
from .router import local_dispatch, route

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_repo"


def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(prog="lore", description="LORE engineering memory")
    p.add_argument("--db", help="SQLite path (default data/lore.db or $LORE_DB)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ingest", help="import a folder of records/docs")
    s.add_argument("path", nargs="?", default=str(SAMPLE))
    s = sub.add_parser("github", help="import merged PRs from a GitHub repo")
    s.add_argument("repo")
    s.add_argument("--limit", type=int, default=20)
    s = sub.add_parser("ask")
    s.add_argument("question", nargs="+")
    s = sub.add_parser("review", help="review a change description, or a diff file with --diff")
    s.add_argument("change", nargs="*")
    s.add_argument("--diff", help="path to a unified diff ('-' for stdin)")
    s.add_argument("--override", default="", help="justification for overriding conflicts")
    s.add_argument("--strict", action="store_true", help="exit 1 on BLOCK (for CI)")
    s = sub.add_parser("onboard")
    s.add_argument("focus", nargs="*")
    sub.add_parser("chat", help="interactive chat, same commands as ASI:One")
    sub.add_parser("stats")
    sub.add_parser("reset", help="delete all memories")
    a = p.parse_args(argv)

    lore = Lore(a.db)
    if a.cmd == "ingest":
        print(lore.ingest_folder(a.path))
    elif a.cmd == "github":
        print(lore.ingest_github(a.repo, limit=a.limit))
    elif a.cmd == "ask":
        print(render.ask(lore.ask(" ".join(a.question))))
    elif a.cmd == "review":
        if a.diff:
            change = sys.stdin.read() if a.diff == "-" else Path(a.diff).read_text()
        else:
            change = " ".join(a.change)
        r = lore.review(change, justification=a.override, actor="cli")
        print(render.review(r))
        if a.strict and r["status"] == "BLOCK":
            sys.exit(1)
    elif a.cmd == "onboard":
        print(render.onboard(lore.onboard(" ".join(a.focus))))
    elif a.cmd == "stats":
        print(render.stats(lore.stats()))
    elif a.cmd == "reset":
        lore.store.reset()
        print("Memory cleared.")
    elif a.cmd == "chat":
        call = local_dispatch(lore)
        print(render.HELP + "\n\n(ctrl-D to quit)")
        while True:
            try:
                text = input("\nyou> ")
            except EOFError:
                break
            print("\n" + asyncio.run(route(text, "cli-user", call, lore)))


if __name__ == "__main__":
    main()
