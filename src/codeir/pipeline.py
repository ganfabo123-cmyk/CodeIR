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
    error: str = ""  # set when generation (API/JSON parse) failed, vs plain WA


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
    last_error = ""

    for sample_idx, temperature in enumerate(temperatures):
        # Generation (API call + JSON parse) can fail; treat it as a failed
        # attempt and resample rather than crashing the whole batch.
        try:
            sample = provider.generate(problem, temperature=temperature, sample_idx=sample_idx)
        except Exception as exc:  # noqa: BLE001 - API/parse errors are expected
            last_error = f"{type(exc).__name__}: {exc}"
            continue

        triple = build_triple(problem, sample, teacher_name=provider_name, sample_idx=sample_idx)
        persist_teacher_raw(output_root, triple, f"sample_{sample_idx}")

        verification = verify_triple(triple, tests)
        last_verification = verification
        if verification.verified:
            triple.verified = True
            persist_verified(output_root, triple)
            return DistillResult(triple=triple, verification=verification, attempts=sample_idx + 1)

    return DistillResult(
        triple=None,
        verification=last_verification,
        attempts=len(temperatures),
        error=last_error,
    )


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
    resume: bool = True,
    abort_after_errors: int = 8,
    skip_ids: set[str] | None = None,
) -> dict:
    """Distill a directory of problems with one shared provider, then derive 3 lines.

    - resume: skip problems whose verified triple already exists (no re-spend).
    - abort_after_errors: stop early after this many consecutive *generation*
      failures (likely API down / out of credit); 0 disables.
    Per-problem errors never crash the batch. Returns a data_gen metrics dict.
    """
    provider = load_teacher_provider(provider_name)
    problems_dir = Path(problems_dir)
    tests_dir = Path(tests_dir)
    verified_dir = Path(output_root) / "verified_triples"

    start = time.time()
    kept = 0
    resumed = 0
    dropped = 0
    skiplisted = 0
    attempts_total = 0
    dropped_ids: list[str] = []
    error_streak = 0
    aborted = False

    problem_paths = sorted(problems_dir.glob("*.json"))
    total_n = len(problem_paths)

    for idx, problem_path in enumerate(problem_paths, start=1):
        problem = problem_from_dict(load_json(problem_path))
        pid = problem.problem_id

        if skip_ids and pid in skip_ids:
            skiplisted += 1
            print(f"[{idx}/{total_n}] {pid} -> skip (in skip-list)", flush=True)
            continue

        if resume and (verified_dir / f"{pid}.json").exists():
            kept += 1
            resumed += 1
            print(f"[{idx}/{total_n}] {pid} -> skip (already verified)", flush=True)
            continue

        tests_path = tests_dir / problem_path.name
        if not tests_path.exists():
            dropped += 1
            dropped_ids.append(pid)
            print(f"[{idx}/{total_n}] {pid} -> drop (no tests file)", flush=True)
            continue
        tests = tests_from_dict(load_json(tests_path))

        try:
            result = _distill_with_provider(
                problem, tests, provider, provider_name, output_root, max_resamples
            )
        except Exception as exc:  # noqa: BLE001 - never let one problem kill the batch
            dropped += 1
            dropped_ids.append(pid)
            error_streak += 1
            print(f"[{idx}/{total_n}] {pid} -> ERROR {type(exc).__name__}: {exc}", flush=True)
            if abort_after_errors and error_streak >= abort_after_errors:
                aborted = True
                break
            continue

        attempts_total += result.attempts
        if result.triple is not None:
            derive_training_samples(result.triple, output_root=output_root, ir_format=ir_format)
            kept += 1
            error_streak = 0
            print(f"[{idx}/{total_n}] {pid} -> AC (attempts={result.attempts})", flush=True)
        else:
            dropped += 1
            dropped_ids.append(pid)
            if result.error:  # generation failure (API/parse), not a plain WA
                error_streak += 1
                print(f"[{idx}/{total_n}] {pid} -> drop (gen error: {result.error[:120]})", flush=True)
                if abort_after_errors and error_streak >= abort_after_errors:
                    aborted = True
                    break
            else:
                error_streak = 0
                print(f"[{idx}/{total_n}] {pid} -> drop (WA after {result.attempts} attempts)", flush=True)

    if aborted:
        print(
            f"ABORTED after {error_streak} consecutive generation errors "
            f"(API down or out of credit?). Recharge and rerun to resume.",
            flush=True,
        )

    total = kept + dropped
    metrics = {
        "api_calls": getattr(provider, "api_calls", 0),
        "tokens_in": getattr(provider, "tokens_in", 0),
        "tokens_out": getattr(provider, "tokens_out", 0),
        "wall_sec": round(time.time() - start, 2),
        "ac_rate": round(kept / total, 4) if total else 0.0,
        "kept": kept,
        "resumed": resumed,
        "dropped": dropped,
        "skiplisted": skiplisted,
        "aborted": aborted,
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
    # The teacher often leaves codeir.signature null, which strips the method
    # interface from the IR. armB sees ONLY the IR, so without the signature it
    # guesses the method name/params and the verifier raises AttributeError.
    # triple.signature is the authoritative interface (LeetCode starter_code);
    # force it into the IR so armA learns to emit it and armB has an anchor.
    rich_dict["signature"] = triple.signature
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
