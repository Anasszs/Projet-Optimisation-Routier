"""Construct and score the toy solution using paths rooted at this repository.

Run with ``py -3 scripts/quickstart.py`` on Windows or
``python3 scripts/quickstart.py`` on macOS/Linux. An absolute script path also
works from another working directory. Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    instance = root / "examples" / "toy.json"
    solution = root / "output" / "toy_baseline.json"
    score = root / "output" / "toy_score.json"

    if not (root / "sttrpsd" / "__main__.py").is_file() or not instance.is_file():
        print(
            "The complete project is required. Extract the entire ZIP or clone "
            "the repository, keeping scripts/, sttrpsd/ and examples/ together.",
            file=sys.stderr,
        )
        return 2

    print("Constructing output/toy_baseline.json...", flush=True)
    baseline_command = [
        sys.executable, "-m", "sttrpsd", "baseline",
        "--instance", str(instance), "--solution", str(solution),
        "--method", "nearest", "--seed", "0", "--time-limit", "30",
    ]
    try:
        constructed = subprocess.run(baseline_command, cwd=root, check=False)
        if constructed.returncode != 0:
            print(
                "Construction failed; scoring was not run. Read the error above.",
                file=sys.stderr,
            )
            return constructed.returncode
        if not solution.is_file():
            print(
                "Construction returned success but output/toy_baseline.json "
                "is missing. Scoring was not run.",
                file=sys.stderr,
            )
            return 2

        print("Scoring that solution and writing output/toy_score.json...", flush=True)
        scored = subprocess.run(
            [
                sys.executable, "-m", "sttrpsd", "score",
                "--instance", str(instance), "--solution", str(solution),
                "--output", str(score),
            ],
            cwd=root,
            check=False,
        )
    except OSError as exc:
        print(f"Could not run the Python command: {exc}", file=sys.stderr)
        return 2

    if scored.returncode == 0:
        print("Quick start completed: the constructed toy solution is feasible.")
    return scored.returncode


if __name__ == "__main__":
    raise SystemExit(main())
