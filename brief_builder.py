"""Selection + LLM synthesis + assembly into the `brief` dict the templates expect.

Newsletter structure (after the salutation):
  Top-3 signals — one per section, categorized, in the same order as the sections:
     1) Potential Customer #1   2) Potential Customer #2   3) Industry Outlook
  Then the OUTLOOK blocks, EACH followed by its own Coherent Take:
     1) POTENTIAL CUSTOMER × 2 — two companies captured on trigger signals → Coherent Take
     2) INDUSTRY OUTLOOK       — the industry trend we track               → Coherent Take
  Then: Inside CoherentConnect — a static capability showcase baked into the template.

The per-card "Approach plan" is deliberately NOT an LLM-written sales checklist: it is a
fixed CoherentConnect pitch (see `CC_PITCH_PLAN`), identical on every card and every issue.
Competition Outlook is intentionally not produced.

Every LLM step degrades to source-derived text so the newsletter always renders. All
tenant-specific facts come from a `tenant.Profile`, so this works for ANY seller.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone

import config
import llm
import cluster
import free_research
from collect import Article

_INLINE_OPEN = re.compile(r"^<(b|i|em|strong|span|a)\b", re.I)
_INLINE_CLOSE = re.compile(r"</(b|i|em|strong|span|a)>$", re.I)

# Every "Book a demo" link in the brief (3 section CTAs + the footer button) resolves
# from this one value via footer.cta_url.
# Industry Outlook credits the engine, not the publisher: the story is the synthesis across
# many sources, and naming one outlet reads as a link-share. The underlying article is still
# collected, scored and fingerprinted — only the on-page attribution changes.
SIGNAL_ATTRIBUTION = "CoherentConnect Signal Algorithm"

DEMO_URL = "https://coherentconnect.ai/booking"
SITE_URL = "https://coherentconnect.ai/"


def _clean_frag(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.strip()
    if s.startswith("<") and s.endswith(">") and not _INLINE_OPEN.match(s):
        s = s[1:-1].strip()
    if s.startswith("<") and not _INLINE_OPEN.match(s):
        s = s[1:].lstrip()
    if s.endswith(">") and not _INLINE_CLOSE.search(s):
        s = s[:-1].rstrip()
    return s.strip()


def _date_label(dt: datetime) -> str:
    return f"{dt.strftime('%b')} {dt.day}"


def _cands_block(arts: list[Article]) -> str:
    lines = []
    for i, a in enumerate(arts):
        lines.append(f"[{i}] TITLE: {a.title}\n    SOURCE: {a.source} | DATE: {_date_label(a.published)}"
                     f" | TRIGGER: {a.trigger_type or 'none'} | QUERY: {a.query} | SCORE: {a.composite}\n"
                     f"    SUMMARY: {a.summary[:280]}")
    return "\n".join(lines)


def cc_pitch_plan(companies: list[str]) -> list[dict]:
    """The action plan closing the Potential Customers section — ONE block covering both
    cards, since the process is identical for either company. Fixed pitch, never LLM-written."""
    names = " and ".join(c for c in companies if c) or "every company above"
    return [
        {"title": "Subscribe to CoherentConnect.",
         "body_html": f"We funnel these deals for you — {names} tracked, researched and worked end to end, "
                      f"from the trigger to the reply in your inbox."},
        {"title": "Find 1000+ more like them.",
         "body_html": "The same engine surfaces similar opportunities across <b>1000+ potential customers</b>, "
                      "each mapped to real, verified buying intent — not a scraped industry list."},
        {"title": "Let it run the outreach itself.",
         "body_html": "CoherentConnect writes the email for <b>your exact ICP</b> off that company's own news and "
                      "<b>sends it from your own inbox</b> — warmed, verified and tracked. Autonomous end to end; "
                      "your team only steps in for the reply."},
    ]


def cc_industry_plan() -> list[dict]:
    """The action plan under Industry Outlook. Same three-beat shape as the prospect plan, but
    about turning a market shift into pipeline rather than working one named account."""
    return [
        {"title": "Turn the trend into a target list.",
         "body_html": "CoherentConnect reads every shift like this the night it breaks and names the companies "
                      "it puts under pressure — the buyers who now have a budget, a deadline or a gap you close."},
        {"title": "Reach 1000+ companies riding the same shift.",
         "body_html": "One trend becomes <b>1000+ mapped accounts</b>, each ranked on how hard the change hits "
                      "them and how closely their need matches what you sell."},
        {"title": "Get in front of it before the market does.",
         "body_html": "The engine writes the trend-led email for <b>your exact ICP</b> and <b>sends it from your "
                      "own inbox</b> while the shift is still news — so you arrive as the read on the market, "
                      "not as another vendor after the fact."},
    ]


def _industry_of(a: Article, profile) -> str:
    return a.matched_industries[0] if a.matched_industries else (profile.industries[0] if profile.industries else "Technology")


# ── Triage: classify each trigger company as BUYER vs PEER (competitor) vs OTHER ─
def triage_triggers(triggers: list[Article], profile):
    """One LLM call. Returns {index: (company_name, relationship)} over the top candidates.
    'buyer' = would purchase the seller's product; 'peer' = sells a competing product
    (a rival); 'other' = neither. This is what keeps a rival's funding round OUT of the
    Potential Customer slot and INTO Competition Outlook."""
    cands = triggers[:12]
    if not cands:
        return {}, cands
    system = (
        f"You are a B2B sales analyst for {profile.company} ({profile.short}), which sells {profile.value_prop} "
        f"Its CUSTOMERS are companies in these buyer industries: {', '.join(profile.industries)}. "
        "For each news signal, classify the company's relationship to the seller:\n"
        "  'buyer' = a company that would BUY the seller's product (a customer in the buyer industries with a "
        "need the product solves)\n"
        "  'peer'  = a company that SELLS a similar/competing product — a RIVAL in the seller's own space "
        "(even if well-funded). A rival's funding/launch is competition, NOT a customer.\n"
        "  'other' = neither.\n"
        "Be strict: if the company does what the seller does, it is 'peer', never 'buyer'.\n"
        "company_name MUST be one specific, real, named COMPANY or organisation from the signal (e.g. 'Medicover', "
        "'HDFC Bank'). Classify as 'other' — never 'buyer' — when the signal is about:\n"
        "  · a sector, market, index or country as a whole with no single company named "
        "('India's banks', 'the healthcare industry', 'IT giants')\n"
        "  · a PERSON — an appointment, promotion, obituary, award or interview. A named individual is never a "
        "company_name.\n"
        "  · a government body, ministry, regulator or political office."
    )
    user = (f"SELLER sells: {profile.value_prop}\nKnown competitors: {', '.join(profile.competitors) or '—'}\n\n"
            f"SIGNALS:\n{_cands_block(cands)}\n\n"
            "Return JSON {\"items\":[{\"index\":<int>,\"company_name\":\"...\",\"relationship\":\"buyer|peer|other\"}]}"
            " — one entry per signal index above.")
    data = llm.chat_json(system, user, max_tokens=600, default={})
    rel: dict[int, tuple[str, str]] = {}
    for it in (data.get("items") or []):
        i = it.get("index")
        if isinstance(i, int) and 0 <= i < len(cands):
            r = (it.get("relationship") or "other").strip().lower()
            r = r if r in ("buyer", "peer", "other") else "other"
            rel[i] = (_clean_frag(it.get("company_name") or "") or cands[i].title[:48], r)
    return rel, cands


# ── 1. POTENTIAL CUSTOMERS — the best BUYERS (never a peer/rival), enriched + written ─
def build_customers(triggers: list[Article], profile, want: int = 2, log=print):
    """Pick up to `want` distinct buyer companies, in composite order. Peers (rivals) are
    never eligible; 'other' fills in only after the buyers run out."""
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
        card = _write_card(art, company, enr, profile)
        card["_sources"] = enr.get("sources_used", [])
        cards.append(card)
        arts.append(art)
    return cards, arts


# ── Card writer ──────────────────────────────────────────────────────────────
def _write_card(article: Article, name: str, enr: dict, profile) -> dict:
    a = article
    ind = _industry_of(a, profile)
    ctx = free_research.context_block(enr)
    fr = f"\nFREE RESEARCH (Wikipedia / recent company news):\n{ctx}\n" if ctx else ""
    src = (f"SIGNAL:\n TITLE: {a.title}\n SOURCE: {a.source} | DATE: {_date_label(a.published)}\n"
           f" SUMMARY: {a.summary[:400]}\n")

    system = (
        f"You are CoherentConnect, a sales-intelligence analyst for {profile.company} ({profile.short}), which "
        f"sells {profile.value_prop} Write a prospect brief for {name}. Ground every claim in the SIGNAL and FREE "
        "RESEARCH; do NOT invent numbers. Only <b>/<i> inline HTML. No angle-bracket placeholders."
    )
    user = (
        f"{src}{fr}\nReturn a JSON object with keys:\n"
        f"  narrative_html — 2 to 4 sentences: what happened, figures if stated, company context from the free "
        f"research, and why it creates a buying need for {profile.short}.\n"
        "     BOLDING RULE — wrap exactly two things in <b>…</b> and nothing else:\n"
        "       (a) the TRIGGER SIGNAL — the event and its figure/date as it appears in the sentence "
        "(e.g. <b>agreed to acquire Medicover's India hospital business for €1.2 billion</b>)\n"
        f"       (b) WHAT {profile.short} CAN DO — the clause naming the need or opening this creates "
        "(e.g. <b>a pressing need for document automation and data extraction to manage the transition</b>)\n"
        "     Leave the connecting context unbolded. Do not bold whole sentences or the company name alone.\n"
        "  why_now — one sentence on why the buying window is open now\n"
        "  who_to_target — 2 to 3 buyer roles\n"
        f"  recommended_action — 1 to 2 sentences: the concrete first outreach move for {profile.short}"
    )
    data = llm.chat_json(system, user, max_tokens=900, default={})
    return {
        "flag": f"Potential Customer · {ind}",
        "company_name": name,
        "narrative_html": _clean_frag(data.get("narrative_html") or "") or a.summary or a.title,
        "left": {"h": "Why now", "v": _clean_frag(data.get("why_now") or "") or "The buying window is open now."},
        "right": {"h": "Who to target", "v": _clean_frag(data.get("who_to_target") or "") or "Head of Corporate Development, VP of Strategy."},
        "action": {"h": "Recommended action", "v": _clean_frag(data.get("recommended_action") or "")},
        # No per-card plan — one plan closes the whole Potential Customers section.
    }


# ── 3. INDUSTRY OUTLOOK — synthesize the industry news we track ───────────────
def synthesize_news(arts: list[Article], profile) -> list[dict]:
    if not arts:
        return []
    system = (
        f"You are a sales-intelligence editor for {profile.company} ({profile.short}). For each signal, explain the "
        "industry shift and what it changes for the seller. Ground in the signal; no invented figures. "
        "Only <b>/<i> inline HTML."
    )
    user = (
        f"SIGNALS:\n{_cands_block(arts)}\n\n"
        "Return a JSON object {\"items\":[ ... ]} with one entry per signal index above. Each entry has keys:\n"
        "  index — integer\n"
        "  headline — punchy, faithful, plain text, no angle brackets\n"
        "  body_html — 2 to 3 sentences on the shift itself and what it changes in the market. Describe the "
        "shift ONLY; do not give advice here and do not write phrases like 'the so what' or 'this means for'.\n"
        f"  action_html — ONE separate sentence, in the imperative, on the move {profile.short} should make off "
        "the back of this shift. Start with a verb (e.g. 'Target …', 'Lead with …', 'Get ahead of …'). Never "
        "begin with 'The so what' or any similar label.\n"
        "Finished prose, never placeholders."
    )
    data = llm.chat_json(system, user, max_tokens=1300, default={})
    items = data.get("items") if isinstance(data, dict) else None
    out: list[dict] = []
    if items:
        for it in items:
            i = it.get("index")
            if not isinstance(i, int) or i < 0 or i >= len(arts):
                continue
            a = arts[i]
            out.append({"headline": _clean_frag(it.get("headline") or "") or a.title,
                        "body_html": _clean_frag(it.get("body_html") or "") or a.summary or a.title,
                        "action_label": f"Where {profile.short} comes in",
                        "action_html": _clean_frag(it.get("action_html") or ""),
                        "source": SIGNAL_ATTRIBUTION, "date": _date_label(a.published), "verified": True})
    if not out:
        for a in arts:
            out.append({"headline": a.title, "body_html": a.summary or a.title,
                        "source": SIGNAL_ATTRIBUTION, "date": _date_label(a.published), "verified": True})
    return out[:3]


# ── Editorial: lede, 3 categorized top-3 lines, 3 section Takes ──────────────
def build_editorial(customers, industry_news, profile) -> dict:
    import json as _json
    market = getattr(profile, "market", "Global") or "Global"
    ctx = {
        "potential_customers": [{"company": c["company_name"], "narrative": _plain(c["narrative_html"]),
                                 "why_now": c["left"]["v"]} for c in customers],
        "industry_headlines": [n["headline"] for n in industry_news],
        "industries_watched": profile.industries[:4],
        "target_market": market,
    }
    system = (
        f"You are CoherentConnect, the autonomous sales-intelligence agent for {profile.company} ({profile.short}), "
        f"which sells {profile.value_prop} Write the editorial framing for today's Daily Signal Brief in a sharp, "
        "confident operator voice. Be specific to the signals; never generic. Never wrap values in angle brackets. "
        'Inline HTML allowed: <b>, <i>, <span class="accent">…</span>.'
    )
    user = (
        f"CONTEXT:\n{_json.dumps(ctx, ensure_ascii=False)}\n\n"
        "Return a JSON object with these keys (finished prose, no angle brackets):\n"
        "  lede_html — 2 to 3 sentences: what CoherentConnect watched overnight across the industries"
        + (f" in {market}" if market != "Global" else "") + " and why today's signals matter. Name industries with "
        f"<b>. You MUST also name the seller, <b>{profile.company}</b>, at least once — say what today's signals "
        f"open up for {profile.company} specifically.\n"
        # Each top-3 line has its own job. Same shape: <b>what happened</b> — em dash — why it matters.
        "  customer_lines — an array with ONE line per company in potential_customers, in the same order. Each: "
        "<b>the company and the trigger event</b>, then an em dash and why it is a live buying trigger RIGHT NOW "
        "(the timing, not the theme). Example shape: "
        "'<b>Acme banks a ~$180M debut round</b> for its lead asset — a live research-buying trigger, closed this week.'\n"
        "  line_industry — one line: <b>the major industry shift</b>, then an em dash and what it resets or "
        "re-prices for buyers across the market. Example shape: "
        "'<b>AI agents move into the core of market research</b> — Meta takes research workflows in-house, "
        "resetting what buyers expect from every provider.'"
    )
    data = llm.chat_json(system, user, max_tokens=900, default={})

    scope = f" in <b>{market}</b>" if market != "Global" else ""
    lede = _clean_frag(data.get("lede_html") or "")
    # The seller's name is required in the lede — if the model dropped it, append the tie-back.
    if lede and profile.company.lower() not in _plain(lede).lower():
        lede += f" Each one is an opening for <b>{profile.company}</b>."
    raw_lines = data.get("customer_lines") if isinstance(data.get("customer_lines"), list) else []
    cust_lines = []
    for i, c in enumerate(customers):
        line = _clean_frag(raw_lines[i]) if i < len(raw_lines) and isinstance(raw_lines[i], str) else ""
        cust_lines.append(line or f"<b>{c['company_name']}</b> — {_plain(c['left']['v'])}")
    return {
        "lede_html": lede or (f"CoherentConnect watched your live source graph across "
                              f"<b>{', '.join(profile.industries[:4])}</b>{scope} overnight. Here are today's "
                              f"highest-signal moves for <b>{profile.company}</b>."),
        "customer_lines": cust_lines,
        "line_industry": _clean_frag(data.get("line_industry") or "") or (industry_news[0]["headline"] if industry_news else ""),
    }


def _plain(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()[:400]


# ── Assemble ─────────────────────────────────────────────────────────────────
def build_brief(scored: list[Article], profile, log=print) -> tuple[dict, dict]:
    now = datetime.now(timezone.utc)

    triggers = [a for a in scored if a.bucket == "trigger" and a.trigger_type]
    industry = [a for a in scored if a.bucket == "industry"] or [a for a in scored if a.bucket == "trigger" and not a.trigger_type]
    log(f"  selecting: {len(triggers)} trigger / {len(industry)} industry eligible")

    # On thin news days the trigger bucket can hold fewer than two usable companies, so the
    # top industry signals join the candidate pool — triage still decides buyer/peer/other.
    pool = triggers + [a for a in industry if a not in triggers]
    pool.sort(key=lambda a: a.composite, reverse=True)
    log("  → [1] Potential Customers ×2: triage buyers → free-enrich → write")
    customers, cust_arts = build_customers(pool, profile, want=2, log=log)

    used = {a.title for a in cust_arts}
    industry_pool = [a for a in industry if a.title not in used]
    theme, themed = cluster.dominant_theme(industry_pool)
    industry_sel = (themed or industry_pool)[:3]
    if theme:
        log(f"  → [2] Industry Outlook: TF-IDF theme = '{theme}' ({len(themed)} signals)")
    log("  → [2] Industry Outlook: synthesize news")
    industry_news = synthesize_news(industry_sel, profile)

    log("  → editorial (lede / top-3 lines)")
    ed = build_editorial(customers, industry_news, profile)

    # Order mirrors the body sections below: customer ×2 → industry.
    top3 = [{"category": "Potential Customer", "html": line} for line in ed["customer_lines"]]
    if industry_news:
        top3.append({"category": "Industry Outlook", "html": ed["line_industry"]})

    _market = getattr(profile, "market", "Global") or "Global"
    brief = {
        "brand": {"wordmark": "CoherentConnect",
                  "issue_label": "Daily Brief",
                  "issue_date": now.strftime("%d %b %Y"), "tagline": profile.tagline},
        "recipient": {"first_name": profile.recipient},
        "meta": {"date_pill": now.strftime("%A, %B ") + str(now.day) + now.strftime(", %Y"), "seller": profile.company},
        "intro": {"lede_html": ed["lede_html"]},
        "top3": top3,
        # 1. Potential Customers (two cards, one section) — one shared action plan closes it
        "potential_customers": customers,
        "customer_plan": {"h": "How CoherentConnect works this",
                          "steps": cc_pitch_plan([c["company_name"] for c in customers])} if customers else None,
        # 2. Industry Outlook — closes with the same fixed CoherentConnect action plan
        "industry_outlook": industry_news,
        "industry_plan": {"h": "How CoherentConnect works this trend", "steps": cc_industry_plan()},
        # closing — the "Inside CoherentConnect" showcase is static in the template
        # SendGrid substitutes this literal string with the real per-recipient
        # unsubscribe URL at send time — ONLY because the "Replacement tag" field
        # in SendGrid's dashboard (Settings > Tracking > Subscription Tracking) is
        # explicitly set to this SAME value, "[unsubscribe]" WITH brackets (per
        # SendGrid's own docs example: href="[unsubscribe]"). This string must
        # match that dashboard field byte-for-byte, or SendGrid will not
        # recognize it and no substitution happens — confirmed by testing that
        # a mismatch (dashboard field empty, or brackets missing on one side)
        # silently leaves the literal text as the href with no error.
        "footer": {"assembled_note": "Assembled & verified by CoherentConnect", "cta_text": "Book a Demo →",
                   "cta_url": DEMO_URL, "site_text": "Visit the Site →", "site_url": SITE_URL,
                   "tagline": profile.tagline, "subline": "Your autonomous sales intelligence agent",
                   "unsubscribe_url": "[unsubscribe]"},
    }
    debug = {
        "customers": [{"company": c["company_name"], "article": a.title, "score": a.composite,
                       "enriched_via": c.get("_sources", [])} for c, a in zip(customers, cust_arts)],
        "industry_theme": theme,
        "counts": {"trigger": len(triggers), "industry": len(industry_news), "customers": len(customers)},
    }
    return brief, debug
