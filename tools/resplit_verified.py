"""Re-split the existing verified triples into a difficulty-matched train/test set.

Why: the original pipeline trained on an easier pool (~27/58/15 easy/med/hard)
but tested on a hardest-first slice (0/21/79), a designed-in distribution
inversion that floored the student. This rebuilds a clean split FROM the already
verified problems (no teacher re-run): N_TEST problems are carved out as a test
set whose difficulty mix mirrors the full verified pool; the rest become train.

It writes a fresh, self-contained data root (default data/A-exp-resplit) and
never mutates the source tree, so it is fully reversible:

    <out>/verified_triples/<pid>.json        320 train triples  -> derive -> SFT
    <out>/raw_problems/test/problem/<pid>.json   100 test problems -> eval
    <out>/raw_problems/test/tests/<pid>.json     100 test cases    -> eval
    <out>/split/{train_ids,test_ids}.txt         the chosen split

Usage (server, repo root):
    python tools/resplit_verified.py
    python tools/resplit_verified.py --src data/A-exp --out data/A-exp-resplit \
        --n-test 100 --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

_DIFFS = ("easy", "medium", "hard")


def _norm(value) -> str:
    d = str(value or "").strip().lower()
    return d if d in _DIFFS else "medium"


def _allocate(n: int, weights: dict[str, int]) -> dict[str, int]:
    """Split n across buckets proportional to weights (largest-remainder)."""
    total = sum(weights.values()) or 1
    raw = {k: n * weights[k] / total for k in weights}
    out = {k: int(v) for k, v in raw.items()}
    short = n - sum(out.values())
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[:short]:
        out[k] += 1
    return out


def _dist(pids, diff_of) -> str:
    c = Counter(diff_of[p] for p in pids)
    n = len(pids) or 1
    return "  ".join(f"{d}={c.get(d,0)} ({100.0*c.get(d,0)/n:.1f}%)" for d in _DIFFS)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/A-exp")
    ap.add_argument("--out", default="data/A-exp-resplit")
    ap.add_argument("--n-test", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    verified_dir = src / "verified_triples"
    train_problem_dir = src / "raw_problems" / "train" / "problem"
    train_tests_dir = src / "raw_problems" / "train" / "tests"

    if not verified_dir.is_dir():
        sys.exit(f"not found: {verified_dir.resolve()}")

    # 1) read every verified triple -> pid + difficulty
    diff_of: dict[str, str] = {}
    for fp in sorted(verified_dir.glob("*.json")):
        rec = json.loads(fp.read_text(encoding="utf-8"))
        pid = rec.get("problem_id") or fp.stem
        diff_of[pid] = _norm(rec.get("difficulty"))
    if not diff_of:
        sys.exit(f"no verified triples under {verified_dir.resolve()}")

    # 2) bucket by difficulty, deterministic order, seeded shuffle
    buckets: dict[str, list[str]] = {d: [] for d in _DIFFS}
    for pid, d in diff_of.items():
        buckets[d].append(pid)
    rng = random.Random(args.seed)
    for d in _DIFFS:
        buckets[d].sort()
        rng.shuffle(buckets[d])

    # 3) stratified test allocation mirroring the full pool's distribution
    want = _allocate(args.n_test, {d: len(buckets[d]) for d in _DIFFS})
    test_ids: list[str] = []
    train_ids: list[str] = []
    for d in _DIFFS:
        k = min(want[d], len(buckets[d]))
        test_ids += buckets[d][:k]
        train_ids += buckets[d][k:]
    # fill any rounding shortfall from leftover train, keep deterministic
    if len(test_ids) < args.n_test:
        train_ids.sort()
        move = train_ids[: args.n_test - len(test_ids)]
        test_ids += move
        train_ids = [p for p in train_ids if p not in set(move)]

    assert not (set(train_ids) & set(test_ids)), "train/test overlap!"

    # 4) materialize the fresh data root (copies only; source untouched)
    def _copy(rel_src: Path, rel_dst: Path, pid: str) -> bool:
        s = rel_src / f"{pid}.json"
        if not s.exists():
            print(f"[warn] missing {s}", file=sys.stderr)
            return False
        rel_dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, rel_dst / f"{pid}.json")
        return True

    out_verified = out / "verified_triples"
    out_test_problem = out / "raw_problems" / "test" / "problem"
    out_test_tests = out / "raw_problems" / "test" / "tests"
    out_split = out / "split"
    out_split.mkdir(parents=True, exist_ok=True)

    n_tr = sum(_copy(verified_dir, out_verified, p) for p in train_ids)
    n_te_p = sum(_copy(train_problem_dir, out_test_problem, p) for p in test_ids)
    n_te_t = sum(_copy(train_tests_dir, out_test_tests, p) for p in test_ids)

    (out_split / "train_ids.txt").write_text("\n".join(sorted(train_ids)) + "\n", encoding="utf-8")
    (out_split / "test_ids.txt").write_text("\n".join(sorted(test_ids)) + "\n", encoding="utf-8")

    # 5) report
    print(f"src: {src.resolve()}")
    print(f"out: {out.resolve()}")
    print(f"pool: {len(diff_of)}  | {_dist(list(diff_of), diff_of)}")
    print()
    print(f"TRAIN {len(train_ids)}  | {_dist(train_ids, diff_of)}")
    print(f"      copied verified_triples: {n_tr}/{len(train_ids)}")
    print(f"TEST  {len(test_ids)}  | {_dist(test_ids, diff_of)}")
    print(f"      copied test problem/tests: {n_te_p}/{len(test_ids)}, {n_te_t}/{len(test_ids)}")
    print(f"overlap: {len(set(train_ids) & set(test_ids))} (must be 0)")
    if n_tr != len(train_ids) or n_te_p != len(test_ids) or n_te_t != len(test_ids):
        sys.exit("ERROR: some source files were missing; see [warn] lines above")


if __name__ == "__main__":
    main()
