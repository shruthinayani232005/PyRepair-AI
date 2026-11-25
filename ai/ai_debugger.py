"""LLM debugging service. Providers: Anthropic and any OpenAI-compatible API.
Configure through .env or the Settings page. Falls back to rules if AI is unavailable."""
import json
import os

import requests
from dotenv import load_dotenv

from ai.fallback_debugger import diagnose as fallback_diagnose
from ai.prompts import SYSTEM_PROMPT, build_user_prompt

load_dotenv()
REQUIRED = ["error_type", "root_cause", "problem_line", "explanation", "repair_strategy",
            "repaired_code", "confidence"]


class AIError(Exception):
    pass


def load_default_settings():
    return {"provider": os.getenv("AI_PROVIDER", "auto"),
            "anthropic_key": os.getenv("ANTHROPIC_API_KEY", ""),
            "openai_key": os.getenv("OPENAI_API_KEY", ""),
            "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "model": os.getenv("AI_MODEL", ""),
            "max_attempts": int(os.getenv("MAX_REPAIR_ATTEMPTS", "3")),
            "timeout": int(os.getenv("EXEC_TIMEOUT", "10")),
            "theme": "Midnight"}


def resolve_provider(s):
    p = s.get("provider", "auto")
    if p == "fallback":
        return "fallback"
    if p == "anthropic" or (p == "auto" and s.get("anthropic_key")):
        return "anthropic" if s.get("anthropic_key") else "fallback"
    if p == "openai" or (p == "auto" and s.get("openai_key")):
        return "openai" if s.get("openai_key") else "fallback"
    return "fallback"


def _call_llm(provider, s, user_prompt):
    try:
        if provider == "anthropic":
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=90,
                              headers={"x-api-key": s["anthropic_key"], "anthropic-version": "2023-06-01",
                                       "content-type": "application/json"},
                              json={"model": s.get("model") or "claude-sonnet-5-5", "max_tokens": 4096,
                                    "system": SYSTEM_PROMPT,
                                    "messages": [{"role": "user", "content": user_prompt}]})
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json()["content"])
        r = requests.post(s["base_url"].rstrip("/") + "/chat/completions", timeout=90,
                          headers={"Authorization": f"Bearer {s['openai_key']}"},
                          json={"model": s.get("model") or "gpt-4o-mini", "temperature": 0,
                                "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                             {"role": "user", "content": user_prompt}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except (requests.RequestException, KeyError, ValueError) as e:
        raise AIError(f"AI service failure: {e}")


def parse_response(text):
    """Strictly turn the model reply into the expected JSON structure."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise AIError("AI reply did not contain JSON")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise AIError(f"Invalid JSON from AI: {e}")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise AIError(f"AI JSON missing keys: {missing}")
    try:
        data["confidence"] = max(0.0, min(0.99, float(data["confidence"])))
    except (TypeError, ValueError):
        data["confidence"] = 0.5
    for k in REQUIRED[:-1]:
        data[k] = str(data[k])
    return data


def get_diagnosis(info, settings, log=None):
    """Try the LLM; on any problem use the rule-based fallback."""
    note = lambda m, lv="info": log.add(m, lv) if log else None
    provider = resolve_provider(settings)
    if provider == "fallback":
        note("No AI API key configured - using built-in fallback debugger", "warning")
    else:
        try:
            try:
                data = parse_response(_call_llm(provider, settings, build_user_prompt(info)))
            except AIError as e:
                if "service failure" in str(e):
                    raise
                note(f"{e} - retrying once", "warning")
                data = parse_response(_call_llm(provider, settings, build_user_prompt(info)))
            if data["repaired_code"].strip() and data["repaired_code"].strip() != info["code"].strip():
                data["source"] = f"AI ({provider})"
                return data
            note("AI returned no change - using fallback debugger", "warning")
        except AIError as e:
            note(f"{e} - using fallback debugger", "warning")
    data = fallback_diagnose(info)
    data["source"] = "Fallback rules"
    return data
