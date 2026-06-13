from __future__ import annotations

from pathlib import Path
from typing import Any
import json


ARM_DATASETS = {
    "armA": "sft_armA",
    "armB": "sft_armB",
    "baseline": "sft_baseline",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")


def export_llamafactory_datasets(
    output_root: str | Path,
    export_root: str | Path,
    dataset_dir_name: str = "codeir_llamafactory",
) -> dict[str, str]:
    output_root = Path(output_root)
    export_root = Path(export_root)
    dataset_root = export_root / dataset_dir_name
    dataset_info: dict[str, Any] = {}
    exported: dict[str, str] = {}

    for arm_name, source_dir in ARM_DATASETS.items():
        arm_root = output_root / source_dir
        rows = []
        for path in sorted(arm_root.glob("*.json")):
            payload = _read_json(path)
            rows.append(
                {
                    "instruction": payload["instruction"],
                    "input": payload["input"],
                    "output": payload["output"],
                }
            )

        dataset_file = f"{arm_name}.jsonl"
        _write_jsonl(dataset_root / dataset_file, rows)
        dataset_info[arm_name] = {
            "file_name": dataset_file,
            "formatting": "alpaca",
            "columns": {
                "prompt": "instruction",
                "query": "input",
                "response": "output",
            },
        }
        exported[arm_name] = str(dataset_root / dataset_file)

    _write_json(dataset_root / "dataset_info.json", dataset_info)
    return exported
