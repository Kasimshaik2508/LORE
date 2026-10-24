# LORE — Living Organizational Record Engine

![domain:engineering](https://img.shields.io/badge/engineering-memory-7c5cff)
![tech:uagents](https://img.shields.io/badge/uAgents-chat_protocol-1f9d8b)

LORE remembers **why** a software team made its decisions, and uses that memory to review new work.

It reads a repository's merge requests, review comments, incidents, commits and docs, extracts
evidence-backed memories (decisions, rules, incidents, commitments), links them in a knowledge
graph of services, files and people, and answers questions with sources.

## What you can ask

- *Why did we choose PostgreSQL instead of MongoDB?* — the decision, its rationale, what it superseded, and the incident that caused it.
- *Can I replace our payment service's database?* — every dependent service, the rules that govern them, and an explicit note that missing conflicts are not proof of safety.
- `review: add a 5 minute Redis cache to verify_token` — LORE blocks it, cites the incident and the rule, and suggests the reviewer's recorded alternative.
- `review: … override: <justification>` — proceed with an audited exception.
- `onboard` / `onboard auth` — a new-developer briefing.
- `challenge MEM-007: <evidence>` · `reaffirm MEM-007: <reason>` · `show MEM-007`
- `remember: <decision> because <reason> affects <components>`
- `import github owner/repo` — learn from a public GitHub repository's merged PRs.

## How it works

`lore` (this agent) speaks the Agent Chat Protocol and routes each request to a specialist agent:
**lore-extractor** (memory extraction), **lore-retriever** (Q&A and impact analysis),
**lore-reviewer** (conflict checking) and **lore-onboarding** (briefings). Every memory keeps
a verbatim quote from its source, a timestamp, a confidence score and a status
(active / superseded / disputed).
