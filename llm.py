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

# When a provider retires a model (HTTP 404 / "does not exist"), pick the best current one from its
# /models list and remember it in data/llm_models.json, so the chain heals itself without a config edit.
_PREFER = [r"gpt-oss-120b", r"gemma-4-31b", r"qwen-?3[\.\d]*-27b", r"nemotron-3-super", r"llama-?3\.3-70b",
           r"gpt-oss-20b", r"flash-lite", r"flash"]
_SKIP = re.compile(r"guard|safety|whisper|tts|orpheus|image|audio|embed|-vl|omni|live|prompt|allam|nano|2\.6b|lightning|code", re.I)


def _model_cache():
    from util import ROOT
    return ROOT / "data" / "llm_models.json"


def _healed():
    try:
        return json.loads(_model_cache().read_text())
    except Exception:
        return {}


def _discover(name, url, key):
    """Return the best available model id for this provider, or None."""
    base = url.rsplit("/chat/completions", 1)[0]
    try:
        r = http().get(base + "/models", headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=20)
        ids = [m.get("id", "").replace("models/", "") for m in r.json().get("data", [])]
    except Exception:
        return None
    if name == "openrouter":
        ids = [i for i in ids if i.endswith(":free")]
    ids = [i for i in ids if i and not _SKIP.search(i)]
    for pat in _PREFER:
        for i in ids:
            if re.search(pat, i, re.I):
                return i
    return ids[0] if ids else None


def _heal(name, url, key, model, log=None):
    new = _discover(name, url, key)
    if not new or new == model:
        return None
    h = _healed()
    h[f"{name}:{model}"] = new
    try:
        _model_cache().write_text(json.dumps(h, indent=1))
    except Exception:
        pass
    if log:
        log(f"  {name}: model {model} is retired - switched to {new}")
    return new


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
        model = _healed().get(f"{name}:{p['model']}", p["model"])
        out.append((name, url, keys.get(keyname) if keyname else None, model))
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
                # only a real "this model no longer exists" counts - a busy/overloaded 503 must not switch models
                gone = r.status_code in (400, 404) and bool(re.search(
                    r"does not exist|not found|no longer (available|supported)|decommission|deprecat|unknown model|"
                    r"invalid model|model_not_found|unavailable for free", r.text, re.I))
                if r.status_code in (500, 502, 503, 504) and attempt == 0:
                    time.sleep(8)
                    continue
                if gone and attempt == 0:
                    new = _heal(name, url, key, model, log)
                    if new:
                        model = body["model"] = new
                        continue
                errors.append(f"{name}: HTTP {r.status_code} {r.text[:200]}")
                if r.status_code in (401, 403, 404) or gone:
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
    """Always returns a dict. Retries once (cooler, stricter) if the model's JSON is broken."""
    text, who = chat(system, user, **kw)
    try:
        return _as_dict(parse_json(text)), who
    except Exception:
        kw2 = dict(kw, temperature=0.1)
        text, who = chat(system + "\nReturn ONLY one valid JSON object. No comments, no trailing commas.", user, **kw2)
        return _as_dict(parse_json(text)), who


def _as_dict(v):
    if isinstance(v, dict):
        return v
    if isinstance(v, list):
        dicts = [x for x in v if isinstance(x, dict)]
        if len(dicts) == 1:
            return dicts[0]
        return {"items": v}
    return {"value": v}


def _repair(t):
    t = re.sub(r"//[^\n\"]*$", "", t, flags=re.M)              # // comments at line end
    t = re.sub(r",\s*([}\]])", r"\1", t)                       # trailing commas
    t = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', t)  # unquoted keys
    t = t.replace("\u201c", '"').replace("\u201d", '"').replace("\u2019", "'")
    t = re.sub(r'"\s*\n\s*"', '",\n"', t)                    # missing comma between lines
    return t


def parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"(?s)<think>.*?</think>", "", text).strip()   # reasoning models
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    for cand in (text, (re.search(r"[\{\[].*[\}\]]", text, re.S) or [None])[0]):
        if not cand:
            continue
        for t in (cand, _repair(cand)):
            try:
                return json.loads(t)
            except Exception:
                pass
    return json.loads(text)  # raise the original error


def health():
    """Ping each configured provider with a tiny prompt, all at once. Used by the UI."""
    from concurrent.futures import ThreadPoolExecutor

    def one(p):
        name, url, key, model = p
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            r = http().post(url, headers=headers, timeout=25, json={
                "model": model, "max_tokens": 5, "messages": [{"role": "user", "content": "Reply with OK"}]})
            if r.status_code in (400, 404) and re.search(r"does not exist|not found|model_not_found|decommission",
                                                         r.text, re.I) and _heal(name, url, key, model):
                return one((name, url, key, _healed()[f"{name}:{model}"]))
            return f"{name} ({model})", ("ok" if r.status_code < 300 else f"HTTP {r.status_code}: {r.text[:120]}")
        except Exception as e:
            return f"{name} ({model})", f"error: {e}"[:160]
    with ThreadPoolExecutor(6) as ex:
        return dict(ex.map(one, available()))
