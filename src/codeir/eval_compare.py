from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .infer import build_inference_prompt
from .metrics import load_or_new, write_manifest
from .schemas import load_json, problem_from_dict, tests_from_dict
from .verifier import verify_code

# Instruction strings MUST match pipeline.derive_training_samples exactly.
INSTR_BASELINE = "Think first, then write code."
INSTR_ARM_A = "Output CodeIR only. Do not write code."
INSTR_ARM_B = "Translate CodeIR into Python without changing the logic."

_FENCE = chr(96) * 3  # triple backtick


def extract_python_code(text: str) -> str:
    """Pull runnable Python out of a model response (handles CoT prefix / fences)."""
    pattern = _FENCE + r"(?:python)?\s*\n(.*?)" + _FENCE
    fenced = re.search(pattern, text, re.S)
    if fenced:
        return fenced.group(1).strip()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^(from |import |class |def )", line.strip()):
            return "\n".join(lines[i:]).strip()
    return text.strip()


def _load_models(base_model: str, adapters: dict):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    base = AutoModelForCausalLM.from_pretrained(
        base_model,
        trust_remote_code=True,
        torch_dtype=torch.float16,
        device_map="auto",
    )
    items = list(adapters.items())
    first_name, first_path = items[0]
    model = PeftModel.from_pretrained(base, first_path, adapter_name=first_name)
    for name, path in items[1:]:
        model.load_adapter(path, adapter_name=name)
    model.eval()
    return model, tokenizer


def _generate(model, tokenizer, adapter: str, prompt: str, max_new_tokens: int):
    import torch

    model.set_adapter(adapter)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    gen_ids = out[0][inputs.input_ids.shape[-1]:]
    text = tokenizer.decode(gen_ids, skip_special_tokens=True)
    return text.strip(), int(gen_ids.shape[-1])


def _empty_bucket() -> dict:
    return {"passed": 0, "total": 0}


def _summarize(per_problem: list) -> dict:
    total = len(per_problem)
    passed = sum(1 for r in per_problem if r["passed"])
    by_diff: dict = {}
    tokens = 0
    wall = 0.0
    for r in per_problem:
        b = by_diff.setdefault(r["difficulty"] or "unknown", _empty_bucket())
        b["total"] += 1
        b["passed"] += 1 if r["passed"] else 0
        tokens += r["tokens"]
        wall += r["wall_sec"]
    return {
        "pass_at_1": round(passed / total, 4) if total else 0.0,
        "passed": passed,
        "total": total,
        "by_difficulty": {
            k: round(v["passed"] / v["total"], 4) if v["total"] else 0.0
            for k, v in by_diff.items()
        },
        "tokens_per_problem": round(tokens / total, 1) if total else 0,
        "wall_sec_per_problem": round(wall / total, 3) if total else 0.0,
    }


def evaluate_compare(
    base_model: str,
    adapter_baseline: str,
    adapter_armA: str,
    adapter_armB: str,
    test_problem_dir,
    test_tests_dir,
    manifest_path,
    report_path,
    max_new_tokens: int = 1024,
    ir_max_new_tokens: int = 512,
    run_id: str = "",
    config: dict | None = None,
) -> dict:
    """M6: pass@1 for baseline (single) and experiment (A->B cascade); write report."""
    model, tokenizer = _load_models(
        base_model,
        {"baseline": adapter_baseline, "armA": adapter_armA, "armB": adapter_armB},
    )

    problem_dir = Path(test_problem_dir)
    tests_dir = Path(test_tests_dir)
    baseline_rows: list = []
    experiment_rows: list = []

    for problem_path in sorted(problem_dir.glob("*.json")):
        problem = problem_from_dict(load_json(problem_path))
        tests_path = tests_dir / problem_path.name
        if not tests_path.exists():
            continue
        tests = tests_from_dict(load_json(tests_path))
        query = f"{problem.statement}\n\n{problem.signature}"

        t0 = time.time()
        text, tok = _generate(
            model, tokenizer, "baseline",
            build_inference_prompt(INSTR_BASELINE, query), max_new_tokens,
        )
        verified = verify_code(extract_python_code(text), tests).verified
        baseline_rows.append({
            "problem_id": problem.problem_id, "difficulty": problem.difficulty,
            "passed": verified, "tokens": tok, "wall_sec": round(time.time() - t0, 3),
        })

        t0 = time.time()
        ir_text, tok_a = _generate(
            model, tokenizer, "armA",
            build_inference_prompt(INSTR_ARM_A, query), ir_max_new_tokens,
        )
        code_text, tok_b = _generate(
            model, tokenizer, "armB",
            build_inference_prompt(INSTR_ARM_B, ir_text), max_new_tokens,
        )
        verified2 = verify_code(extract_python_code(code_text), tests).verified
        experiment_rows.append({
            "problem_id": problem.problem_id, "difficulty": problem.difficulty,
            "passed": verified2, "tokens": tok_a + tok_b, "wall_sec": round(time.time() - t0, 3),
        })

    baseline_summary = _summarize(baseline_rows)
    experiment_summary = _summarize(experiment_rows)
    delta = round(experiment_summary["pass_at_1"] - baseline_summary["pass_at_1"], 4)

    manifest = load_or_new(manifest_path, run_id, config or {})
    manifest["eval"]["baseline"] = baseline_summary
    manifest["eval"]["experiment"] = experiment_summary
    manifest["verdict"] = {"experiment_minus_baseline": delta, "go": delta > 0}
    write_manifest(manifest_path, manifest)

    _write_report(report_path, baseline_summary, experiment_summary, delta)
    return manifest


def _write_report(path, baseline: dict, experiment: dict, delta: float) -> None:
    diffs = sorted(set(baseline["by_difficulty"]) | set(experiment["by_difficulty"]))
    go_text = "GO (experiment > baseline)" if delta > 0 else "NO-GO (not above baseline)"
    b1 = baseline["pass_at_1"]
    e1 = experiment["pass_at_1"]
    lines = [
        "# A Experiment Compare Report (baseline vs IR)",
        "",
        "## pass@1 (greedy, temp0)",
        "",
        "| metric | baseline | experiment |",
        "|---|---|---|",
        "| pass@1 | " + str(b1) + " | " + str(e1) + " |",
        "| passed/total | " + f"{baseline['passed']}/{baseline['total']}" + " | " + f"{experiment['passed']}/{experiment['total']}" + " |",
        "| tokens/problem | " + str(baseline["tokens_per_problem"]) + " | " + str(experiment["tokens_per_problem"]) + " |",
        "| wall_sec/problem | " + str(baseline["wall_sec_per_problem"]) + " | " + str(experiment["wall_sec_per_problem"]) + " |",
        "",
        "## pass@1 by difficulty",
        "",
        "| difficulty | baseline | experiment |",
        "|---|---|---|",
    ]
    for d in diffs:
        b = baseline["by_difficulty"].get(d, "-")
        e = experiment["by_difficulty"].get(d, "-")
        lines.append("| " + d + " | " + str(b) + " | " + str(e) + " |")
    lines += [
        "",
        "## Verdict",
        "",
        "- experiment - baseline = " + str(delta),
        "- go/no-go: " + go_text,
        "",
        "Note: experiment tokens/problem is about 2x baseline (two-stage cascade); judge cost-effectiveness with the pass@1 delta.",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
