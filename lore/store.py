"""SQLite persistence for source records, memories, graph edges and the audit log."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, type TEXT, title TEXT, author TEXT, date TEXT, url TEXT,
    repo TEXT, payload TEXT, processed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY, type TEXT, title TEXT, statement TEXT, rationale TEXT,
    components TEXT, source_id TEXT, source_url TEXT, timestamp TEXT, confidence REAL,
    status TEXT, extracted_by TEXT, quote TEXT, repo TEXT
);
CREATE TABLE IF NOT EXISTS edges (
    src TEXT, rel TEXT, dst TEXT, evidence TEXT, PRIMARY KEY (src, rel, dst)
);
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY, kind TEXT, label TEXT, attrs TEXT
);
CREATE TABLE IF NOT EXISTS events (
    ts TEXT, kind TEXT, memory_id TEXT, actor TEXT, detail TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Memory:
    id: str
    type: str  # architecture_decision | rule | incident | commitment
    title: str
    statement: str
    rationale: str = ""
    components: list[str] = field(default_factory=list)
    source_id: str = ""
    source_url: str = ""
    timestamp: str = ""
    confidence: float = 0.5
    status: str = "active"  # active | superseded | disputed
    extracted_by: str = "heuristic"
    quote: str = ""  # verbatim source text the memory was taken from
    repo: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Memory":
        d = dict(row)
        d["components"] = json.loads(d["components"] or "[]")
        return cls(**d)


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        try:
            yield self.db
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    # sources ---------------------------------------------------------------
    def upsert_source(self, rec: dict, repo: str = "") -> bool:
        """Insert a source record. Returns True if it was new."""
        exists = self.db.execute("SELECT 1 FROM sources WHERE id=?", (rec["id"],)).fetchone()
        with self.tx() as db:
            db.execute(
                "INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?,?,?)",
                (rec["id"], rec.get("type", ""), rec.get("title", ""), rec.get("author", ""),
                 rec.get("date", ""), rec.get("url", ""), repo, json.dumps(rec),
                 1 if exists and exists[0] else 0),
            )
        return not exists

    def source(self, sid: str) -> dict | None:
        row = self.db.execute("SELECT payload FROM sources WHERE id=?", (sid,)).fetchone()
        return json.loads(row[0]) if row else None

    def sources(self, unprocessed_only: bool = False) -> list[dict]:
        q = "SELECT payload FROM sources" + (" WHERE processed=0" if unprocessed_only else "")
        return [json.loads(r[0]) for r in self.db.execute(q + " ORDER BY date")]

    def mark_processed(self, sid: str):
        with self.tx() as db:
            db.execute("UPDATE sources SET processed=1 WHERE id=?", (sid,))

    # memories --------------------------------------------------------------
    def next_memory_id(self) -> str:
        n = self.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        return f"MEM-{n + 1:03d}"

    def add_memory(self, m: Memory) -> Memory:
        dup = self.db.execute(
            "SELECT id FROM memories WHERE source_id=? AND statement=?", (m.source_id, m.statement)
        ).fetchone()
        if dup:
            return self.memory(dup[0])
        m.id = m.id or self.next_memory_id()
        with self.tx() as db:
            db.execute(
                "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (m.id, m.type, m.title, m.statement, m.rationale, json.dumps(m.components),
                 m.source_id, m.source_url, m.timestamp, m.confidence, m.status,
                 m.extracted_by, m.quote, m.repo),
            )
        self.log("memory_created", m.id, m.extracted_by, m.statement)
        return m

    def memory(self, mid: str) -> Memory | None:
        row = self.db.execute("SELECT * FROM memories WHERE id=?", (mid.upper(),)).fetchone()
        return Memory.from_row(row) if row else None

    def memories(self, status: str | None = None) -> list[Memory]:
        if status:
            rows = self.db.execute("SELECT * FROM memories WHERE status=? ORDER BY id", (status,))
        else:
            rows = self.db.execute("SELECT * FROM memories ORDER BY id")
        return [Memory.from_row(r) for r in rows]

    def memories_from_source(self, sid: str) -> list[Memory]:
        rows = self.db.execute("SELECT * FROM memories WHERE source_id=?", (sid,))
        return [Memory.from_row(r) for r in rows]

    def set_status(self, mid: str, status: str, actor: str, reason: str):
        with self.tx() as db:
            db.execute("UPDATE memories SET status=? WHERE id=?", (status, mid))
        self.log(f"status:{status}", mid, actor, reason)

    # graph -----------------------------------------------------------------
    def add_node(self, nid: str, kind: str, label: str, **attrs):
        with self.tx() as db:
            db.execute(
                "INSERT INTO nodes VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "attrs=json_patch(nodes.attrs, excluded.attrs)",
                (nid, kind, label, json.dumps(attrs)),
            )

    def add_edge(self, src: str, rel: str, dst: str, evidence: str = ""):
        with self.tx() as db:
            db.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?,?)", (src, rel, dst, evidence))

    def nodes(self) -> list[dict]:
        return [dict(r) | {"attrs": json.loads(r["attrs"] or "{}")}
                for r in self.db.execute("SELECT * FROM nodes")]

    def edges(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM edges")]

    # audit log -------------------------------------------------------------
    def log(self, kind: str, memory_id: str = "", actor: str = "", detail: str = ""):
        with self.tx() as db:
            db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (now(), kind, memory_id, actor, detail))

    def events(self, memory_id: str | None = None) -> list[dict]:
        if memory_id:
            rows = self.db.execute("SELECT * FROM events WHERE memory_id=? ORDER BY ts", (memory_id,))
        else:
            rows = self.db.execute("SELECT * FROM events ORDER BY ts DESC LIMIT 200")
        return [dict(r) for r in rows]

    def reset(self):
        with self.tx() as db:
            for t in ("sources", "memories", "edges", "nodes", "events"):
                db.execute(f"DELETE FROM {t}")
