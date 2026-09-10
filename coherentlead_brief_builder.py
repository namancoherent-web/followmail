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
        f"You are CoherentLead, an AI-powered B2B prospecting and sales-intelligence platform. "
        f"{VOICE} Write an Ideal Customer brief for {name} — a company that would BUY "
        "CoherentLead's contact-discovery, email-verification and outbound-sales tooling because "
        "it is actively scaling its own outbound motion (new funding, a first sales hire, market "
        "expansion, or similar). Ground every claim in the SIGNAL and FREE RESEARCH; do NOT "
        "invent numbers. Only <b>/<i> inline HTML. No angle-bracket placeholders."
    )
    user = (
        f"{src}{fr}\nReturn a JSON object with keys:\n"
        f"  narrative_html — 2 to 4 sentences: what happened, figures if stated, company context "
        f"from the free research, and why it creates a need for CoherentLead's discovery/"
        f"verification/outreach platform right now.\n"
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


# ── 1. IDEAL CUSTOMERS — best BUYERS of CoherentLead itself, enriched + written ───
def build_ideal_customers(triggers: list[Article], profile, want: int = 2, log=print) -> tuple[list[dict], list[Article]]:
    """Pick up to `want` distinct buyer companies, in composite order. Reuses
    brief_builder.triage_triggers verbatim — 'buyer' here means a company that would
    purchase CoherentLead (i.e. is scaling its own outbound sales), never a rival
    prospecting/data-enrichment tool."""
    rel, cands = triage_triggers(triggers, profile)
    picks: list[tuple[Article, str]] = []
    seen: set[str] = set()
    for kind in ("buyer", "other"):
        for i, a in enumerate(cands):
            if len(picks) >= want:
                break
            name = rel.get(i, ("", "other"))[0]
            if rel.get(i, (None, "other"))[1] != kind or not name or name.lower() in seen:
                continue
            seen.add(name.lower())
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
    # Fixed closing line (matches both reference demos verbatim) — never LLM-written, so it
    # can never duplicate a similar sentence the model already produced on its own.
    CLOSING = " Both are exactly the profile <b>CoherentLead</b> is built to discover, verify, and reach for you automatically."
    if not re_plain(lede).rstrip().endswith("automatically."):
        lede += CLOSING
    return {"lede_html": lede}


def re_plain(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html or "").strip()[:400]


# ── Assemble ─────────────────────────────────────────────────────────────────
def build_coherentlead_brief(scored: list[Article], profile, log=print) -> tuple[dict, dict]:
    now = datetime.now(timezone.utc)

    triggers = [a for a in scored if a.bucket == "trigger" and a.trigger_type]
    industry = [a for a in scored if a.bucket == "industry"] or [a for a in scored if a.bucket == "trigger" and not a.trigger_type]
    log(f"  selecting: {len(triggers)} trigger / {len(industry)} industry eligible")

    pool = triggers + [a for a in industry if a not in triggers]
    pool.sort(key=lambda a: a.composite, reverse=True)
    log("  → Ideal Customers ×2: triage buyers → free-enrich → write")
    customers, cust_arts = build_ideal_customers(pool, profile, want=2, log=log)

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
