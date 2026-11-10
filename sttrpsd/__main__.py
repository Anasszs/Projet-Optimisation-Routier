"""Command-line entry point; run from the extracted project directory."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from . import __version__, COURSE_TIME_LIMIT_SECONDS
from .model import FormatError, describe_path, load_instance, load_json
from .scoring import load_solution, score_solution


def _positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a finite positive number") from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def _nonnegative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a nonnegative integer") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return number


def _different_paths(output: Path, *inputs: Path) -> None:
    if any(output.resolve() == source.resolve() for source in inputs):
        raise ValueError("Output must be a different file from every input")


def _write_json(path: Path, data: Any) -> None:
    """Publish a complete JSON file atomically within its target directory."""
    content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".sttrpsd-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    except OSError as exc:
        raise OSError(f"Cannot write JSON ({describe_path(path)}): {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _print_json(data: Any) -> None:
    # JSON escapes preserve Unicode paths exactly while remaining writable
    # through legacy Windows code pages and redirected ASCII/cp1252 stdout.
    # Files themselves remain UTF-8; this only affects the command response.
    print(json.dumps(data, ensure_ascii=True, indent=2, allow_nan=False))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m sttrpsd",
        description="STTRPSD solution validation, baseline construction and reproducible comparison.",
        epilog=("Command-line file paths are relative to the current working directory unless absolute. "
                "The score command reads an existing solution; it does not create one."),
    )
    parser.add_argument("--version", action="version", version=f"STTRPSD course tools {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    score = commands.add_parser("score", help="check one solution and recompute its travel cost")
    score.add_argument("--instance", type=Path, required=True, help="canonical instance JSON")
    score.add_argument("--solution", type=Path, required=True,
                       help="existing solution JSON to validate (relative to the current directory)")
    score.add_argument("--output", type=Path, help="also write the scoring result as JSON")

    baseline = commands.add_parser("baseline", help="produce a simple feasible starter solution")
    baseline.add_argument("--instance", type=Path, required=True)
    baseline.add_argument("--solution", type=Path, required=True,
                          help="output JSON path; parent directories are created if needed")
    baseline.add_argument("--seed", type=_nonnegative_int, default=0)
    baseline.add_argument("--time-limit", type=_positive_float, default=COURSE_TIME_LIMIT_SECONDS,
                          help="course budget: 30 seconds per run; the harness enforces the deadline")
    baseline.add_argument("--method", choices=("nearest", "random"), default="nearest")

    convert = commands.add_parser("convert", help="convert an original Villegas .dat instance to JSON")
    convert.add_argument("--input", type=Path, required=True, help="original STTRP .dat file")
    convert.add_argument("--output", type=Path, required=True, help="canonical JSON destination")

    benchmark = commands.add_parser("benchmark", help="run solvers and write JSON, CSV and offline HTML")
    benchmark.add_argument("--config", type=Path, required=True)
    benchmark.add_argument("--output", type=Path, required=True, help="fresh output directory, which must not exist")

    report = commands.add_parser("report", help="render an existing results.json as self-contained HTML")
    report.add_argument("--results", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)

    split = commands.add_parser("split", help="create matched public and held-out sets from the original benchmark")
    split.add_argument("--source", type=Path, default=Path("instructor/instances"))
    split.add_argument("--public", type=Path, default=Path("instances/public"))
    split.add_argument("--private", type=Path, default=Path("instructor/evaluation"))
    split.add_argument("--manifest", type=Path, default=Path("instructor/split_manifest.json"))
    split.add_argument("--seed", type=_nonnegative_int, required=True,
                       help="lecturer-chosen private seed for the held-out selection")
    return parser


def _score(args: argparse.Namespace) -> int:
    result: dict[str, Any]
    try:
        if args.output:
            _different_paths(args.output, args.instance, args.solution)
        instance = load_instance(args.instance)
        try:
            solution = load_solution(args.solution)
        except FormatError as exc:
            if isinstance(exc.__cause__, FileNotFoundError):
                raise FormatError(
                    f"{exc} Run your solver or the baseline command successfully first, "
                    "using this same --solution path. Then score from the same working "
                    "directory, or use the absolute output path reported by baseline. "
                    "The score command does not create a solution or search for another file."
                ) from exc
            raise
        result = score_solution(instance, solution)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        result = {
            "feasible": False, "cost": None, "main_cost": None, "subroute_cost": None,
            "errors": [str(exc)], "n_customers": None, "n_satellites_used": 0,
            "n_subroutes": 0, "loads": [],
        }
    _print_json(result)
    if args.output:
        # A destination conflict must never overwrite the source while trying
        # to report that conflict.
        _different_paths(args.output, args.instance, args.solution)
        _write_json(args.output, result)
    return 0 if result["feasible"] else 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "score":
            return _score(args)
        if args.command == "baseline":
            from .baseline import make_solution
            _different_paths(args.solution, args.instance)
            instance = load_instance(args.instance)
            solution = make_solution(instance, seed=args.seed, method=args.method)
            result = score_solution(instance, solution)
            if not result["feasible"]:
                raise ValueError(f"Baseline construction failed validation: {result['errors']}")
            _write_json(args.solution, solution)
            _print_json({"solution": str(args.solution.resolve()), "feasible": True, "cost": result["cost"]})
            return 0
        if args.command == "convert":
            from .importer import convert_dat
            _different_paths(args.output, args.input)
            data = convert_dat(args.input)
            # Keep conversion independent of permissive downstream loaders.
            from .model import parse_instance
            parse_instance(data)
            _write_json(args.output, data)
            _print_json({"instance": data["name"], "output": str(args.output)})
            return 0
        if args.command == "benchmark":
            from .harness import run_benchmark
            data = run_benchmark(args.config, args.output)
            _print_json({"output": str(args.output), "report": str(args.output / "report.html"),
                         "runs": len(data["runs"]), "leaderboard": data["leaderboard"]})
            return 0
        if args.command == "report":
            from .report import write_report
            _different_paths(args.output, args.results)
            data = load_json(args.results, max_bytes=512 * 1024 * 1024)
            if not isinstance(data, dict) or not {"instances", "solvers", "runs", "leaderboard", "ranking_rule"} <= data.keys():
                raise FormatError("Expected a completed benchmark results.json, including its leaderboard")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            write_report(data, args.output)
            _print_json({"report": str(args.output)})
            return 0
        if args.command == "split":
            try:
                from .split import split_benchmark
            except ImportError as exc:
                raise ValueError("The split command is available in the instructor package") from exc
            manifest = split_benchmark(args.source, args.public, args.private,
                                       args.manifest, seed=args.seed)
            _print_json({"manifest": str(args.manifest), "public": str(args.public),
                         "private": str(args.private), "seed": args.seed})
            return 0
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
