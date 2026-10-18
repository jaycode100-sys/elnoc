"""AI assistant tests: guardrails, provider shapes, playbook grounding, logging."""
from __future__ import annotations
import json
import sys
import types
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import llm  # noqa: E402


class FakeResp:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _settings(**kw):
    base = {"LLM_API_KEY": "", "LLM_MODEL": "", "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_MODEL": "", "ASSISTANT_DAILY_CAP": 200,
            "ASSISTANT_HISTORY_TURNS": 8}
    base.update(kw)
    return types.SimpleNamespace(**base)


def _patch(m):
    orig = llm.settings
    llm.settings = _settings(**m)
    return orig


# ---------- provider detection / readiness

def test_no_provider_is_offline_and_says_why():
    orig = _patch({})
    try:
        assert llm.active_provider() == ""
        st = llm.provider_ready()
        assert st["ready"] is False
        assert "API key" in st["reason"]
    finally:
        llm.settings = orig


def test_openai_detected():
    orig = _patch({"LLM_API_KEY": "sk-test"})
    try:
        assert llm.active_provider() == "openai"
        assert llm.provider_ready()["ready"] is True
    finally:
        llm.settings = orig


def test_anthropic_wins_when_both_set():
    orig = _patch({"LLM_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "sk-ant"})
    try:
        assert llm.active_provider() == "anthropic"
    finally:
        llm.settings = orig


def test_models_have_defaults():
    orig = _patch({"LLM_API_KEY": "k"})
    try:
        assert llm.get_model("openai") == llm.DEFAULT_MODELS["openai"]
        assert llm.get_model("anthropic") == llm.DEFAULT_MODELS["anthropic"]
    finally:
        llm.settings = orig


# ---------- request shapes (the two APIs differ in ways that matter)

def test_openai_request_shape(monkeypatch):
    orig = _patch({"LLM_API_KEY": "sk-test"})
    seen = {}

    def fake(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.headers)
        seen["body"] = json.loads(req.data.decode())
        return FakeResp({"choices": [{"message": {"content": "hi"},
                                      "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 11, "completion_tokens": 4}})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    try:
        r = llm.ask_openai("SYS", [{"role": "user", "content": "q"}])
    finally:
        llm.settings = orig
    assert seen["url"] == llm.OPENAI_URL
    assert seen["headers"]["Authorization"] == "Bearer sk-test"
    # system prompt must be a message, and first
    assert seen["body"]["messages"][0]["role"] == "system"
    assert seen["body"]["messages"][0]["content"] == "SYS"
    assert r.text == "hi" and r.input_tokens == 11 and r.output_tokens == 4


def test_anthropic_request_shape(monkeypatch):
    orig = _patch({"ANTHROPIC_API_KEY": "sk-ant"})
    seen = {}

    def fake(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.headers)
        seen["body"] = json.loads(req.data.decode())
        return FakeResp({"content": [{"type": "text", "text": "answer"}],
                         "usage": {"input_tokens": 7, "output_tokens": 3},
                         "stop_reason": "end_turn"})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    try:
        r = llm.ask_anthropic("SYS", [{"role": "user", "content": "q"}])
    finally:
        llm.settings = orig
    assert seen["url"] == llm.ANTHROPIC_URL
    # urllib capitalises header names, so compare case-insensitively
    lower = {k.lower(): v for k, v in seen["headers"].items()}
    assert lower["x-api-key"] == "sk-ant"
    assert lower["anthropic-version"] == "2023-06-01"
    # Anthropic takes system out of band, NOT as a message
    assert seen["body"]["system"] == "SYS"
    assert all(m["role"] != "system" for m in seen["body"]["messages"])
    assert r.text == "answer" and r.provider == "anthropic"


def test_anthropic_joins_multiple_text_blocks(monkeypatch):
    orig = _patch({"ANTHROPIC_API_KEY": "sk-ant"})
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeResp(
        {"content": [{"type": "text", "text": "part one "},
                     {"type": "thinking", "thinking": "ignored"},
                     {"type": "text", "text": "part two"}]}))
    try:
        r = llm.ask_anthropic("s", [])
    finally:
        llm.settings = orig
    assert r.text == "part one part two"


# ---------- error handling

def test_missing_key_raises_actionable_error():
    orig = _patch({})
    try:
        with pytest.raises(llm.LLMError) as e:
            llm.ask("s", [])
        # the message must tell the engineer exactly what to do
        assert "ANTHROPIC_API_KEY" in str(e.value)
        assert "OPENAI_API_KEY" in str(e.value)
    finally:
        llm.settings = orig


def test_bad_key_message_is_actionable(monkeypatch):
    orig = _patch({"LLM_API_KEY": "sk-bad"})

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    try:
        with pytest.raises(llm.LLMError, match="rejected"):
            llm.ask_openai("s", [])
    finally:
        llm.settings = orig


def test_rate_limit_message_mentions_billing(monkeypatch):
    orig = _patch({"LLM_API_KEY": "sk"})

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    try:
        with pytest.raises(llm.LLMError, match="credit"):
            llm.ask_openai("s", [])
    finally:
        llm.settings = orig


def test_malformed_response_does_not_leak_raw(monkeypatch):
    orig = _patch({"LLM_API_KEY": "sk"})
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeResp(
        {"unexpected": True}))
    try:
        with pytest.raises(llm.LLMError, match="unexpected OpenAI response"):
            llm.ask_openai("s", [])
    finally:
        llm.settings = orig


# ---------- grounding: playbooks and rules reach the model

def test_system_prompt_carries_rules_glossary_and_playbooks():
    s = llm.build_system_prompt("PB: Fibre cut\nSTEPS: OTDR first")
    assert "PLAYBOOKS" in s
    assert "OTDR first" in s
    assert "GLOSSARY" in s
    assert "rsl" in s.lower()
    # the hard rules must be present verbatim in intent
    assert "NEVER invent a ticket number" in s
    assert "do not recompute" in s.lower()


def test_playbook_context_includes_trigger_and_escalation():
    p = types.SimpleNamespace(id=14, title="Fibre cut",
                              trigger_category="fibre",
                              steps="OTDR from both ends",
                              who_to_call="Fibre team", when_to_escalate="no light after 2h")
    ctx = llm.playbooks_as_context([p])
    assert "[14] Fibre cut" in ctx
    assert "trigger: fibre" in ctx
    assert "OTDR from both ends" in ctx
    assert "WHEN TO ESCALATE: no light after 2h" in ctx


def test_playbook_context_is_truncated():
    rows = [types.SimpleNamespace(id=i, title=f"T{i}", trigger_category="x",
                                  steps="y" * 5000, who_to_call="", when_to_escalate="")
            for i in range(20)]
    assert len(llm.playbooks_as_context(rows, max_chars=3000)) == 3000


def test_playbook_citation_detection():
    from app.routers.assistant import _playbook_refs
    p = types.SimpleNamespace(id=14, title="Fibre cut")
    assert _playbook_refs("Per PB-14, OTDR first.", [p]) == "Fibre cut"
    assert _playbook_refs("No procedure used.", [p]) == ""


# ---------- offline fallback still useful without a provider

def test_offline_rsl_fallback_computes_in_code():
    from app.routers.assistant import _offline_answer
    out = _offline_answer("what does -29 dBm mean?", None)
    assert "-29" in out and "dBm" in out
    assert "FAIL" in out or "MARGINAL" in out
    assert "offline tool" in out