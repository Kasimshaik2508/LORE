import asyncio
import os
from pathlib import Path

import pytest

os.environ["LORE_OFFLINE"] = "1"  # deterministic: never call ASI:One from tests

from lore.engine import Lore  # noqa: E402
from lore.extract import heuristic_extract  # noqa: E402
from lore.router import classify, local_dispatch, route  # noqa: E402
from lore.text import split_constraint, tokens  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_repo"


@pytest.fixture()
def lore(tmp_path):
    l = Lore(str(tmp_path / "t.db"))
    l.ingest_folder(str(SAMPLE))
    return l


def by_statement(lore, needle):
    return next(m for m in lore.store.memories() if needle.lower() in m.statement.lower())


# extraction ---------------------------------------------------------------

def test_extracts_rule_with_rationale_and_source(lore):
    m = by_statement(lore, "never be cached")
    assert m.type == "rule" and m.source_id == "MR-42" and m.status == "active"
    assert "revoked" in m.rationale
    assert m.quote in lore.store.source("MR-42")["body"]


def test_reviewer_comment_becomes_rule(lore):
    m = by_statement(lore, "integer cents")
    assert m.source_id == "MR-57" and m.confidence < 0.9


def test_suggestions_are_not_decisions(lore):
    assert lore.store.memories_from_source("ISSUE-63") == []
    assert heuristic_extract({"id": "X", "body": "maybe we should use GraphQL?"}) == []


def test_supersession_is_tracked(lore):
    mongo = by_statement(lore, "MongoDB")
    pg = by_statement(lore, "PostgreSQL")
    assert mongo.status == "superseded" and pg.status == "active"
    assert any(l["rel"] == "SUPERSEDES" and l["to"] == f"memory:{mongo.id}" for l in lore.evidence(pg)["links"])


def test_ingest_is_idempotent(lore):
    before = len(lore.store.memories())
    lore.ingest_folder(str(SAMPLE))
    assert len(lore.store.memories()) == before


# retrieval ----------------------------------------------------------------

def test_ask_returns_decision_history(lore):
    r = lore.ask("Why did we choose PostgreSQL instead of MongoDB?")
    ids = [e["source_id"] for e in r["evidence"]]
    assert ids[0] == "MR-31" and "MR-12" in ids
    assert "superseded" in r["answer"]


def test_impact_analysis_finds_dependents(lore):
    r = lore.ask("Can I replace our payment service's database?")
    imp = r["impact"]
    assert imp["target"] == "payments-db"
    assert {"payments_api", "ledger_service", "webhooks_service", "reporting_service"} <= set(imp["dependents"])
    assert "proving it is safe" in r["answer"]


def test_unknown_topic_is_not_called_safe(lore):
    r = lore.ask("What colour is the logo?")
    assert "not that the change is safe" in r["answer"] or r["evidence"] == [] or "safe" not in r["answer"].lower()


# review -------------------------------------------------------------------

def test_conflicting_change_is_blocked_with_evidence(lore):
    r = lore.review("Add a 5 minute Redis cache to verify_token in auth_service/verify.py")
    assert r["status"] == "BLOCK"
    top = r["findings"][0]
    assert top["verdict"] == "conflict" and top["memory"]["source_id"] == "MR-42"
    assert "horizontally" in top["safer_alternative"]


def test_diff_review(lore):
    diff = """diff --git a/auth_service/verify.py b/auth_service/verify.py
--- a/auth_service/verify.py
+++ b/auth_service/verify.py
@@ -1,3 +1,5 @@
+from functools import lru_cache
+@lru_cache(maxsize=1024)
 def verify_token(token):
"""
    r = lore.review(diff)
    assert r["files"] == ["auth_service/verify.py"]
    assert r["status"] == "BLOCK"


def test_removing_the_forbidden_thing_is_not_a_conflict(lore):
    r = lore.review("Remove the leftover redis cache helper from auth_service/cache.py")
    assert r["status"] != "BLOCK"
    diff = "--- a/auth_service/verify.py\n+++ b/auth_service/verify.py\n-@lru_cache()\n def verify_token(t):\n"
    assert lore.review(diff)["status"] != "BLOCK"


def test_float_money_conflict(lore):
    r = lore.review("Store refund totals as float in payments_api/refunds.py")
    assert r["findings"][0]["memory"]["source_id"] == "MR-57"
    assert r["status"] == "BLOCK"


def test_unrelated_change_has_no_known_conflicts(lore):
    r = lore.review("Fix typo in README")
    assert r["status"] == "NO_KNOWN_CONFLICTS" and "not proof of safety" in r["note"]


def test_override_is_audited(lore):
    r = lore.review("Add redis caching to verify_token", justification="load-test env only", actor="kasim")
    assert r["findings"][0]["verdict"] == "overridden"
    mid = r["findings"][0]["memory"]["id"]
    assert any(e["kind"] == "override" and e["actor"] == "kasim" for e in lore.store.events(mid))


def test_challenged_rule_stops_blocking(lore):
    m = by_statement(lore, "never be cached")
    lore.challenge(m.id, "We moved to 30s tokens with push revocation", "kasim")
    assert lore.review("Add redis caching to verify_token")["status"] != "BLOCK"
    lore.reaffirm(m.id, "push revocation was rolled back", "sam")
    assert lore.review("Add redis caching to verify_token")["status"] == "BLOCK"


def test_remember_and_supersede(lore):
    old = by_statement(lore, "never be cached")
    new = lore.remember("Cache auth responses for at most 5 seconds", "push revocation makes short TTLs safe",
                        ["authentication_service"], "kasim", supersedes=old.id)
    assert lore.store.memory(old.id).status == "superseded"
    assert new.status == "active" and new.source_id.startswith("CHAT-")


# text + routing -----------------------------------------------------------

def test_constraint_split():
    kind, ctx, forb = split_constraint("Authentication responses must never be cached.")
    assert kind == "forbid" and "auth" in ctx and forb == ["cache"]
    assert split_constraint("Use PostgreSQL for the ledger") is None
    assert "cache" in tokens("@lru_cache on verify_token") and "auth" in tokens("verify_token")


@pytest.mark.parametrize("text,intent", [
    ("help", "help"), ("Why postgres?", "ask"), ("review: add a cache", "review"),
    ("challenge MEM-001: outdated", "challenge"), ("onboard", "onboard"), ("show MEM-002", "show"),
    ("import github fetchai/uAgents", "ingest"), ("remember: X because Y", "remember"),
])
def test_classify(text, intent):
    assert classify(text)[0] == intent


def test_asi_one_mentions_are_ignored():
    addr = "@agent1qghefamymd3qjgpty3q0dny6tsw56n66rmaallz0l5zvhftu9ndfxjxnrur"
    assert classify(f"{addr} status") == ("status", {})
    assert classify(f"{addr} LORE engineering memory")[0] == "help"
    assert classify(f"{addr} review: add a cache")[1]["change"] == "add a cache"
    assert classify(f"{addr} Why postgres?") == ("ask", {"question": "Why postgres?"})


def test_route_end_to_end(lore):
    call = local_dispatch(lore)
    out = asyncio.run(route("review: add redis cache to verify_token", "u", call, lore))
    assert "BLOCK" in out and "MR-42" in out
    out = asyncio.run(route("review: add redis cache to verify_token override: test env", "u", call, lore))
    assert "overridden" in out
