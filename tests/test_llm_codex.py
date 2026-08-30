from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from applypilot import llm
from applypilot.llm import CodexExecClient, _messages_to_prompt, get_client


def test_messages_to_prompt_includes_roles_and_no_tools():
    text = _messages_to_prompt(
        [
            {"role": "system", "content": "Score jobs."},
            {"role": "user", "content": "RESUME:\nPipin"},
        ]
    )
    assert "SYSTEM:\nScore jobs." in text
    assert "USER:\nRESUME:\nPipin" in text
    assert "Do not use tools" in text


def test_codex_exec_client_reads_last_message(monkeypatch):
    def fake_run(cmd, input, capture_output, text, timeout, check):
        out = Path(cmd[cmd.index("-o") + 1])
        out.write_text("SCORE: 8\nKEYWORDS: hr\nREASONING: strong fit\n", encoding="utf-8")
        assert cmd[0] == "/usr/bin/codex"
        assert "exec" in cmd
        assert "-m" in cmd and "gpt-5.6-luna" in cmd
        assert 'model_reasoning_effort="high"' in cmd
        assert input.startswith("USER:\nhello")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    client = CodexExecClient("/usr/bin/codex", "gpt-5.6-luna", "high")
    assert client.ask("hello") == "SCORE: 8\nKEYWORDS: hr\nREASONING: strong fit"


def test_get_client_prefers_codex(monkeypatch):
    llm._instance = None
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/opt/codex" if name == "codex" else None)
    client = get_client()
    assert isinstance(client, CodexExecClient)
    assert client.model == "gpt-5.6-luna"
    assert client.reasoning_effort == "high"
    llm._instance = None
