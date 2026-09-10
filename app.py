"""Streamlit frontend — two DIFFERENT newsletters, each in its own top-level tab.

  • CoherentConnect (Outbound)      — type a seller company → outbound prospecting brief
        (Potential Customer / Competition Outlook / Industry Outlook, each + a Coherent Take)
  • Coherent Market Insights (Inbound) — paste a lead who requested a report → nurture brief
        (What's Happening in Your Market / Adjacent Markets / Competitor Watch, each + a Take)

Both share the same free engine (Google-News RSS → score → free-enrich → DeepSeek/OpenAI
synthesis → Jinja render); only the structure, inputs and template differ.

Run:  streamlit run app.py
"""
from __future__ import annotations
import datetime as _dt

import streamlit as st

import config
import geo
import llm
import render
from tenant import Profile
from collect import collect
from score import score_all, eligible
from brief_builder import build_brief
from cmi_brief_builder import build_cmi_brief

st.set_page_config(page_title="CoherentConnect · Newsletters", page_icon="📈", layout="wide")
st.markdown("<h1 style='margin-bottom:2px'>CoherentConnect · Newsletter Studio</h1>"
            "<p style='color:#6C6A62;margin-top:2px'>Two newsletters, one engine. Pick a tab.</p>",
            unsafe_allow_html=True)

TAB_CC, TAB_CMI = st.tabs([
    "📧  CoherentConnect — Outbound prospecting",
    "🏛  Coherent Market Insights — Inbound lead nurture",
])


def _reset_llm(provider):
    llm.PROVIDER = provider
    llm.STATS.update({"deepseek": 0, "openai": 0, "failed": 0, "provider_used": None})


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — CoherentConnect (outbound). Input: a SELLER company.
# ══════════════════════════════════════════════════════════════════════════════
with TAB_CC:
    st.caption("Give a seller company. The engine finds live buying-trigger prospects, a competitor "
               "move, and an industry shift — each with a Coherent Take.")
    with st.form("cc"):
        c1, c2, c3 = st.columns([3, 2, 2])
        company = c1.text_input("Seller company", value="Coherent Market Insights")
        website = c2.text_input("Website (optional)", value="")
        recipient = c3.text_input("Recipient first name", value="Raj")
        c4, c5 = st.columns([2, 2])
        cc_country = c4.selectbox("🌍 Target country", list(config.COUNTRIES.keys()), index=0, key="cc_country")
        cc_provider = c5.radio("LLM provider", ["openai", "deepseek"], index=0, horizontal=True, key="cc_prov")
        cc_go = st.form_submit_button("⚡ Generate outbound brief", type="primary", use_container_width=True)

    if cc_go:
        _reset_llm(cc_provider)
        try:
            country = config.get_country(cc_country)
            market_name = country["name"]
            with st.status("Generating…", expanded=True) as status:
                st.write(f"🔎 Profile for **{company or 'CMI'}** (market: **{market_name}**) …")
                profile = Profile.from_company(company, website, recipient or "there", market_name) \
                    if company.strip() else Profile.cmi_default(market_name)
                st.write(f"→ targets: {', '.join(profile.industries)}")
                st.write(f"📰 Collecting live news ({market_name}) …")
                articles = collect(profile, country)
                if not geo.is_global(country):
                    articles, fb = geo.filter_country(articles, country)
                    st.write(f"→ geo-filter {market_name}: {len(articles)} kept" + ("  ⚠️ loosened" if fb else ""))
                st.write("📊 Scoring (relevancy × freshness × importance) …")
                scored = score_all(articles, profile)
                keep = eligible(scored)
                st.write("✍️ Synthesizing (triage buyers/peers → free-enrich → write) …")
                brief, debug = build_brief(keep or scored, profile, log=lambda m: None)
                status.update(label=f"Done — {llm.STATS.get('provider_used')}", state="complete")
            st.session_state["cc_brief"] = brief
            st.session_state["cc_scored"] = scored[:25]
            st.session_state["cc_debug"] = debug
            st.session_state["cc_profile"] = profile
        except Exception as e:  # noqa: BLE001
            st.error(f"Generation failed: {type(e).__name__}: {e}")

    if "cc_brief" in st.session_state:
        debug = st.session_state["cc_debug"]
        bits = []
        if debug.get("customer"):
            bits.append(f"Customer: {debug['customer']['company']}")
        if debug.get("competition"):
            bits.append(f"Competitor: {debug['competition']['company']}")
        t_nl, t_sig, t_prof = st.tabs(["📧 Newsletter", "📊 Scored signals", "🧬 Inferred profile"])
        with t_nl:
            st.caption(" · ".join(bits))
            html = render.render(st.session_state["cc_brief"], "CoherentConnect")
            st.components.v1.html(html, height=1500, scrolling=True)
            st.download_button("⬇ Download HTML", html, key="dl_cc",
                               file_name=f"coherentconnect_{_dt.date.today():%Y%m%d}.html", mime="text/html")
        with t_sig:
            st.caption(f"composite = {config.SCORING['w_relevancy']}·rel + {config.SCORING['w_freshness']}·fresh "
                       f"+ {config.SCORING['w_importance']}·imp")
            st.dataframe([{"score": a.composite, "rel": a.relevancy, "fresh": a.freshness, "imp": a.importance,
                           "bucket": a.bucket, "trigger": a.trigger_type or "—", "source": a.source,
                           "title": a.title} for a in st.session_state["cc_scored"]],
                         use_container_width=True, hide_index=True)
        with t_prof:
            p = st.session_state["cc_profile"]
            st.write(f"**{p.company}** ({p.short}) · market: {getattr(p,'market','Global')}")
            st.write(f"**Value prop:** {p.value_prop}")
            st.write(f"**Target (buyer) industries:** {', '.join(p.industries)}")
            st.write(f"**Competitors:** {', '.join(p.competitors)}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Coherent Market Insights (inbound). Input: a LEAD who requested a report.
# ══════════════════════════════════════════════════════════════════════════════
with TAB_CMI:
    st.caption("Paste a lead who requested a report/sample. CMI nurtures them with what's moving in "
               "their market, adjacent markets to explore, and what their competitors are up to.")
    with st.form("cmi"):
        d1, d2, d3 = st.columns(3)
        lead_name = d1.text_input("Name", value="Satyen Amin")
        lead_company = d2.text_input("Company", value="ImmunoACT")
        lead_title = d3.text_input("Job title", value="VP Sales and Market Access")
        d4, d5 = st.columns([3, 1])
        report_name = d4.text_input("Report name (the market they requested)", value="Bone Marrow Transplant Market")
        price = d5.text_input("Standard price", value="US $3500")
        report_link = st.text_input("Report link", value="https://www.coherentmarketinsights.com/market-insight/bone-marrow-transplant-market-232")
        objectives = st.text_area("Precise business objectives", value="BMT and CAR-T market research across major countries for lymphoma and leukemia", height=70)
        e1, e2 = st.columns([2, 2])
        cmi_country = e1.selectbox("🌍 Sourcing region", list(config.COUNTRIES.keys()),
                                   index=list(config.COUNTRIES).index("India"), key="cmi_country")
        cmi_provider = e2.radio("LLM provider", ["openai", "deepseek"], index=0, horizontal=True, key="cmi_prov")
        cmi_go = st.form_submit_button("⚡ Generate lead-nurture brief", type="primary", use_container_width=True)

    if cmi_go:
        _reset_llm(cmi_provider)
        lead = {"name": lead_name, "company": lead_company, "job_title": lead_title,
                "report_name": report_name, "report_link": report_link, "price": price, "objectives": objectives}
        try:
            country = config.get_country(cmi_country)
            with st.status("Generating…", expanded=True) as status:
                st.write(f"🔎 Deriving market plan for **{lead_company}** on **{report_name}** …")
                brief, debug = build_cmi_brief(lead, country, log=lambda m: st.write(m))
                status.update(label=f"Done — {llm.STATS.get('provider_used')}", state="complete")
            st.session_state["cmi_brief"] = brief
            st.session_state["cmi_debug"] = debug
        except Exception as e:  # noqa: BLE001
            st.error(f"Generation failed: {type(e).__name__}: {e}")

    if "cmi_brief" in st.session_state:
        debug = st.session_state["cmi_debug"]
        t_nl, t_meta = st.tabs(["📧 Newsletter", "🧭 Plan"])
        with t_nl:
            st.caption(f"Market: {debug['market_name']} · competitors: {', '.join(debug['competitors'])}")
            html = render.render(st.session_state["cmi_brief"], "Coherent Market Insights")
            st.components.v1.html(html, height=1600, scrolling=True)
            st.download_button("⬇ Download HTML", html, key="dl_cmi",
                               file_name=f"cmi_leadbrief_{_dt.date.today():%Y%m%d}.html", mime="text/html")
        with t_meta:
            st.write(f"**Market:** {debug['market_name']}")
            st.write(f"**Competitors tracked:** {', '.join(debug['competitors'])}")
            st.write(f"**Section counts:** {debug['counts']}")
