from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .exporters import export_llamafactory_datasets
from .infer import resolve_default_demo_prompt, run_adapter_inference
from .pipeline import derive_from_directory, run_distillation, run_distillation_batch
from .schemas import (
    load_json,
    problem_from_dict,
    tests_from_dict,
    triple_from_dict,
)
from .verifier import verify_triple


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CodeIR minimal deployment CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_parser = subparsers.add_parser("verify", help="Verify one triple against test cases")
    verify_parser.add_argument("--triple", required=True)
    verify_parser.add_argument("--tests", required=True)

    distill_parser = subparsers.add_parser("distill", help="Run teacher generation + verification")
    distill_parser.add_argument("--problem", required=True)
    distill_parser.add_argument("--tests", required=True)
    distill_parser.add_argument("--output-root", default="data")
    distill_parser.add_argument("--provider", default=os.environ.get("CODEIR_PROVIDER", "mock"))
    distill_parser.add_argument("--max-resamples", type=int, default=8)

    prepare_parser = subparsers.add_parser(
        "prepare-leetcode",
        help="Download LeetCodeDataset, map fields, split into raw_problems/{train,test}",
    )
    prepare_parser.add_argument("--output-root", default="data")
    prepare_parser.add_argument("--n-train", type=int, default=300)
    prepare_parser.add_argument("--n-test", type=int, default=100)
    prepare_parser.add_argument("--version", default=None)
    prepare_parser.add_argument("--smoke", action="store_true")
    prepare_parser.add_argument(
        "--dump-sample",
        default=None,
        help="If set, dump one raw dataset record to this path and exit (for field/check inspection).",
    )

    batch_parser = subparsers.add_parser(
        "distill-batch",
        help="Batch teacher generation + verification + 3-line derivation over a directory",
    )
    batch_parser.add_argument("--problems-dir", required=True)
    batch_parser.add_argument("--tests-dir", required=True)
    batch_parser.add_argument("--output-root", default="data")
    batch_parser.add_argument("--provider", default=os.environ.get("CODEIR_PROVIDER", "mock"))
    batch_parser.add_argument("--max-resamples", type=int, default=8)
    batch_parser.add_argument("--ir-format", choices=["yaml", "json"], default="yaml")
    batch_parser.add_argument("--manifest", default=None, help="Write data_gen metrics into this manifest.")
    batch_parser.add_argument("--run-id", default="A-exp")
    batch_parser.add_argument(
        "--no-resume", action="store_true",
        help="Regenerate every problem even if a verified triple already exists.",
    )
    batch_parser.add_argument(
        "--abort-after-errors", type=int, default=8,
        help="Stop after N consecutive generation errors (API down/out of credit); 0 disables.",
    )
    batch_parser.add_argument(
        "--skip-ids-file", default=None,
        help="Newline-separated problem_ids to skip entirely (no API spend). "
             "Use for known-bad drops you don't want to re-attempt.",
    )

    eval_parser = subparsers.add_parser(
        "eval-compare",
        help="M6: pass@1 baseline (single) vs experiment (A->B cascade) + report",
    )
    eval_parser.add_argument("--base-model", required=True)
    eval_parser.add_argument("--adapter-baseline", required=True)
    eval_parser.add_argument("--adapter-armA", required=True)
    eval_parser.add_argument("--adapter-armB", required=True)
    eval_parser.add_argument("--test-problem-dir", required=True)
    eval_parser.add_argument("--test-tests-dir", required=True)
    eval_parser.add_argument("--manifest", default="artifacts/metrics_manifest.json")
    eval_parser.add_argument("--report", default="artifacts/比对报告.md")
    eval_parser.add_argument("--max-new-tokens", type=int, default=1024)
    eval_parser.add_argument("--ir-max-new-tokens", type=int, default=512)
    eval_parser.add_argument("--run-id", default="A-exp")

    derive_parser = subparsers.add_parser("derive", help="Derive SFT data from verified triples")
    derive_parser.add_argument("--verified-root", required=True)
    derive_parser.add_argument("--output-root", default="data")
    derive_parser.add_argument("--ir-format", choices=["yaml", "json"], default="yaml")

    export_parser = subparsers.add_parser(
        "export-llamafactory",
        help="Export derived SFT datasets into LlamaFactory Alpaca format",
    )
    export_parser.add_argument("--output-root", default="data")
    export_parser.add_argument("--export-root", default="artifacts")
    export_parser.add_argument("--dataset-dir-name", default="codeir_llamafactory")

    infer_parser = subparsers.add_parser(
        "infer-adapter",
        help="Run one demo inference using a LoRA adapter and a prepared sample",
    )
    infer_parser.add_argument("--base-model", required=True)
    infer_parser.add_argument("--adapter-path", required=True)
    infer_parser.add_argument("--prompt-file")
    infer_parser.add_argument("--output-root", default="data")
    infer_parser.add_argument("--arm", choices=["armA", "armB", "baseline"], default="baseline")
    infer_parser.add_argument("--max-new-tokens", type=int, default=512)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "verify":
        triple = triple_from_dict(load_json(args.triple))
        tests = tests_from_dict(load_json(args.tests))
        result = verify_triple(triple, tests)
        print(
            json.dumps(
                {
                    "verified": result.verified,
                    "passed": result.passed,
                    "total": result.total,
                    "error": result.error,
                },
                ensure_ascii=False,
            )
        )
        return

    if args.command == "distill":
        problem = problem_from_dict(load_json(args.problem))
        tests = tests_from_dict(load_json(args.tests))
        result = run_distillation(
            problem,
            tests,
            output_root=args.output_root,
            provider_name=args.provider,
            max_resamples=args.max_resamples,
        )
        print(
            json.dumps(
                {
                    "accepted": result.triple is not None,
                    "attempts": result.attempts,
                    "problem_id": problem.problem_id,
                    "verified": result.verification.verified if result.verification else False,
                    "error": result.verification.error if result.verification else "",
                },
                ensure_ascii=False,
            )
        )
        return

    if args.command == "prepare-leetcode":
        from .datasets_leetcode import dump_raw_sample, prepare_leetcode

        if args.dump_sample:
            dump_raw_sample(args.dump_sample, version=args.version)
            print(json.dumps({"dumped": args.dump_sample}, ensure_ascii=False))
            return
        counts = prepare_leetcode(
            output_root=args.output_root,
            n_train=args.n_train,
            n_test=args.n_test,
            version=args.version,
            smoke=args.smoke,
        )
        print(json.dumps(counts, ensure_ascii=False))
        return

    if args.command == "distill-batch":
        skip_ids: set[str] | None = None
        if args.skip_ids_file:
            skip_path = Path(args.skip_ids_file)
            if not skip_path.exists():
                parser.error(f"--skip-ids-file not found: {skip_path}")
            skip_ids = {
                line.strip()
                for line in skip_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
            print(f"skip-list: {len(skip_ids)} ids loaded from {skip_path}", flush=True)
        metrics = run_distillation_batch(
            problems_dir=args.problems_dir,
            tests_dir=args.tests_dir,
            output_root=args.output_root,
            provider_name=args.provider,
            max_resamples=args.max_resamples,
            ir_format=args.ir_format,
            resume=not args.no_resume,
            abort_after_errors=args.abort_after_errors,
            skip_ids=skip_ids,
        )
        if args.manifest:
            from .metrics import update_section

            update_section(
                args.manifest, "data_gen", metrics,
                run_id=args.run_id,
                config={"provider": args.provider},
            )
        print(json.dumps(metrics, ensure_ascii=False))
        return

    if args.command == "eval-compare":
        from .eval_compare import evaluate_compare

        manifest = evaluate_compare(
            base_model=args.base_model,
            adapter_baseline=args.adapter_baseline,
            adapter_armA=args.adapter_armA,
            adapter_armB=args.adapter_armB,
            test_problem_dir=args.test_problem_dir,
            test_tests_dir=args.test_tests_dir,
            manifest_path=args.manifest,
            report_path=args.report,
            max_new_tokens=args.max_new_tokens,
            ir_max_new_tokens=args.ir_max_new_tokens,
            run_id=args.run_id,
        )
        print(json.dumps(manifest["verdict"], ensure_ascii=False))
        return

    if args.command == "derive":
        count = derive_from_directory(
            verified_root=args.verified_root,
            output_root=args.output_root,
            ir_format=args.ir_format,
        )
        print(json.dumps({"derived": count}, ensure_ascii=False))
        return

    if args.command == "export-llamafactory":
        exported = export_llamafactory_datasets(
            output_root=args.output_root,
            export_root=args.export_root,
            dataset_dir_name=args.dataset_dir_name,
        )
        print(json.dumps({"exported": exported}, ensure_ascii=False))
        return

    if args.command == "infer-adapter":
        prompt_file = args.prompt_file or resolve_default_demo_prompt(args.output_root, args.arm)
        text = run_adapter_inference(
            base_model=args.base_model,
            adapter_path=args.adapter_path,
            prompt_path=prompt_file,
            max_new_tokens=args.max_new_tokens,
        )
        print(json.dumps({"prompt_file": prompt_file, "response": text}, ensure_ascii=False))
        return


if __name__ == "__main__":
    main()
