"""DeepSeek-first LLM wrapper with automatic OpenAI fallback.

Mirrors the mother repo's `email/_llm.py` idea (DeepSeek is OpenAI-API-compatible, so we
use the `openai` SDK with a custom base_url). Provider order is DeepSeek → OpenAI so the
newsletter "uses DeepSeek" as requested, but still runs if the DeepSeek balance is 0.
"""
from __future__ import annotations
import json
import os

from openai import OpenAI
from dotenv import dotenv_values

import config

# Load keys from a local .env in this folder (values never printed) + process env.
_vals = {}
_local_env = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_local_env):
    _vals = dotenv_values(_local_env) or {}


def _key(name: str) -> str:
    return os.getenv(name) or _vals.get(name) or ""


DEEPSEEK_API_KEY = _key("DEEPSEEK_API_KEY")
OPENAI_API_KEY = _key("OPENAI_API_KEY")
PROVIDER = os.getenv("LLM_PROVIDER") or config.LLM["provider"]

_ds_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=config.LLM["deepseek_base_url"]) if DEEPSEEK_API_KEY else None
_oa_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Tracks which provider actually served calls this run (for the run report).
STATS = {"deepseek": 0, "openai": 0, "failed": 0, "provider_used": None}


def _call(client, model, messages, json_mode, temperature, max_tokens):
    kwargs = dict(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    r = client.chat.completions.create(**kwargs)
    return r.choices[0].message.content or ""


def chat(system: str, user: str, *, json_mode: bool = False,
         temperature: float | None = None, max_tokens: int = 1200) -> str:
    """One completion. Tries DeepSeek first (if selected + keyed), falls back to OpenAI."""
    temp = config.LLM["temperature"] if temperature is None else temperature
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    order = []
    if PROVIDER == "deepseek":
        order = [("deepseek", _ds_client, config.LLM["deepseek_model"]),
                 ("openai", _oa_client, config.LLM["openai_model"])]
    else:
        order = [("openai", _oa_client, config.LLM["openai_model"]),
                 ("deepseek", _ds_client, config.LLM["deepseek_model"])]
    if not config.LLM["fallback_to_openai"]:
        order = order[:1]

    last_err = None
    for name, client, model in order:
        if client is None:
            continue
        try:
            out = _call(client, model, messages, json_mode, temp, max_tokens)
            STATS[name] += 1
            STATS["provider_used"] = STATS["provider_used"] or name
            return out
        except Exception as e:  # noqa: BLE001 — degrade to next provider (mother-repo resilience rule)
            last_err = e
            print(f"  [llm] {name}:{model} failed ({type(e).__name__}: {str(e)[:80]}) → falling back")
            continue
    STATS["failed"] += 1
    raise RuntimeError(f"all LLM providers failed: {last_err}")


def chat_json(system: str, user: str, *, temperature: float | None = None,
              max_tokens: int = 1200, default: dict | None = None) -> dict:
    """chat() in JSON mode, parsed. Returns `default` on any failure."""
    try:
        raw = chat(system, user, json_mode=True, temperature=temperature, max_tokens=max_tokens)
        raw = raw.strip()
        # tolerate ```json fences
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1].removeprefix("json").strip()
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        print(f"  [llm] json parse/degrade: {type(e).__name__}: {str(e)[:80]}")
        return default if default is not None else {}
