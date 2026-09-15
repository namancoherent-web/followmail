# CoherentLead Newsletter Campaign — Final Report

**Date:** 2026-09-11
**Status:** Complete — all 264 contacts processed, tool stopped.

## Result

| Metric | Count |
|---|---|
| Total contacts in list | 264 |
| Sent | 230 |
| Unsubscribed (skipped) | 34 |
| Failed | 0 |
| **Total tracked** | **264 / 264** |

Source file: `fnal files/Unique_Emails_264_FullData.xlsx`
Local send log: `campaign_state.db` (per-email status, picked companies, timestamp — gitignored, not in repo)

## What was built

- **`coherentlead_brief_builder.py`** — new LLM pipeline generating a fresh "Ideal Customers" brief per recipient (live news discovery → buyer/peer triage → LLM-written narrative/why-now/who-to-target/recommended-action → editorial lede).
- **`templates/daily_brief_coherentlead.html`** — reconstructed CoherentLead-branded template (Ember/Ink/Snow palette, Bricolage Grotesque), "Inside CoherentLead" showcase rewritten to match the real coherentlead.ai site content (AI-powered ICP search, 7-layer verification, account intelligence, verified-only/pay-per-success billing — replacing an earlier stale demo-file version).
- **`emailify.py`** — made brand-aware (`Palette` dataclass, auto-detects CoherentConnect vs. CoherentLead), added logo delivery via CID inline attachment (data-URI logos were found to be stripped by SendGrid's relay in testing).
- **`send_brief.py`** — SendGrid HTTP API sender with per-brand Reply-To routing (CoherentLead → `vimarsh@`/`naman@coherentmarketinsights.com`), inline logo attachment support.
- **`campaign.py`** — batch engine: tolerant xlsx contact reader (handles varying header names), local SQLite send-state tracking (safe to stop/resume), SendGrid suppression-list cross-check before sending, 12s inter-send delay (new-domain safe pacing), and a rolling 15-company exclusion window so one high-scoring news outlier doesn't dominate every recipient's brief.
- **`campaign_dashboard.py`** — Streamlit UI: upload xlsx, preview/counts, Start/Stop (background-thread + `threading.Event`), live per-row progress, full send history table.

## Bugs found and fixed during the run

1. **CoherentLead never had a template/pipeline at all** — reconstructed from two demo HTML files; wired into `render.py`'s `TEMPLATES` dict.
2. **`emailify.py` dropped the `.featable` feature-table block** for CoherentLead emails — added a dedicated parser branch.
3. **Logo rendered as a broken image in real inboxes** — root cause was SendGrid stripping base64 `data:` URIs in transit; fixed by switching to a `cid:`-referenced inline MIME attachment.
4. **`send_brief.py` rewrite (SendGrid HTTP API) dropped CoherentLead support** — no attachment handling, no `send_html()` function (broke `campaign.py`), single hardcoded Reply-To list. Restored and made brand-aware.
5. **`_sendgrid_suppressed()` crashed** (`'str' object has no attribute 'get'`) — one of the two suppression-list endpoints returns a different JSON shape than assumed; this silently killed every Start click until diagnosed via the Streamlit error log.
6. **Newsletter copy implied CoherentLead autonomously contacts prospects** ("built to discover, verify, and reach for you automatically") — factually wrong per the product's own site copy (it's a self-serve discovery/verification tool; the user does the outreach). Rewrote the fixed closing line and system prompt to correctly attribute outreach to the recipient's own sales team.
7. **Same top news story ("Theater") kept appearing for every recipient** — root cause was a genuine score outlier plus a dashboard **not being restarted after a code fix** (Python/Streamlit doesn't hot-reload already-imported modules). Fixed by widening the candidate shortlist (5→8) and adding a batch-wide rolling exclusion window; verified with an 8-run simulation showing real variety before resuming sends.

## Known limitations (not fixed, documented for follow-up)

- Personalization is by **first name only** — recipient's own company/job title (present in the xlsx) is parsed but not used to tailor which prospects get featured.
- No BCC support in the current SendGrid-HTTP-API `send_brief.py` (dropped when it moved off SMTP envelope recipients).
- Unsubscribe relies on SendGrid's account-level **Subscription Tracking** setting (confirmed working) — the template's own static "Unsubscribe" footer link is a non-functional `#` placeholder.
- One occasional content glitch: when a picked company name is also a common word (e.g. "Theater"), free-research enrichment can pull irrelevant results, and the LLM sometimes exposes this as meta-commentary in the narrative text instead of silently discarding it.

## Repo

Pushed to `github.com/namancoherent-web/followmail` (branch `main`). Real contact lists, `.env`, and generated `output/` are gitignored — never committed.
