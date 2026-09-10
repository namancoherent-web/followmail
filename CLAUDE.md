# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A standalone, self-contained distillation of the `sales-agent-draft-` "mother codebase" that
generates B2B sales-intelligence newsletters. No database, no auth — the only paid dependency
is one LLM key (DeepSeek and/or OpenAI). This repo produces **two distinct newsletters** that
share one engine:

- **CoherentConnect (outbound)** — given a seller company, finds live buying-trigger prospects
  and an industry shift (`brief_builder.py`, `run.py`, `templates/daily_brief.html`).
- **Coherent Market Insights / CMI (inbound)** — given a lead who requested a report, produces a
  nurture brief covering their market, adjacent markets, and their competitors
  (`cmi_brief_builder.py`, `templates/daily_brief_cmi.html`).

Every mapping back to the mother repo's modules is documented in the README's "Mapping back to
the mother codebase" table — consult it when porting a fix upstream or downstream.

## Commands

```bash
pip install -r requirements.txt
```

`requirements.txt` only lists the CLI-path deps (`feedparser`, `openai`, `jinja2`,
`python-dotenv`). Several entry points import packages **not** in requirements.txt — install
them manually before running that entry point:
- `app.py`, `newsletter_app.py` need `streamlit`
- `server.py` needs `fastapi` and `uvicorn`
- `emailify.py` / `send_brief.py` need `beautifulsoup4` (`bs4`)
- `cluster.py` optionally uses `scikit-learn` (degrades gracefully if absent)
- `free_research.py` optionally uses `yfinance` (best-effort, skipped if absent/fails)

Keys go in a local `.env` (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `LLM_PROVIDER`); `llm.py` also
auto-reads `../sales-agent-draft-/.env` if run next to the mother repo.

```bash
# CLI: generate one CoherentConnect brief → output/daily_brief_<slug>_<market>_<date>.html
python run.py
python run.py --company "Acme Inc" --website acme.com --recipient Sam --market India
LLM_PROVIDER=openai python run.py

# Streamlit UIs (need `pip install streamlit` first)
streamlit run app.py             # both newsletters, tabbed (CoherentConnect + CMI)
streamlit run newsletter_app.py  # CoherentConnect only, simpler 2-field form

# FastAPI HTTP wrapper for both pipelines (need `pip install fastapi "uvicorn[standard]"`)
uvicorn server:app --host 127.0.0.1 --port 8000 --reload
# POST /generate/coherentconnect  {company, website, country, provider} -> {html, meta}
# POST /generate/cmi              {lead fields..., country, provider}   -> {html, meta}
# GET  /health

# Diagnostics: verify API keys are present (booleans only) + RSS/DeepSeek reachability
python probe.py

# Convert a rendered brief to email-safe HTML and send it (needs SMTP_USER / SMTP_APP_PASSWORD env vars)
python send_brief.py output/daily_brief_et_india_20260806.html you@example.com
```

There is no test suite, linter, or build step configured in this repo.

## Architecture

Both newsletters run the same five-stage pipeline; only the queries, selection logic, prompts,
and template differ.

```
collect.py        Google News RSS (parallel fetch, SHA-256 fingerprint dedup, lookback window)
score.py          composite = 0.40·relevancy + 0.25·freshness + 0.35·importance
brief_builder.py / cmi_brief_builder.py
                  select signals → LLM synthesis (DeepSeek→OpenAI) → assemble the `brief` dict
render.py         Jinja2 → templates/*.html → output/*.html
```

**config.py** is the single source of truth for tenant defaults (the hardcoded CMI profile),
the industry-keyword lexicon, the trigger-event taxonomy + weights, the `COUNTRIES` locale/geo
table, research-firm blocklist, and `SCORING` weights. Read this file first when a score or
selection looks wrong.

**tenant.py (`Profile`)** generalizes the hardcoded `config.TENANT`: `Profile.cmi_default()`
uses the static CMI config; `Profile.from_company()` calls the LLM once to infer an arbitrary
seller's value prop, buyer industries, competitors, and query seeds. The critical distinction
the inference prompt enforces: a **customer** buys the seller's product (operates in the
seller's *buyer* industries); a **competitor** sells something similar — these must never be
conflated, and this same buyer-vs-peer distinction reappears in `brief_builder.triage_triggers`.

**collect.py** fires all trigger/industry/competitor queries in parallel
(`ThreadPoolExecutor`), tags each `Article` with a `bucket` (`trigger`/`industry`/`competitor`),
and dedupes by a title+URL fingerprint — preferring the `trigger` bucket on collision. Google
News locale (`hl`/`gl`/`ceid`) and a country-name query suffix come from `config.COUNTRIES`.
`geo.py` then hard-filters articles to the target country by matching aliases/cities/
currency/outlets/TLD in the text — but falls back to the unfiltered set if too few match
(`geo.MIN_KEEP`), since an empty brief is worse than off-country dilution.

**score.py** computes three independent `[0,1]` axes per article — `relevancy` (saturating
keyword overlap with `industry_keywords`, with a bucket-based floor so trigger/industry-bucket
articles aren't zeroed out by a narrow LLM-inferred lexicon), `freshness` (piecewise decay by
hours-old), `importance` (best-matching `TRIGGER_TYPES` weight + a money-scale boost) — then
combines them into `composite` via `config.SCORING` weights. Anything below `min_composite` is
dropped by `eligible()`.

**brief_builder.py** (CoherentConnect): triages trigger articles into buyer/peer/other via one
LLM call (`triage_triggers`) so a rival's funding round never lands in "Potential Customer";
picks up to 2 buyer companies, enriches each with `free_research.py`, and writes a card per
company. Industry Outlook signals are clustered by `cluster.py` (free TF-IDF+KMeans, no
embeddings) to pick a dominant theme before synthesis. The "Approach plan" / "How CoherentConnect
works this" blocks are **fixed, non-LLM copy** (`cc_pitch_plan`, `cc_industry_plan`) — do not
try to make the LLM write them. Editorial framing (lede + top-3 lines) is a separate, final LLM
call (`build_editorial`) that stitches together the already-written cards/sections.

**cmi_brief_builder.py** (CMI): completely different structure — driven by a lead dict (name,
company, requested report, objectives), not a seller profile. `derive_context()` (1 LLM call)
plans the market to track, adjacent cross-sell markets, and the lead's own competitors.
`config.RESEARCH_FIRM_SOURCES` / `is_research_pr()` strip out rival market-research firms and
generic "market size/forecast" PR from collected articles — CMI must never cite or quote a
competing research firm's numbers; all figures are framed as CMI's own estimates. The `VOICE`
system-prompt block encodes a deliberately human, non-AI-sounding house style (varied sentence
length, no "not X, but Y" reversals, no three-item list rhythm, no em-dash-as-connector, etc.) —
reuse/extend `VOICE` rather than writing a new style block if you add more CMI prose generation.

**llm.py**: DeepSeek-first, OpenAI-fallback chat wrapper. Both providers go through the `openai`
SDK (DeepSeek is OpenAI-API-compatible via a custom `base_url`). Order is controlled by
`LLM_PROVIDER` env var / `config.LLM["provider"]`; a failed call transparently falls through to
the next provider. `llm.STATS` tracks which provider actually served each run. `chat_json()`
tolerates ```json-fenced responses and returns a caller-supplied `default` dict on any
parse/call failure — **every LLM call in this codebase is expected to degrade gracefully to
source-derived text**, never raise and break the pipeline.

**render.py**: `render()` accepts either a display name (`"CoherentConnect"` /
`"Coherent Market Insights"`, mapped via `TEMPLATES`) or a raw template filename, and renders
the assembled `brief` dict through Jinja2 with autoescape on. Template changes to
`templates/daily_brief.html` or `templates/daily_brief_cmi.html` must stay in sync with the
dict shape assembled at the bottom of `brief_builder.build_brief` / `cmi_brief_builder.build_cmi_brief`
respectively — there's no schema validation between them.

**emailify.py**: converts a rendered browser HTML brief into email-client-safe HTML (nested
tables, inlined literal colors, no CSS custom properties/flexbox/grid/SVG) because Outlook and
friends discard the browser template's styling. It parses by CSS class, so it must be kept in
sync with `templates/daily_brief.html`'s class names — anything it doesn't recognize is silently
skipped rather than half-rendered.

`server.py` and the two Streamlit apps (`app.py`, `newsletter_app.py`) are thin wrappers around
the same `collect → score → build_brief/build_cmi_brief → render` calls used by `run.py` — when
changing pipeline behavior, check whether all four entry points need the update.

`probe.py`, `_render_recyclify_preview.py`, `output/*.html` are diagnostic/one-off scripts and
generated artifacts, not part of the pipeline proper.
