"""LORE engine: the shared brain the uAgents call into.

Each public method backs one specialist agent:
  ingest/process  -> Memory Extraction Agent (+ Commit Keeper linking)
  ask             -> Retrieval Agent (LORE Ask) with impact analysis
  review          -> Conflict Review Agent (MR Review)
  onboard         -> Onboarding Agent
  challenge/override/supersede -> Reply Handler
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import graph as G
from . import llm
from .extract import REF, extract
from .ingest import GitHub, load_folder
from .store import Memory, Store
from .text import BM25, split_constraint, tokens

DEFAULT_DB = os.getenv("LORE_DB", str(Path(__file__).resolve().parent.parent / "data" / "lore.db"))

CHANGE_WORDS = {"replace", "change", "modify", "remove", "delete", "refactor", "upgrade", "drop",
                "rewrite", "rename", "deprecate", "move", "split", "merge"}

REMOVAL = re.compile(r"\b(?:remov|drop|delet|disabl|stop|revert|get rid of|rip out)\w*\s+(?:\S+\s+){0,4}\S+",
                     re.I)
PATH = re.compile(r"\b[\w.-]+/[\w./-]+")

ANSWER_PROMPT = """You are LORE Ask, the retrieval agent of an engineering-memory system.
Answer the developer's question using ONLY the evidence JSON provided.
- Cite memories inline as [MEM-xxx] and give the source id (e.g. MR-42).
- Separate "Verified" (stated in a source) from "Inferred risk" (your reasoning).
- Mention when a memory is superseded and what replaced it.
- If evidence is missing, say what is unknown. Never claim a change is safe just because no conflict was found.
- Be concise. Markdown, no more than ~250 words."""

REVIEW_PROMPT = """You are the LORE Review Agent. Compare a proposed code change with stored engineering memories.
For each memory, decide:
  "conflict"  - the change does what the memory forbids, or breaks what it requires
  "compliant" - the change touches the same area and respects the memory
  "unrelated" - not actually relevant
Only say "conflict" when the change genuinely violates the memory; removing a forbidden thing is compliant.
Return a JSON list: [{"memory_id": "...", "verdict": "...", "explanation": one sentence,
"safer_alternative": one sentence or ""}]"""


class Lore:
    def __init__(self, db_path: str | None = None):
        self.store = Store(db_path or DEFAULT_DB)
        self._g = None

    # ------------------------------------------------------------------ graph
    @property
    def g(self):
        if self._g is None:
            self._g = G.build(self.store)
        return self._g

    def _dirty(self):
        self._g = None

    # ----------------------------------------------------------------- ingest
    def load_services(self, services: dict):
        for name, spec in services.items():
            nid = f"service:{name}"
            self.store.add_node(nid, "service", name, owner=spec.get("owner", ""),
                                service_kind=spec.get("kind", "service"),
                                paths=spec.get("paths", []))
            for dep in spec.get("depends_on", []):
                self.store.add_edge(nid, "DEPENDS_ON", f"service:{dep}", "services.json")
            if spec.get("owner"):
                self.store.add_edge(f"person:{spec['owner']}", "OWNS", nid, "services.json")
        self._dirty()

    def _service_for_path(self, path: str) -> str | None:
        for n in self.store.nodes():
            for prefix in n["attrs"].get("paths", []) if n["kind"] == "service" else []:
                if path.startswith(prefix):
                    return n["id"]
        return None

    def ingest_records(self, records: list[dict], repo: str = "") -> int:
        new = sum(self.store.upsert_source(r, repo) for r in records)
        self._dirty()
        return new

    def ingest_folder(self, path: str) -> dict:
        records, services = load_folder(path)
        if services:
            self.load_services(services)
        new = self.ingest_records(records, repo=str(path))
        created = self.process()
        return {"records": len(records), "new_records": new, "memories_created": len(created),
                "services": len(services)}

    def ingest_github(self, repo: str, limit: int = 20, since: str = "") -> dict:
        gh = GitHub(repo)
        records = gh.merged_prs(limit=limit, since=since)
        readme = gh.readme()
        if readme:
            records.append(readme)
        new = self.ingest_records(records, repo=repo)
        created = self.process()
        return {"records": len(records), "new_records": new, "memories_created": len(created),
                "latest_merge": max((r.get("merged_at", "") for r in records), default="")}

    def _link_source(self, rec: dict):
        sid = f"source:{rec['id']}"
        self.store.add_node(sid, rec.get("type", "source"), rec.get("title", rec["id"]),
                            url=rec.get("url", ""), date=rec.get("date", ""))
        if rec.get("author"):
            self.store.add_edge(f"person:{rec['author']}", "AUTHORED", sid, rec["id"])
        for r in rec.get("reviewers", []):
            self.store.add_edge(f"person:{r}", "REVIEWED", sid, rec["id"])
        for f in rec.get("files", []):
            fid = f"file:{f}"
            self.store.add_edge(sid, "MODIFIES", fid, rec["id"])
            svc = self._service_for_path(f)
            if svc:
                self.store.add_edge(fid, "PART_OF", svc, "services.json paths")
        text = f"{rec.get('title', '')}\n{rec.get('body', '')}"
        for ref in sorted(set(REF.findall(text)) - {rec["id"]}):
            self.store.add_edge(sid, "REFERENCES", f"source:{ref}", rec["id"])

    def process(self) -> list[Memory]:
        """Extract memories from unprocessed sources and link them into the graph."""
        created = []
        for rec in self.store.sources(unprocessed_only=True):
            self._link_source(rec)
            for ex in extract(rec):
                m = self.store.add_memory(ex.memory)
                created.append(m)
                mid = f"memory:{m.id}"
                self.store.add_edge(mid, "SUPPORTED_BY", f"source:{rec['id']}", m.quote)
                for c in m.components:
                    cid = G.component_node(c)
                    self.store.add_edge(mid, "AFFECTS", cid, rec["id"])
                    if cid.startswith("file:"):
                        svc = self._service_for_path(c)
                        if svc:
                            self.store.add_edge(cid, "PART_OF", svc, "services.json paths")
                for inc in ex.caused_by:
                    self.store.add_edge(mid, "CAUSED_BY", f"source:{inc}", rec["id"])
                for old_src in ex.supersedes:
                    for old in self.store.memories_from_source(old_src):
                        if old.type == m.type and old.status == "active":
                            self.store.add_edge(mid, "SUPERSEDES", f"memory:{old.id}", rec["id"])
                            self.store.set_status(old.id, "superseded", "extractor",
                                                  f"Superseded by {m.id} ({rec['id']})")
            self.store.mark_processed(rec["id"])
        self._dirty()
        return created

    # -------------------------------------------------------------- retrieval
    def _doc(self, m: Memory) -> str:
        return " ".join([m.title, m.statement, m.rationale, " ".join(m.components), m.quote])

    def search(self, query: str, k: int = 5, include_superseded: bool = True) -> list[tuple[Memory, float]]:
        mems = {m.id: m for m in self.store.memories()
                if include_superseded or m.status != "superseded"}
        if not mems:
            return []
        scores = dict(BM25({mid: self._doc(m) for mid, m in mems.items()}).search(query, k=len(mems)))
        # Graph boost: memories attached to components named in the query.
        for nid in G.memories_touching(self.g, set(G.match_components(self.g, query))):
            mid = nid.split(":", 1)[1]
            if mid in mems:
                scores[mid] = scores.get(mid, 0) + 1.5
        ranked = sorted(scores.items(), key=lambda x: -x[1])[:k]
        return [(mems[mid], s) for mid, s in ranked]

    def evidence(self, m: Memory) -> dict:
        nid = f"memory:{m.id}"
        links = []
        for s, rel, d in G.neighborhood(self.g, nid):
            if rel in ("CAUSED_BY", "SUPERSEDES", "AFFECTS"):
                links.append({"from": s, "rel": rel, "to": d})
        return m.to_dict() | {"links": links}

    def impact(self, question: str) -> dict | None:
        comps = G.match_components(self.g, question)
        if not comps or not (set(tokens(question)) & CHANGE_WORDS):
            return None
        target = comps[0]
        deps = G.dependents(self.g, target)
        governed = G.memories_touching(self.g, {target, *deps})
        active = [g.split(":", 1)[1] for g in governed
                  if self.g.nodes[g].get("status") == "active"]
        return {
            "target": G.label(target),
            "dependents": {G.label(k): [G.label(x) for x in p] for k, p in deps.items()},
            "governing_memories": active,
        }

    def ask(self, question: str, k: int = 5) -> dict:
        hits = self.search(question, k=k)
        ev = [self.evidence(m) | {"score": round(s, 2)} for m, s in hits]
        # Pull in whatever superseded or replaced the hits, so history is complete.
        ids = {e["id"] for e in ev}
        for e in list(ev):
            for link in e["links"]:
                if link["rel"] == "SUPERSEDES":
                    other = (link["to"] if link["from"].endswith(e["id"]) else link["from"]).split(":", 1)[1]
                    if other not in ids and (om := self.store.memory(other)):
                        ev.append(self.evidence(om) | {"score": 0})
                        ids.add(other)
        imp = self.impact(question)
        answer, mode = None, "offline"
        if ev and llm.available():
            answer = llm.chat(ANSWER_PROMPT, json.dumps(
                {"question": question, "evidence": ev, "impact_analysis": imp}, default=str))
            mode = f"asi1:{llm.MODEL}" if answer else "offline"
        if answer is None:
            answer = self._template_answer(question, ev, imp)
        return {"question": question, "answer": answer, "evidence": ev, "impact": imp, "mode": mode}

    def _template_answer(self, question: str, ev: list[dict], imp: dict | None) -> str:
        if not ev and not imp:
            return ("LORE has no recorded memory about this. That means the history is unknown, "
                    "not that the change is safe. Type `help` to see what I can do.")
        lines = []
        if ev:
            lines.append("**What the project history says (verified from sources):**")
            for e in ev:
                status = "" if e["status"] == "active" else f" _({e['status']})_"
                why = f" — because {e['rationale'][0].lower()}{e['rationale'][1:]}" if e["rationale"] else ""
                lines.append(f"- **[{e['id']}]** {e['statement']}{why}{status} "
                             f"([{e['source_id']}]({e['source_url']}), {e['timestamp'] or 'undated'})")
                for link in e["links"]:
                    if link["rel"] == "CAUSED_BY":
                        lines.append(f"  - caused by {G.label(link['to'])}")
                    elif link["rel"] == "SUPERSEDES" and link["from"].endswith(e["id"]):
                        lines.append(f"  - supersedes {G.label(link['to'])}")
                    elif link["rel"] == "SUPERSEDES":
                        lines.append(f"  - superseded by {G.label(link['from'])}")
        if imp:
            lines.append(f"\n**Impact of changing `{imp['target']}` (from the dependency graph):**")
            if imp["dependents"]:
                for svc, path in imp["dependents"].items():
                    lines.append(f"- `{svc}` depends on it ({' ← '.join(path)})")
            else:
                lines.append("- No recorded dependents.")
            if imp["governing_memories"]:
                lines.append("- Active memories governing it or its dependents: "
                             + ", ".join(f"[{x}]" for x in imp["governing_memories"]))
            lines.append("\n**Inferred risk:** any replacement must keep every guarantee above "
                         "for every dependent service. LORE found no record proving it is safe.")
        return "\n".join(lines)

    # ----------------------------------------------------------------- review
    @staticmethod
    def parse_change(change: str) -> tuple[str, list[str]]:
        """Return (text that describes what the change ADDS, files touched)."""
        files = re.findall(r"^\+\+\+ (?:b/)?(\S+)", change, re.M)
        files += re.findall(r"^diff --git a/(\S+)", change, re.M)
        if re.search(r"^[+-]", change, re.M) and files:
            kept = [ln[1:] for ln in change.splitlines()
                    if ln.startswith("+") and not ln.startswith("+++")]
            kept += [ln for ln in change.splitlines()
                     if not ln.startswith(("+", "-", "@@", "diff ", "index ", " "))]
            text = "\n".join(kept)
        else:
            text = change
        files += re.findall(r"\b[\w./-]+/[\w.-]+\.(?:py|sql|js|ts|go|java|rb)\b", text)
        return text, sorted(set(files))

    def review(self, change: str, files: list[str] | None = None, justification: str = "",
               actor: str = "developer") -> dict:
        added, touched = self.parse_change(change)
        touched = sorted(set(touched) | set(files or []))
        terms = set(tokens(added + " " + " ".join(touched)))
        # "remove the redis cache" must not count as introducing a cache.
        introduced = set(tokens(PATH.sub(" ", REMOVAL.sub(" ", added))))
        comp_nodes = {G.component_node(f) for f in touched} | set(G.match_components(self.g, added))
        governed = {n.split(":", 1)[1] for n in G.memories_touching(self.g, comp_nodes)}

        findings: dict[str, dict] = {}
        for m in self.store.memories("active") + self.store.memories("disputed"):
            overlap = m.id in governed
            c = split_constraint(m.statement)
            if c:
                _, ctx, forb = c
                hit_forb = sorted(set(forb) & introduced)
                hit_ctx = sorted(set(ctx) & terms)
                if hit_forb and (hit_ctx or overlap):
                    disputed = m.status == "disputed"
                    findings[m.id] = {"verdict": "possible_conflict" if disputed else "conflict",
                                      "by": "heuristic",
                                      "explanation": f"Change introduces {', '.join(hit_forb)} in the "
                                                     f"context of {', '.join(hit_ctx) or 'a governed component'}."
                                                     + (" The rule is currently disputed." if disputed else "")}
                    continue
            if overlap:
                findings[m.id] = {"verdict": "related", "by": "graph",
                                  "explanation": "Change touches a component governed by this memory."}

        if llm.available():
            cand = [self.store.memory(mid) for mid in findings]
            cand += [m for m, _ in self.search(added, k=6, include_superseded=False) if m.id not in findings]
            if cand:
                verdicts = llm.chat_json(REVIEW_PROMPT, json.dumps({
                    "change": added[:6000], "files": touched,
                    "memories": [{"memory_id": m.id, "statement": m.statement, "rationale": m.rationale,
                                  "components": m.components} for m in cand]}))
                for v in verdicts if isinstance(verdicts, list) else []:
                    mid = str(v.get("memory_id", "")).upper()
                    if not self.store.memory(mid):
                        continue
                    verdict = v.get("verdict")
                    prior = findings.get(mid, {})
                    if verdict == "unrelated" and prior.get("verdict") == "conflict":
                        verdict = "possible_conflict"  # model and rules disagree: stay cautious
                    if verdict in ("conflict", "possible_conflict", "compliant") or prior:
                        findings[mid] = {"verdict": verdict if verdict != "unrelated" else prior["verdict"],
                                         "by": f"asi1:{llm.MODEL}",
                                         "explanation": v.get("explanation", prior.get("explanation", "")),
                                         "safer_alternative": v.get("safer_alternative", "")}

        results = []
        for mid, f in findings.items():
            m = self.store.memory(mid)
            item = {"memory": self.evidence(m), **f}
            if f["verdict"] in ("conflict", "possible_conflict"):
                item.setdefault("safer_alternative", "")
                if not item["safer_alternative"]:
                    item["safer_alternative"] = self._alternative(m)
                if justification:
                    item["verdict"] = "overridden"
                    self.store.log("override", mid, actor, justification)
            results.append(item)
        order = {"conflict": 0, "possible_conflict": 1, "overridden": 2, "related": 3, "compliant": 4}
        results.sort(key=lambda r: order.get(r["verdict"], 9))

        if any(r["verdict"] == "conflict" for r in results):
            status = "BLOCK"
        elif any(r["verdict"] in ("possible_conflict", "related", "overridden") for r in results):
            status = "CAUTION"
        else:
            status = "NO_KNOWN_CONFLICTS"
        self.store.log("review", "", actor, f"{status}: {added[:200]}")
        return {"status": status, "files": touched, "findings": results,
                "note": "No known conflict is not proof of safety; LORE only knows what was recorded."}

    def _alternative(self, m: Memory) -> str:
        src = self.store.source(m.source_id) or {}
        for c in src.get("comments", []):
            body = c.get("body", "")
            if re.search(r"\binstead\b", body, re.I):
                sent = next((s for s in re.split(r"(?<=[.!?])\s+", body) if "instead" in s.lower()), body)
                return f"{sent.strip()} (suggested by {c.get('author')} in {m.source_id})"
        return f"Keep the guarantee in {m.id}; if it no longer holds, challenge it with evidence first."

    # ------------------------------------------------------------ reply handler
    def challenge(self, mid: str, reason: str, actor: str = "developer") -> Memory | None:
        m = self.store.memory(mid)
        if m:
            self.store.set_status(m.id, "disputed", actor, reason)
            self._dirty()
        return self.store.memory(mid)

    def reaffirm(self, mid: str, reason: str, actor: str = "developer") -> Memory | None:
        m = self.store.memory(mid)
        if m:
            self.store.set_status(m.id, "active", actor, reason)
            self._dirty()
        return self.store.memory(mid)

    def remember(self, statement: str, rationale: str, components: list[str], actor: str,
                 supersedes: str = "") -> Memory:
        """A developer records a decision directly (e.g. via chat). Stored with lower confidence
        and attributed, since it has no repository source."""
        src_id = f"CHAT-{self.store.next_memory_id()[4:]}"
        rec = {"id": src_id, "type": "chat", "title": statement[:80], "author": actor, "reviewers": [],
               "date": "", "url": "", "files": [], "comments": [],
               "body": f"Decision: {statement}\nWhy: {rationale}\nAffects: {', '.join(components)}"}
        self.store.upsert_source(rec, "chat")
        created = self.process()
        m = created[0]
        if supersedes and (old := self.store.memory(supersedes)):
            self.store.add_edge(f"memory:{m.id}", "SUPERSEDES", f"memory:{old.id}", src_id)
            self.store.set_status(old.id, "superseded", actor, f"Superseded by {m.id}")
        self._dirty()
        return self.store.memory(m.id)

    # ---------------------------------------------------------------- onboard
    def onboard(self, focus: str = "") -> dict:
        g = self.g
        services = []
        for nid, d in g.nodes(data=True):
            if d.get("kind") != "service":
                continue
            deps = [G.label(v) for _, v, e in g.out_edges(nid, data=True) if e["rel"] == "DEPENDS_ON"]
            services.append({"name": G.label(nid), "owner": d.get("owner", ""),
                             "kind": d.get("service_kind", "service"), "depends_on": deps})
        mems = self.store.memories()
        if focus:
            keep = {m.id for m, _ in self.search(focus, k=8)}
            mems = [m for m in mems if m.id in keep]
        files: dict[str, int] = {}
        for u, v, e in g.edges(data=True):
            if e["rel"] == "AFFECTS" and v.startswith("file:"):
                files[G.label(v)] = files.get(G.label(v), 0) + 1
        people: dict[str, int] = {}
        for u, v, e in g.edges(data=True):
            if u.startswith("person:") and e["rel"] in ("AUTHORED", "REVIEWED"):
                people[G.label(u)] = people.get(G.label(u), 0) + 1
        return {
            "services": sorted(services, key=lambda s: s["name"]),
            "rules": [m.to_dict() for m in mems if m.status == "active" and m.type in ("rule", "commitment")],
            "decisions": [m.to_dict() for m in mems if m.type == "architecture_decision"],
            "incidents": [m.to_dict() for m in mems if m.type == "incident"],
            "key_files": sorted(files.items(), key=lambda x: -x[1])[:8],
            "people": sorted(people.items(), key=lambda x: -x[1]),
        }

    def stats(self) -> dict:
        mems = self.store.memories()
        return {"sources": len(self.store.sources()), "memories": len(mems),
                "active": sum(m.status == "active" for m in mems),
                "superseded": sum(m.status == "superseded" for m in mems),
                "disputed": sum(m.status == "disputed" for m in mems),
                "nodes": self.g.number_of_nodes(), "edges": self.g.number_of_edges(),
                "llm": f"asi1:{llm.MODEL}" if llm.available() else "offline"}
