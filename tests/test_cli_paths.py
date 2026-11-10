"""Exercise the real command-line file lifecycle on Windows and POSIX.

Arguments are passed as a list without a shell, using the current interpreter.
Each test gets a small copied project, so unrelated working directories and
spaces/non-ASCII characters cannot be masked by the repository's own cwd.
"""
from __future__ import annotations

import codecs
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CLIPathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="cli-lifecycle-", dir=ROOT / "tests")
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "cours en équipe Ω"
        self.project.mkdir()
        shutil.copytree(ROOT / "sttrpsd", self.project / "sttrpsd",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(ROOT / "examples", self.project / "examples")
        quickstart = ROOT / "scripts" / "quickstart.py"
        if quickstart.is_file():
            (self.project / "scripts").mkdir()
            shutil.copy2(quickstart, self.project / "scripts" / "quickstart.py")

        self.relative_instance = Path("instances d'essai") / "entrée Ω.json"
        self.relative_solution = Path("résultats Ω") / "routes du groupe.json"
        self.instance = self.project / self.relative_instance
        self.instance.parent.mkdir()
        data = json.loads((ROOT / "examples" / "toy.json").read_text(encoding="utf-8"))
        data["name"] = "toy Ω"
        self.instance.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.other_cwd = Path(self.temporary.name) / "autre dossier Ω"
        self.other_cwd.mkdir()

    def invoke(self, *arguments, cwd=None, environment=None, script=None):
        env = os.environ.copy()
        # Make -m work from an unrelated directory without installing anything.
        env["PYTHONPATH"] = str(self.project)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if environment:
            env.update(environment)
        command = ([sys.executable, str(script)] if script else
                   [sys.executable, "-m", "sttrpsd"])
        command.extend(str(argument) for argument in arguments)
        return subprocess.run(command, cwd=cwd or self.project, env=env,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=30, check=False)

    def json_result(self, result, expected_code=0):
        self.assertEqual(
            result.returncode, expected_code,
            f"stdout={result.stdout.decode('utf-8', errors='replace')}\n"
            f"stderr={result.stderr.decode('utf-8', errors='replace')}")
        self.assertNotIn(b"Traceback", result.stderr)
        return json.loads(result.stdout.decode("utf-8"))

    def construct(self, *, solution=None, instance=None, **options):
        return self.invoke("baseline", "--instance", instance or self.relative_instance,
                           "--solution", solution or self.relative_solution,
                           "--seed", "7", "--time-limit", "30", **options)

    def test_constructor_then_scorer_creates_nested_unicode_output(self):
        original_instance = self.instance.read_bytes()
        baseline = self.json_result(self.construct())
        solution = self.project / self.relative_solution
        self.assertTrue(solution.is_file())
        self.assertTrue(Path(baseline["solution"]).is_absolute())
        self.assertEqual(Path(baseline["solution"]).resolve(), solution.resolve())
        self.assertIn("Ω".encode("utf-8"), solution.read_bytes())
        self.assertEqual(json.loads(solution.read_text(encoding="utf-8"))["instance"], "toy Ω")

        score_path = Path("rapports d'essai") / "note Ω.json"
        score = self.json_result(self.invoke(
            "score", "--instance", self.relative_instance,
            "--solution", self.relative_solution, "--output", score_path))
        self.assertTrue(score["feasible"])
        self.assertAlmostEqual(score["cost"], baseline["cost"], places=12)
        self.assertEqual(json.loads((self.project / score_path).read_text(encoding="utf-8")), score)
        self.assertEqual(self.instance.read_bytes(), original_instance)
        self.assertEqual(list(self.project.rglob(".sttrpsd-*.tmp")), [])

    def test_absolute_paths_work_from_an_unrelated_working_directory(self):
        solution = self.project / self.relative_solution
        baseline = self.json_result(self.construct(
            instance=self.instance, solution=solution, cwd=self.other_cwd))
        score = self.json_result(self.invoke(
            "score", "--instance", self.instance, "--solution", solution,
            cwd=self.other_cwd))
        self.assertTrue(score["feasible"])
        self.assertAlmostEqual(score["cost"], baseline["cost"], places=12)
        self.assertFalse((self.other_cwd / self.relative_solution).exists())

    def test_cwd_mismatch_reports_the_missing_path_without_searching_elsewhere(self):
        self.json_result(self.construct())
        result = self.json_result(self.invoke(
            "score", "--instance", self.instance, "--solution", self.relative_solution,
            cwd=self.other_cwd), expected_code=2)
        self.assertFalse(result["feasible"])
        self.assertIsNone(result["cost"])
        error = "\n".join(result["errors"])
        self.assertIn(str((self.other_cwd / self.relative_solution).resolve()), error)
        self.assertIn(str(self.other_cwd.resolve()), error)
        self.assertIn("working directory", error.lower())
        self.assertIn("baseline", error.lower())
        self.assertTrue((self.project / self.relative_solution).is_file())
        self.assertFalse((self.other_cwd / self.relative_solution).exists())

    def test_missing_baseline_file_has_actionable_diagnostics(self):
        missing = Path("output") / "toy_baseline.json"
        result = self.json_result(self.invoke(
            "score", "--instance", self.relative_instance, "--solution", missing),
            expected_code=2)
        self.assertFalse(result["feasible"])
        self.assertIsNone(result["cost"])
        error = "\n".join(result["errors"])
        self.assertIn(str((self.project / missing).resolve()), error)
        self.assertIn(str(self.project.resolve()), error)
        self.assertIn("baseline", error.lower())
        self.assertIn("--solution", error)
        self.assertFalse((self.project / missing).exists())

    def test_failed_constructor_does_not_publish_an_output(self):
        self.instance.write_text("{ this is not JSON }", encoding="utf-8")
        result = self.construct()
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(b"Traceback", result.stderr)
        self.assertTrue(result.stderr)
        self.assertFalse((self.project / self.relative_solution).exists())

    def test_existing_solution_is_replaced_by_a_complete_file(self):
        destination = self.project / self.relative_solution
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"an old incomplete output")
        self.json_result(self.construct())
        score = self.json_result(self.invoke(
            "score", "--instance", self.relative_instance, "--solution", self.relative_solution))
        self.assertTrue(score["feasible"])
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8"))["metadata"]["seed"], 7)
        self.assertEqual(list(destination.parent.glob(".sttrpsd-*.tmp")), [])

    def test_output_parent_that_is_a_file_is_a_clean_failure(self):
        parent = self.project / "blocked output"
        parent.write_text("This is a file, not a directory", encoding="utf-8")
        result = self.construct(solution=Path("blocked output") / "solution.json")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(b"Traceback", result.stderr)
        self.assertFalse(result.stdout.strip())
        self.assertEqual(parent.read_text(encoding="utf-8"), "This is a file, not a directory")

    def test_legacy_stdout_encoding_keeps_success_and_unicode_path(self):
        result = self.construct(environment={"PYTHONIOENCODING": "cp1252"})
        baseline = self.json_result(result)
        result.stdout.decode("ascii")  # JSON escapes survive redirected Windows code pages.
        self.assertEqual(Path(baseline["solution"]), (self.project / self.relative_solution).resolve())
        score = self.json_result(self.invoke(
            "score", "--instance", self.relative_instance, "--solution", self.relative_solution,
            environment={"PYTHONIOENCODING": "cp1252"}))
        self.assertTrue(score["feasible"])

    def test_utf8_bom_is_accepted_for_instance_and_solution(self):
        self.instance.write_bytes(codecs.BOM_UTF8 + self.instance.read_bytes())
        self.json_result(self.construct())
        solution = self.project / self.relative_solution
        solution.write_bytes(codecs.BOM_UTF8 + solution.read_bytes())
        score = self.json_result(self.invoke(
            "score", "--instance", self.relative_instance, "--solution", self.relative_solution))
        self.assertTrue(score["feasible"])

    def test_bom_does_not_relax_duplicate_key_or_nonfinite_checks(self):
        solution = self.project / self.relative_solution
        solution.parent.mkdir(parents=True)
        cases = [('{"schema_version":1,"schema_version":1}', "duplicate"),
                 ('{"metadata":{"value":NaN}}', "non-finite"),
                 ('{"metadata":{"value":Infinity}}', "non-finite"),
                 ('{"metadata":{"value":1e999}}', "finite")]
        for content, diagnostic in cases:
            with self.subTest(diagnostic=diagnostic, content=content):
                solution.write_bytes(codecs.BOM_UTF8 + content.encode("utf-8"))
                result = self.json_result(self.invoke(
                    "score", "--instance", self.relative_instance,
                    "--solution", self.relative_solution), expected_code=2)
                self.assertFalse(result["feasible"])
                self.assertIn(diagnostic, " ".join(result["errors"]).lower())

    def test_bom_configuration_and_precomputed_solution_work_in_harness(self):
        self.json_result(self.construct())
        source = self.project / "saved solutions Ω" / "toy Ω" / "seed_0.json"
        source.parent.mkdir(parents=True)
        source.write_bytes(codecs.BOM_UTF8 + (self.project / self.relative_solution).read_bytes())
        configuration = {
            "schema_version": 1, "instances": [str(self.relative_instance)],
            "seeds": [0], "time_limit": 30,
            "solvers": [{"name": "Équipe Ω", "solutions_dir": "saved solutions Ω"}],
        }
        config_path = self.project / "configuration Ω.json"
        config_path.write_bytes(codecs.BOM_UTF8 + json.dumps(
            configuration, ensure_ascii=False).encode("utf-8"))
        destination = self.project / "comparison results Ω"
        self.json_result(self.invoke("benchmark", "--config", config_path,
                                     "--output", destination, cwd=self.other_cwd))
        data = json.loads((destination / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(data["runs"][0]["status"], "feasible")
        self.assertEqual(data["runs"][0]["solver"], "Équipe Ω")
        self.assertEqual(data["time_limit"], 30)

    @unittest.skipUnless(os.name == "nt", "Native Windows path syntax is checked on Windows CI")
    def test_windows_backslash_spelling_of_the_documented_commands(self):
        baseline = self.json_result(self.invoke(
            "baseline", "--instance", r"examples\toy.json",
            "--solution", r"output\toy_baseline.json", "--time-limit", "30"))
        score = self.json_result(self.invoke(
            "score", "--instance", r"examples\toy.json",
            "--solution", r"output\toy_baseline.json"))
        self.assertTrue(score["feasible"])
        self.assertAlmostEqual(baseline["cost"], score["cost"], places=12)
        self.assertTrue((self.project / "output" / "toy_baseline.json").is_file())

    def test_quickstart_script_works_from_an_unrelated_directory(self):
        script = self.project / "scripts" / "quickstart.py"
        self.assertTrue(script.is_file(), "The public quickstart script must be included")
        result = self.invoke(cwd=self.other_cwd, script=script)
        self.assertEqual(result.returncode, 0,
                         result.stderr.decode("utf-8", errors="replace"))
        self.assertNotIn(b"Traceback", result.stderr)
        solution = self.project / "output" / "toy_baseline.json"
        score_path = self.project / "output" / "toy_score.json"
        self.assertTrue(solution.is_file())
        stored_score = json.loads(score_path.read_text(encoding="utf-8"))
        score = self.json_result(self.invoke(
            "score", "--instance", self.project / "examples" / "toy.json",
            "--solution", solution, cwd=self.other_cwd))
        self.assertTrue(stored_score["feasible"])
        self.assertAlmostEqual(stored_score["cost"], score["cost"], places=12)
        self.assertFalse((self.other_cwd / "output").exists())


if __name__ == "__main__":
    unittest.main()
