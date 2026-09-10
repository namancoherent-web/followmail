"""Streamlit app — type a recipient name and a company, get the CoherentConnect newsletter.

The whole pipeline behind `run.py`, driven from a two-field form:

    name + company  →  infer tenant profile  →  collect live news  →  score
                    →  LLM synthesis  →  Jinja render  →  preview / download

Run:  streamlit run newsletter_app.py
"""
from __future__ import annotations

import datetime as _dt
import re

import streamlit as st

import config
import geo
import llm
import render
from tenant import Profile
from collect import collect
from score import score_all, eligible
from brief_builder import build_brief

st.set_page_config(page_title="CoherentConnect · Newsletter", page_icon="📧", layout="wide")

st.markdown(
    "<h1 style='margin-bottom:2px'>CoherentConnect · Daily Brief</h1>"
    "<p style='color:#6C6A62;margin-top:2px'>Name the recipient and their company. "
    "The engine does the rest — live signals, two prospects, an industry read.</p>",
    unsafe_allow_html=True,
)

with st.form("brief"):
    c1, c2 = st.columns(2)
    name = c1.text_input("Recipient first name", value="", placeholder="Chetan")
    company = c2.text_input("Company", value="", placeholder="Elansol Technologies")

    with st.expander("Options"):
        o1, o2, o3 = st.columns(3)
        website = o1.text_input("Website (optional)", value="", placeholder="https://www.elansol.com")
        market = o2.selectbox("Target market", list(config.COUNTRIES.keys()), index=0)
        provider = o3.radio("LLM provider", ["deepseek", "openai"], index=0, horizontal=True)

    go = st.form_submit_button("⚡ Generate newsletter", type="primary", use_container_width=True)

if go:
    if not company.strip():
        st.warning("Enter a company — it's what the whole brief is built for.")
        st.stop()

    llm.PROVIDER = provider
    llm.STATS.update({"deepseek": 0, "openai": 0, "failed": 0, "provider_used": None})
    country = config.get_country(market)
    market_name = country["name"]

    try:
        with st.status("Generating…", expanded=True) as status:
            st.write(f"🔎 Inferring the profile for **{company}** (market: **{market_name}**) …")
            profile = Profile.from_company(company, website, name.strip() or "there", market_name)
            st.write(f"→ buyer industries: {', '.join(profile.industries)}")

            st.write(f"📰 Collecting live news ({market_name} edition) …")
            articles = collect(profile, country)
            if not articles:
                raise RuntimeError("No articles collected — check the network connection.")
            if not geo.is_global(country):
                articles, loosened = geo.filter_country(articles, country)
                st.write(f"→ geo-filter {market_name}: {len(articles)} kept"
                         + ("  ⚠️ too few matched, kept all" if loosened else ""))

            st.write("📊 Scoring (relevancy × freshness × importance) …")
            scored = score_all(articles, profile)
            keep = eligible(scored)
            st.write(f"→ {len(keep)}/{len(scored)} above the cut")

            st.write("✍️ Writing (triage buyers → free research → synthesis) …")
            brief, debug = build_brief(keep or scored, profile, log=lambda m: None)

            status.update(label=f"Done — served by {llm.STATS.get('provider_used')}", state="complete")

        st.session_state["brief"] = brief
        st.session_state["debug"] = debug
        st.session_state["profile"] = profile
        st.session_state["scored"] = scored[:25]
    except Exception as exc:  # noqa: BLE001
        st.error(f"Generation failed — {type(exc).__name__}: {exc}")

if "brief" in st.session_state:
    brief, debug, profile = (st.session_state[k] for k in ("brief", "debug", "profile"))
    html = render.render(brief, "CoherentConnect")

    picked = " · ".join(f"{c['company']} ({c['score']:.2f})" for c in debug.get("customers") or [])
    st.caption(f"Prospects: {picked or '—'}   |   industry theme: {debug.get('industry_theme') or '—'}")

    slug = re.sub(r"[^a-z0-9]+", "-", (profile.short or "brief").lower()).strip("-")
    st.download_button("⬇ Download HTML", html, type="primary",
                       file_name=f"daily_brief_{slug}_{_dt.date.today():%Y%m%d}.html", mime="text/html")

    tab_view, tab_signals, tab_profile = st.tabs(["📧 Newsletter", "📊 Signals", "🧬 Inferred profile"])
    with tab_view:
        st.components.v1.html(html, height=1600, scrolling=True)
    with tab_signals:
        st.caption(f"composite = {config.SCORING['w_relevancy']}·relevancy "
                   f"+ {config.SCORING['w_freshness']}·freshness + {config.SCORING['w_importance']}·importance")
        st.dataframe([{"score": a.composite, "rel": a.relevancy, "fresh": a.freshness, "imp": a.importance,
                       "bucket": a.bucket, "trigger": a.trigger_type or "—", "source": a.source,
                       "title": a.title} for a in st.session_state["scored"]],
                     use_container_width=True, hide_index=True)
    with tab_profile:
        st.write(f"**{profile.company}** ({profile.short}) · market: {profile.market}")
        st.write(f"**Sells:** {profile.value_prop}")
        st.write(f"**Buyer industries:** {', '.join(profile.industries)}")
        st.write(f"**Competitors:** {', '.join(profile.competitors) or '—'}")
