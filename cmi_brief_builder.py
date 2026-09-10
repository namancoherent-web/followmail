"""Coherent Market Insights — INBOUND LEAD-NURTURE brief.

Completely different newsletter from CoherentConnect. Input is a lead who requested a
report/sample (name, company, job title, the report/market they asked about, their stated
objective). CMI nurtures them toward purchase with three sections:

  1) WHAT'S HAPPENING IN YOUR MARKET     — live news in the market they requested
  2) OTHER MARKETS THAT MIGHT INTEREST YOU — adjacent markets to cross-sell (LLM-derived)
  3) WHAT YOUR COMPETITORS ARE UP TO      — moves by the LEAD COMPANY's competitors

Each section is followed by a Coherent Take. Reuses the same free engine (Google-News RSS
collection, free enrichment, DeepSeek→OpenAI synthesis) — only the framing/structure differs.
"""
from __future__ import annotations
from datetime import datetime, timezone

import config
import geo
import llm
from collect import Article, collect_queries
from brief_builder import _clean_frag, _date_label   # shared helpers


# ── House voice ──────────────────────────────────────────────────────────────
# Appended to every system prompt that generates reader-facing prose. The goal is
# not "less formal" — it is prose that reads like one named analyst wrote it for
# one named person, instead of prose assembled by a model.
VOICE = """
WHO YOU ARE
You are a senior analyst at CMI. You have covered this sector for about ten years.
You have sat in the rooms where these decisions get made, you have been wrong before
and remember it, and you are writing a short note to one person you would happily
meet for coffee. You are not addressing "the market" or "stakeholders". You are
telling one competent professional the thing you would tell them across a table.

HOW YOU WRITE
- Vary sentence length hard. Some sentences run four words. Others carry a clause,
  then a qualification, then land. Uniform rhythm is the single clearest tell that
  no human wrote something.
- Commit to claims. "This is the constraint" beats "this may potentially represent
  a key consideration". If you are genuinely unsure, say you are unsure and why —
  hedging language is not the same as honesty about uncertainty.
- Use ordinary words. Leverage, utilize, robust, seamless, landscape, ecosystem,
  navigate, unlock, delve, tapestry, testament, crucial, pivotal, realm — none of
  these. Say use, strong, area, important.
- One idea per paragraph, and let it end when it is finished. Do not close every
  paragraph on a neat aphorism or a reversal. Sometimes a paragraph just stops.

WHAT TO AVOID (these are the tells)
- The "not X, but Y" reversal, and its cousins "isn't just X, it's Y" / "the
  question isn't X, it's Y". Powerful once. Used twice in a document, it reads
  synthetic. Limit: at most one per brief, ideally zero.
- Three-item lists as the default rhythm ("faster, cheaper and more reliable").
  Real writers use two items, or four, or an ordinary sentence.
- Em-dashes as the universal connector. Use full stops, commas, and occasionally
  a semicolon or a colon.
- Opening on the subject's importance ("The X market is undergoing rapid
  transformation"). Start with the specific thing that happened.
- Empty summary closers ("This highlights the importance of..."). If the paragraph
  did its job, the reader already knows.
- Bold used for emphasis on ordinary phrases. Bold marks a company, a figure, or a
  term of art. Nothing else.

WHAT GOOD LOOKS LIKE
Specific over general. Concrete nouns. Numbers where you have them, and no numbers
where you do not. A reader who knows this sector should finish a paragraph thinking
"yes, that is right, and I had not put it that way" — not "that sounds like a
report".
"""


def _drop_research_pr(arts: list[Article]) -> list[Article]:
    """Remove rival market-research firms + generic market-report PR. CMI must never quote a
    competitor's numbers; all figures in the brief are presented as CMI's own."""
    return [a for a in arts if not config.is_research_pr(a.source, a.title)]


def _collect_with_fallback(queries: list[str], country: dict, bucket: str) -> list[Article]:
    """Market/competitor news is inherently global — if the chosen country edition is thin,
    top up from the Global edition. Research-firm PR is filtered out."""
    arts = _drop_research_pr(collect_queries(queries, country, bucket))
    if len(arts) < 4 and not geo.is_global(country):
        seen = {a.fingerprint for a in arts}
        arts += [a for a in _drop_research_pr(collect_queries(queries, config.COUNTRIES["Global"], bucket))
                 if a.fingerprint not in seen]
        arts.sort(key=lambda x: x.published, reverse=True)
    return arts


# ── Derive the intelligence plan from the lead (1 LLM call) ──────────────────
def derive_context(lead: dict) -> dict:
    company = lead.get("company", "")
    report = lead.get("report_name", "")
    objective = lead.get("objectives", "")
    title = lead.get("job_title", "")
    system = (
        "You are Coherent Market Insights (CMI), a global market-research firm. A lead has requested a "
        "report/sample. Plan a personalized market-intelligence brief for them. Identify: the market they "
        "care about, news queries to surface what's moving in it, ADJACENT markets CMI could cross-sell, and "
        "the LEAD COMPANY's competitors (companies that compete with the lead's own company) plus queries to "
        "track them. Be precise and industry-accurate. No placeholders, no angle brackets."
    )
    user = (
        f"LEAD COMPANY: {company}\nLEAD TITLE: {title}\nREQUESTED REPORT / MARKET: {report}\n"
        f"STATED OBJECTIVE: {objective}\n\n"
        "Return a JSON object with keys:\n"
        "  market_name — the canonical market name the lead cares about\n"
        "  market_queries — 6 Google-News queries about REAL EVENTS in this space (clinical trials, drug "
        "approvals, regulatory decisions, deals/partnerships, product launches, funding) — NOT 'market size' "
        "or 'forecast' queries (those only surface rival market-research reports). Combine the therapy/market "
        "with event words like trial, approval, FDA, launch, deal, partnership, breakthrough.\n"
        "  adjacent_markets — 4 objects {\"market_name\": \"...\", \"growth_tag\": \"a 1-2 word CMI growth "
        "descriptor, e.g. 'High-growth', 'Fast-growing', 'Emerging', 'Expanding', 'Established'\", "
        "\"why_relevant\": \"1-2 sentences tying this market to the lead's objective and strategy\"} — related "
        "markets CMI also publishes on. Do NOT cite external firms or reproduce outside numbers.\n"
        "  competitor_company — the lead's own company (echo it back)\n"
        "  competitors — 5 real companies that COMPETE with the lead's company in its space\n"
        "  competitor_queries — 5 Google-News queries to track those competitors' moves"
    )
    data = llm.chat_json(system, user, max_tokens=900, default={}) or {}
    return {
        "market_name": _clean_frag(data.get("market_name") or "") or report or "your market",
        "market_queries": _list(data.get("market_queries"))[:6] or [report, f"{report} market growth"],
        "adjacent_markets": [
            {"market_name": _clean_frag(x.get("market_name", "")),
             "growth_tag": _clean_frag(x.get("growth_tag", "")) or "Growing",
             "why_relevant": _clean_frag(x.get("why_relevant", ""))}
            for x in (data.get("adjacent_markets") or []) if isinstance(x, dict) and x.get("market_name")
        ][:4],
        "competitors": _list(data.get("competitors"))[:5],
        "competitor_queries": _list(data.get("competitor_queries"))[:5] or _list(data.get("competitors"))[:5],
    }


def _list(v):
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [v.strip()] if isinstance(v, str) and v.strip() else []


# ── Synthesize a news section (market or competitor) — 1 LLM call ────────────
def _synth_section(arts: list[Article], kind: str, ctx: dict, lead: dict) -> list[dict]:
    if not arts:
        return []
    if kind == "market":
        frame = (f"what's moving in the {ctx['market_name']} that the lead ({lead.get('company','')}) is "
                 "researching. End each with why it matters for their decision.")
    else:
        frame = (f"what {lead.get('company','')}'s competitors are doing and what it means for the lead. "
                 "Name the competitor.")
    system = (
        "You are a market-research analyst at Coherent Market Insights (CMI) writing for a prospective client "
        f"in a professional, authoritative, analytical voice. For each signal, write ONE tight paragraph (2-3 "
        f"sentences) about {frame} "
        "CRITICAL RULES — this brief is CMI's OWN proprietary intelligence:\n"
        "• NEVER name, cite, or attribute anything to another market-research firm (e.g. Grand View, Fortune "
        "Business Insights, MarketsandMarkets, Precedence, Mordor, IMARC, openPR, GlobeNewswire, etc.).\n"
        "• NEVER reproduce another firm's market-size or forecast number. If you state a market size or growth "
        "rate, frame it as CMI's own estimate ('CMI estimates…', 'our research indicates…') or keep it "
        "directional and point to the full CMI report for exact figures.\n"
        "• Rewrite the 'headline' as a concise CMI market insight — do NOT echo a report title or a source name.\n"
        "• Do not invent event facts. Only <b>/<i> inline HTML."
        + VOICE
    )
    user = (f"SIGNALS (report the underlying development in CMI's own words; ignore the publisher):\n" + "\n".join(
        f"[{i}] {a.title}\n    {a.summary[:260]}" for i, a in enumerate(arts)) +
        "\n\nReturn JSON {\"items\":[{\"index\":<int>,\"headline\":\"a CMI market insight, plain text\","
        "\"body_html\":\"the paragraph\"}]} — one entry per index. Finished prose, no angle brackets, no source names.")
    data = llm.chat_json(system, user, max_tokens=1200, default={})
    out = []
    for it in (data.get("items") or []):
        i = it.get("index")
        if isinstance(i, int) and 0 <= i < len(arts):
            a = arts[i]
            out.append({"headline": _clean_frag(it.get("headline") or "") or a.title,
                        "body_html": _clean_frag(it.get("body_html") or "") or a.summary or a.title,
                        "source": a.source, "date": _date_label(a.published), "verified": True})
    if not out:
        out = [{"headline": a.title, "body_html": a.summary or a.title, "source": a.source,
                "date": _date_label(a.published), "verified": True} for a in arts[:3]]
    return out[:3]


# ── Editorial: lede + 3 section Takes (1 LLM call) ───────────────────────────
def _editorial(lead: dict, ctx: dict, market_news, competitor_news) -> dict:
    import json as _json
    payload = {
        "lead_first_name": lead.get("first_name", "there"), "lead_company": lead.get("company", ""),
        "requested_report": lead.get("report_name", ""), "objective": lead.get("objectives", ""),
        "market_name": ctx["market_name"],
        "market_headlines": [n["headline"] for n in market_news],
        "adjacent_markets": [a["market_name"] for a in ctx["adjacent_markets"]],
        "competitor_headlines": [n["headline"] for n in competitor_news],
    }
    system = (
        "You are Coherent Market Insights (CMI), a global market-research firm, writing a personalized "
        "intelligence brief to a lead who requested a report sample. Voice: professional, authoritative, "
        "analytical, helpful — you are demonstrating depth to earn the purchase. "
        "CRITICAL: every number is CMI's OWN. NEVER name or cite another market-research firm. Any market "
        "size / growth / CAGR figure must be framed as CMI's own estimate ('CMI estimates…', 'per our "
        "research…') or kept directional, pointing to the full CMI report for exact numbers. Never attribute a "
        "figure to an outside source. Never wrap values in angle brackets. Inline HTML allowed: <b>, <i>, "
        '<span class="accent">…</span>.'
        + VOICE
    )
    user = (
        f"CONTEXT:\n{_json.dumps(payload, ensure_ascii=False)}\n\n"
        "Return a JSON object (finished prose, no angle brackets) with keys:\n"
        "  lede_html — 2-3 sentences to the lead by name: acknowledge the report they requested and their "
        "objective, and set up the three things below. Name the market with <b>.\n"
        "  take_market — 3-4 sentences of sharp analysis of the market's direction and what it means for the lead.\n"
        "  take_adjacent — 2-3 sentences on why the adjacent markets matter to their strategy.\n"
        "  take_competitors — 3-4 sentences on the competitive picture and where the lead should focus.\n"
        "  top3 — array of exactly 3 short one-liners summarizing, in order: (1) their market, (2) an adjacent "
        "opportunity, (3) a competitor move."
    )
    data = llm.chat_json(system, user, max_tokens=1400, default={})

    def take(k):
        v = _clean_frag(data.get(k) or "")
        return {"body_html": v} if v else None
    top3 = [_clean_frag(x) for x in (data.get("top3") or [])][:3]
    return {
        "lede_html": _clean_frag(data.get("lede_html") or "") or (
            f"Hi {lead.get('first_name','there')} — since you're evaluating our <b>{ctx['market_name']}</b> "
            "report, here's what's moving in your space right now."),
        "take_market": take("take_market"),
        "take_adjacent": take("take_adjacent"),
        "take_competitors": take("take_competitors"),
        "top3": top3,
    }


# ── Assemble ─────────────────────────────────────────────────────────────────
def build_cmi_brief(lead: dict, country: dict | None = None, log=print) -> tuple[dict, dict]:
    now = datetime.now(timezone.utc)
    country = country or config.COUNTRIES["Global"]
    lead = dict(lead)
    lead["first_name"] = (lead.get("name", "") or "there").split()[0]

    log("  → deriving market plan (LLM)")
    ctx = derive_context(lead)
    log(f"    market: {ctx['market_name']} | adjacent: {len(ctx['adjacent_markets'])} | competitors: {', '.join(ctx['competitors']) or '—'}")

    log("  → collecting market news")
    market_arts = _collect_with_fallback(ctx["market_queries"], country, "market")
    log(f"    {len(market_arts)} market articles")
    log("  → collecting competitor news")
    # widen coverage: LLM competitor queries + plain competitor names
    comp_queries = list(dict.fromkeys(ctx["competitor_queries"] + ctx["competitors"]))
    comp_arts = _collect_with_fallback(comp_queries, country, "competitor")
    log(f"    {len(comp_arts)} competitor articles")

    log("  → synthesizing sections (LLM)")
    market_news = _synth_section(market_arts[:6], "market", ctx, lead)
    competitor_news = _synth_section(comp_arts[:6], "competitor", ctx, lead)
    ed = _editorial(lead, ctx, market_news, competitor_news)

    top3 = []
    cats = ["Your Market", "Adjacent Market", "Competitor Move"]
    for i, line in enumerate(ed["top3"]):
        if line:
            top3.append({"category": cats[i] if i < len(cats) else "", "html": line})

    brief = {
        "brand": {"wordmark": "COHERENT", "issue_label": "Market Signal Brief",
                  "issue_date": now.strftime("%d %b %Y"), "tagline": "Empowering businesses with data and analytics."},
        "recipient": {"first_name": lead["first_name"]},
        "meta": {"date_pill": now.strftime("%A, %B ") + str(now.day) + now.strftime(", %Y")},
        "lead": lead,
        "requested_report": {"name": lead.get("report_name", ""), "link": lead.get("report_link", "#"),
                             "price": lead.get("price", ""), "objective": lead.get("objectives", "")},
        "intro": {"lede_html": ed["lede_html"]},
        "top3": top3,
        "your_market": {"market_name": ctx["market_name"], "stories": market_news, "take": ed["take_market"]},
        "adjacent_markets": {"entries": ctx["adjacent_markets"], "take": ed["take_adjacent"]},
        "competitor_watch": {"company": lead.get("company", ""), "stories": competitor_news, "take": ed["take_competitors"]},
        "footer": {"cta_text": "Get the full report →", "cta_url": lead.get("report_link", "#"),
                   "report_name": lead.get("report_name", ""), "price": lead.get("price", "")},
    }
    debug = {"market_name": ctx["market_name"], "competitors": ctx["competitors"],
             "counts": {"market": len(market_news), "adjacent": len(ctx["adjacent_markets"]),
                        "competitor": len(competitor_news)}}
    return brief, debug
