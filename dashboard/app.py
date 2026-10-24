"""LORE knowledge dashboard: streamlit run dashboard/app.py

ASI:One is the primary interface; this is the inspector for the memory and graph behind it."""

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lore import graph as G  # noqa: E402
from lore import render  # noqa: E402
from lore.engine import Lore  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_repo"
COLORS = {"memory": "#7c5cff", "service": "#1f9d8b", "file": "#d9822b", "person": "#8a8f98",
          "merge_request": "#3b82f6", "incident": "#e5484d", "commit": "#64748b", "doc": "#3b82f6",
          "issue": "#3b82f6", "source": "#3b82f6", "chat": "#3b82f6"}

st.set_page_config(page_title="LORE", page_icon="🧠", layout="wide")


@st.cache_resource
def get_lore() -> Lore:
    return Lore()


lore = get_lore()
lore._dirty()  # agents may have written to the shared DB since last render

with st.sidebar:
    st.title("🧠 LORE")
    st.caption("Living Organizational Record Engine")
    s = lore.stats()
    c1, c2 = st.columns(2)
    c1.metric("Memories", s["memories"])
    c2.metric("Sources", s["sources"])
    c1.metric("Active", s["active"])
    c2.metric("Superseded", s["superseded"])
    st.caption(f"Graph: {s['nodes']} nodes · {s['edges']} edges · LLM: {s['llm']}")
    st.divider()
    if st.button("Import sample repo", width="stretch"):
        st.success(lore.ingest_folder(str(SAMPLE)))
        st.rerun()
    repo = st.text_input("GitHub repo (owner/name)")
    if st.button("Import from GitHub", width="stretch", disabled=not repo):
        with st.spinner("Fetching merged PRs…"):
            try:
                st.success(lore.ingest_github(repo))
            except Exception as exc:
                st.error(str(exc))

tab_ask, tab_review, tab_mem, tab_graph, tab_onb, tab_log = st.tabs(
    ["Ask", "Review a change", "Memories", "Graph", "Onboarding", "Audit log"])

with tab_ask:
    q = st.text_input("Ask about the project", "Can I replace our payment service's database?")
    if q:
        r = lore.ask(q)
        st.markdown(r["answer"])
        with st.expander(f"Evidence ({len(r['evidence'])} memories, mode {r['mode']})"):
            for e in r["evidence"]:
                st.markdown(f"**[{e['id']}]** {e['statement']} — `{e['status']}` · score {e['score']}  \n"
                            f"> {e['quote']}  \n[{e['source_id']}]({e['source_url']})")
        if r["impact"]:
            st.json(r["impact"])

with tab_review:
    change = st.text_area("Proposed change (description or unified diff)",
                          "Add a 5 minute Redis cache to verify_token in auth_service/verify.py to cut latency",
                          height=160)
    just = st.text_input("Override justification (optional)")
    if st.button("Review", type="primary"):
        st.markdown(render.review(lore.review(change, justification=just, actor="dashboard")))

with tab_mem:
    status = st.selectbox("Status", ["all", "active", "superseded", "disputed"])
    mems = lore.store.memories(None if status == "all" else status)
    st.dataframe([{"id": m.id, "type": m.type, "status": m.status, "statement": m.statement,
                   "source": m.source_id, "date": m.timestamp, "confidence": m.confidence,
                   "by": m.extracted_by} for m in mems], width="stretch", hide_index=True)
    pick = st.selectbox("Inspect", [m.id for m in mems] or ["—"])
    if (m := lore.store.memory(pick)):
        st.markdown(render.memory(m.to_dict(), lore.store.events(m.id), lore.evidence(m)["links"]))
        c1, c2 = st.columns(2)
        reason = c1.text_input("Reason", key="reason")
        if c2.button("Challenge") and reason:
            lore.challenge(m.id, reason, "dashboard")
            st.rerun()
        if c2.button("Reaffirm") and reason:
            lore.reaffirm(m.id, reason, "dashboard")
            st.rerun()

with tab_graph:
    g = lore.g
    kinds = sorted({d.get("kind", "?") for _, d in g.nodes(data=True)})
    show = st.multiselect("Node kinds", kinds, default=[k for k in kinds if k != "person"])
    options = ["(whole graph)"] + sorted(g.nodes)
    # Default to the story node: the rule born from the auth-caching incident, if present.
    story = next((n for n in options if g.nodes.get(n, {}).get("statement", "").startswith("Authentication responses")), None)
    focus = st.selectbox("Focus on", options, index=options.index(story) if story else 0)
    nodes = set(n for n, d in g.nodes(data=True) if d.get("kind") in show)
    if focus != "(whole graph)":
        hood = {focus} | set(g.successors(focus)) | set(g.predecessors(focus))
        for n in list(hood):
            hood |= set(g.successors(n)) if g.nodes[n].get("kind") != "service" else set()
        nodes &= hood | {focus}
    dot = ["digraph{rankdir=LR;node[style=filled,fontcolor=white,fontname=Helvetica,shape=box];"
           "edge[fontsize=9,fontname=Helvetica,color=\"#999999\",fontcolor=\"#777777\"];"]
    for n in nodes:
        d = g.nodes[n]
        text = G.label(n) if d.get("kind") != "memory" else f"{G.label(n)}\\n{d.get('label', '')[:40]}"
        style = ",style=\"filled,dashed\"" if d.get("status") == "superseded" else ""
        dot.append(f'"{n}"[label={json.dumps(text)},fillcolor="{COLORS.get(d.get("kind"), "#555")}"{style}];')
    for u, v, d in g.edges(data=True):
        if u in nodes and v in nodes:
            dot.append(f'"{u}"->"{v}"[label="{d["rel"]}"];')
    dot.append("}")
    st.graphviz_chart("".join(dot), width="stretch")

with tab_onb:
    focus = st.text_input("Focus (optional)", "")
    st.markdown(render.onboard(lore.onboard(focus)))

with tab_log:
    st.dataframe(lore.store.events(), width="stretch", hide_index=True)
