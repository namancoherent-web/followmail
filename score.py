"""The scoring matrix: composite = relevancy x freshness x importance (weighted sum).

Each candidate signal is scored on three independent axes, then combined. This is the
gate that decides which trigger signals earn a place in the newsletter — the explicit
ask. All three sub-scores are in [0,1]; composite is a weighted sum in [0,1].
"""
from __future__ import annotations
from datetime import datetime, timezone

import config
from collect import Article

_TRIG = config.TRIGGER_TYPES
_S = config.SCORING


def _text(a: Article) -> str:
    return f"{a.title} {a.summary}".lower()


# ── 1. RELEVANCY — does this map onto the seller's coverage verticals? ───────
def relevancy(a: Article, industry_keywords: dict) -> tuple[float, list[str]]:
    t = _text(a)
    matched: list[str] = []
    hits = 0
    for industry, kws in industry_keywords.items():
        ind_hit = sum(1 for kw in kws if kw in t)
        if ind_hit:
            matched.append(industry)
            hits += ind_hit
    # saturating: 0 hits → 0.0, 1 → ~0.45, 3 → ~0.75, 6+ → ~0.95
    score = 1.0 - 0.6 ** hits if hits else 0.0
    # a signal touching 2+ distinct verticals is broadly relevant → small boost
    if len(matched) >= 2:
        score = min(1.0, score + 0.10)
    return round(score, 3), matched


# ── 2. FRESHNESS — recency decay (piecewise, from config bands) ──────────────
def freshness(a: Article) -> float:
    hours = (datetime.now(timezone.utc) - a.published).total_seconds() / 3600.0
    for band_h, factor in _S["freshness_bands"]:
        if hours <= band_h:
            return factor
    return _S["freshness_floor"]


# ── 3. IMPORTANCE — strength of the trigger event (+ money-scale boost) ──────
def importance(a: Article) -> tuple[float, str]:
    t = _text(a)
    best_type, best_imp = "", 0.0
    for ttype, spec in _TRIG.items():
        if any(kw in t for kw in spec["keywords"]):
            if spec["importance"] > best_imp:
                best_imp, best_type = spec["importance"], ttype
    if not best_type:
        # structural/industry item with no company trigger → low but non-zero
        return 0.30, ""
    # money-scale amplifier
    if any(h in t for h in config.BIG_MONEY_HINTS):
        best_imp = min(1.0, best_imp + 0.05)
    return round(best_imp, 3), best_type


# ── Composite ────────────────────────────────────────────────────────────────
def score_all(articles: list[Article], profile) -> list[Article]:
    for a in articles:
        rel, inds = relevancy(a, profile.industry_keywords)
        # Bucket-based relevancy floor: a trigger/industry article already matched a
        # seller-SCOPED query, so it is topically relevant even if the keyword lexicon
        # (LLM-inferred, sometimes narrow) missed it. Prevents broad-market sellers from
        # losing every prospect to relevancy=0.
        if a.bucket == "trigger":
            rel = max(rel, 0.35)
        elif a.bucket == "industry":
            rel = max(rel, 0.25)
        fr = freshness(a)
        imp, ttype = importance(a)
        a.relevancy, a.freshness, a.importance = rel, fr, imp
        a.matched_industries, a.trigger_type = inds, ttype
        a.composite = round(
            _S["w_relevancy"] * rel + _S["w_freshness"] * fr + _S["w_importance"] * imp, 4
        )
    articles.sort(key=lambda x: x.composite, reverse=True)
    return articles


def eligible(articles: list[Article]) -> list[Article]:
    return [a for a in articles if a.composite >= _S["min_composite"]]
