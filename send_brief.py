"""Send a rendered daily brief as an email via SendGrid, converted to email-safe HTML first.

    python send_brief.py output/daily_brief_et_india_20260806.html you@example.com

Credentials come from the environment so they stay out of the repo:
    SENDGRID_API_KEY   required — a SendGrid API key (starts with "SG.")
    SENDGRID_FROM      optional — defaults to SENDER_EMAIL from .env, else "no-reply@<DOMAIN>"
    SENDGRID_FROM_NAME optional — display name for the From header (default: "CoherentConnect")

Reply-to addresses are NOT a secret, so they are hardcoded below in REPLY_TO_EMAILS
rather than read from .env — edit that list directly to change who replies go to.

The From address MUST be a verified single sender or part of an authenticated domain
in SendGrid, or the send is rejected with a 403.

UNSUBSCRIBE — handled entirely by SendGrid, not by this script or the Jinja
templates. Confirmed empirically on 2026-09-10:
    "Subscription Tracking" is enabled in the SendGrid dashboard (Settings >
    Tracking > Subscription Tracking). With it on, SendGrid APPENDS its own
    unsubscribe line to the bottom of every email — the html_content/
    plain_content configured on that settings page — with a real, working,
    per-recipient link. That appended line is the only unsubscribe control
    that is actually clickable; it is not part of templates/daily_brief*.html.
    Clicking it records the opt-out in the account's Global Unsubscribe list,
    and SendGrid refuses future sends to that address on its own from then on
    (confirmed: a send attempt to a suppressed address comes back from the API
    as accepted, but the message log shows status "not_delivered", reason
    "Unsubscribed Address" — no error is raised in this script).

    Tested and found NOT to work: placing a tag (e.g. "[unsubscribe]") inside
    our own template's <a href="..."> and hoping SendGrid substitutes it, and
    Gmail's native one-click "Unsubscribe" pill next to the sender name — the
    pill did not appear in testing even with Subscription Tracking on, SPF/
    DKIM/DMARC all valid. SendGrid's own docs say inbox providers, not
    SendGrid, ultimately decide whether to render that pill; it may still
    appear later as this domain builds sending reputation, but nothing here
    causes it directly.

    To customize the appended line's styling: PATCH the html_content field at
    https://api.sendgrid.com/v3/tracking_settings/subscription — the text
    wrapped in <% %> becomes the actual link (e.g. "<% Unsubscribe %>").

    To see who has unsubscribed: GET /v3/suppression/unsubscribes, or check
    one address directly: GET /v3/asm/suppressions/global/<email>
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values

from emailify import emailify, resolve_palette, logo_bytes, LOGO_CID, COHERENTLEAD

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"

# Replies to a CoherentConnect brief go to every address in REPLY_TO_EMAILS; replies to
# a CoherentLead brief go to COHERENTLEAD_REPLY_TO instead (per Raj's original routing
# email: CC -> ujjwal@/aditya@, CoherentLead -> vimarsh@/naman@coherentmarketinsights.com).
# The brand is auto-detected from the source HTML (see resolve_palette) — callers never
# need to say which list applies. Edit these lists directly; they are not read from .env.
REPLY_TO_EMAILS = [
    "ujjwal@coherentmarketinsights.com",
    "aditya@coherentmarketinsights.com",
]
COHERENTLEAD_REPLY_TO = [
    "vimarsh@coherentmarketinsights.com",
    "naman@coherentmarketinsights.com",
]

# Local .env (never printed) + process env. Mirrors llm.py's key-loading pattern.
_here = os.path.dirname(__file__)
_local_env = os.path.join(_here, ".env")
_vals = dotenv_values(_local_env) if os.path.exists(_local_env) else {}


def _env(name: str, default: str = "") -> str:
    return os.getenv(name) or _vals.get(name) or default


def _default_from() -> str:
    # SENDER_EMAIL is the current .env key; EMAIL is kept for backward compatibility.
    if _env("SENDER_EMAIL"):
        return _env("SENDER_EMAIL")
    if _env("EMAIL"):
        return _env("EMAIL")
    domain = _env("DOMAIN")
    if domain:
        return f"no-reply@{domain}"
    raise RuntimeError(
        "No From address available: set SENDGRID_FROM, SENDER_EMAIL, or DOMAIN in .env."
    )


def _reply_to_list(pal) -> list[dict]:
    """Reply-To addresses for the given brand Palette, in SendGrid's {"email": ...} shape."""
    addrs = COHERENTLEAD_REPLY_TO if pal is COHERENTLEAD else REPLY_TO_EMAILS
    return [{"email": a.strip()} for a in addrs if a.strip()]


def send_html(source_html: str, to: str, subject: str, *, filename_hint: str = "brief") -> None:
    """Core sender: takes already-rendered browser HTML (not a path), converts it via
    emailify(), and sends it to one recipient via the SendGrid API. Used by both the
    CLI (send()) and campaign.py's batch loop.

    The brand (CoherentConnect vs CoherentLead) is auto-detected from `source_html` to
    pick the right Reply-To list and, for CoherentLead, to attach its logo — the
    template references it as `cid:{LOGO_CID}` rather than a data: URI (SendGrid's own
    relay was found to strip/mangle base64-embedded <img src> content in transit), so
    the image must travel as an inline attachment with a matching Content-ID.
    """
    api_key = _env("SENDGRID_API_KEY")
    if not api_key:
        raise RuntimeError("SENDGRID_API_KEY is not set (env or .env).")

    from_email = _env("SENDGRID_FROM") or _default_from()
    from_name = _env("SENDGRID_FROM_NAME", "CoherentConnect")

    pal = resolve_palette(source_html)
    html = emailify(source_html, brand=pal)

    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": from_email, "name": from_name},
        "subject": subject,
        "content": [
            {"type": "text/plain",
             "value": "This brief is formatted as HTML. Please view it in an HTML-capable client."},
            {"type": "text/html", "value": html},
        ],
    }
    reply_to = _reply_to_list(pal)
    if len(reply_to) == 1:
        payload["reply_to"] = reply_to[0]
    elif len(reply_to) > 1:
        payload["reply_to_list"] = reply_to

    logo = logo_bytes(pal)
    if logo:
        payload["attachments"] = [{
            "content": base64.b64encode(logo).decode("ascii"),
            "type": "image/png",
            "filename": "logo.png",
            "disposition": "inline",
            "content_id": LOGO_CID,
        }]

    r = requests.post(
        SENDGRID_API_URL,
        json=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=15,
    )
    if r.status_code >= 300:
        # SendGrid puts the real reason in the JSON body (bad from-address, unverified
        # sender, invalid key, etc.) — surface it instead of a bare status code.
        detail = ""
        try:
            detail = r.json()
        except ValueError:
            detail = r.text
        raise RuntimeError(f"SendGrid send failed ({r.status_code}): {detail}")

    msg_id = r.headers.get("X-Message-Id", "")
    print(f"sent {filename_hint} -> {to}" + (f"  [X-Message-Id: {msg_id}]" if msg_id else ""))


def send(path: str | Path, to: str, subject: str | None = None) -> None:
    """CLI entry point: send an already-rendered .html FILE to one recipient."""
    path = Path(path)
    source = path.read_text(encoding="utf-8")
    send_html(source, to, subject or path.stem.replace("_", " "), filename_hint=path.name)


if __name__ == "__main__":
    send(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
