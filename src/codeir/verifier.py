from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
import sys
import tempfile

from .schemas import TestCaseSpec, Triple


@dataclass
class VerificationResult:
    verified: bool
    passed: int
    total: int
    error: str = ""


def _build_runner(code: str, tests: TestCaseSpec) -> str:
    payload = {
        "entry_point": tests.entry_point,
        "test_cases": tests.test_cases,
    }
    lines = [
        "import json",
        "",
        f"payload = {json.dumps(payload, ensure_ascii=False)}",
        "namespace = {}",
        f"exec(compile({code!r}, '<candidate>', 'exec'), namespace, namespace)",
        "solution_cls = namespace['Solution']",
        "solver = solution_cls()",
        "entry = getattr(solver, payload['entry_point'])",
        "",
        "passed = 0",
        "for case in payload['test_cases']:",
        "    actual = entry(**case['input'])",
        "    if actual != case['expected']:",
        "        raise AssertionError(",
        "            f\"expected={case['expected']!r}, actual={actual!r}, input={case['input']!r}\"",
        "        )",
        "    passed += 1",
        "",
        "print(json.dumps({'passed': passed, 'total': len(payload['test_cases'])}))",
    ]
    return "\n".join(lines)


def _build_check_runner(code: str, tests: TestCaseSpec) -> str:
    """Human-eval style runner (LeetCodeDataset).

    Execs the import prefix (dataset `prompt`: typing + ListNode/TreeNode helpers),
    the candidate `class Solution`, then the dataset `check(candidate)` program,
    and invokes it as `check(<entry_point>)`.

    NOTE: LeetCodeDataset's `entry_point` is a *callable expression* such as
    "Solution().twoSum", so it is eval'd (not getattr'd).
    """
    lines = [
        "import json",
        "namespace = {}",
        f"exec(compile({tests.prompt_imports!r}, '<imports>', 'exec'), namespace, namespace)",
        f"exec(compile({code!r}, '<candidate>', 'exec'), namespace, namespace)",
        f"exec(compile({tests.check_program!r}, '<check>', 'exec'), namespace, namespace)",
        "check = namespace['check']",
        f"candidate = eval({tests.entry_point!r}, namespace)",
        "check(candidate)",
        "print(json.dumps({'passed': 1, 'total': 1}))",
    ]
    return "\n".join(lines)


def verify_code(code: str, tests: TestCaseSpec) -> VerificationResult:
    if tests.check_program:
        runner = _build_check_runner(code, tests)
    else:
        runner = _build_runner(code, tests)
    with tempfile.TemporaryDirectory(prefix="codeir_verify_") as temp_dir:
        script_path = Path(temp_dir) / "runner.py"
        script_path.write_text(runner, encoding="utf-8")
        try:
            completed = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=tests.timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return VerificationResult(
                verified=False,
                passed=0,
                total=len(tests.test_cases),
                error=f"Timed out after {tests.timeout_sec}s",
            )

    if completed.returncode != 0:
        return VerificationResult(
            verified=False,
            passed=0,
            total=len(tests.test_cases),
            error=completed.stderr.strip() or completed.stdout.strip(),
        )

    summary = json.loads(completed.stdout.strip())
    return VerificationResult(
        verified=summary["passed"] == summary["total"],
        passed=summary["passed"],
        total=summary["total"],
    )


def verify_triple(triple: Triple, tests: TestCaseSpec) -> VerificationResult:
    return verify_code(triple.code, tests)
