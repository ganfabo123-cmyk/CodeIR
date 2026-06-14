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


def _try_parse(candidate: str) -> dict | None:
    """Best-effort JSON parse with escalating leniency.

    Models frequently emit invalid JSON when embedding Python code (literal
    newlines / unescaped quotes inside the "code" string). We try:
      1. strict json
      2. strict=False (tolerates literal control chars inside strings)
      3. json_repair, if it happens to be installed (optional, no hard dep)
    """
    try:
        return json.loads(candidate)
    except JSONDecodeError:
        pass
    try:
        return json.loads(candidate, strict=False)
    except JSONDecodeError:
        pass
    try:
        import json_repair  # type: ignore

        repaired = json_repair.loads(candidate)
        if isinstance(repaired, dict):
            return repaired
    except Exception:
        pass
    return None


def extract_json_block(text: str) -> dict:
    cleaned = _trim_fence(text)
    candidate = _find_balanced_object(cleaned)
    payload = _try_parse(candidate)
    if payload is None:
        raise ValueError(f"Failed to parse teacher JSON near {candidate[:240]!r}")
    if not isinstance(payload, dict):
        raise ValueError(f"Teacher output must be a JSON object, got {type(payload).__name__}.")
    return payload
