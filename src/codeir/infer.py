from __future__ import annotations

from pathlib import Path
import json
import os


def build_inference_prompt(instruction: str, query: str) -> str:
    return (
        "Below is an instruction that describes a task, paired with an input.\n"
        "Write a response that appropriately completes the request.\n\n"
        f"### Instruction:\n{instruction}\n\n"
        f"### Input:\n{query}\n\n"
        "### Response:\n"
    )


def run_adapter_inference(
    base_model: str,
    adapter_path: str,
    prompt_path: str,
    max_new_tokens: int = 512,
) -> str:
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "Inference dependencies missing. Install transformers, peft, and torch first."
        ) from exc

    payload = json.loads(Path(prompt_path).read_text(encoding="utf-8"))
    prompt = build_inference_prompt(payload["instruction"], payload["input"])

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        trust_remote_code=True,
        torch_dtype=torch.float16,
        device_map="auto",
    )
    model = PeftModel.from_pretrained(model, adapter_path)
    model.eval()

    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        outputs = model.generate(**inputs, max_new_tokens=max_new_tokens)
    text = tokenizer.decode(outputs[0], skip_special_tokens=True)
    if "### Response:" in text:
        return text.split("### Response:", 1)[1].strip()
    return text.strip()


def resolve_default_demo_prompt(output_root: str | Path, arm: str) -> str:
    mapping = {
        "armA": "sft_armA",
        "armB": "sft_armB",
        "baseline": "sft_baseline",
    }
    source_dir = mapping[arm]
    root = Path(output_root) / source_dir
    files = sorted(root.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No demo samples found under {root}")
    return str(files[0])
