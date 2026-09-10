"""Probe: verify DeepSeek key presence (never printed) + network reach. Booleans only."""
import os, sys
from dotenv import dotenv_values

# Load the local .env WITHOUT exposing values to stdout.
local_env = os.path.join(os.path.dirname(__file__), ".env")
vals = {}
try:
    vals = dotenv_values(local_env)
except Exception as e:
    print("could not load .env:", type(e).__name__)

ds = vals.get("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or ""
oa = vals.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
print(f"DEEPSEEK_API_KEY present: {bool(ds)}  (len={len(ds)})")
print(f"OPENAI_API_KEY   present: {bool(oa)}  (len={len(oa)})")

# Network reach: RSS
try:
    import feedparser
    d = feedparser.parse("https://news.google.com/rss/search?q=biotech%20funding&hl=en-US&gl=US&ceid=US:en")
    print(f"RSS reachable: {len(d.entries)} entries")
except Exception as e:
    print("RSS error:", type(e).__name__, e)

# Network reach: DeepSeek (only if a key exists) — tiny call, prints only status
if ds:
    try:
        from openai import OpenAI
        c = OpenAI(api_key=ds, base_url="https://api.deepseek.com")
        r = c.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "reply with the single word: ok"}],
            max_tokens=5, temperature=0,
        )
        print("DeepSeek call OK ->", r.choices[0].message.content.strip()[:20])
    except Exception as e:
        print("DeepSeek error:", type(e).__name__, str(e)[:160])
else:
    print("DeepSeek: skipped (no key)")
