from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .ir import linearize_baseline_thought, serialize_ir, to_lean_dict, to_rich_dict
from .schemas import (
    ProblemSpec,
    TestCaseSpec,
    Triple,
    dataclass_to_dict,
    dump_json,
    dump_text,
    load_json,
    problem_from_dict,
    tests_from_dict,
)
from .teacher import TeacherProvider, build_triple, load_teacher_provider
from .verifier import VerificationResult, verify_triple


@dataclass
class DistillResult:
    triple: Triple | None
    verification: VerificationResult | None
    attempts: int


def persist_teacher_raw(output_root: str | Path, triple: Triple, suffix: str) -> Path:
    path = Path(output_root) / "teacher_raw" / triple.problem_id / f"{suffix}.json"
    dump_json(path, dataclass_to_dict(triple))
    return path


def persist_verified(output_root: str | Path, triple: Triple) -> Path:
    path = Path(output_root) / "verified_triples" / f"{triple.problem_id}.json"
    dump_json(path, dataclass_to_dict(triple))
    return path


def _distill_with_provider(
    problem: ProblemSpec,
    tests: TestCaseSpec,
    provider: TeacherProvider,
    provider_name: str,
    output_root: str | Path,
    max_resamples: int = 8,
) -> DistillResult:
    """Adaptive Best-of-N with an already-constructed provider.

    Greedy (temp 0) first; on WA resample at temp 0.8 up to max_resamples times.
    """
    temperatures = [0.0] + [0.8] * max_resamples
    last_verification: VerificationResult | None = None

    for sample_idx, temperature in enumerate(temperatures):
        sample = provider.generate(problem, temperature=temperature, sample_idx=sample_idx)
        triple = build_triple(problem, sample, teacher_name=provider_name, sample_idx=sample_idx)
        persist_teacher_raw(output_root, triple, f"sample_{sample_idx}")

        verification = verify_triple(triple, tests)
        last_verification = verification
        if verification.verified:
            triple.verified = True
            persist_verified(output_root, triple)
            return DistillResult(triple=triple, verification=verification, attempts=sample_idx + 1)

    return DistillResult(triple=None, verification=last_verification, attempts=len(temperatures))


def run_distillation(
    problem: ProblemSpec,
    tests: TestCaseSpec,
    output_root: str | Path,
    provider_name: str = "mock",
    max_resamples: int = 8,
) -> DistillResult:
    provider = load_teacher_provider(provider_name)
    return _distill_with_provider(
        problem, tests, provider, provider_name, output_root, max_resamples
    )


def run_distillation_batch(
    problems_dir: str | Path,
    tests_dir: str | Path,
    output_root: str | Path,
    provider_name: str = "mock",
    max_resamples: int = 8,
    ir_format: str = "yaml",
) -> dict:
    """Distill a directory of problems with one shared provider, then derive 3 lines.

    Returns a data_gen metrics dict (doc section 4.1).
    """
    provider = load_teacher_provider(provider_name)
    problems_dir = Path(problems_dir)
    tests_dir = Path(tests_dir)

    start = time.time()
    kept = 0
    dropped = 0
    attempts_total = 0
    dropped_ids: list[str] = []

    for problem_path in sorted(problems_dir.glob("*.json")):
        problem = problem_from_dict(load_json(problem_path))
        tests_path = tests_dir / problem_path.name
        if not tests_path.exists():
            dropped += 1
            dropped_ids.append(problem.problem_id)
            continue
        tests = tests_from_dict(load_json(tests_path))

        result = _distill_with_provider(
            problem, tests, provider, provider_name, output_root, max_resamples
        )
        attempts_total += result.attempts
        if result.triple is not None:
            derive_training_samples(result.triple, output_root=output_root, ir_format=ir_format)
            kept += 1
        else:
            dropped += 1
            dropped_ids.append(problem.problem_id)

    total = kept + dropped
    metrics = {
        "api_calls": getattr(provider, "api_calls", 0),
        "tokens_in": getattr(provider, "tokens_in", 0),
        "tokens_out": getattr(provider, "tokens_out", 0),
        "wall_sec": round(time.time() - start, 2),
        "ac_rate": round(kept / total, 4) if total else 0.0,
        "kept": kept,
        "dropped": dropped,
        "avg_attempts": round(attempts_total / total, 2) if total else 0.0,
        "dropped_ids": dropped_ids,
    }
    return metrics


def derive_training_samples(
    triple: Triple,
    output_root: str | Path,
    ir_format: str = "yaml",
) -> None:
    rich_dict = to_rich_dict(triple.codeir)
    lean_dict = to_lean_dict(triple.codeir)
    rich_text = serialize_ir(rich_dict, fmt=ir_format)
    lean_text = serialize_ir(lean_dict, fmt=ir_format)
    baseline_text = linearize_baseline_thought(triple.codeir)

    arm_a = {
        "instruction": "Output CodeIR only. Do not write code.",
        "input": f"{triple.statement}\n\n{triple.signature}",
        "output": rich_text,
    }
    arm_b = {
        "instruction": "Translate CodeIR into Python without changing the logic.",
        "input": rich_text,
        "output": triple.code,
    }
    baseline = {
        "instruction": "Think first, then write code.",
        "input": f"{triple.statement}\n\n{triple.signature}",
        "output": f"{baseline_text}\n\n{triple.code}",
    }

    root = Path(output_root)
    dump_text(root / "ir_variants" / "rich" / f"{triple.problem_id}.{ir_format}", rich_text)
    dump_text(root / "ir_variants" / "lean" / f"{triple.problem_id}.{ir_format}", lean_text)
    dump_json(root / "sft_armA" / f"{triple.problem_id}.json", arm_a)
    dump_json(root / "sft_armB" / f"{triple.problem_id}.json", arm_b)
    dump_json(root / "sft_baseline" / f"{triple.problem_id}.json", baseline)


def derive_from_directory(
    verified_root: str | Path,
    output_root: str | Path,
    ir_format: str = "yaml",
) -> int:
    from .schemas import load_json, triple_from_dict

    count = 0
    for path in Path(verified_root).glob("*.json"):
        triple = triple_from_dict(load_json(path))
        derive_training_samples(triple, output_root=output_root, ir_format=ir_format)
        count += 1
    return count
