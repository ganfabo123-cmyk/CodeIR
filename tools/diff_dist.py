"""Count the difficulty distribution of verified_triples JSON files.

Each element under the target directory is one problem JSON with a top-level
"difficulty" key (case-insensitive: Easy/Medium/Hard) and an optional
"verified" boolean. This script only reads; it changes nothing.

Usage (on the server, from repo root):
    python tools/diff_dist.py
    python tools/diff_dist.py data/A-exp/verified_triples
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

_ORDER = ["easy", "medium", "hard", "unknown"]


def _iter_records(path: Path):
    """Yield each problem record. A file is either one dict or a list of dicts."""
    for fp in sorted(path.rglob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as exc:  # surface unreadable files, keep going
            print(f"[skip] {fp.name}: {exc}", file=sys.stderr)
            continue
        for rec in (data if isinstance(data, list) else [data]):
            if isinstance(rec, dict):
                yield fp.name, rec


def _norm(value) -> str:
    s = str(value or "").strip().lower()
    return s if s in ("easy", "medium", "hard") else "unknown"


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "data/A-exp/verified_triples")
    if not root.exists():
        print(f"path not found: {root.resolve()}", file=sys.stderr)
        sys.exit(1)

    total = Counter()
    verified = Counter()
    has_verified_key = 0
    n_records = 0

    for _name, rec in _iter_records(root):
        n_records += 1
        diff = _norm(rec.get("difficulty"))
        total[diff] += 1
        if "verified" in rec:
            has_verified_key += 1
            if _truthy(rec.get("verified")):
                verified[diff] += 1

    if n_records == 0:
        print(f"no JSON records found under {root.resolve()}")
        return

    def _row(label: str, counts: Counter, denom: int) -> str:
        parts = []
        for d in _ORDER:
            c = counts.get(d, 0)
            if c == 0 and d == "unknown":
                continue
            pct = (100.0 * c / denom) if denom else 0.0
            parts.append(f"{d}={c} ({pct:.1f}%)")
        return f"{label:<14} total={denom:<4} | " + "  ".join(parts)

    print(f"dir: {root.resolve()}")
    print(f"files/records scanned: {n_records}")
    print()
    print(_row("ALL", total, n_records))
    if has_verified_key:
        n_verified = sum(verified.values())
        print(_row("verified=True", verified, n_verified))
        print(f"(records carrying a 'verified' key: {has_verified_key}/{n_records})")
    else:
        print("(no 'verified' key present in these records)")


if __name__ == "__main__":
    main()
