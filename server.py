"""FastAPI wrapper around the CoherentConnect / CMI newsletter engine.

Exposes the existing collect → score → synthesize → render pipeline as HTTP so the
Next.js studio (newsletter-studio) can request newsletter HTML on demand.

Run:
    pip install -r requirements.txt fastapi "uvicorn[standard]"
    uvicorn server:app --host 127.0.0.1 --port 8000 --reload

Endpoints:
    GET  /health
    POST /generate/coherentconnect   {company, website, country, provider} -> {html, meta}
    POST /generate/cmi               {lead..., country, provider}          -> {html, meta}
"""
from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
import geo
import llm
import render
from tenant import Profile
from collect import collect
from score import score_all, eligible
from brief_builder import build_brief
from cmi_brief_builder import build_cmi_brief

app = FastAPI(title="Coherent Newsletter Engine", version="0.1.0")

# The studio (Next.js) calls this from the server side, but allow browser calls too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _reset_llm(provider: str) -> None:
    llm.PROVIDER = provider
    llm.STATS.update({"deepseek": 0, "openai": 0, "failed": 0, "provider_used": None})


class ConnectRequest(BaseModel):
    company: str = "Coherent Market Insights"
    website: str = ""
    country: str = "Global"
    provider: str = "openai"
    recipient: str = "there"


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "deepseek_key": bool(llm.DEEPSEEK_API_KEY),
        "openai_key": bool(llm.OPENAI_API_KEY),
    }


@app.post("/generate/coherentconnect")
def generate_coherentconnect(req: ConnectRequest) -> dict:
    _reset_llm(req.provider)
    country = config.get_country(req.country)
    market_name = country["name"]

    profile = (
        Profile.from_company(req.company, req.website, req.recipient or "there", market_name)
        if req.company.strip()
        else Profile.cmi_default(market_name)
    )

    articles = collect(profile, country)
    if not geo.is_global(country):
        articles, _fb = geo.filter_country(articles, country)

    scored = score_all(articles, profile)
    keep = eligible(scored)
    brief, debug = build_brief(keep or scored, profile, log=lambda m: None)
    html = render.render(brief, "CoherentConnect")

    return {
        "html": html,
        "meta": {
            "market": market_name,
            "provider_used": llm.STATS.get("provider_used"),
            "customer": (debug.get("customer") or {}).get("company"),
            "competition": (debug.get("competition") or {}).get("company"),
            "signals_scored": len(scored),
        },
    }


class CmiRequest(BaseModel):
    name: str = ""
    company: str = ""
    job_title: str = ""
    report_name: str = ""
    report_link: str = ""
    price: str = ""
    objectives: str = ""
    country: str = "India"
    provider: str = "openai"


@app.post("/generate/cmi")
def generate_cmi(req: CmiRequest) -> dict:
    _reset_llm(req.provider)
    country = config.get_country(req.country)
    lead = req.model_dump()
    brief, debug = build_cmi_brief(lead, country, log=lambda m: None)
    html = render.render(brief, "Coherent Market Insights")
    return {
        "html": html,
        "meta": {
            "market": debug.get("market_name"),
            "provider_used": llm.STATS.get("provider_used"),
            "competitors": debug.get("competitors"),
        },
    }
