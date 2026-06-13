from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import json


@dataclass
class Complexity:
    time: str
    space: str


@dataclass
class CodeIR:
    pattern: str
    key_insight: str
    algorithm: list[str]
    signature: str | None = None
    data_structures: list[str] = field(default_factory=list)
    complexity: Complexity | None = None
    edge_cases: list[str] = field(default_factory=list)
    state: str | None = None
    transition: str | None = None


@dataclass
class Triple:
    problem_id: str
    difficulty: str
    statement: str
    signature: str
    codeir: CodeIR
    code: str
    verified: bool = False
    teacher: str = ""
    sample_idx: int = 0


@dataclass
class TestCaseSpec:
    problem_id: str
    entry_point: str
    test_cases: list[dict[str, Any]]
    timeout_sec: int = 10


@dataclass
class ProblemSpec:
    problem_id: str
    difficulty: str
    statement: str
    signature: str


def _complexity_from_raw(raw: dict[str, Any] | None) -> Complexity | None:
    if raw is None:
        return None
    return Complexity(time=raw["time"], space=raw["space"])


def codeir_from_dict(raw: dict[str, Any]) -> CodeIR:
    return CodeIR(
        signature=raw.get("signature"),
        pattern=raw["pattern"],
        key_insight=raw["key_insight"],
        data_structures=raw.get("data_structures", []),
        algorithm=raw["algorithm"],
        complexity=_complexity_from_raw(raw.get("complexity")),
        edge_cases=raw.get("edge_cases", []),
        state=raw.get("state"),
        transition=raw.get("transition"),
    )


def triple_from_dict(raw: dict[str, Any]) -> Triple:
    return Triple(
        problem_id=raw["problem_id"],
        difficulty=raw["difficulty"],
        statement=raw["statement"],
        signature=raw["signature"],
        codeir=codeir_from_dict(raw["codeir"]),
        code=raw["code"],
        verified=raw.get("verified", False),
        teacher=raw.get("teacher", ""),
        sample_idx=raw.get("sample_idx", 0),
    )


def tests_from_dict(raw: dict[str, Any]) -> TestCaseSpec:
    return TestCaseSpec(
        problem_id=raw["problem_id"],
        entry_point=raw["entry_point"],
        test_cases=raw["test_cases"],
        timeout_sec=raw.get("timeout_sec", 10),
    )


def problem_from_dict(raw: dict[str, Any]) -> ProblemSpec:
    return ProblemSpec(
        problem_id=raw["problem_id"],
        difficulty=raw["difficulty"],
        statement=raw["statement"],
        signature=raw["signature"],
    )


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(path: str | Path, payload: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def dump_text(path: str | Path, content: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")


def dataclass_to_dict(value: Any) -> Any:
    return asdict(value)
