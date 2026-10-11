"""Free-tier LLM chain. Never touches Claude.

Every provider below speaks the OpenAI chat-completions format, so one function
covers them all. The order comes from config.json -> llm.providers; the first
provider with a key (or a running Ollama) that answers wins. If one is rate
limited it is skipped for the rest of the run and the next one is tried.
"""
import json, re, time
from util import load_config, load_keys, http

ENDPOINTS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "GEMINI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY"),
    "cerebras": ("https://api.cerebras.ai/v1/chat/completions", "CEREBRAS_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1/chat/completions", "MISTRAL_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
    "ollama": ("http://127.0.0.1:11434/v1/chat/completions", None),
}

_dead = {}  # provider -> reason, for the rest of this process


class NoLLM(Exception):
    pass


def available():
    cfg = load_config().get("llm", {})
    keys = load_keys()
    out = []
    for p in cfg.get("providers", []):
        name = p["name"]
        if name not in ENDPOINTS or p.get("enabled") is False:
            continue
        url, keyname = ENDPOINTS[name]
        if keyname and not keys.get(keyname):
            continue
        out.append((name, url, keys.get(keyname) if keyname else None, p["model"]))
    return out


def chat(system, user, max_tokens=2500, temperature=0.4, want_json=True, log=None):
    """Returns (text, provider_name). Raises NoLLM when nothing answers."""
    errors = []
    for name, url, key, model in available():
        if f"{name}:{model}" in _dead:
            continue
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if name == "openrouter":
            headers["HTTP-Referer"] = "http://localhost"
            headers["X-Title"] = "Job Engine"
        body = {"model": model, "temperature": temperature, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if want_json and name in ("gemini", "groq", "cerebras", "mistral", "ollama"):
            body["response_format"] = {"type": "json_object"}
        for attempt in range(2):
            try:
                r = http().post(url, headers=headers, json=body, timeout=180 if name == "ollama" else 90)
            except Exception as e:
                errors.append(f"{name}: {e}")
                if name == "ollama":
                    _dead[f"{name}:{model}"] = "not running"
                break
            if r.status_code == 429:
                if attempt == 0:
                    time.sleep(20)
                    continue
                _dead[f"{name}:{model}"] = "rate limited"
                errors.append(f"{name}: rate limited")
                break
            if r.status_code >= 400:
                errors.append(f"{name}: HTTP {r.status_code} {r.text[:200]}")
                if r.status_code in (401, 403, 404):
                    _dead[f"{name}:{model}"] = f"HTTP {r.status_code}"
                break
            try:
                text = r.json()["choices"][0]["message"]["content"] or ""
            except Exception as e:
                errors.append(f"{name}: bad response {e}")
                break
            if text.strip():
                return text, f"{name}:{model}"
            errors.append(f"{name}: empty answer")
            break
    if log and errors:
        log("LLM errors:", "; ".join(errors))
    raise NoLLM("; ".join(errors) or "no free LLM configured (add a key in Settings)")


def chat_json(system, user, **kw):
    text, who = chat(system, user, **kw)
    return parse_json(text), who


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def health():
    """Ping each configured provider with a tiny prompt. Used by the UI."""
    res = {}
    for name, url, key, model in available():
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            r = http().post(url, headers=headers, timeout=40, json={
                "model": model, "max_tokens": 5,
                "messages": [{"role": "user", "content": "Reply with OK"}]})
            res[f"{name} ({model})"] = "ok" if r.status_code < 300 else f"HTTP {r.status_code}: {r.text[:120]}"
        except Exception as e:
            res[f"{name} ({model})"] = f"error: {e}"[:160]
    return res
