"""Markdown renderers for chat replies (ASI:One renders Markdown)."""

from __future__ import annotations

HELP = """**LORE — Living Organizational Record Engine**
I remember why your team made its engineering decisions, and I check new work against them.

Try:
- `Why did we choose PostgreSQL instead of MongoDB?`
- `Can I replace our payment service's database?`
- `review: add a 5 minute Redis cache to verify_token in auth_service/verify.py`
- `review: ... override: <why this exception is OK>`
- `onboard` or `onboard auth`
- `show MEM-007` · `challenge MEM-007: <evidence>` · `reaffirm MEM-007: <reason>`
- `remember: <decision> because <reason> affects <component, ...>`
- `import github <owner/repo>` · `status`"""

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
