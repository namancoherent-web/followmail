"""CoherentConnect Daily Signal Brief — standalone generator.

Pipeline (a distilled version of the mother codebase's algorithm):
    collect (Google News RSS)  →  score (relevancy x freshness x importance)
      →  select + LLM synthesis (DeepSeek→OpenAI)  →  render (Jinja template)

Usage:
    python run.py                 # live run, writes output/daily_brief_<date>.html
    LLM_PROVIDER=openai python run.py
"""
from __future__ import annotations
import os
import sys
from datetime import datetime, timezone

# Windows consoles default to cp1252 and choke on ·/→/✓ — force UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import re

import config
import geo
import llm
import render
from tenant import Profile
from collect import collect
from score import score_all, eligible
from brief_builder import build_brief


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a CoherentConnect Daily Signal Brief.")
    ap.add_argument("--company", default="", help="Seller company to generate the brief FOR (default: CMI)")
    ap.add_argument("--website", default="", help="Optional seller website")
    ap.add_argument("--recipient", default="", help="Recipient first name")
    ap.add_argument("--market", default="Global", help="Target country (e.g. India, United States, Global)")
    args = ap.parse_args()

    country = config.get_country(args.market)
    market_name = country["name"]

    if args.company:
        print(f"Inferring tenant profile for: {args.company}  (market: {market_name}) …")
        profile = Profile.from_company(args.company, args.website, args.recipient or "there", market_name)
    else:
        profile = Profile.cmi_default(market_name)

    print(f"CoherentConnect · Daily Signal Brief — {profile.company}  [{market_name}]")
    print(f"  targets: {', '.join(profile.industries)}")
    print(f"  competitors: {', '.join(profile.competitors) or '—'}")
    print(f"LLM provider order: {llm.PROVIDER} first"
          f"{' (→ OpenAI fallback)' if config.LLM['fallback_to_openai'] else ''}")
    print(f"  deepseek key: {bool(llm.DEEPSEEK_API_KEY)} | openai key: {bool(llm.OPENAI_API_KEY)}")

    print(f"\n[1/4] Collecting live news (Google News RSS, {market_name} edition)…")
    articles = collect(profile, country)
    print(f"      {len(articles)} unique articles in the last {config.LOOKBACK_HOURS}h")
    if not articles:
        print("      No articles collected (network?). Aborting.")
        return 1
    if not geo.is_global(country):
        kept, fallback = geo.filter_country(articles, country)
        print(f"      geo-filter → {market_name}: kept {len(kept)}/{len(articles)}"
              f"{'  (too few matched — kept all)' if fallback else ''}")
        articles = kept

    print("[2/4] Scoring (relevancy × freshness × importance)…")
    scored = score_all(articles, profile)
    keep = eligible(scored)
    print(f"      {len(keep)}/{len(scored)} passed min composite {config.SCORING['min_composite']}")
    print("      top 5 signals:")
    for a in scored[:5]:
        print(f"        {a.composite:.3f}  rel={a.relevancy:.2f} fr={a.freshness:.2f} imp={a.importance:.2f}"
              f"  [{a.bucket}/{a.trigger_type or '-'}]  {a.title[:70]}")

    print("[3/4] Building brief (LLM synthesis)…")
    brief, debug = build_brief(keep or scored, profile)
    for n, d in enumerate(debug.get("customers") or [], 1):
        via = ", ".join(d.get("enriched_via", [])) or "none"
        print(f"      Potential Customer {n}: {d['company']}  ({d['score']})  [free-research: {via}]  ← {d['article'][:48]}")
    if debug.get("industry_theme"):
        print(f"      Industry Outlook theme (TF-IDF): {debug['industry_theme']}")
    print(f"      llm calls served by: {llm.STATS}")

    print("[4/4] Rendering…")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    slug = re.sub(r"[^a-z0-9]+", "-", (profile.short or "cmi").lower()).strip("-")
    mslug = re.sub(r"[^a-z0-9]+", "-", market_name.lower()).strip("-")
    out = os.path.join(os.path.dirname(__file__), "output", f"daily_brief_{slug}_{mslug}_{stamp}.html")
    render.render_to_file(brief, out)
    print(f"\n✓ Newsletter written: {out}")
    print(f"  provider actually used for LLM: {llm.STATS.get('provider_used')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
