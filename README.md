# CoherentConnect — Daily Signal Brief (standalone newsletter generator)

A self-contained distillation of the CoherentConnect (`sales-agent-draft-`) algorithm that
generates the **Daily Signal Brief** newsletter for a single tenant (Coherent Market Insights).
No database, no auth, no paid APIs required beyond one LLM key.

## Pipeline

```
collect.py   Google News RSS  →  trigger / industry / competitor queries, fingerprint-deduped
score.py     SCORING MATRIX: composite = 0.40·relevancy + 0.25·freshness + 0.35·importance
brief_builder.py  select top signals  →  DeepSeek/OpenAI synthesis (prospect card, news,
                  Coherent Takes, lede, top-3)
render.py    Jinja2 → templates/daily_brief.html  →  output/daily_brief_<date>.html
```

### The scoring matrix (`score.py`)
Every candidate signal is scored on three independent axes in `[0,1]`:
- **relevancy** — saturating keyword overlap with CMI's coverage verticals (`INDUSTRY_KEYWORDS`); +boost if it spans 2+ verticals.
- **freshness** — piecewise recency decay (≤24h → 1.0, ≤48h → 0.85, ≤72h → 0.65, ≤96h → 0.45, ≤7d → 0.25, else 0.10).
- **importance** — the trigger-event weight (`TRIGGER_TYPES`: funding 0.95, IPO 0.92, trial 0.90, approval 0.85, M&A 0.88, expansion 0.72, …) + a money-scale boost for billion/hundred-million figures.

Composite = weighted sum; anything below `SCORING.min_composite` (0.18) is dropped. The highest-scored
**trigger** becomes "Today's Top Prospect"; top **industry** and **competitor** signals fill their sections.

## LLM provider
DeepSeek-first (as requested), OpenAI fallback. DeepSeek is OpenAI-API-compatible, so both use the
`openai` SDK; DeepSeek just sets `base_url=https://api.deepseek.com`. If a DeepSeek call fails (e.g.
`402 Insufficient Balance`), it transparently falls back to OpenAI. Switch the order with
`LLM_PROVIDER=deepseek|openai`.

## Run
```bash
pip install -r requirements.txt
# keys: put DEEPSEEK_API_KEY / OPENAI_API_KEY in .env  (or it auto-reads ../sales-agent-draft-/.env)
python run.py
# → output/daily_brief_<YYYYMMDD>.html
```

## Files
| File | Role |
|---|---|
| `config.py` | CMI tenant profile, industry lexicon, trigger taxonomy, feeds, **scoring weights** |
| `collect.py` | Google News RSS collection + fingerprint dedup (from `trends/collector.py`) |
| `score.py` | the relevancy × freshness × importance **scoring matrix** |
| `llm.py` | DeepSeek→OpenAI chat wrapper (`chat`, `chat_json`) |
| `brief_builder.py` | signal selection + LLM synthesis + assembly of the `brief` dict |
| `render.py` | Jinja2 render |
| `templates/daily_brief.html` | the tokenized newsletter template |
| `run.py` | entrypoint / orchestration |

## Mapping back to the mother codebase
| This repo | `sales-agent-draft-` equivalent |
|---|---|
| `collect.py` | `backend/trends/collector.py`, `google_news_discovery.py` |
| `score.py` | `synthesis/lead_generator.compute_lead_confidence` + `scoring/company_score.freshness_score` |
| trigger taxonomy | `config.TRIGGER_EVENT_KEYWORDS` |
| `brief_builder.build_prospect` | `email/brain.py` strategy + `pitch_synthesizer` |
| `llm.py` | `backend/email/_llm.py` (DeepSeek dispatch) |
| template | the `coherentconnect_daily_brief_TEMPLATE.html` |
