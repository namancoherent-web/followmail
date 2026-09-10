"""News collection — Google News RSS across trigger / industry / competitor queries.

Distilled from the mother repo's `trends/collector.py`: parallel feed fetch, SHA-256
fingerprint dedup, date-window filtering. Free sources only (no paid news APIs).
"""
from __future__ import annotations
import concurrent.futures as cf
import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

import feedparser

import config


@dataclass
class Article:
    title: str
    url: str
    source: str
    published: datetime
    summary: str = ""
    query: str = ""
    bucket: str = ""            # trigger | industry | competitor  (set later)
    fingerprint: str = field(default="", repr=False)
    # scoring fields filled by score.py
    relevancy: float = 0.0
    freshness: float = 0.0
    importance: float = 0.0
    composite: float = 0.0
    trigger_type: str = ""
    matched_industries: list = field(default_factory=list)


def _fingerprint(title: str, url: str) -> str:
    norm = re.sub(r"\s+", " ", (title or "").lower()).strip()
    return hashlib.sha256(f"{norm}|{url}".encode()).hexdigest()


def _clean(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


def _parse_dt(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
    return None


def _source_of(entry, fallback: str) -> str:
    src = getattr(entry, "source", None)
    if src and getattr(src, "title", None):
        return src.title
    # Google News titles are usually "Headline - Publisher"
    return fallback


def _fetch_one(query: str, bucket: str, cutoff: datetime, locale: tuple) -> list[Article]:
    hl, gl, ceid = locale
    url = config.GOOGLE_NEWS.format(q=quote_plus(query), hl=hl, gl=gl, ceid=ceid)
    out: list[Article] = []
    try:
        feed = feedparser.parse(url)
    except Exception:
        return out
    for e in feed.entries:
        dt = _parse_dt(e)
        if dt is None or dt < cutoff:
            continue
        title = _clean(getattr(e, "title", ""))
        link = getattr(e, "link", "")
        if not title or not link:
            continue
        # split "Headline - Publisher"
        publisher = ""
        if " - " in title:
            head, publisher = title.rsplit(" - ", 1)
            title = head.strip()
        out.append(Article(
            title=title, url=link,
            source=_source_of(e, publisher or "Google News"),
            published=dt, summary=_clean(getattr(e, "summary", ""))[:600],
            query=query, bucket=bucket, fingerprint=_fingerprint(title, link),
        ))
    return out


def collect(profile, country: dict | None = None) -> list[Article]:
    """Fetch all queries in parallel, dedupe by fingerprint, return within window.

    `profile` carries trigger_queries / industry_queries / competitors.
    `country` (a config.COUNTRIES entry) sets the Google-News locale and appends the
    country name to each query so results are geo-biased. None/Global = worldwide English.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.LOOKBACK_HOURS)
    locale = (country or config.COUNTRIES["Global"]).get("gn", config.GN_DEFAULT_LOCALE)
    cname = (country or {}).get("name", "Global")
    suffix = "" if cname in ("", "Global") else f" {cname}"   # e.g. "biotech funding India"

    jobs = ([(q + suffix, "trigger") for q in profile.trigger_queries]
            + [(q + suffix, "industry") for q in profile.industry_queries]
            + [(c + suffix, "competitor") for c in profile.competitors])

    articles: list[Article] = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_fetch_one, q, b, cutoff, locale): (q, b) for q, b in jobs}
        for fut in cf.as_completed(futs):
            try:
                articles.extend(fut.result())
            except Exception:
                pass

    # dedupe (first seen wins, but prefer a trigger bucket over industry/competitor)
    seen: dict[str, Article] = {}
    bucket_rank = {"trigger": 0, "competitor": 1, "industry": 2}
    for a in articles:
        cur = seen.get(a.fingerprint)
        if cur is None or bucket_rank[a.bucket] < bucket_rank[cur.bucket]:
            seen[a.fingerprint] = a
    return list(seen.values())


def collect_queries(queries: list[str], country: dict | None = None, bucket: str = "market") -> list[Article]:
    """Fetch an explicit list of Google-News queries (used by the CMI lead-nurture pipeline).

    Uses the country's GN locale for sourcing but does NOT hard-filter by country — market
    intelligence is inherently global. Dedupes by fingerprint, returns within the lookback window.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.LOOKBACK_HOURS)
    locale = (country or config.COUNTRIES["Global"]).get("gn", config.GN_DEFAULT_LOCALE)
    articles: list[Article] = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_fetch_one, q, bucket, cutoff, locale): q for q in queries if q and q.strip()}
        for fut in cf.as_completed(futs):
            try:
                articles.extend(fut.result())
            except Exception:
                pass
    seen: dict[str, Article] = {}
    for a in articles:
        seen.setdefault(a.fingerprint, a)
    out = list(seen.values())
    out.sort(key=lambda x: x.published, reverse=True)   # freshest first
    return out
