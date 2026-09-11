"""CoherentLead — "Ideal Customers" brief: selection + LLM synthesis + assembly.

Same engine as brief_builder.py (collect → score → triage buyer/peer/other → free-enrich
→ LLM-write), reused verbatim, but scoped to what templates/daily_brief_coherentlead.html
actually renders: two "Ideal Customer" cards plus the static "Inside CoherentLead" showcase
(baked into the template — nothing to assemble here). No top3, no Industry Outlook, no
per-section action plans — those sections don't exist in this template.

CoherentLead's own voice (from coherentlead_brand_book_by_pomelli.pdf, page 6):
  Values: Data Accuracy, Transparency, Precision Intelligence, Efficiency
  Tone:   Professional, Precise, Authoritative, Data-driven
"""
from __future__ import annotations
import random
from datetime import datetime, timezone

import config
import llm
import free_research
from collect import Article
from brief_builder import triage_triggers, _clean_frag, _date_label, _cands_block, _industry_of

VOICE = (
    "Voice: Professional, Precise, Authoritative, Data-driven. Values: Data Accuracy, "
    "Transparency, Precision Intelligence, Efficiency. Write like a sales-intelligence "
    "analyst handing a colleague a verified lead, not a marketer hyping a feature."
)

DEMO_URL = "https://www.coherentlead.ai/book-a-demo"
SITE_URL = "https://coherentlead.ai/"


# ── Card writer — same shape as brief_builder._write_card, CoherentLead voice/framing ──
def _write_ideal_customer_card(article: Article, name: str, enr: dict, profile) -> dict:
    a = article
    ind = _industry_of(a, profile)
    ctx = free_research.context_block(enr)
    fr = f"\nFREE RESEARCH (Wikipedia / recent company news):\n{ctx}\n" if ctx else ""
    src = (f"SIGNAL:\n TITLE: {a.title}\n SOURCE: {a.source} | DATE: {_date_label(a.published)}\n"
           f" SUMMARY: {a.summary[:400]}\n")

    system = (
        f"You are CoherentLead, a self-serve AI-powered B2B prospecting platform: users describe "
        f"who they sell to, CoherentLead's AI builds an ICP and surfaces matching contacts from a "
        f"250M+ contact/company database, verifies each email through a 7-layer engine, and gives "
        f"the user company/account intelligence — the USER then does the actual outreach; "
        f"CoherentLead does not send outreach on its own. "
        f"{VOICE} Write an Ideal Customer brief for {name} — a company that would BUY "
        "CoherentLead because it is actively scaling its own outbound motion (new funding, a "
        "first sales hire, market expansion, or similar) and needs to find and verify its own "
        "prospects faster. Never describe CoherentLead as sending outreach, reaching prospects, "
        "or acting 'automatically' on the user's behalf — it discovers and verifies; the user "
        "reaches out. Ground every claim in the SIGNAL and FREE RESEARCH; do NOT invent numbers. "
        "Only <b>/<i> inline HTML. No angle-bracket placeholders."
    )
    user = (
        f"{src}{fr}\nReturn a JSON object with keys:\n"
        f"  narrative_html — 2 to 4 sentences: what happened, figures if stated, company context "
        f"from the free research, and why {name}'s own sales team would need CoherentLead's "
        f"ICP search and verification right now (never phrase it as CoherentLead acting on "
        f"their behalf).\n"
        "     BOLDING RULE — wrap exactly two things in <b>…</b> and nothing else:\n"
        "       (a) the TRIGGER SIGNAL — the event and its figure/date as it appears in the "
        "sentence (e.g. <b>just closed a Series B</b>)\n"
        "       (b) WHAT COHERENTLEAD CAN DO — the clause naming the outbound need this opens "
        "(e.g. <b>a precise fit for CoherentLead's discovery and verification engine</b>)\n"
        "     Leave the connecting context unbolded. Do not bold whole sentences or the company "
        "name alone.\n"
        "  why_now — one sentence on why the buying window for outbound infrastructure is open now\n"
        "  who_to_target — 2 to 3 buyer roles (e.g. VP of Sales, Head of Revenue Operations)\n"
        "  recommended_action — 1 to 2 sentences: the concrete first outreach move for CoherentLead, "
        "referencing a specific platform capability (AI Builder / ICP, 7-layer verification, "
        "LinkedIn import, account intelligence) rather than a generic pitch"
    )
    data = llm.chat_json(system, user, max_tokens=900, default={})
    return {
        "flag": f"Ideal Customer · {ind}",
        "company_name": name,
        "narrative_html": _clean_frag(data.get("narrative_html") or "") or a.summary or a.title,
        "left": {"h": "Why now", "v": _clean_frag(data.get("why_now") or "") or "The buying window is open now."},
        "right": {"h": "Who to target", "v": _clean_frag(data.get("who_to_target") or "") or "VP of Sales, Head of Revenue Operations."},
        "action": {"h": "Recommended action", "v": _clean_frag(data.get("recommended_action") or "")},
    }


# Pool size for randomized selection: pick candidates from the top N eligible buyers by
# score rather than always the single #1. This alone is NOT enough when one candidate is
# a genuine score outlier (e.g. Theater at 0.914 vs. everything else at ~0.859) — with
# only 2 picks per run it still lands in a large fraction of independent shuffles, so a
# batch of many sends can still show it far more often than any other company. The real
# fix is `recently_used` below: an exclusion set the CALLER (campaign.py) carries across
# the whole batch, so a company already featured recently is skipped until it cycles out.
_SHORTLIST_SIZE = 8


# ── 1. IDEAL CUSTOMERS — best BUYERS of CoherentLead itself, enriched + written ───
def build_ideal_customers(triggers: list[Article], profile, want: int = 2, log=print,
                           recently_used: set[str] | None = None) -> tuple[list[dict], list[Article]]:
    """Pick up to `want` distinct buyer companies. Reuses brief_builder.triage_triggers
    verbatim — 'buyer' here means a company that would purchase CoherentLead (i.e. is
    scaling its own outbound sales), never a rival prospecting/data-enrichment tool.

    `recently_used` (lowercased company names) are skipped when a same-or-better-scored
    alternative exists in the shortlist — guarantees real variety across a long batch,
    not just per-call randomness among an unchanging top-N. Falls back to using them
    anyway if nothing else is eligible, so a thin-news run never comes up empty."""
    recently_used = recently_used or set()
    rel, cands = triage_triggers(triggers, profile)
    eligible: dict[str, list[tuple[int, Article, str]]] = {"buyer": [], "other": []}
    seen: set[str] = set()
    for i, a in enumerate(cands):
        name = rel.get(i, ("", "other"))[0]
        kind = rel.get(i, (None, "other"))[1]
        if kind not in eligible or not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        eligible[kind].append((i, a, name))

    picks: list[tuple[Article, str]] = []
    for kind in ("buyer", "other"):
        if len(picks) >= want:
            break
        shortlist = eligible[kind][:_SHORTLIST_SIZE]  # already composite-sorted; top N only
        fresh = [c for c in shortlist if c[2].lower() not in recently_used]
        pool = fresh if fresh else shortlist  # exhausted the fresh pool → reuse is fine
        random.shuffle(pool)
        for i, a, name in pool:
            if len(picks) >= want:
                break
            picks.append((a, name))
    cards, arts = [], []
    for art, company in picks:
        log(f"    · free-research: {company}")
        enr = free_research.enrich_company(company, config.get_country(getattr(profile, "market", "Global")))
        card = _write_ideal_customer_card(art, company, enr, profile)
        card["_sources"] = enr.get("sources_used", [])
        cards.append(card)
        arts.append(art)
    return cards, arts


# ── Editorial: lede only — this template has no top3 / industry / plan sections ──
def build_editorial(customers: list[dict], profile) -> dict:
    import json as _json
    market = getattr(profile, "market", "Global") or "Global"
    ctx = {
        "ideal_customers": [{"company": c["company_name"], "narrative": re_plain(c["narrative_html"]),
                             "why_now": c["left"]["v"]} for c in customers],
        "target_market": market,
    }
    system = (
        f"You are CoherentLead, an AI-powered B2B prospecting and sales-intelligence platform. "
        f"{VOICE} Write the opening line(s) of today's Daily Brief. Be specific to the signals; "
        "never generic. Never wrap values in angle brackets. Inline HTML allowed: <b>, <i>."
    )
    user = (
        f"CONTEXT:\n{_json.dumps(ctx, ensure_ascii=False)}\n\n"
        "Return a JSON object with key:\n"
        "  lede_html — 2 to 3 sentences introducing the two Ideal Customer companies below: name "
        "the buyer situation for each (e.g. funding just closed, new market expansion, first sales "
        "hire). You MUST name <b>CoherentLead</b> at least once. Do NOT add a closing sentence "
        "about CoherentLead being 'the profile it is built to discover' — that line is appended "
        "separately; end after describing the two companies."
    )
    data = llm.chat_json(system, user, max_tokens=500, default={})
    lede = _clean_frag(data.get("lede_html") or "")
    if not lede:
        names = " and ".join(c["company_name"] for c in customers) or "today's signals"
        lede = f"Two ideal-fit prospects for your pipeline this week — {names}."
    # Fixed closing line — never LLM-written, so it can't duplicate a similar sentence the
    # model already produced on its own. IMPORTANT: CoherentLead is a self-serve discovery/
    # verification workspace (per coherentlead.ai) — it surfaces the ICP match and verified
    # contacts for the USER to act on; it does not autonomously send outreach on its own.
    # Do not reintroduce language implying CoherentLead "reaches" prospects "for you" or
    # "automatically" without the user in the loop — that was a real bug (confirmed by the
    # product's own site copy) carried over from CoherentConnect's fully-autonomous framing.
    CLOSING = " Both are exactly the kind of buyer <b>CoherentLead</b>'s AI-powered ICP search and 7-layer verification are built to surface — so you can find and reach them with confidence."
    if not re_plain(lede).rstrip().endswith("confidence."):
        lede += CLOSING
    return {"lede_html": lede}


def re_plain(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html or "").strip()[:400]


# ── Assemble ─────────────────────────────────────────────────────────────────
def build_coherentlead_brief(scored: list[Article], profile, log=print,
                              recently_used: set[str] | None = None) -> tuple[dict, dict]:
    """`recently_used` (lowercased company names) — pass a set that PERSISTS across an
    entire campaign batch (see campaign.py) so a single high-scoring outlier story
    doesn't dominate every recipient's brief; see build_ideal_customers for details."""
    now = datetime.now(timezone.utc)

    triggers = [a for a in scored if a.bucket == "trigger" and a.trigger_type]
    industry = [a for a in scored if a.bucket == "industry"] or [a for a in scored if a.bucket == "trigger" and not a.trigger_type]
    log(f"  selecting: {len(triggers)} trigger / {len(industry)} industry eligible")

    pool = triggers + [a for a in industry if a not in triggers]
    pool.sort(key=lambda a: a.composite, reverse=True)
    log("  → Ideal Customers ×2: triage buyers → free-enrich → write")
    customers, cust_arts = build_ideal_customers(pool, profile, want=2, log=log, recently_used=recently_used)

    log("  → editorial (lede)")
    ed = build_editorial(customers, profile)

    brief = {
        "brand": {"wordmark": "CoherentLead", "issue_label": "Daily Brief",
                  "issue_date": f"{now.day} {now.strftime('%b %Y')}",
                  "tagline": profile.tagline},
        "recipient": {"first_name": profile.recipient},
        "meta": {"date_pill": now.strftime("%A, %B ") + str(now.day) + now.strftime(", %Y")},
        "intro": {"lede_html": ed["lede_html"]},
        "potential_customers": customers,
        "footer": {"cta_url": DEMO_URL, "site_url": SITE_URL, "cta_text": "Book a Demo →",
                   "site_text": "Visit the Site →", "tagline": profile.tagline,
                   "assembled_note": "Assembled &amp; verified by CoherentLead",
                   "subline": "Your AI-powered prospecting &amp; sales intelligence platform",
                   "unsubscribe_url": "#"},
    }
    debug = {
        "customers": [{"company": c["company_name"], "article": a.title, "score": a.composite,
                       "enriched_via": c.get("_sources", [])} for c, a in zip(customers, cust_arts)],
        "counts": {"trigger": len(triggers), "customers": len(customers)},
    }
    return brief, debug
