from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .parsing import extract_json_block
from .schemas import ProblemSpec, codeir_from_dict
from .teacher import TeacherProvider, TeacherSample, _validate_teacher_payload, build_teacher_prompt


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader: KEY=VALUE per line, does not override existing env vars.

    Avoids adding python-dotenv as a dependency. Blank lines and lines starting
    with '#' are ignored. Surrounding quotes on the value are stripped.
    """
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class ApiTeacherProvider(TeacherProvider):
    """OpenAI-compatible API teacher (e.g. DashScope qwen3-30b-a3b).

    Reads credentials from environment (populated from .env by load_dotenv):
      - LLM_API_KEY        : API key
      - LLM_API_BASE_URL   : OpenAI-compatible base url (".../compatible-mode/v1")
      - LLM_MODEL          : model id

    Exposes cumulative counters for metrics: api_calls, tokens_in, tokens_out.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int = 2048,
        request_timeout: int = 120,
        max_http_retries: int = 4,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.request_timeout = request_timeout
        self.max_http_retries = max_http_retries
        self.api_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def _post_chat(self, prompt: str, temperature: float) -> dict:
        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
            "temperature": temperature,
        }
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_err: Exception | None = None
        for attempt in range(self.max_http_retries):
            request = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.request_timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                self.api_calls += 1
                usage = payload.get("usage", {}) or {}
                self.tokens_in += int(usage.get("prompt_tokens", 0) or 0)
                self.tokens_out += int(usage.get("completion_tokens", 0) or 0)
                return payload
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                last_err = exc
                time.sleep(2 ** attempt)
        raise RuntimeError(
            f"API request failed after {self.max_http_retries} retries: {last_err!r}"
        )

    def generate(
        self,
        problem: ProblemSpec,
        temperature: float,
        sample_idx: int,
    ) -> TeacherSample:
        prompt = build_teacher_prompt(problem)
        payload = self._post_chat(prompt, temperature)
        content = payload["choices"][0]["message"]["content"]
        raw = extract_json_block(content)
        _validate_teacher_payload(raw)
        return TeacherSample(
            codeir=codeir_from_dict(raw["codeir"]),
            code=raw["code"],
        )


def build_api_provider_from_env() -> ApiTeacherProvider:
    load_dotenv()
    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_API_BASE_URL")
    model = os.environ.get("LLM_MODEL")
    missing = [
        name
        for name, value in (
            ("LLM_API_KEY", api_key),
            ("LLM_API_BASE_URL", base_url),
            ("LLM_MODEL", model),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"Missing required env vars for api provider: {missing} (set them in .env)"
        )
    return ApiTeacherProvider(api_key=api_key, base_url=base_url, model=model)
