#!/usr/bin/env python
"""Triage the dropped_ids from an A-exp data_gen run.

For each dropped problem, replay the verifier over its persisted teacher_raw
samples (no API re-spend) and bucket *why* it was dropped:

  RECOVERABLE  some persisted sample now verifies True in the CURRENT env
               -> it was a FALSE drop (e.g. a missing dep at gen time);
                  re-running distill-batch with resume will recover it.
  REAL_WA      all samples run but assert wrong answer  -> genuine model bug.
  INFRA_IMPORT all samples die on ImportError/ModuleNotFoundError -> env still
               missing a dependency (name reported).
  SYNTAX/OTHER all samples die on SyntaxError / something else.
  NO_SAMPLES   no teacher_raw sample on disk (generation/API failed entirely).

Run this AFTER `pip install sortedcontainers` to see what the rerun will recover.

Usage:
  python tools/scan_dropped.py \
      --run-json   <path to A-exp run summary json> \
      --output-root <distill output root>            # contains teacher_raw/, raw_problems/
      [--tests-dir <dir>]      # default: <output-root>/raw_problems/train/tests
      [--report   scan_report.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


def _load_dropped_ids(run_json: Path) -> list[str]:
    data = json.loads(run_json.read_text(encoding="utf-8"))
    # accept either the full run object or a bare data_gen dict
    dg = data.get("data_gen", data)
    return list(dg.get("dropped_ids", []))


def _last_error_line(err: str) -> str:
    err = (err or "").strip()
    if not err:
        return ""
    return err.splitlines()[-1].strip()


def _classify(samples: list[dict]) -> tuple[str, str]:
    """Return (bucket, detail) for one problem's list of {verified, error} results."""
    if not samples:
        return "NO_SAMPLES", ""
    if any(s["verified"] for s in samples):
        return "RECOVERABLE", ""

    last_lines = [_last_error_line(s["error"]) for s in samples]
    joined = " | ".join(last_lines)

    # infra: every attempt died on an import problem
    if all(("ModuleNotFoundError" in l or "ImportError" in l) for l in last_lines if l):
        mods = sorted({m for l in last_lines for m in re.findall(r"No module named '([^']+)'", l)})
        return "INFRA_IMPORT", ",".join(mods) or joined[:120]
    if any("AssertionError" in l for l in last_lines):
        return "REAL_WA", ""
    if any("SyntaxError" in l for l in last_lines):
        return "SYNTAX", last_lines[-1][:120]
    return "OTHER", last_lines[-1][:120] if last_lines else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-json", required=True, type=Path)
    ap.add_argument("--output-root", required=True, type=Path)
    ap.add_argument("--tests-dir", type=Path, default=None)
    ap.add_argument("--src", type=Path, default=Path(__file__).resolve().parent.parent / "src")
    ap.add_argument("--report", type=Path, default=Path("scan_report.json"))
    args = ap.parse_args()

    sys.path.insert(0, str(args.src))
    from codeir.schemas import tests_from_dict, load_json  # noqa: E402
    from codeir.verifier import verify_code  # noqa: E402

    tests_dir = args.tests_dir or (args.output_root / "raw_problems" / "train" / "tests")
    teacher_root = args.output_root / "teacher_raw"

    dropped = _load_dropped_ids(args.run_json)
    print(f"scanning {len(dropped)} dropped ids")
    print(f"  tests_dir   = {tests_dir}")
    print(f"  teacher_raw = {teacher_root}\n")

    report: dict[str, dict] = {}
    buckets: Counter[str] = Counter()

    for pid in dropped:
        tests_path = tests_dir / f"{pid}.json"
        if not tests_path.exists():
            report[pid] = {"bucket": "NO_TESTS", "detail": str(tests_path)}
            buckets["NO_TESTS"] += 1
            continue
        spec = tests_from_dict(load_json(tests_path))

        sample_files = sorted((teacher_root / pid).glob("sample_*.json"))
        results = []
        for sf in sample_files:
            triple = load_json(sf)
            code = triple.get("code", "")
            res = verify_code(code, spec)
            results.append({"sample": sf.name, "verified": res.verified, "error": res.error})

        bucket, detail = _classify(results)
        buckets[bucket] += 1
        report[pid] = {
            "bucket": bucket,
            "detail": detail,
            "n_samples": len(results),
        }
        print(f"  {pid:45s} {bucket:13s} {detail}")

    print("\n=== summary ===")
    for b, n in buckets.most_common():
        print(f"  {b:13s} {n}")
    recoverable = buckets.get("RECOVERABLE", 0)
    real = buckets.get("REAL_WA", 0) + buckets.get("SYNTAX", 0)
    print(f"\n  FALSE drops (recoverable on rerun): {recoverable}")
    print(f"  REAL model bugs (won't recover):    {real}")
    still_infra = buckets.get("INFRA_IMPORT", 0)
    if still_infra:
        print(f"  STILL missing deps (install them):  {still_infra}  <-- see INFRA_IMPORT rows")

    args.report.write_text(json.dumps({"buckets": dict(buckets), "by_id": report},
                                      ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
