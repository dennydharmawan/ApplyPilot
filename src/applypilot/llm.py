from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_CODEX_MODEL = "gpt-5.6-luna"
_CODEX_REASONING = "high"
_CODEX_TIMEOUT = 300
_MAX_RETRIES = 5
_TIMEOUT = 120
_RATE_LIMIT_BASE_WAIT = 10
_GEMINI_COMPAT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
_GEMINI_NATIVE_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _messages_to_prompt(messages: list[dict]) -> str:
    parts: list[str] = []
    for msg in messages:
        role = str(msg.get("role", "user")).upper()
        content = str(msg.get("content", ""))
        parts.append(f"{role}:\n{content}")
    parts.append(
        "Reply with only the requested output. Do not use tools or edit files."
    )
    return "\n\n".join(parts)


class CodexExecClient:
    def __init__(
        self,
        binary: str,
        model: str,
        reasoning_effort: str,
        timeout: int = _CODEX_TIMEOUT,
    ) -> None:
        self.binary = binary
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        del temperature, max_tokens
        prompt = _messages_to_prompt(messages)
        with tempfile.TemporaryDirectory(prefix="applypilot-codex-") as tmp:
            last_path = Path(tmp) / "last.txt"
            cmd = [
                self.binary,
                "exec",
                "--skip-git-repo-check",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--ignore-user-config",
                "--color",
                "never",
                "-m",
                self.model,
                "-c",
                f'model_reasoning_effort="{self.reasoning_effort}"',
                "-C",
                tmp,
                "-o",
                str(last_path),
                "-",
            ]
            log.info("LLM provider: codex exec  model: %s  effort: %s", self.model, self.reasoning_effort)
            try:
                proc = subprocess.run(
                    cmd,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"codex exec timed out after {self.timeout}s"
                ) from exc
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()[-500:]
                raise RuntimeError(f"codex exec exited {proc.returncode}: {err}")
            if not last_path.exists():
                raise RuntimeError("codex exec produced no last-message file")
            text = last_path.read_text(encoding="utf-8").strip()
            if not text:
                raise RuntimeError("codex exec last message was empty")
            return text

    def ask(self, prompt: str, **kwargs) -> str:
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    def close(self) -> None:
        return


class LLMClient:
    def __init__(self, base_url: str, model: str, api_key: str) -> None:
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self._client = httpx.Client(timeout=_TIMEOUT)
        self._use_native_gemini: bool = False
        self._is_gemini: bool = base_url.startswith(_GEMINI_COMPAT_BASE)

    def _chat_native_gemini(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        contents: list[dict] = []
        system_parts: list[dict] = []

        for msg in messages:
            role = msg["role"]
            text = msg.get("content", "")
            if role == "system":
                system_parts.append({"text": text})
            elif role == "user":
                contents.append({"role": "user", "parts": [{"text": text}]})
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": text}]})

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        url = f"{_GEMINI_NATIVE_BASE}/models/{self.model}:generateContent"
        resp = self._client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            params={"key": self.api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def _chat_compat(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
        )

        if resp.status_code == 403 and self._is_gemini:
            raise _GeminiCompatForbidden(resp)

        return self._handle_compat_response(resp)

    @staticmethod
    def _handle_compat_response(resp: httpx.Response) -> str:
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        if "qwen" in self.model.lower() and messages:
            first = messages[0]
            if first.get("role") == "user" and not first["content"].startswith("/no_think"):
                messages = [{"role": first["role"], "content": f"/no_think\n{first['content']}"}] + messages[1:]

        for attempt in range(_MAX_RETRIES):
            try:
                if self._use_native_gemini:
                    return self._chat_native_gemini(messages, temperature, max_tokens)

                return self._chat_compat(messages, temperature, max_tokens)

            except _GeminiCompatForbidden:
                log.warning(
                    "Gemini compat endpoint returned 403 for model '%s'. "
                    "Switching to native generateContent API.",
                    self.model,
                )
                self._use_native_gemini = True
                try:
                    return self._chat_native_gemini(messages, temperature, max_tokens)
                except httpx.HTTPStatusError as native_exc:
                    raise RuntimeError(
                        f"Both Gemini endpoints failed. Compat: 403 Forbidden. "
                        f"Native: {native_exc.response.status_code} — "
                        f"{native_exc.response.text[:200]}"
                    ) from native_exc

            except httpx.HTTPStatusError as exc:
                resp = exc.response
                if resp.status_code in (429, 503) and attempt < _MAX_RETRIES - 1:
                    retry_after = (
                        resp.headers.get("Retry-After")
                        or resp.headers.get("X-RateLimit-Reset-Requests")
                    )
                    if retry_after:
                        try:
                            wait = float(retry_after)
                        except (ValueError, TypeError):
                            wait = _RATE_LIMIT_BASE_WAIT * (2 ** attempt)
                    else:
                        wait = min(_RATE_LIMIT_BASE_WAIT * (2 ** attempt), 60)

                    log.warning(
                        "LLM rate limited (HTTP %s). Waiting %ds before retry %d/%d.",
                        resp.status_code, wait, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                raise

            except httpx.TimeoutException:
                if attempt < _MAX_RETRIES - 1:
                    wait = min(_RATE_LIMIT_BASE_WAIT * (2 ** attempt), 60)
                    log.warning(
                        "LLM request timed out, retrying in %ds (attempt %d/%d)",
                        wait, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                raise

        raise RuntimeError("LLM request failed after all retries")

    def ask(self, prompt: str, **kwargs) -> str:
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    def close(self) -> None:
        self._client.close()


class _GeminiCompatForbidden(Exception):
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"Gemini compat 403: {response.text[:200]}")


_instance = None


def _forced_provider() -> str:
    return os.environ.get("LLM_PROVIDER", "").strip().lower()


def _http_provider() -> tuple[str, str, str] | None:
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    local_url = os.environ.get("LLM_URL", "")
    model_override = os.environ.get("LLM_MODEL", "")
    forced = _forced_provider()

    if forced == "gemini" or (not forced and gemini_key and not local_url):
        if not gemini_key:
            return None
        return (
            "https://generativelanguage.googleapis.com/v1beta/openai",
            model_override or "gemini-2.0-flash",
            gemini_key,
        )

    if forced == "openai" or (not forced and openai_key and not local_url):
        if not openai_key:
            return None
        return (
            "https://api.openai.com/v1",
            model_override or "gpt-4o-mini",
            openai_key,
        )

    if forced == "local" or local_url:
        if not local_url:
            return None
        return (
            local_url.rstrip("/"),
            model_override or "local-model",
            os.environ.get("LLM_API_KEY", ""),
        )

    return None


def get_client():
    global _instance
    if _instance is not None:
        return _instance

    forced = _forced_provider()
    codex_bin = shutil.which("codex")
    use_codex = forced == "codex" or (not forced and codex_bin)

    if use_codex:
        if not codex_bin:
            raise RuntimeError("LLM_PROVIDER=codex but `codex` is not on PATH")
        _instance = CodexExecClient(
            binary=codex_bin,
            model=os.environ.get("LLM_MODEL", _CODEX_MODEL),
            reasoning_effort=os.environ.get("LLM_REASONING_EFFORT", _CODEX_REASONING),
        )
        return _instance

    http = _http_provider()
    if http is None:
        raise RuntimeError(
            "No LLM provider configured. Install Codex CLI (`codex` on PATH) "
            "or set GEMINI_API_KEY, OPENAI_API_KEY, or LLM_URL."
        )
    base_url, model, api_key = http
    log.info("LLM provider: %s  model: %s", base_url, model)
    _instance = LLMClient(base_url, model, api_key)
    return _instance
