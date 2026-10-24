"""Tokenisation and lightweight lexical matching shared by retrieval and review."""

from __future__ import annotations

import math
import re
from collections import Counter

# Domain synonyms collapse to one canonical term so "redis TTL" matches "cached"
# and "verify_token" matches "authentication". Keep this small and obvious.
CANONICAL = {
    "cache": "cache", "cached": "cache", "caching": "cache", "caches": "cache",
    "lru_cache": "cache", "lru": "cache", "memoize": "cache", "memoized": "cache",
    "redis": "cache", "ttl": "cache", "memcached": "cache",
    "auth": "auth", "authentication": "auth", "authenticate": "auth", "authn": "auth",
    "token": "auth", "tokens": "auth", "jwt": "auth", "credential": "auth",
    "credentials": "auth", "login": "auth",
    "database": "database", "db": "database", "datastore": "database",
    "postgresql": "postgres", "postgres": "postgres", "psql": "postgres",
    "mongodb": "mongo", "mongo": "mongo",
    "payment": "payment", "payments": "payment", "pay": "payment",
    "float": "float", "floats": "float", "double": "float", "decimal": "decimal",
    "cent": "cent", "cents": "cent",
    "money": "money", "amount": "money", "amounts": "money", "price": "money", "total": "money",
    "transaction": "transaction", "transactions": "transaction", "atomic": "transaction",
    "atomically": "transaction", "acid": "transaction",
    "idempotent": "idempotent", "idempotency": "idempotent", "dedupe": "idempotent",
    "webhook": "webhook", "webhooks": "webhook", "callback": "webhook",
    "replace": "replace", "swap": "replace", "migrate": "replace", "switch": "replace",
}

STOPWORDS = set(
    """a an the and or of to in on for by with from as at is are was were be been being it
    its this that these those we our you your they their i me my must should shall will would
    can could may might do does did not no never always all any every only than then there
    here what why how when which who whom into out over under up down so if but also just
    instead rather use used using same one two new old via per each such very too more most
    have has had get got make made let lets s t ve ll re d m""".split()
)

NEGATIONS = ("must never", "must not", "should never", "should not", "never", "do not",
             "don't", "cannot", "can't", "no longer")

_SPLIT = re.compile(r"[^A-Za-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


def _stem(word: str) -> str:
    for suffix in ("ations", "ation", "ings", "ing", "ies", "es", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            break
    # "store"/"stored" -> "stor"
    return word[:-1] if word.endswith("e") and len(word) > 4 else word


def norm(word: str) -> str:
    w = word.lower()
    if w in CANONICAL:
        return CANONICAL[w]
    stem = _stem(w)
    return CANONICAL.get(stem) or CANONICAL.get(w.rstrip("s")) or stem


def tokens(text: str) -> list[str]:
    """Content terms, canonicalised. Splits snake_case, camelCase and paths."""
    raw = text.replace("_", " ")
    out = []
    # Keep compound identifiers (lru_cache) visible to the synonym table first.
    for ident in re.findall(r"[A-Za-z]+_[A-Za-z_]+", text):
        if ident.lower() in CANONICAL:
            out.append(CANONICAL[ident.lower()])
    for part in _SPLIT.split(_CAMEL.sub(" ", raw)):
        if not part:
            continue
        low = part.lower()
        if low in STOPWORDS or (len(low) < 3 and low not in CANONICAL):
            continue
        out.append(norm(low))
    return out


def split_constraint(statement: str) -> tuple[str, list[str], list[str]] | None:
    """For a prohibition like "Auth responses must never be cached", return
    ("forbid", context_terms, forbidden_terms). None if it is not a prohibition."""
    low = statement.lower()
    for neg in NEGATIONS:
        idx = low.find(neg)
        if idx >= 0:
            before, after = statement[:idx], statement[idx + len(neg):]
            ctx, forb = tokens(before), tokens(after)
            # "stored as integer cents, never as floats": the positive clause is context.
            if not forb:
                return None
            return "forbid", sorted(set(ctx)), sorted(set(forb))
    return None


class BM25:
    """Tiny BM25 index; plenty for a few thousand memories."""

    def __init__(self, docs: dict[str, str], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = {key: Counter(tokens(text)) for key, text in docs.items()}
        self.len = {key: sum(c.values()) for key, c in self.tf.items()}
        self.avg = (sum(self.len.values()) / len(self.len)) if self.len else 0.0
        df: Counter = Counter()
        for c in self.tf.values():
            df.update(c.keys())
        n = len(self.tf)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        q = tokens(query)
        scores = []
        for key, tf in self.tf.items():
            s = 0.0
            for t in q:
                if t not in tf:
                    continue
                f = tf[t]
                denom = f + self.k1 * (1 - self.b + self.b * self.len[key] / (self.avg or 1))
                s += self.idf[t] * f * (self.k1 + 1) / denom
            if s > 0:
                scores.append((key, s))
        scores.sort(key=lambda x: -x[1])
        return scores[:k]
