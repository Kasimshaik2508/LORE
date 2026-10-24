"""Markdown renderers for chat replies (ASI:One renders Markdown)."""

from __future__ import annotations

HELP = """**Hi, I'm LORE (Living Organizational Record Engine).**
I remember *why* a software team made its engineering decisions, and I warn you before a new change repeats an old mistake. Every answer cites the pull request or incident it came from.

I've already learned the history of **Payflow**, a sample payments company: its pull requests, review comments, incidents and docs. Just ask in plain English, for example:

- *Why did the team choose PostgreSQL instead of MongoDB?*
- *What would break if I replace the payments database?*
- *Is it safe to add a Redis cache to the login token check?* ← I'll block this one, and show why
- *I want to store refund amounts as floats*
- *What incidents has the team had?*
- *What rules should I know?*
- *I'm new here, give me an overview*
- *Who owns the authentication service?*

**How I work:** five Fetch.ai agents. I route your message to an extractor, a retriever, a reviewer or an onboarding agent, and they share one memory: a knowledge graph of decisions, incidents, files, services and people.

Power commands: `review: <change>` · `review: <change> override: <reason>` · `show MEM-007` · `challenge MEM-007: <evidence>` · `remember: <decision> because <reason>` · `import github owner/repo` · `status`"""

ICON = {"conflict": "⛔", "possible_conflict": "⚠️", "overridden": "📝", "related": "🔎", "compliant": "✅"}
STATUS = {"BLOCK": "⛔ **BLOCK — conflicts with recorded decisions**",
          "CAUTION": "⚠️ **CAUTION — touches components with recorded history**",
          "NO_KNOWN_CONFLICTS": "✅ **No known conflicts**"}


def ask(r: dict) -> str:
    footer = f"\n\n_Answered by LORE Ask · {len(r['evidence'])} memories · {r['mode']}_"
    return r["answer"] + footer


def review(r: dict, limit: int = 6) -> str:
    lines = [STATUS[r["status"]]]
    if r["files"]:
        lines.append("Files: " + ", ".join(f"`{f}`" for f in r["files"]))
    for f in r["findings"][:limit]:
        m = f["memory"]
        lines.append(f"\n{ICON.get(f['verdict'], '•')} **{f['verdict'].replace('_', ' ')}** with "
                     f"**[{m['id']}]** {m['statement']}")
        if m.get("rationale"):
            lines.append(f"  - Why it exists: {m['rationale']}")
        lines.append(f"  - Evidence: [{m['source_id']}]({m['source_url']}) — “{m['quote']}”")
        lines.append(f"  - {f['explanation']}")
        if f.get("safer_alternative"):
            lines.append(f"  - Safer alternative: {f['safer_alternative']}")
    if len(r["findings"]) > limit:
        lines.append(f"\n…and {len(r['findings']) - limit} more related memories.")
    if r["status"] == "BLOCK":
        lines.append("\nTo proceed anyway, resend with `override: <justification>` "
                     "(recorded in the audit log), or `challenge MEM-xxx: <evidence>` if the rule is outdated.")
    lines.append(f"\n_{r['note']}_")
    return "\n".join(lines)


def onboard(r: dict) -> str:
    lines = ["**Welcome aboard — project briefing**", "\n**Services**"]
    for s in r["services"]:
        dep = f" → depends on {', '.join(s['depends_on'])}" if s["depends_on"] else ""
        lines.append(f"- `{s['name']}` ({s['kind']}, owner {s['owner'] or '?'}){dep}")
    if r["rules"]:
        lines.append("\n**Rules you must not break**")
        lines += [f"- [{m['id']}] {m['statement']} _(from {m['source_id']})_" for m in r["rules"]]
    if r["decisions"]:
        lines.append("\n**Architecture decisions**")
        for m in r["decisions"]:
            tag = "" if m["status"] == "active" else f" _({m['status']})_"
            lines.append(f"- [{m['id']}] {m['statement']}{tag} _(from {m['source_id']})_")
    if r["incidents"]:
        lines.append("\n**Past incidents worth knowing**")
        lines += [f"- {m['source_id']}: {m['title']} — {m['statement']}" for m in r["incidents"]]
    if r["key_files"]:
        lines.append("\n**Most-governed files:** " + ", ".join(f"`{f}` ({n})" for f, n in r["key_files"]))
    if r["people"]:
        lines.append("**People with the most history:** " + ", ".join(f"{p} ({n})" for p, n in r["people"][:5]))
    return "\n".join(lines)


def memory(m: dict, events: list[dict], links: list[dict]) -> str:
    lines = [f"**[{m['id']}] {m['title']}**", f"- Type: {m['type']} · Status: **{m['status']}** · "
             f"Confidence: {m['confidence']:.2f} · Extracted by: {m['extracted_by']}",
             f"- Statement: {m['statement']}"]
    if m["rationale"]:
        lines.append(f"- Rationale: {m['rationale']}")
    lines.append(f"- Components: {', '.join(m['components']) or '—'}")
    lines.append(f"- Source: [{m['source_id']}]({m['source_url']}) ({m['timestamp'] or 'undated'}) — “{m['quote']}”")
    for link in links:
        lines.append(f"- {link['from']} **{link['rel']}** {link['to']}")
    if events:
        lines.append("\n**History**")
        lines += [f"- {e['ts']} {e['kind']} by {e['actor'] or 'system'}: {e['detail']}" for e in events]
    return "\n".join(lines)


def stats(s: dict) -> str:
    return (f"**LORE status** — {s['sources']} sources · {s['memories']} memories "
            f"({s['active']} active, {s['superseded']} superseded, {s['disputed']} disputed) · "
            f"graph {s['nodes']} nodes / {s['edges']} edges · LLM: {s['llm']}")


def impact(imp: dict) -> str:
    lines = [f"**What depends on `{imp['target']}` (from the dependency graph):**"]
    if imp["dependents"]:
        lines += [f"- `{svc}` ({' ← '.join(path)})" for svc, path in imp["dependents"].items()]
    else:
        lines.append("- No recorded dependents.")
    if imp["governing_memories"]:
        lines.append("- Memories governing it or its dependents: "
                     + ", ".join(f"[{x}]" for x in imp["governing_memories"]))
    return "\n".join(lines)


def rules(r: dict) -> str:
    lines = ["**Rules the team has agreed on**"]
    lines += [f"- **[{m['id']}]** {m['statement']} _(from {m['source_id']})_" for m in r["rules"]] or ["- None recorded."]
    lines.append("\n**Architecture decisions**")
    for m in r["decisions"]:
        tag = "" if m["status"] == "active" else f" _({m['status']})_"
        lines.append(f"- **[{m['id']}]** {m['statement']}{tag} _(from {m['source_id']})_")
    lines.append("\nAsk *“why”* about any of them, or say `show MEM-007` for the full evidence.")
    return "\n".join(lines)


def incidents(r: dict) -> str:
    if not r["incidents"]:
        return "No incidents are recorded."
    lines = ["**Incidents the team has had, and what they taught it**"]
    for m in r["incidents"]:
        lines.append(f"- **{m['source_id']} ({m['timestamp'] or 'undated'}): {m['title']}**  \n"
                     f"  Root cause: {m['statement']}")
    lines.append("\nAsk *“what rule came out of INC-11?”* or *“why can’t we cache auth?”* to follow one through.")
    return "\n".join(lines)
