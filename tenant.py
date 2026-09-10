"""Tenant (seller) profile — either the CMI default or inferred from any company name.

This generalizes the hardcoded `config.TENANT` so the newsletter can be produced for ANY
seller: given a company name, the LLM infers what they sell, which customer industries they
target, who their competitors are, and the news queries that surface buying-trigger prospects.
Mirrors the mother repo's onboarding "enrich domain" + niche-query-generation step.
"""
from __future__ import annotations
from dataclasses import dataclass, field

import config
import llm


@dataclass
class Profile:
    company: str
    short: str
    recipient: str
    tagline: str
    value_prop: str
    industries: list[str]                       # customer verticals the seller targets
    competitors: list[str]
    industry_keywords: dict[str, list[str]]     # vertical -> relevancy keywords
    trigger_queries: list[str]                  # Google-News queries for prospect triggers
    industry_queries: list[str]                 # structural / industry-trend queries
    market: str = "Global"                      # target country name, or "Global"

    # ---- constructors -------------------------------------------------------
    @classmethod
    def cmi_default(cls, market: str = "Global") -> "Profile":
        t = config.TENANT
        return cls(
            company=t["company"], short=t["short"], recipient=t["recipient_first_name"],
            tagline=t["tagline"], value_prop=t["value_prop"], industries=t["industries"],
            competitors=t["competitors"], industry_keywords=config.INDUSTRY_KEYWORDS,
            trigger_queries=config.TRIGGER_QUERIES, industry_queries=config.INDUSTRY_QUERIES,
            market=market or "Global",
        )

    @classmethod
    def coherentlead_default(cls, market: str = "Global") -> "Profile":
        t = config.COHERENTLEAD_TENANT
        return cls(
            company=t["company"], short=t["short"], recipient=t["recipient_first_name"],
            tagline=t["tagline"], value_prop=t["value_prop"], industries=t["industries"],
            competitors=t["competitors"], industry_keywords=config.COHERENTLEAD_INDUSTRY_KEYWORDS,
            trigger_queries=config.COHERENTLEAD_TRIGGER_QUERIES,
            industry_queries=config.COHERENTLEAD_INDUSTRY_QUERIES,
            market=market or "Global",
        )

    @classmethod
    def from_company(cls, company: str, website: str = "", recipient: str = "there",
                     country_name: str = "") -> "Profile":
        """Infer a full tenant profile from just a company name (LLM), with safe fallbacks.
        If country_name is given, competitors and queries are biased to that market."""
        company = (company or "").strip()
        market = (country_name or "Global").strip() or "Global"
        if not company:
            return cls.cmi_default(market)

        geo_line = (f" The target MARKET is {market}: prefer competitors, keywords and news queries "
                    f"relevant to {market}." if market != "Global" else "")
        system = (
            "You are CoherentConnect, a B2B sales-intelligence engine. Given a SELLER company, infer its "
            "sales-prospecting profile. CRITICAL DISTINCTION: a POTENTIAL CUSTOMER is a company that would BUY "
            "the seller's product — it operates in the seller's CUSTOMER industries (its buyers), NOT in the "
            "seller's OWN product category. A company that sells a similar/competing product is a COMPETITOR, "
            "not a customer. So `target_industries` must be the industries of the seller's BUYERS, never the "
            "seller's own category. Example: an AI waste-management/recycling SaaS sells TO consumer-goods "
            "brands, manufacturers, retailers, packaging firms and municipalities (those are target_industries) "
            "— other 'waste management' or 'recycling platform' companies are its COMPETITORS, never "
            "target_industries. A 'buying trigger' is an event (funding, IPO, M&A, expansion, new plant, product "
            "launch, regulatory/compliance obligation, big hire) at a BUYER that creates demand for what the "
            "seller sells." + geo_line + " Return finished values — never placeholders, never angle brackets."
        )
        user = (
            f"SELLER: {company}\n" + (f"WEBSITE: {website}\n" if website else "") +
            (f"TARGET MARKET: {market}\n" if market != "Global" else "") +
            "\nReturn a JSON object with keys:\n"
            "  value_prop — one sentence: what the seller sells and to whom\n"
            "  target_industries — 4 to 7 CUSTOMER verticals that BUY from the seller (its buyers). Do NOT list "
            "the seller's own product category here.\n"
            f"  competitors — 4 to 8 real companies that SELL a competing/similar product to the seller"
            f"{' active in ' + market if market != 'Global' else ''}\n"
            "  industry_keywords — object mapping each target_industry to a list of 6 to 10 lowercase "
            "keywords/phrases that identify news about companies IN that buyer vertical\n"
            "  trigger_query_seeds — 10 to 14 Google-News queries that surface BUYERS (companies in the "
            "target_industries) with a live buying trigger — combine each buyer vertical with trigger words "
            "(funding, raises, expansion, new plant, launches, compliance, hiring). Do NOT write queries that "
            "surface the seller's competitors.\n"
            "  industry_query_seeds — 5 to 7 Google-News queries for structural/industry-trend stories that "
            "change what the seller's buyers expect"
        )
        data = llm.chat_json(system, user, max_tokens=1500, default={}) or {}

        industries = _as_str_list(data.get("target_industries"))[:7]
        competitors = _as_str_list(data.get("competitors"))[:8]
        ind_kw = data.get("industry_keywords")
        industry_keywords: dict[str, list[str]] = {}
        if isinstance(ind_kw, dict):
            for k, v in ind_kw.items():
                kws = _as_str_list(v)
                if k and kws:
                    industry_keywords[str(k)] = [w.lower() for w in kws]
        trig = _as_str_list(data.get("trigger_query_seeds"))[:14]
        indq = _as_str_list(data.get("industry_query_seeds"))[:7]

        # Fallbacks so the pipeline always has something to search/score.
        if not industries:
            industries = ["Technology", "Healthcare", "Financial Services", "Manufacturing"]
        if not industry_keywords:
            industry_keywords = {i: [i.lower()] for i in industries}
        if not trig:
            trig = [f"{i} company raises funding" for i in industries] + \
                   [f"{i} startup Series B" for i in industries[:3]]
        if not indq:
            indq = [f"{industries[0]} industry trends 2026", f"AI disruption {industries[0]}"]

        short = _short_name(company)
        vp = (data.get("value_prop") or "").strip() or f"{company}'s products and services."
        return cls(
            company=company, short=short, recipient=recipient or "there",
            tagline="Sales intelligence, made coherent.", value_prop=vp,
            industries=industries, competitors=competitors,
            industry_keywords=industry_keywords, trigger_queries=trig, industry_queries=indq,
            market=market,
        )


def _as_str_list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _short_name(company: str) -> str:
    words = [w for w in company.replace(",", " ").split() if w]
    drop = {"inc", "inc.", "llc", "ltd", "ltd.", "corp", "corp.", "co", "co.", "plc", "the"}
    core = [w for w in words if w.lower().strip(".") not in drop]
    if len(core) >= 2 and all(len(w) > 1 for w in core[:3]):
        acr = "".join(w[0] for w in core[:3]).upper()
        if len(acr) >= 2:
            return acr
    return (core[0] if core else company)[:16]
