from __future__ import annotations

from json import JSONDecodeError
import json


def _trim_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if not lines:
        return stripped
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _find_balanced_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        raise ValueError(f"No JSON object found in teacher output: {text[:240]!r}")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    raise ValueError(f"Unbalanced JSON object in teacher output: {text[:240]!r}")


def extract_json_block(text: str) -> dict:
    cleaned = _trim_fence(text)
    candidate = _find_balanced_object(cleaned)
    try:
        payload = json.loads(candidate)
    except JSONDecodeError as exc:
        raise ValueError(
            f"Failed to parse teacher JSON near {candidate[:240]!r}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError(f"Teacher output must be a JSON object, got {type(payload).__name__}.")
    return payload
