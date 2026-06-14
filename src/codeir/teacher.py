from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import json
import os

from .parsing import extract_json_block
from .schemas import CodeIR, ProblemSpec, Triple, codeir_from_dict


@dataclass
class TeacherSample:
    codeir: CodeIR
    code: str


class TeacherProvider(ABC):
    @abstractmethod
    def generate(
        self,
        problem: ProblemSpec,
        temperature: float,
        sample_idx: int,
    ) -> TeacherSample:
        raise NotImplementedError


class MockTeacherProvider(TeacherProvider):
    def __init__(self, fixture_dir: str | Path) -> None:
        self.fixture_dir = Path(fixture_dir)

    def generate(
        self,
        problem: ProblemSpec,
        temperature: float,
        sample_idx: int,
    ) -> TeacherSample:
        fixture_path = self.fixture_dir / f"{problem.problem_id}.json"
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
        return TeacherSample(
            codeir=codeir_from_dict(raw["codeir"]),
            code=raw["code"],
        )


class TransformersTeacherProvider(TeacherProvider):
    def __init__(self, model_path: str) -> None:
        self.model_path = model_path
        self._model = None
        self._tokenizer = None

    def _ensure_model(self) -> tuple[object, object]:
        if self._model is not None and self._tokenizer is not None:
            return self._model, self._tokenizer

        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        except ImportError as exc:
            raise RuntimeError(
                "transformers provider unavailable; install transformers/bitsandbytes first."
            ) from exc

        tokenizer = AutoTokenizer.from_pretrained(self.model_path, trust_remote_code=True)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token

        model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            device_map="auto",
            trust_remote_code=True,
            quantization_config=BitsAndBytesConfig(load_in_8bit=True),
        )
        self._model = model
        self._tokenizer = tokenizer
        return model, tokenizer

    def generate(
        self,
        problem: ProblemSpec,
        temperature: float,
        sample_idx: int,
    ) -> TeacherSample:
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("transformers provider requires torch to run generation.") from exc

        model, tokenizer = self._ensure_model()
        messages = [{"role": "user", "content": build_teacher_prompt(problem)}]
        rendered = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        )
        if hasattr(rendered, "to") and hasattr(rendered, "input_ids"):
            rendered = rendered.to(model.device)
            input_ids = rendered.input_ids
            attention_mask = rendered.attention_mask
        else:
            input_ids = rendered.to(model.device) if hasattr(rendered, "to") else torch.as_tensor(rendered, device=model.device)
            attention_mask = torch.ones_like(input_ids)

        generation_kwargs = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "max_new_tokens": 2048,
            "pad_token_id": tokenizer.pad_token_id,
            "eos_token_id": tokenizer.eos_token_id,
            "do_sample": temperature > 0,
        }
        if temperature > 0:
            generation_kwargs["temperature"] = temperature

        with torch.inference_mode():
            outputs = model.generate(**generation_kwargs)

        generated_ids = outputs[0][input_ids.shape[-1] :]
        text = tokenizer.decode(generated_ids, skip_special_tokens=True)
        raw = extract_json_block(text)
        _validate_teacher_payload(raw)
        return TeacherSample(
            codeir=codeir_from_dict(raw["codeir"]),
            code=raw["code"],
        )


def build_teacher_prompt(problem: ProblemSpec) -> str:
    return (
        "You are an algorithms expert.\n"
        "Produce CodeIR first, then produce Python code that passes the tests.\n"
        "Output exactly one JSON object and nothing else. No markdown, no code fences, no prose.\n"
        "The top-level JSON schema must be:\n"
        '{\n  "codeir": {...},\n  "code": "full Python code"\n}\n'
        "The codeir object must follow this schema exactly:\n"
        '- Required fields: `pattern` (string), `key_insight` (string), `algorithm` (array of strings)\n'
        '- Optional fields: `signature` (string), `data_structures` (array of strings), '
        '`complexity` (object with `time` and `space` strings), `edge_cases` (array of strings)\n'
        "- Extra fields `state` and `transition` are allowed, but do not omit any required fields.\n"
        "- `algorithm` must be a step-by-step array of strings.\n"
        "- `code` must be complete executable Python, define `class Solution`, and implement the required method.\n\n"
        f"problem_id: {problem.problem_id}\n"
        f"difficulty: {problem.difficulty}\n"
        f"signature: {problem.signature}\n"
        f"statement:\n{problem.statement}"
    )


def _validate_teacher_payload(raw: dict) -> None:
    if "codeir" not in raw or not isinstance(raw["codeir"], dict):
        raise ValueError(f"Teacher output missing object field 'codeir': {raw!r}")
    if "code" not in raw or not isinstance(raw["code"], str) or not raw["code"].strip():
        raise ValueError(f"Teacher output missing non-empty string field 'code': {raw!r}")

    missing = [
        field
        for field in ("pattern", "key_insight", "algorithm")
        if field not in raw["codeir"]
    ]
    if missing:
        raise ValueError(f"Teacher codeir missing required fields {missing}: {raw['codeir']!r}")
    if not isinstance(raw["codeir"]["algorithm"], list) or not all(
        isinstance(step, str) for step in raw["codeir"]["algorithm"]
    ):
        raise ValueError(f"Teacher codeir field 'algorithm' must be a string array: {raw['codeir']!r}")

    complexity = raw["codeir"].get("complexity")
    if complexity is not None:
        if not isinstance(complexity, dict) or "time" not in complexity or "space" not in complexity:
            raise ValueError(
                f"Teacher codeir field 'complexity' must contain 'time' and 'space': {raw['codeir']!r}"
            )


def build_triple(
    problem: ProblemSpec,
    sample: TeacherSample,
    teacher_name: str,
    sample_idx: int,
) -> Triple:
    return Triple(
        problem_id=problem.problem_id,
        difficulty=problem.difficulty,
        statement=problem.statement,
        signature=problem.signature,
        codeir=sample.codeir,
        code=sample.code,
        teacher=teacher_name,
        sample_idx=sample_idx,
        verified=False,
    )


def load_teacher_provider(
    provider_name: str,
    fixture_dir: str | Path = "examples/teacher_mock",
) -> TeacherProvider:
    if provider_name == "mock":
        return MockTeacherProvider(fixture_dir)
    if provider_name == "transformers":
        model_path = os.environ.get("CODEIR_MODEL_PATH")
        if not model_path:
            raise RuntimeError("CODEIR_MODEL_PATH is required for transformers provider.")
        return TransformersTeacherProvider(model_path)
    if provider_name == "api":
        from .teacher_api import build_api_provider_from_env

        return build_api_provider_from_env()
    raise ValueError(f"Unknown provider: {provider_name}")
