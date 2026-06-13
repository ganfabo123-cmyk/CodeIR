from __future__ import annotations

import argparse
import json
import os

from .pipeline import derive_from_directory, run_distillation
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

    derive_parser = subparsers.add_parser("derive", help="Derive SFT data from verified triples")
    derive_parser.add_argument("--verified-root", required=True)
    derive_parser.add_argument("--output-root", default="data")
    derive_parser.add_argument("--ir-format", choices=["yaml", "json"], default="yaml")
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

    if args.command == "derive":
        count = derive_from_directory(
            verified_root=args.verified_root,
            output_root=args.output_root,
            ir_format=args.ir_format,
        )
        print(json.dumps({"derived": count}, ensure_ascii=False))
        return


if __name__ == "__main__":
    main()
