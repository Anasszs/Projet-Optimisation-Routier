"""Reproducible, language-independent STTRPSD evaluation (Python 3.10+).

This runner imposes a wall-clock deadline and collects bounded logs. It is not
an operating-system security sandbox. Run submitted programs in a dedicated
account or container when evaluating code you do not trust.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import stat
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any

from . import COURSE_TIME_LIMIT_SECONDS
from .model import load_instance, load_json
from .scoring import score_solution

LOG_LIMIT = 64 * 1024
SOLUTION_LIMIT = 10 * 1024 * 1024
TIE_TOLERANCE = 1e-9


def _strict_object(pairs: list[tuple[str, Any]]) -> dict:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _read_json(path: Path) -> Any:
    # Match the CLI readers, including optional UTF-8 BOMs from Windows tools,
    # duplicate-key/non-finite rejection, and useful missing-file diagnostics.
    return load_json(path)


def _finite_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError(f"JSON number is outside the finite range: {token[:80]}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")[:70] or "item"


def _resolve(path: str, base: Path) -> Path:
    if not isinstance(path, str) or not path:
        raise ValueError("Paths must be nonempty strings")
    result = Path(path).expanduser()
    return (base / result).resolve() if not result.is_absolute() else result.resolve()


def _number(value: Any, label: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number) or number <= minimum:
        raise ValueError(f"{label} must be greater than {minimum}")
    return number


def _load_config(config_path: Path) -> tuple[dict, list[Path], list[dict]]:
    config = _read_json(config_path)
    if (not isinstance(config, dict) or type(config.get("schema_version")) is not int
            or config["schema_version"] != 1):
        raise ValueError("Config must be an object with schema_version equal to 1")
    allowed = {"schema_version", "title", "instances", "instance_glob", "seeds",
               "time_limit", "solvers", "baseline_name", "notes", "environment"}
    if set(config) - allowed:
        raise ValueError(f"Unknown config fields: {sorted(set(config) - allowed)}")
    base = config_path.parent
    if ("instances" in config) == ("instance_glob" in config):
        raise ValueError("Specify exactly one of instances or instance_glob")
    if "instances" in config:
        if not isinstance(config["instances"], list) or not config["instances"]:
            raise ValueError("instances must be a nonempty list of paths")
        paths = [_resolve(path, base) for path in config["instances"]]
    else:
        pattern = config["instance_glob"]
        if not isinstance(pattern, str) or not pattern or Path(pattern).is_absolute():
            raise ValueError("instance_glob must be a nonempty relative glob")
        paths = [path.resolve() for path in base.glob(pattern) if path.is_file()]
    if not paths:
        raise ValueError("No instance files matched")
    if len(set(paths)) != len(paths):
        raise ValueError("Instance paths must be unique")
    paths.sort(key=lambda path: str(path))
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Instance file not found: {path}")
    seeds = config.get("seeds", [0, 1, 2])
    if not isinstance(seeds, list) or not seeds or any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError("seeds must contain distinct nonnegative integers")
    config["seeds"] = seeds
    config["time_limit"] = _number(config.get("time_limit", COURSE_TIME_LIMIT_SECONDS), "time_limit")
    raw_solvers = config.get("solvers")
    if not isinstance(raw_solvers, list) or not raw_solvers:
        raise ValueError("solvers must be a nonempty list")
    solvers: list[dict] = []
    names: set[str] = set()
    for raw in raw_solvers:
        if not isinstance(raw, dict):
            raise ValueError("Each solver must be an object")
        permitted = {"name", "command", "solutions_dir", "cwd", "include_in_ranking"}
        if set(raw) - permitted:
            raise ValueError(f"Unknown solver fields: {sorted(set(raw) - permitted)}")
        solver = dict(raw)
        name = solver.get("name")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("Solver names must be nonempty and unique")
        names.add(name)
        if ("command" in solver) == ("solutions_dir" in solver):
            raise ValueError(f"{name}: specify exactly one of command or solutions_dir")
        ranked = solver.get("include_in_ranking", True)
        if not isinstance(ranked, bool):
            raise ValueError("include_in_ranking must be true or false")
        solver["include_in_ranking"] = ranked
        if "command" in solver:
            command = solver["command"]
            if not isinstance(command, list) or not command or any(
                    not isinstance(token, str) or not token for token in command):
                raise ValueError(f"{name}: command must be a nonempty array of strings")
            cwd = _resolve(solver.get("cwd", "."), base)
            if not cwd.is_dir():
                raise ValueError(f"{name}: cwd is not a directory: {cwd}")
            solver["cwd"] = str(cwd)
            # An explicitly relative executable is resolved like cwd, against
            # the configuration directory. Interpreter script arguments remain
            # relative to cwd, which defaults to that same directory.
            if "/" in command[0] or "\\" in command[0]:
                solver["command"] = [str(_resolve(command[0], base)), *command[1:]]
            for token in solver["command"]:
                try:
                    token.format(instance="I", solution="S", seed="0", time_limit="1",
                                 python=sys.executable)
                except (KeyError, ValueError, IndexError) as exc:
                    raise ValueError(f"{name}: invalid command placeholder: {token}") from exc
        else:
            solver["solutions_dir"] = str(_resolve(solver["solutions_dir"], base))
        solvers.append(solver)
    if not any(solver["include_in_ranking"] for solver in solvers):
        raise ValueError("At least one solver must participate in ranking")
    baseline = config.get("baseline_name")
    if baseline is not None and baseline not in names:
        raise ValueError("baseline_name must match a configured solver name")
    return config, paths, solvers


class _BoundedCapture:
    def __init__(self, stream: Any, limit: int = LOG_LIMIT):
        self.stream = stream
        self.limit = limit
        self.buffer = bytearray()
        self.total = 0
        self.thread = threading.Thread(target=self._drain, daemon=True)

    def _drain(self) -> None:
        try:
            while True:
                block = os.read(self.stream.fileno(), 65536)
                if not block:
                    return
                self.total += len(block)
                if len(self.buffer) < self.limit:
                    self.buffer.extend(block[:self.limit - len(self.buffer)])
        except (OSError, ValueError):
            return

    def finish(self) -> str:
        self.thread.join(timeout=2.0)
        text = self.buffer.decode("utf-8", errors="replace")
        if self.total > len(self.buffer):
            text += f"\n[log truncated: captured {len(self.buffer)} of {self.total} bytes]\n"
        return text


def _kill_tree(process: subprocess.Popen) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif os.name == "nt":
        # taskkill belongs to Windows. An unavailable utility still falls back
        # to terminating the direct child, and the environment records this OS.
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            if process.poll() is None:
                process.kill()
    elif process.poll() is None:
        process.kill()


def _run_process(command: list[str], cwd: str, limit: float) -> dict:
    started = time.perf_counter()
    environment = os.environ.copy()
    for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                     "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        environment[variable] = "1"
    allowed_cpus = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else []
    pinned_cpu = allowed_cpus[0] if allowed_cpus and hasattr(os, "sched_setaffinity") else None
    # Jobs are launched sequentially. Pin before exec so any child threads and
    # subprocesses inherit the same single-core affinity on supported systems.
    pin = (lambda: os.sched_setaffinity(0, {pinned_cpu})) if pinned_cpu is not None else None
    try:
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   shell=False, start_new_session=(os.name == "posix"),
                                   bufsize=0, env=environment, preexec_fn=pin)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"status": "error", "seconds": time.perf_counter() - started,
                "returncode": None, "stdout": "", "stderr": str(exc),
                "errors": [f"Could not start program {command[0]!r} in working directory {cwd!r}: {exc}. "
                           "Check the executable and configured cwd; a bare executable name must be on PATH."]}
    out = _BoundedCapture(process.stdout)
    err = _BoundedCapture(process.stderr)
    out.thread.start()
    err.thread.start()
    timed_out = False
    try:
        remaining = max(0.0, limit - (time.perf_counter() - started))
        process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        timed_out = True
    elapsed = time.perf_counter() - started
    # On successful exit, terminate children left behind in the process group
    # as well. A solver cannot spend the next team's budget in the background.
    _kill_tree(process)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    stdout, stderr = out.finish(), err.finish()
    process.stdout.close()
    process.stderr.close()
    status = "timeout" if timed_out else ("ok" if process.returncode == 0 else "error")
    errors = ([f"Exceeded the {limit:g} s wall-clock limit"] if timed_out else
              ([] if process.returncode == 0 else
               [f"Program exited with code {process.returncode}"]))
    return {"status": status, "seconds": elapsed, "returncode": process.returncode,
            "stdout": stdout, "stderr": stderr, "errors": errors,
            "cpu_affinity": [pinned_cpu] if pinned_cpu is not None else None}


def _solution_bytes(path: Path) -> bytes:
    """Read one regular output file once, with a hard bound on allocated bytes."""
    if path.is_symlink():
        raise ValueError("A solution must be a regular file, not a symbolic link")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("A solution must be a regular file")
        raw = stream.read(SOLUTION_LIMIT + 1)
    if len(raw) > SOLUTION_LIMIT:
        raise ValueError("Solution file exceeds 10 MiB")
    return raw


def _score_file(instance: Any, solution_path: Path) -> tuple[dict, Any, str | None, bytes | None]:
    try:
        raw = _solution_bytes(solution_path)
    except FileNotFoundError:
        return ({"status": "missing", "errors": [
                    f"No solution file was found at the requested path: {solution_path.resolve()}. "
                    "Check the producer's output path and working directory."],
                 "feasible": False, "cost": None}, None, None, None)
    except (OSError, ValueError) as exc:
        return ({"status": "invalid_json", "errors": [f"Cannot read solution: {exc}"],
                 "feasible": False, "cost": None}, None, None, None)
    digest = hashlib.sha256(raw).hexdigest()
    try:
        solution = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_strict_object,
                              parse_float=_finite_float,
                              parse_constant=lambda value: (_ for _ in ()).throw(
                                  ValueError(f"Non-finite JSON number: {value}")))
        if not isinstance(solution, dict):
            raise ValueError("Solution must be a JSON object")
    except (ValueError, TypeError, RecursionError) as exc:
        return ({"status": "invalid_json", "errors": [f"Cannot read solution: {exc}"],
                 "feasible": False, "cost": None}, None, digest, raw)
    try:
        result = score_solution(instance, solution)
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as exc:
        return ({"status": "invalid", "errors": [f"Malformed solution: {exc}"],
                 "feasible": False, "cost": None}, solution, digest, raw)
    result = dict(result)
    result["status"] = "feasible" if result["feasible"] else "invalid"
    return result, solution, digest, raw


def aggregate_results(data: dict) -> dict:
    """Compute normalized scores; every scheduled instance/seed has equal weight.

    Reference costs use ranked solvers only. A nonranked baseline can therefore
    be compared without changing participants' grades. No score is an optimality
    certificate; references are best observed feasible results in this run.
    """
    ranked_names = {solver["name"] for solver in data["solvers"]
                    if solver.get("include_in_ranking", True)}
    references: dict[tuple[str, int], float] = {}
    baseline_costs: dict[tuple[str, int], float] = {}
    baseline_name = data.get("baseline_name")
    for result in data["runs"]:
        key = (result["instance"], result["seed"])
        if result["status"] == "feasible":
            cost = result["cost"]
            if result["solver"] in ranked_names:
                references[key] = min(cost, references.get(key, math.inf))
            if result["solver"] == baseline_name:
                baseline_costs[key] = cost
    for result in data["runs"]:
        key = (result["instance"], result["seed"])
        reference = references.get(key)
        feasible = result["status"] == "feasible"
        if not feasible or reference is None:
            normalized = 0.0
        elif reference == 0:
            normalized = 1.0 if result["cost"] == 0 else 0.0
        else:
            normalized = min(1.0, reference / result["cost"]) if result["cost"] else 1.0
        result["reference_cost"] = reference
        result["normalized_score"] = normalized
        baseline = baseline_costs.get(key)
        result["baseline_cost"] = baseline
        result["improvement_vs_baseline_pct"] = (
            100.0 * (baseline - result["cost"]) / baseline
            if feasible and baseline is not None and baseline > 0 else
            (0.0 if feasible and baseline == 0 and result["cost"] == 0 else None))
        result["gap_to_reference_pct"] = (
            100.0 * (result["cost"] - reference) / reference
            if feasible and reference is not None and reference > 0 else
            (0.0 if feasible and reference == 0 and result["cost"] == 0 else None))
    expected = len(data["instances"]) * len(data["seeds"])
    leaderboard: list[dict] = []
    for solver in data["solvers"]:
        rows = [row for row in data["runs"] if row["solver"] == solver["name"]]
        if len(rows) != expected:
            raise ValueError(f"Incomplete run matrix for {solver['name']}: {len(rows)}/{expected}")
        keys = {(row["instance"], row["seed"]) for row in rows}
        expected_keys = {(item["name"], seed) for item in data["instances"] for seed in data["seeds"]}
        if keys != expected_keys:
            raise ValueError(f"Duplicate or missing run cells for {solver['name']}")
        seconds = [row["seconds"] for row in rows if row.get("seconds") is not None]
        feasible = sum(row["status"] == "feasible" for row in rows)
        score = math.fsum(row["normalized_score"] for row in rows) / expected
        improvements = [row["improvement_vs_baseline_pct"] for row in rows
                        if row["improvement_vs_baseline_pct"] is not None]
        leaderboard.append({
            "solver": solver["name"], "include_in_ranking": solver.get("include_in_ranking", True),
            "rank": None, "score": score,
            "ranking_grade": 8.0 * score if solver.get("include_in_ranking", True) else None,
            "feasible_runs": feasible, "scheduled_runs": expected,
            "feasibility_pct": 100.0 * feasible / expected,
            "mean_seconds": statistics.fmean(seconds) if seconds else None,
            "total_seconds": math.fsum(seconds) if seconds else None,
            "mean_improvement_vs_baseline_pct": statistics.fmean(improvements) if improvements else None,
            "comparison_runs": len(improvements),
        })
    leaderboard.sort(key=lambda item: (not item["include_in_ranking"], -item["score"], item["solver"]))
    previous_score: float | None = None
    previous_rank: int | None = None
    position = 0
    for row in leaderboard:
        if not row["include_in_ranking"]:
            continue
        position += 1
        if previous_score is not None and math.isclose(row["score"], previous_score,
                                                       abs_tol=TIE_TOLERANCE, rel_tol=0.0):
            row["rank"] = previous_rank
        else:
            row["rank"] = position
            previous_score = row["score"]
            previous_rank = position
    data["leaderboard"] = leaderboard
    data["instance_summary"] = []
    for instance in data["instances"]:
        for solver in data["solvers"]:
            rows = [row for row in data["runs"]
                    if row["instance"] == instance["name"] and row["solver"] == solver["name"]]
            costs = [row["cost"] for row in rows if row["status"] == "feasible"]
            seconds = [row["seconds"] for row in rows if row.get("seconds") is not None]
            data["instance_summary"].append({
                "instance": instance["name"], "solver": solver["name"],
                "feasible_runs": len(costs), "scheduled_runs": len(rows),
                "mean_cost": statistics.fmean(costs) if costs else None,
                "best_cost": min(costs) if costs else None,
                "population_std_cost": statistics.pstdev(costs) if costs else None,
                "mean_seconds": statistics.fmean(seconds) if seconds else None,
                "mean_normalized_score": statistics.fmean(row["normalized_score"] for row in rows),
            })
    data["ranking_rule"] = {
        "formula": "ranking grade = 8 × mean(best ranked feasible cost / submitted cost)",
        "reference": "Best observed feasible cost among ranked solvers for the same instance and seed",
        "failure_score": 0, "zero_reference": "1 if both costs are zero, otherwise 0",
        "weights": "Every instance and every seed have equal weight; failures remain in the denominator",
        "tie_tolerance": TIE_TOLERANCE, "rank_style": "shared competition rank (1, 1, 3)",
        "all_invalid_cells": sum((item["name"], seed) not in references
                                 for item in data["instances"] for seed in data["seeds"]),
        "note": "Observed references are not proven optima. Nonranked baselines do not change grades.",
    }
    return data


def write_results(data: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    columns = ["solver", "instance", "seed", "status", "cost", "main_cost", "subroute_cost",
               "seconds", "returncode", "normalized_score", "reference_cost", "baseline_cost",
               "improvement_vs_baseline_pct", "gap_to_reference_pct", "instance_sha256",
               "solution_sha256", "errors"]
    with (output_dir / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in data["runs"]:
            value = dict(row)
            value["errors"] = " | ".join(row.get("errors", []))
            writer.writerow(value)
    from .report import write_report
    write_report(data, output_dir / "report.html")


def run_benchmark(config_path: str | Path, outdir: str | Path) -> dict:
    """Execute or import the complete solver × instance × seed experiment.

    ``outdir`` must not already exist; this prevents stale solution reuse.
    Relative config paths resolve against the configuration file's directory.
    Imported solutions are expected at ``solutions_dir/<instance>/seed_<seed>.json``.
    """
    config_path = Path(config_path).resolve()
    output_dir = Path(outdir).resolve()
    config, paths, solvers = _load_config(config_path)
    instances: list[tuple[Path, Any]] = [(path, load_instance(path)) for path in paths]
    names = [instance.name for _, instance in instances]
    if len(set(names)) != len(names):
        raise ValueError("Instance names must be unique across the experiment")
    if output_dir.exists():
        raise ValueError(f"Output directory already exists; choose a fresh directory: {output_dir}")
    output_dir.mkdir(parents=True)
    data: dict[str, Any] = {
        "schema_version": 1, "title": config.get("title", "STTRPSD benchmark comparison"),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path), "config_sha256": _sha256(config_path),
        "time_limit": config["time_limit"], "seeds": config["seeds"],
        "baseline_name": config.get("baseline_name"), "notes": config.get("notes", ""),
        "solvers": solvers, "instances": [], "runs": [],
        "environment": {"platform": platform.platform(), "python": sys.version,
                        "machine": platform.machine(), "processor": platform.processor(),
                        "logical_cpus": os.cpu_count(), "execution": "sequential",
                        "time_measurement": "wall clock, includes process startup",
                        "security": "process deadlines are not a security sandbox",
                        "cpu_affinity": ([min(os.sched_getaffinity(0))]
                                         if hasattr(os, "sched_getaffinity") else None),
                        "thread_environment": {key: "1" for key in (
                            "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                            "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")},
                        "user_description": config.get("environment", "")},
    }
    for path, instance in instances:
        data["instances"].append({"name": instance.name, "path": str(path),
                                  "sha256": _sha256(path), "data": instance.to_dict()})
    # Fixed instance/seed order, rotating solver order to avoid systematically
    # giving one team the first position on every instance. No jobs overlap.
    for instance_index, ((path, instance), descriptor) in enumerate(zip(instances, data["instances"])):
        for seed_index, seed in enumerate(config["seeds"]):
            offset = (instance_index * len(config["seeds"]) + seed_index) % len(solvers)
            order = list(range(len(solvers)))[offset:] + list(range(len(solvers)))[:offset]
            for solver_index in order:
                solver = solvers[solver_index]
                run_dir = (output_dir / "runs" / f"s{solver_index:02d}_{_slug(solver['name'])}" /
                           f"i{instance_index:03d}_{_slug(instance.name)}" / f"seed_{seed}")
                run_dir.mkdir(parents=True)
                solution_path = run_dir / "solution.json"
                result: dict[str, Any] = {
                    "solver": solver["name"], "instance": instance.name, "seed": seed,
                    "instance_sha256": descriptor["sha256"], "solution_sha256": None,
                    "feasible": False, "cost": None, "errors": [],
                    "seconds": None, "returncode": None, "solution": None,
                    "run_directory": str(run_dir.relative_to(output_dir)),
                }
                if "command" in solver:
                    command = [token.format(instance=str(path), solution=str(solution_path),
                                            seed=str(seed), time_limit=f"{config['time_limit']:g}",
                                            python=sys.executable)
                               for token in solver["command"]]
                    result["command"] = command
                    process = _run_process(command, solver["cwd"], config["time_limit"])
                    stdout, stderr = process.pop("stdout"), process.pop("stderr")
                    (run_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
                    (run_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
                    result.update(process)
                    result["stdout_excerpt"] = stdout[:8192]
                    result["stderr_excerpt"] = stderr[:8192]
                    if result["status"] == "ok":
                        score, solution, digest, _ = _score_file(instance, solution_path)
                        result.update(score)
                        result["solution"], result["solution_sha256"] = solution, digest
                    else:
                        # Keep provenance of rejected timeout/crash output, but
                        # never score it as an accepted incumbent.
                        try:
                            result["solution_sha256"] = hashlib.sha256(
                                _solution_bytes(solution_path)).hexdigest()
                        except (OSError, ValueError):
                            pass
                else:
                    source_root = Path(solver["solutions_dir"])
                    source = source_root / instance.name / f"seed_{seed}.json"
                    result["source_solution"] = str(source)
                    if not source.parent.resolve().is_relative_to(source_root):
                        score = {"status": "invalid_json", "feasible": False, "cost": None,
                                 "errors": ["Solution path escapes solutions_dir"]}
                        solution, digest, raw = None, None, None
                    else:
                        score, solution, digest, raw = _score_file(instance, source)
                    result.update(score)
                    result["solution"], result["solution_sha256"] = solution, digest
                    if raw is not None:
                        solution_path.write_bytes(raw)
                    result["timing_note"] = "Imported solution; runtime was not measured"
                data["runs"].append(result)
                # Preserve progress if an unrelated interruption stops a long
                # grading campaign. This is not an aggregate ranking yet.
                (output_dir / "progress.json").write_text(
                    json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    aggregate_results(data)
    write_results(data, output_dir)
    (output_dir / "progress.json").unlink(missing_ok=True)
    return data
