from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from sttrpsd.harness import aggregate_results, run_benchmark, _run_process, _score_file, _load_config, SOLUTION_LIMIT
from sttrpsd.model import parse_instance
from sttrpsd.report import write_report


INSTANCE = {
    "schema_version": 1, "name": "tiny", "truck_capacity": 5, "trailer_capacity": 5,
    "depot": {"id": 0, "x": 0, "y": 0},
    "satellites": [{"id": 1, "x": 1, "y": 0}],
    "customers": [{"id": 2, "x": 2, "y": 0, "demand": 3},
                  {"id": 3, "x": 3, "y": 0, "demand": 2}],
    "distance": {"type": "euclidean"},
}

SOLVER = r'''import json, os, pathlib, subprocess, sys, time
mode, instance_path, output_path = sys.argv[1:4]
instance = json.loads(pathlib.Path(instance_path).read_text(encoding="utf-8"))
solution = {"schema_version":1,"instance":instance["name"],"main_route":[0,1,0],
            "truck_routes":[{"satellite":1,"customers":[2,3]}]}
if mode == "missing":
    sys.exit(0)
if mode == "badjson":
    pathlib.Path(output_path).write_text('{"a": NaN}', encoding="utf-8")
    sys.exit(0)
if mode == "overflow":
    pathlib.Path(output_path).write_text('{"metadata":{"overflow":1e999}}', encoding="utf-8")
    sys.exit(0)
if mode == "invalid":
    solution["truck_routes"][0]["customers"] = [2,2]
pathlib.Path(output_path).write_text(json.dumps(solution), encoding="utf-8")
if mode == "crash":
    sys.exit(9)
if mode == "timeout":
    time.sleep(3)
if mode == "logs":
    sys.stdout.write("x" * 2000000)
if mode == "affinity":
    print(json.dumps({"omp":os.environ.get("OMP_NUM_THREADS"),
                     "cpus":sorted(os.sched_getaffinity(0)) if hasattr(os,"sched_getaffinity") else None}))
'''


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "instances").mkdir()
        (self.root / "instances" / "tiny.json").write_text(json.dumps(INSTANCE), encoding="utf-8")
        (self.root / "solver.py").write_text(SOLVER, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def config(self, modes, **changes):
        value = {
            "schema_version": 1, "instances": ["instances/tiny.json"],
            "seeds": [7], "time_limit": 3,
            "solvers": [{"name": mode, "command": [sys.executable, "solver.py", mode,
                         "{instance}", "{solution}"]} for mode in modes],
        }
        value.update(changes)
        path = self.root / "config.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_statuses_and_relative_paths(self):
        data = run_benchmark(self.config(["valid", "missing", "badjson", "overflow", "invalid", "crash"]),
                             self.root / "out")
        runs = {row["solver"]: row for row in data["runs"]}
        self.assertEqual({name: row["status"] for name, row in runs.items()},
                         {"valid": "feasible", "missing": "missing", "badjson": "invalid_json",
                          "overflow": "invalid_json",
                          "invalid": "invalid", "crash": "error"})
        self.assertEqual(runs["valid"]["cost"], 6)
        self.assertEqual(runs["crash"]["normalized_score"], 0)
        self.assertIsNone(runs["crash"]["cost"])
        self.assertIsNotNone(runs["crash"]["solution_sha256"])
        for name in ("report.html", "results.csv", "results.json"):
            self.assertTrue((self.root / "out" / name).is_file())
        self.assertFalse((self.root / "out" / "progress.json").exists())
        with self.assertRaisesRegex(ValueError, "already exists"):
            run_benchmark(self.root / "config.json", self.root / "out")

    def test_timeout_rejects_written_incumbent(self):
        # Leave enough startup time for Windows CI to publish the incumbent;
        # the fixture then sleeps beyond this deadline deliberately.
        data = run_benchmark(self.config(["timeout"], time_limit=1.0), self.root / "out")
        result = data["runs"][0]
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["normalized_score"], 0)
        self.assertIsNotNone(result["solution_sha256"])
        self.assertIsNone(result["solution"])
        self.assertLess(result["seconds"], 2)

    def test_bounded_logs_and_affinity(self):
        data = run_benchmark(self.config(["logs", "affinity"]), self.root / "out")
        logs = next(row for row in data["runs"] if row["solver"] == "logs")
        path = self.root / "out" / logs["run_directory"] / "stdout.txt"
        self.assertLess(path.stat().st_size, 66000)
        self.assertIn("log truncated", path.read_text(encoding="utf-8"))
        affinity = next(row for row in data["runs"] if row["solver"] == "affinity")
        self.assertEqual(affinity["status"], "feasible")
        settings = json.loads(affinity["stdout_excerpt"])
        self.assertEqual(settings["omp"], "1")
        if settings["cpus"] is not None:
            self.assertEqual(len(settings["cpus"]), 1)

    @unittest.skipUnless(os.name == "posix", "Process group cleanup is a POSIX feature")
    def test_timeout_cleans_child_process(self):
        target = self.root / "escaped.txt"
        child = self.root / "child.py"
        child.write_text("import time,pathlib,sys\ntime.sleep(.6)\npathlib.Path(sys.argv[1]).write_text('bad', encoding='utf-8')\n", encoding="utf-8")
        parent = self.root / "parent.py"
        parent.write_text("import subprocess,sys,time\nsubprocess.Popen([sys.executable,sys.argv[1],sys.argv[2]])\ntime.sleep(2)\n", encoding="utf-8")
        result = _run_process([sys.executable, str(parent), str(child), str(target)], str(self.root), .2)
        self.assertEqual(result["status"], "timeout")
        time.sleep(.65)
        self.assertFalse(target.exists())

    def test_import_and_html_injection(self):
        directory = self.root / "precomputed" / "tiny"
        directory.mkdir(parents=True)
        solution = {"schema_version": 1, "instance": "tiny", "main_route": [0, 1, 0],
                    "truck_routes": [{"satellite": 1, "customers": [2, 3]}]}
        (directory / "seed_7.json").write_text(json.dumps(solution), encoding="utf-8")
        malicious = '</script><script>window.pwned=true</script>'
        config = self.config([], solvers=[{"name": malicious, "solutions_dir": "precomputed"}])
        data = run_benchmark(config, self.root / "out")
        self.assertEqual(data["runs"][0]["status"], "feasible")
        self.assertIsNone(data["runs"][0]["seconds"])
        content = (self.root / "out" / "report.html").read_text(encoding="utf-8")
        self.assertNotIn(malicious, content)
        self.assertIn("\\u003c/script\\u003e", content)
        self.assertEqual(content.count("<script"), 2)
        self.assertEqual(data["leaderboard"][0]["solver"], malicious)
        self.assertNotIn("/script", data["runs"][0]["run_directory"])

    def test_duplicate_config_keys_rejected(self):
        path = self.root / "config.json"
        path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
            run_benchmark(path, self.root / "out")

    def test_unreadable_oversized_and_symlink_outputs(self):
        instance = parse_instance(INSTANCE)
        path = self.root / "large.json"
        with path.open("wb") as stream:
            stream.truncate(SOLUTION_LIMIT + 1)
        score, solution, digest, raw = _score_file(instance, path)
        self.assertEqual(score["status"], "invalid_json")
        self.assertIn("10 MiB", score["errors"][0])
        self.assertIsNone(raw)
        with patch("sttrpsd.harness.os.open", side_effect=PermissionError("Unreadable")):
            score, _, _, _ = _score_file(instance, path)
        self.assertEqual(score["status"], "invalid_json")
        if os.name == "posix":
            link = self.root / "link.json"
            link.symlink_to(path)
            score, _, _, _ = _score_file(instance, link)
            self.assertIn("symbolic link", score["errors"][0])
            fifo = self.root / "pipe.json"
            os.mkfifo(fifo)
            score, _, _, _ = _score_file(instance, fifo)
            self.assertEqual(score["status"], "invalid_json")
            self.assertIn("regular file", score["errors"][0])

    def test_missing_executable_does_not_abort_campaign(self):
        path = self.config(["valid"])
        config = json.loads(path.read_text(encoding="utf-8"))
        config["solvers"].insert(0, {"name": "missing executable", "command": ["./does_not_exist"]})
        path.write_text(json.dumps(config), encoding="utf-8")
        data = run_benchmark(path, self.root / "out")
        self.assertEqual({row["solver"]: row["status"] for row in data["runs"]},
                         {"missing executable": "error", "valid": "feasible"})

    def test_python_placeholder_uses_current_interpreter(self):
        path = self.config(["valid"])
        config = json.loads(path.read_text(encoding="utf-8"))
        config["solvers"][0]["command"][0] = "{python}"
        path.write_text(json.dumps(config), encoding="utf-8")
        data = run_benchmark(path, self.root / "out")
        self.assertEqual(data["runs"][0]["status"], "feasible")
        self.assertEqual(data["runs"][0]["command"][0], sys.executable)

    def test_course_budget_is_thirty_seconds(self):
        from sttrpsd.__main__ import _parser
        arguments = _parser().parse_args([
            "baseline", "--instance", "example.json", "--solution", "solution.json"])
        self.assertEqual(arguments.time_limit, 30.0)
        path = self.config(["valid"])
        config = json.loads(path.read_text(encoding="utf-8"))
        config.pop("time_limit")
        path.write_text(json.dumps(config), encoding="utf-8")
        loaded, _, _ = _load_config(path)
        self.assertEqual(loaded["time_limit"], 30.0)

    def test_run_matrix_and_shared_ties(self):
        data = ranking_fixture()
        aggregate_results(data)
        rows = {row["solver"]: row for row in data["leaderboard"]}
        self.assertEqual(rows["A"]["ranking_grade"], 6)
        self.assertEqual(rows["B"]["ranking_grade"], 4)
        self.assertEqual(rows["C"]["ranking_grade"], 4)
        self.assertEqual([rows[x]["rank"] for x in ["A", "B", "C"]], [1, 2, 2])
        self.assertIsNone(rows["Baseline"]["rank"])
        self.assertIsNone(rows["Baseline"]["ranking_grade"])
        self.assertEqual(data["runs"][0]["reference_cost"], 10)
        self.assertEqual(rows["B"]["feasible_runs"], 1)
        summary = next(row for row in data["instance_summary"] if row["solver"] == "A")
        self.assertEqual(summary["mean_cost"], 15)
        self.assertEqual(summary["best_cost"], 10)
        self.assertEqual(summary["population_std_cost"], 5)
        data["runs"].pop(0)
        with self.assertRaisesRegex(ValueError, "Incomplete run matrix"):
            aggregate_results(data)

    def test_zero_and_all_invalid_references(self):
        data = ranking_fixture()
        for row in data["runs"]:
            if row["seed"] == 0:
                row.update(status="feasible", cost=0)
            else:
                row.update(status="invalid", cost=None)
        aggregate_results(data)
        self.assertEqual(data["ranking_rule"]["all_invalid_cells"], 1)
        for row in data["leaderboard"]:
            if row["include_in_ranking"]:
                self.assertEqual(row["ranking_grade"], 4)


def ranking_fixture():
    data = {"solvers": [{"name": x, "include_in_ranking": x != "Baseline"}
                        for x in ["A", "B", "C", "Baseline"]],
            "instances": [{"name": "tiny"}], "seeds": [0, 1],
            "baseline_name": "Baseline", "runs": []}
    for name, costs in [("A", [10, 20]), ("B", [None, 10]), ("C", [10, None]), ("Baseline", [2, 2])]:
        for seed, cost in enumerate(costs):
            data["runs"].append({"solver": name, "instance": "tiny", "seed": seed,
                                 "status": "invalid" if cost is None else "feasible",
                                 "cost": cost, "seconds": .01})
    return data


if __name__ == "__main__":
    unittest.main()
