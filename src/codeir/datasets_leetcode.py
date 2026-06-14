from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .schemas import dump_json

# LeetCodeDataset (newfacade/LeetCodeDataset) field -> project format.
# Mapping confirmed against the dataset README data-fields section. The exact
# check() invocation is locked in verifier._build_check_runner (method-bound,
# LeetCodeDataset convention) and must be re-confirmed on the first smoke run.

_DIFFICULTY_RANK = {"easy": 0, "medium": 1, "hard": 2}


def _slug(task_id: str) -> str:
    """Filesystem-safe problem id derived from the dataset task_id slug."""
    return re.sub(r"[^0-9a-zA-Z_-]", "_", str(task_id))


def map_record(rec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map one dataset record into (problem_dict, tests_dict)."""
    problem_id = _slug(rec["task_id"])
    difficulty = str(rec.get("difficulty", "")).strip()

    problem = {
        "problem_id": problem_id,
        "difficulty": difficulty,
        "statement": rec["problem_description"],
        "signature": rec.get("starter_code", ""),
    }
    tests = {
        "problem_id": problem_id,
        "entry_point": rec["entry_point"],
        "check_program": rec["test"],
        "prompt_imports": rec.get("prompt", ""),
        "timeout_sec": 10,
    }
    return problem, tests


def _load_split(version: str | None, split: str):
    try:
        from datasets import load_dataset
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("datasets is required: pip install 'datasets>=2.19.0'") from exc

    # The dataset exposes plain train/test splits; version selects the revision
    # when provided. HF mirror is honored via the HF_ENDPOINT env var.
    if version:
        try:
            return load_dataset("newfacade/LeetCodeDataset", version, split=split)
        except Exception:
            pass
    return load_dataset("newfacade/LeetCodeDataset", split=split)


def _select_test(records: list[dict[str, Any]], n_test: int) -> list[dict[str, Any]]:
    # Bias toward harder + newer (larger question_id) to fight ceiling effect.
    def key(rec: dict[str, Any]):
        rank = _DIFFICULTY_RANK.get(str(rec.get("difficulty", "")).lower(), 0)
        return (rank, int(rec.get("question_id", 0) or 0))

    return sorted(records, key=key, reverse=True)[:n_test]


def _select_train(records: list[dict[str, Any]], n_train: int) -> list[dict[str, Any]]:
    # Deterministic: order by question_id ascending and take the first n_train.
    ordered = sorted(records, key=lambda r: int(r.get("question_id", 0) or 0))
    return ordered[:n_train]


def dump_raw_sample(out_path: str | Path, version: str | None = None) -> dict[str, Any]:
    """Dump one raw dataset record (for [待确认] field/check inspection)."""
    ds = _load_split(version, "train")
    record = dict(ds[0])
    dump_json(out_path, record)
    return record


def prepare_leetcode(
    output_root: str | Path,
    n_train: int = 300,
    n_test: int = 100,
    version: str | None = None,
    smoke: bool = False,
) -> dict[str, int]:
    """Download dataset, map fields, split, and write raw_problems/{train,test}/."""
    out = Path(output_root)
    if smoke:
        n_train, n_test = 1, 1

    train_split = [dict(r) for r in _load_split(version, "train")]
    try:
        test_split = [dict(r) for r in _load_split(version, "test")]
    except Exception:
        # Fall back: carve the test set out of train if no test split exists.
        test_split = train_split

    train_records = _select_train(train_split, n_train)
    train_ids = {_slug(r["task_id"]) for r in train_records}
    # Keep test disjoint from our train selection.
    test_pool = [r for r in test_split if _slug(r["task_id"]) not in train_ids]
    test_records = _select_test(test_pool, n_test)

    counts = {"train": 0, "test": 0}
    for split_name, records in (("train", train_records), ("test", test_records)):
        for rec in records:
            problem, tests = map_record(rec)
            pid = problem["problem_id"]
            dump_json(out / "raw_problems" / split_name / "problem" / f"{pid}.json", problem)
            dump_json(out / "raw_problems" / split_name / "tests" / f"{pid}.json", tests)
            counts[split_name] += 1
    return counts
