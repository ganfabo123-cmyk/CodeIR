from __future__ import annotations

from typing import Any
import json

from .schemas import CodeIR


def to_rich_dict(codeir: CodeIR) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "signature": codeir.signature,
        "pattern": codeir.pattern,
        "key_insight": codeir.key_insight,
        "data_structures": codeir.data_structures,
        "algorithm": codeir.algorithm,
        "edge_cases": codeir.edge_cases,
    }
    if codeir.complexity is not None:
        payload["complexity"] = {
            "time": codeir.complexity.time,
            "space": codeir.complexity.space,
        }
    return payload


def to_lean_dict(codeir: CodeIR) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "pattern": codeir.pattern,
        "key_insight": codeir.key_insight,
    }
    if codeir.state:
        payload["state"] = codeir.state
    if codeir.transition:
        payload["transition"] = codeir.transition
    elif codeir.algorithm:
        payload["transition"] = "; ".join(codeir.algorithm)
    if codeir.complexity is not None:
        payload["complexity"] = {
            "time": codeir.complexity.time,
            "space": codeir.complexity.space,
        }
    if codeir.edge_cases:
        payload["edge_cases"] = codeir.edge_cases
    return payload


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _to_yaml_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_to_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(_to_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return lines
    return [f"{prefix}{_yaml_scalar(value)}"]


def serialize_ir(payload: dict[str, Any], fmt: str = "yaml") -> str:
    if fmt == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if fmt == "yaml":
        return "\n".join(_to_yaml_lines(payload)) + "\n"
    raise ValueError(f"Unsupported IR format: {fmt}")


def linearize_baseline_thought(codeir: CodeIR) -> str:
    lines = [
        f"Pattern: {codeir.pattern}",
        f"Key insight: {codeir.key_insight}",
    ]
    if codeir.signature:
        lines.append(f"Signature: {codeir.signature}")
    if codeir.data_structures:
        lines.append("Data structures: " + "; ".join(codeir.data_structures))
    if codeir.algorithm:
        lines.append("Algorithm steps: " + "; ".join(codeir.algorithm))
    if codeir.edge_cases:
        lines.append("Edge cases: " + "; ".join(codeir.edge_cases))
    if codeir.complexity is not None:
        lines.append(
            f"Complexity: time {codeir.complexity.time}, space {codeir.complexity.space}"
        )
    return "\n".join(lines)
