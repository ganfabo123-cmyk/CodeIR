from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import json
import os

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

    def generate(
        self,
        problem: ProblemSpec,
        temperature: float,
        sample_idx: int,
    ) -> TeacherSample:
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
        except ImportError as exc:
            raise RuntimeError(
                "transformers provider unavailable; install transformers/bitsandbytes first."
            ) from exc

        tokenizer = AutoTokenizer.from_pretrained(self.model_path, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            device_map="auto",
            trust_remote_code=True,
            load_in_8bit=True,
        )
        generator = pipeline("text-generation", model=model, tokenizer=tokenizer)
        prompt = build_teacher_prompt(problem)
        text = generator(
            prompt,
            do_sample=temperature > 0,
            temperature=max(temperature, 1e-5),
            max_new_tokens=2048,
            return_full_text=False,
        )[0]["generated_text"]
        raw = json.loads(text)
        return TeacherSample(
            codeir=codeir_from_dict(raw["codeir"]),
            code=raw["code"],
        )


def build_teacher_prompt(problem: ProblemSpec) -> str:
    return (
        "你是算法竞赛专家。给定一道编程题，先输出结构化解题中间表示(CodeIR)，"
        "再输出对应 Python 代码。输出必须是 JSON，字段包含 codeir 和 code。\n\n"
        f"problem_id: {problem.problem_id}\n"
        f"difficulty: {problem.difficulty}\n"
        f"signature: {problem.signature}\n"
        f"statement:\n{problem.statement}"
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
    raise ValueError(f"Unknown provider: {provider_name}")
