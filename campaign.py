"""Batch-send the CoherentLead newsletter to a recipient list loaded from Excel.

    python campaign.py contacts.xlsx --sheet Sheet1 --limit 5   # dry-run-ish, small batch
    python campaign.py contacts.xlsx

Reads any .xlsx with columns identifying at least a name and an email address (header
names are matched case/whitespace-insensitively; common variants like "Email", "Email 1",
"Email Address" are all accepted — see `_HEADER_ALIASES`). One brief is generated and sent
per row, each addressed to that row's first name; company/job title (if present) currently
inform nothing about the brief content — every row gets a fresh, independently-discovered
CoherentLead "Ideal Customers" brief, not a brief personalized to the row's own company.

State is tracked in a local SQLite file (campaign_state.db, gitignored) so a batch can be
safely re-run: rows already sent are skipped, and rows previously marked unsubscribed are
always skipped. This is a LOCAL, best-effort suppression list — the authoritative one is
SendGrid's own ASM unsubscribe group (see SENDGRID_ASM_GROUP_ID in send_brief.py); this
file additionally cross-checks SendGrid's suppression API before each batch so addresses
that unsubscribed via a previous campaign are never re-sent to, even from a fresh machine.

Rate limiting: SENDGRID_BATCH_DELAY_SECONDS (default 12) between sends. coherentlead.info
is a brand-new sending domain with no reputation yet — bulk sending without generous
pacing risks the receiving mail servers (Gmail, Outlook, etc.) flagging the pattern as
spam-like, or SendGrid itself throttling the account. 12s is a conservative default for
domain warm-up; each brief also takes ~30-90s to generate (live news + 4 LLM calls), so
real spacing between sends in practice is dominated by generation time, not this delay.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

import config
import render
import send_brief
from tenant import Profile
from collect import collect
from score import score_all, eligible
from coherentlead_brief_builder import build_coherentlead_brief

DB_PATH = os.path.join(os.path.dirname(__file__), "campaign_state.db")

# Header name -> canonical field. Matched after lowercasing + stripping whitespace, so
# "Email 1", "email", "Email Address" all resolve to "email"; "Name", "First Name",
# "FirstName" all resolve to "name". Case/format varies a lot between real-world lists
# (see Coherent Lead Database.xlsx, which uses three different header sets across its
# three sheets), so this is deliberately tolerant rather than requiring one exact schema.
_HEADER_ALIASES = {
    "email": "email", "email 1": "email", "email address": "email", "e-mail": "email",
    "name": "name", "first name": "name", "firstname": "name",
    "company": "company", "organisation": "company", "organization": "company",
    "job title": "job_title", "jobtitle": "job_title", "title": "job_title",
}


@dataclass
class Contact:
    email: str
    name: str
    company: str = ""
    job_title: str = ""
    row_num: int = 0


def _init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sends (
            email TEXT PRIMARY KEY,
            status TEXT NOT NULL,           -- sent | failed | unsubscribed | skipped
            detail TEXT,
            sent_at TEXT
        )
    """)
    conn.commit()
    return conn


def read_contacts(xlsx_path: str | Path, sheet: str | None = None) -> list[Contact]:
    """Load contacts from one sheet of an .xlsx (first sheet if `sheet` is None).
    Skips rows with no usable email address."""
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]

    rows = ws.iter_rows(values_only=True)
    header_row = next(rows)
    col_map: dict[int, str] = {}
    for i, h in enumerate(header_row):
        key = str(h or "").strip().lower()
        if key in _HEADER_ALIASES:
            col_map[i] = _HEADER_ALIASES[key]

    if "email" not in col_map.values():
        raise ValueError(
            f"No recognizable email column in sheet '{ws.title}'. "
            f"Headers found: {[h for h in header_row]}"
        )

    contacts: list[Contact] = []
    for row_num, row in enumerate(rows, start=2):
        fields = {"email": "", "name": "", "company": "", "job_title": ""}
        for i, field in col_map.items():
            v = row[i] if i < len(row) else None
            if v is not None:
                fields[field] = str(v).strip()
        email = fields["email"]
        if not email or "@" not in email:
            continue
        name = fields["name"] or email.split("@")[0]
        contacts.append(Contact(
            email=email, name=name.split()[0] if name else "there",
            company=fields["company"], job_title=fields["job_title"], row_num=row_num,
        ))
    return contacts


def _sendgrid_suppressed(api_key: str) -> set[str]:
    """Query SendGrid's global + group suppression lists so a fresh machine still
    respects opt-outs recorded from a previous campaign. Best-effort: returns an
    empty set (never blocks the batch) if the API call fails for any reason.

    The two endpoints return DIFFERENT shapes: suppression/unsubscribes returns a bare
    list of {"email": ...} objects, but asm/suppressions/global returns a dict
    {"suppressions": [...]} where the inner list is plain email strings, not objects —
    confirmed empirically (a naive item.get("email") on the second shape crashes with
    "'str' object has no attribute 'get'" since dict iteration yields its keys, and
    each key was itself a plain string).
    """
    suppressed: set[str] = set()
    for path in ("suppression/unsubscribes", "asm/suppressions/global"):
        req = urllib.request.Request(
            f"https://api.sendgrid.com/v3/{path}?limit=500",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
                items = data["suppressions"] if isinstance(data, dict) and "suppressions" in data else data
                for item in items:
                    email = item.get("email") if isinstance(item, dict) else item
                    if email:
                        suppressed.add(str(email).lower())
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError, TypeError):
            continue
    return suppressed


def _generate_brief(recipient_name: str, log) -> tuple[dict, dict]:
    country = config.get_country("Global")
    profile = Profile.coherentlead_default("Global")
    profile.recipient = recipient_name
    articles = collect(profile, country)
    scored = score_all(articles, profile)
    keep = eligible(scored)
    return build_coherentlead_brief(keep or scored, profile, log=log)


def run_campaign(
    xlsx_path: str | Path,
    sheet: str | None = None,
    limit: int | None = None,
    delay_seconds: float | None = None,
    subject: str = "CoherentLead · Daily Brief",
    on_progress=None,
    should_stop=None,
) -> dict:
    """Send the CoherentLead newsletter to every eligible contact in `xlsx_path`.

    `on_progress(event: dict)` is called after every row if given — used by the
    Streamlit dashboard to render live progress without polling the DB.
    `should_stop()` is polled before each row if given; when it returns True the loop
    breaks cleanly. Safe to call again later — every send is committed to campaign_state.db
    immediately, so a stopped-then-resumed run skips rows already marked 'sent'.
    Returns a summary dict: {"sent": n, "failed": n, "skipped": n, "unsubscribed": n, "stopped": bool}.
    """
    delay = delay_seconds if delay_seconds is not None else float(os.environ.get("SENDGRID_BATCH_DELAY_SECONDS", "12"))
    conn = _init_db()

    contacts = read_contacts(xlsx_path, sheet)
    if limit:
        contacts = contacts[:limit]

    api_key = os.environ.get("SENDGRID_API_KEY", "")
    remote_suppressed = _sendgrid_suppressed(api_key) if api_key else set()

    summary = {"sent": 0, "failed": 0, "skipped": 0, "unsubscribed": 0, "stopped": False}

    for c in contacts:
        if should_stop and should_stop():
            summary["stopped"] = True
            if on_progress:
                on_progress({"email": "", "status": "stopped", "detail": "stopped by user"})
            break
        email_l = c.email.lower()
        row = conn.execute("SELECT status FROM sends WHERE email = ?", (email_l,)).fetchone()
        already = row[0] if row else None

        if email_l in remote_suppressed or already == "unsubscribed":
            conn.execute(
                "INSERT OR REPLACE INTO sends VALUES (?, 'unsubscribed', ?, ?)",
                (email_l, "opted out (SendGrid suppression list)", datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            summary["unsubscribed"] += 1
            if on_progress:
                on_progress({"email": c.email, "status": "unsubscribed"})
            continue

        if already == "sent":
            summary["skipped"] += 1
            if on_progress:
                on_progress({"email": c.email, "status": "skipped", "detail": "already sent"})
            continue

        try:
            brief, debug = _generate_brief(c.name, log=lambda m: None)
            html = render.render(brief, "CoherentLead")
            send_brief.send_html(html, c.email, subject, filename_hint=f"row{c.row_num}")
            conn.execute(
                "INSERT OR REPLACE INTO sends VALUES (?, 'sent', ?, ?)",
                (email_l, json.dumps(debug.get("customers", [])), datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            summary["sent"] += 1
            if on_progress:
                on_progress({"email": c.email, "status": "sent"})
        except Exception as e:  # noqa: BLE001 — one bad row must not kill the whole batch
            conn.execute(
                "INSERT OR REPLACE INTO sends VALUES (?, 'failed', ?, ?)",
                (email_l, f"{type(e).__name__}: {e}", datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            summary["failed"] += 1
            if on_progress:
                on_progress({"email": c.email, "status": "failed", "detail": str(e)})

        time.sleep(delay)

    conn.close()
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Batch-send the CoherentLead newsletter from an xlsx contact list.")
    ap.add_argument("xlsx", help="Path to the .xlsx contact list")
    ap.add_argument("--sheet", default=None, help="Sheet name (default: first sheet)")
    ap.add_argument("--limit", type=int, default=None, help="Only send to the first N contacts")
    ap.add_argument("--delay", type=float, default=None, help="Seconds between sends (default: 12)")
    ap.add_argument("--subject", default="CoherentLead · Daily Brief")
    args = ap.parse_args()

    result = run_campaign(args.xlsx, sheet=args.sheet, limit=args.limit,
                           delay_seconds=args.delay, subject=args.subject,
                           on_progress=lambda e: print(f"  {e['status']:12} {e['email']}"))
    print(f"\nDone: {result}")
