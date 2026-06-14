from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def new_manifest(run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    """Create the empty metrics manifest skeleton (doc section 4.5)."""
    return {
        "run_id": run_id,
        "config": config,
        "data_gen": {},
        "train": {"baseline": {}, "armA": {}, "armB": {}},
        "eval": {"baseline": {}, "experiment": {}},
        "verdict": {"experiment_minus_baseline": None, "go": None},
    }


def load_or_new(path: str | Path, run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    p = Path(path)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return new_manifest(run_id, config)


def write_manifest(path: str | Path, manifest: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def update_section(path: str | Path, section: str, payload: dict[str, Any], run_id: str = "", config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge payload into a top-level section of the manifest and persist."""
    manifest = load_or_new(path, run_id, config or {})
    if section in manifest and isinstance(manifest[section], dict):
        manifest[section].update(payload)
    else:
        manifest[section] = payload
    write_manifest(path, manifest)
    return manifest


def update_train_arm(path: str | Path, arm: str, payload: dict[str, Any], run_id: str = "", config: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = load_or_new(path, run_id, config or {})
    manifest.setdefault("train", {}).setdefault(arm, {}).update(payload)
    write_manifest(path, manifest)
    return manifest
