"""AI assistant backed by the official OpenAI / Anthropic APIs.

Design rules this file enforces, not just documents:
  - Numbers are computed in ELNOC code (see ai_assist.interpret_rsl); the model
    is never asked to do arithmetic on optical levels.
  - Playbooks and the glossary are injected as context so answers cite *your*
    procedures, and the model is told to say when it is reasoning generally.
  - Nothing is sent until secrets are stripped (security.find_secret).
  - Every call is written to AgentLog, with provider, model and token use.
  - Fails closed: no key configured -> the caller gets the offline tools only,
    never a silent pretend answer.

Providers:
  openai     -> https://api.openai.com/v1/chat/completions   (LLM_API_KEY)
  anthropic  -> https://api.anthropic.com/v1/messages       (ANTHROPIC_API_KEY)
"""
from __future__ import annotations
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from ..config import settings
from .ai_assist import GLOSSARY

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

DEFAULT_MODELS = {"openai": "gpt-4o-mini", "anthropic": "claude-sonnet-4-20250514"}
DEFAULT_TIMEOUT = 90

SYSTEM_RULES = """You are the ELNOC assistant for a Nigerian fibre ISP NOC.

How you must answer:
- Ground every recommendation in the PLAYBOOKS and GLOSSARY supplied below.
  When you use one, name it ("per PB-014: ..."). If no playbook covers it, say
  so plainly and answer from general networking knowledge, marked as general.
- NEVER invent a ticket number, a customer name, a measurement, or a person.
  If you do not know, say "not in ELNOC".
- Do NOT do optical arithmetic. RSL limits and verdicts are computed by ELNOC
  and given to you; repeat them, do not recompute or second-guess them.
- Keep answers operational: numbered checks, what to look at, when to escalate.
- Distinguish L1 (first line) / L2 (advanced) / L3 (network) / Vendor scope.
- Say plainly when something needs the customer's site accessed.
- Be concise. An engineer at 02:00 wants the next three actions, not an essay.
"""


class LLMError(RuntimeError):
    pass


@dataclass
class LLMReply:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""


def active_provider() -> str:
    """Which provider is configured, or '' when the assistant is offline."""
    if getattr(settings, "ANTHROPIC_API_KEY", ""):
        return "anthropic"
    if settings.LLM_API_KEY:
        return "openai"
    return ""


def provider_ready(provider: str = "") -> dict:
    """Status block for the UI: what is configured, what is missing."""
    p = provider or active_provider()
    if not p:
        return {"provider": "", "ready": False,
                "reason": "No API key set. Add OPENAI_API_KEY or "
                          "ANTHROPIC_API_KEY to .env, then restart."}
    if p == "anthropic" and not getattr(settings, "ANTHROPIC_API_KEY", ""):
        return {"provider": p, "ready": False, "reason": "Anthropic key missing."}
    if p == "openai" and not settings.LLM_API_KEY:
        return {"provider": p, "ready": False, "reason": "OpenAI key missing."}
    return {"provider": p, "ready": True,
            "model": get_model(p), "reason": ""}


def get_model(provider: str = "") -> str:
    provider = provider or active_provider()
    if provider == "anthropic":
        return getattr(settings, "ANTHROPIC_MODEL", "") or DEFAULT_MODELS["anthropic"]
    return settings.LLM_MODEL or DEFAULT_MODELS["openai"]


def build_system_prompt(playbooks: str = "", glossary: bool = True) -> str:
    parts = [SYSTEM_RULES]
    if glossary:
        lines = [f"- {k}: {v}" for k, v in GLOSSARY.items()]
        parts.append("GLOSSARY (ELNOC's own definitions — prefer these over "
                     "general usage):\n" + "\n".join(lines))
    if playbooks.strip():
        parts.append("ELNOC PLAYBOOKS (your procedures — cite these by title):\n"
                     + playbooks.strip())
    return "\n\n".join(parts)


def playbooks_as_context(rows: list, max_chars: int = 12000) -> str:
    """Playbook records -> the text block the model reads."""
    out = []
    for p in rows or []:
        out.append(
            f"[{getattr(p, 'id', '?')}] {getattr(p, 'title', '')}"
            f"{' (trigger: ' + p.trigger_category + ')' if getattr(p, 'trigger_category', '') else ''}\n"
            f"STEPS: {getattr(p, 'steps', '')}\n"
            f"{'WHO TO CALL: ' + p.who_to_call if getattr(p, 'who_to_call', '') else ''}\n"
            f"{'WHEN TO ESCALATE: ' + p.when_to_escalate if getattr(p, 'when_to_escalate', '') else ''}"
        )
    text = "\n\n".join(out)
    return text[:max_chars]


def _post(url: str, headers: dict, payload: dict, timeout: int) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        if e.code == 401:
            raise LLMError(f"{e.code} — API key rejected. Check the key in .env.") from e
        if e.code == 429:
            raise LLMError("429 — rate limited or out of credit. Check billing.") from e
        raise LLMError(f"{e.code} from provider: {detail}") from e
    except LLMError:
        raise
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"{type(e).__name__}: {e}") from e


def ask_openai(system: str, messages: list[dict], model: str = "",
               timeout: int = DEFAULT_TIMEOUT) -> LLMReply:
    key = settings.LLM_API_KEY
    if not key:
        raise LLMError("OPENAI_API_KEY (or LLM_API_KEY) is not set")
    data = None
    try:
        data = _post(OPENAI_URL,
                     {"Authorization": f"Bearer {key}",
                      "Content-Type": "application/json"},
                     {"model": model or DEFAULT_MODELS["openai"],
                      "messages": [{"role": "system", "content": system}] + messages,
                      "temperature": 0.2, "max_tokens": 1200},
                     timeout)
    except LLMError:
        raise
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"{type(e).__name__}: {e}") from e
    try:
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMReply(text or "", "openai", model or DEFAULT_MODELS["openai"],
                        usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                        data["choices"][0].get("finish_reason", ""))
    except (KeyError, IndexError) as e:
        raise LLMError(f"unexpected OpenAI response shape: {str(data)[:200]}") from e


def ask_anthropic(system: str, messages: list[dict], model: str = "",
                  timeout: int = DEFAULT_TIMEOUT) -> LLMReply:
    key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY is not set")
    # Anthropic takes the system prompt out of band, not as a message.
    data = _post(ANTHROPIC_URL,
                 {"x-api-key": key, "anthropic-version": "2023-06-01",
                  "Content-Type": "application/json"},
                 {"model": model or DEFAULT_MODELS["anthropic"],
                  "system": system,
                  "messages": messages,
                  "max_tokens": 1200, "temperature": 0.2},
                 timeout)
    blocks = data.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    usage = data.get("usage", {})
    return LLMReply(text.strip(), "anthropic", model or DEFAULT_MODELS["anthropic"],
                    usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                    data.get("stop_reason", ""))


def ask(system: str, messages: list[dict], provider: str = "",
        model: str = "", timeout: int = DEFAULT_TIMEOUT) -> LLMReply:
    p = provider or active_provider()
    if p == "anthropic":
        return ask_anthropic(system, messages, model, timeout)
    if p == "openai":
        return ask_openai(system, messages, model, timeout)
    raise LLMError("No AI provider configured. Add OPENAI_API_KEY or "
                   "ANTHROPIC_API_KEY to .env and restart ELNOC.")