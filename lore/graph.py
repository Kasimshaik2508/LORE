"""Knowledge graph: nodes for memories, sources, files, services and people.
Only relationships stated in source data are added; nothing is inferred from co-occurrence."""

from __future__ import annotations

import networkx as nx

from .store import Store
from .text import tokens

FILE_SUFFIXES = (".py", ".sql", ".md", ".js", ".ts", ".go", ".java", ".rb", ".yml", ".yaml", ".json")


def component_node(name: str) -> str:
    name = name.strip()
    if "/" in name or name.endswith(FILE_SUFFIXES):
        return f"file:{name}"
    return f"service:{name}"


def label(nid: str) -> str:
    return nid.split(":", 1)[1] if ":" in nid else nid


def build(store: Store) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    for n in store.nodes():
        g.add_node(n["id"], kind=n["kind"], label=n["label"], **n["attrs"])
    for m in store.memories():
        g.add_node(f"memory:{m.id}", kind="memory", label=m.title, status=m.status,
                   mtype=m.type, statement=m.statement)
    for e in store.edges():
        for end in (e["src"], e["dst"]):
            if end not in g:
                g.add_node(end, kind=end.split(":", 1)[0], label=label(end))
        g.add_edge(e["src"], e["dst"], rel=e["rel"], evidence=e["evidence"])
    return g


def match_components(g: nx.MultiDiGraph, text: str) -> list[str]:
    """Service/file nodes whose name terms all appear in the text (or path appears verbatim)."""
    q = set(tokens(text))
    hits = []
    for nid, data in g.nodes(data=True):
        if data.get("kind") not in ("service", "file"):
            continue
        name = label(nid)
        terms = set(tokens(name))
        if name in text or (terms and terms <= q):
            hits.append(nid)
    # Prefer the most specific match: drop a node if a longer matched name contains its terms.
    return sorted(hits, key=lambda n: -len(tokens(label(n))))


def dependents(g: nx.MultiDiGraph, nid: str) -> dict[str, list[str]]:
    """Everything that (transitively) DEPENDS_ON nid, with the path that proves it."""
    rev = nx.DiGraph()
    for u, v, d in g.edges(data=True):
        if d.get("rel") == "DEPENDS_ON":
            rev.add_edge(v, u)
    if nid not in rev:
        return {}
    paths = nx.single_source_shortest_path(rev, nid)
    return {k: p for k, p in paths.items() if k != nid}


def service_of(g: nx.MultiDiGraph, nid: str) -> str | None:
    for _, v, d in g.out_edges(nid, data=True):
        if d.get("rel") == "PART_OF":
            return v
    return None


def memories_touching(g: nx.MultiDiGraph, component_nodes: set[str]) -> list[str]:
    """Memory nodes with an AFFECTS edge into any of the components (or their files' services)."""
    targets = set(component_nodes)
    for c in list(component_nodes):
        s = service_of(g, c)
        if s:
            targets.add(s)
    # A rule pinned to a file also governs the service that file belongs to.
    for u, v, d in g.edges(data=True):
        if d.get("rel") == "PART_OF" and v in component_nodes:
            targets.add(u)
    out = []
    for u, v, d in g.edges(data=True):
        if d.get("rel") == "AFFECTS" and v in targets and u not in out:
            out.append(u)
    return out


def neighborhood(g: nx.MultiDiGraph, nid: str) -> list[tuple[str, str, str]]:
    """(src, rel, dst) triples one hop around a node, for evidence display."""
    if nid not in g:
        return []
    triples = [(nid, d["rel"], v) for _, v, d in g.out_edges(nid, data=True)]
    triples += [(u, d["rel"], nid) for u, _, d in g.in_edges(nid, data=True)]
    return triples
