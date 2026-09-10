"""CoherentLead campaign dashboard — upload an xlsx contact list, send, see history.

Run:  streamlit run campaign_dashboard.py

Sending goes through send_brief.py (SendGrid HTTP API). Its config:
  SENDGRID_API_KEY   required, set via environment before launching this app.
  SENDGRID_FROM       optional, defaults to SENDER_EMAIL/.env, else "no-reply@<DOMAIN>".
  SENDGRID_FROM_NAME  optional, defaults to "CoherentConnect" — set to "CoherentLead"
                      when running a CoherentLead campaign, or leave as-is; the display
                      name doesn't affect brand detection (that's done from the HTML).
  Reply-To is NOT an env var — it's hardcoded per-brand in send_brief.py
  (REPLY_TO_EMAILS / COHERENTLEAD_REPLY_TO), auto-selected from the generated brief's
  brand. Edit those constants directly to change who replies go to.
  Unsubscribe is handled by SendGrid's account-level Subscription Tracking setting
  (Settings → Tracking → Subscription Tracking) — confirmed working, nothing to
  configure here.

Sent/failed/unsubscribed state persists in campaign_state.db so re-running the same file
is safe (already-sent rows are skipped automatically).
"""
from __future__ import annotations

import os
import queue
import tempfile
import threading
import time

import streamlit as st

import campaign
import send_brief

st.set_page_config(page_title="CoherentLead · Campaign Dashboard", page_icon="📤", layout="wide")
st.markdown(
    "<h1 style='margin-bottom:2px'>CoherentLead · Campaign Dashboard</h1>"
    "<p style='color:#6C6A62;margin-top:2px'>Upload a contact list, send the daily brief, track history.</p>",
    unsafe_allow_html=True,
)

if not os.environ.get("SENDGRID_API_KEY") and not send_brief._env("SENDGRID_API_KEY"):
    st.error(
        "SENDGRID_API_KEY is not set (env or .env) — sending will fail. "
        "Set it and restart the app.",
        icon="🚫",
    )

st.caption(
    f"Sending from **{send_brief._env('SENDGRID_FROM') or 'not set — see send_brief.py'}** · "
    f"Reply-To (CoherentLead) **{', '.join(send_brief.COHERENTLEAD_REPLY_TO)}** · "
    f"Reply-To (CoherentConnect) **{', '.join(send_brief.REPLY_TO_EMAILS)}** · "
    f"Unsubscribe handled by SendGrid Subscription Tracking"
)

st.divider()

st.subheader("✉️ Send one real test email")
st.caption(
    "Runs the exact same path as a real campaign send — live news discovery, LLM-written "
    "Ideal Customer cards, the real template and unsubscribe footer — just addressed to "
    "one inbox of your choosing instead of a contact-list row."
)
t1, t2 = st.columns([3, 2])
test_email = t1.text_input("Send test to", placeholder="you@example.com")
test_name = t2.text_input("Recipient first name", value="there")
if st.button("Send test email", disabled=not test_email):
    with st.spinner("Generating a live brief and sending…"):
        brief, debug = campaign._generate_brief(test_name or "there", log=lambda m: None)
        import render as _render
        html = _render.render(brief, "CoherentLead")
        try:
            send_brief.send_html(html, test_email, "CoherentLead · Daily Brief", filename_hint="dashboard-test")
            st.success(f"Sent to {test_email} — customers: "
                       f"{', '.join(c['company'] for c in debug.get('customers', []))}")
        except Exception as e:  # noqa: BLE001
            st.error(f"Send failed: {type(e).__name__}: {e}")

st.divider()

uploaded = st.file_uploader("Contact list (.xlsx)", type=["xlsx"])

if uploaded:
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(uploaded.getvalue())
        tmp_path = tmp.name

    import openpyxl
    wb = openpyxl.load_workbook(tmp_path, read_only=True)
    sheet = st.selectbox("Sheet", wb.sheetnames)

    try:
        contacts = campaign.read_contacts(tmp_path, sheet=sheet)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    # Cross-reference against local suppression state so the preview shows what will
    # ACTUALLY happen on this run, not just the raw row count.
    conn = campaign._init_db()
    already_sent = {r[0] for r in conn.execute("SELECT email FROM sends WHERE status='sent'")}
    already_unsub = {r[0] for r in conn.execute("SELECT email FROM sends WHERE status='unsubscribed'")}
    conn.close()

    to_send = [c for c in contacts if c.email.lower() not in already_sent and c.email.lower() not in already_unsub]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Rows in sheet", len(contacts))
    m2.metric("Already sent", len(already_sent & {c.email.lower() for c in contacts}))
    m3.metric("Unsubscribed", len(already_unsub & {c.email.lower() for c in contacts}))
    m4.metric("Will send now", len(to_send))

    st.dataframe(
        [{"email": c.email, "name": c.name, "company": c.company, "job_title": c.job_title} for c in contacts[:50]],
        use_container_width=True, hide_index=True,
    )
    if len(contacts) > 50:
        st.caption(f"Showing first 50 of {len(contacts)} rows.")

    st.divider()
    c1, c2, c3 = st.columns([2, 2, 2])
    test_limit = c1.number_input("Limit this run to first N contacts (0 = all)", min_value=0, value=min(3, len(to_send)))
    delay = c2.number_input(
        "Seconds between sends", min_value=0.0, value=12.0, step=1.0,
        help="coherentlead.info is a new sending domain with no reputation yet — 12s+ "
             "is recommended to avoid tripping spam filters or SendGrid throttling.",
    )
    subject = c3.text_input("Subject line", value="CoherentLead · Daily Brief")

    # A background thread runs the actual send loop so the Stop button — clicked on a
    # LATER Streamlit script rerun — can flip a threading.Event the loop polls between
    # rows. Running send synchronously on the main thread would make Stop unresponsive
    # until the whole batch finished, defeating the point of a stop button.
    if "campaign_thread" not in st.session_state:
        st.session_state.campaign_thread = None
        st.session_state.stop_event = None
        st.session_state.progress_queue = None

    running = st.session_state.campaign_thread is not None and st.session_state.campaign_thread.is_alive()

    b1, b2 = st.columns([1, 1])
    start_clicked = b1.button("▶ Start", type="primary", disabled=not to_send or running)
    stop_clicked = b2.button("⏹ Stop", disabled=not running)

    if start_clicked:
        stop_event = threading.Event()
        progress_q: queue.Queue = queue.Queue()
        limit = test_limit or None

        def _worker():
            def _on_progress(event):
                progress_q.put(event)
            result = campaign.run_campaign(
                tmp_path, sheet=sheet, limit=limit, delay_seconds=delay,
                subject=subject, on_progress=_on_progress,
                should_stop=stop_event.is_set,
            )
            progress_q.put({"email": "", "status": "__done__", "detail": result})

        t = threading.Thread(target=_worker, daemon=True)
        st.session_state.stop_event = stop_event
        st.session_state.progress_queue = progress_q
        st.session_state.campaign_thread = t
        t.start()
        st.rerun()

    if stop_clicked and st.session_state.stop_event:
        st.session_state.stop_event.set()
        st.info("Stopping after the current send finishes…")

    if running or (st.session_state.progress_queue and not st.session_state.progress_queue.empty()):
        limit = test_limit or None
        total = min(limit, len(to_send)) if limit else len(to_send)
        progress_bar = st.progress(0.0)
        log_box = st.container()
        done_count = 0
        final_result = None

        # Drain whatever the worker has produced so far, then poll briefly while it's
        # still alive so this rerun shows live progress without a full page reload loop.
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                event = st.session_state.progress_queue.get(timeout=0.5)
            except queue.Empty:
                if not (st.session_state.campaign_thread and st.session_state.campaign_thread.is_alive()):
                    break
                continue
            if event["status"] == "__done__":
                final_result = event["detail"]
                break
            done_count += 1
            progress_bar.progress(min(1.0, done_count / max(1, total)))
            with log_box:
                st.write(f"{event['status']:12} — {event['email']}" + (f" ({event.get('detail')})" if event.get("detail") else ""))

        if final_result is not None:
            st.session_state.campaign_thread = None
            stopped_note = " (stopped early)" if final_result.get("stopped") else ""
            st.success(f"Done{stopped_note} — sent {final_result['sent']}, failed {final_result['failed']}, "
                       f"skipped {final_result['skipped']}, unsubscribed {final_result['unsubscribed']}")
        else:
            st.rerun()

st.divider()
st.subheader("📊 Send history")
conn = campaign._init_db()
counts = dict(conn.execute("SELECT status, COUNT(*) FROM sends GROUP BY status").fetchall())
rows = conn.execute("SELECT email, status, detail, sent_at FROM sends ORDER BY sent_at DESC LIMIT 500").fetchall()
conn.close()

h1, h2, h3, h4 = st.columns(4)
h1.metric("Total sent", counts.get("sent", 0))
h2.metric("Failed", counts.get("failed", 0))
h3.metric("Unsubscribed", counts.get("unsubscribed", 0))
h4.metric("Total tracked", sum(counts.values()))

if rows:
    st.dataframe(
        [{"email": r[0], "status": r[1], "detail": r[2], "when": r[3]} for r in rows],
        use_container_width=True, hide_index=True,
    )
else:
    st.caption("No sends recorded yet.")
