"""Checks against the original dataset and malformed source files."""

import math
from pathlib import Path
import tempfile
import unittest

from sttrpsd.importer import convert_dat
from sttrpsd.model import parse_instance


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "instructor" / "raw"


class ImporterTests(unittest.TestCase):
    def convert_text(self, content):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tiny.dat"
            path.write_text(content, encoding="utf-8")
            return convert_dat(path)

    def test_all_32_original_instances(self):
        paths = sorted(RAW.glob("*.dat"))
        if not paths:
            self.skipTest("Original instructor dataset is not in this distribution")
        self.assertEqual(len(paths), 32)
        for path in paths:
            with self.subTest(path=path.name):
                instance = convert_dat(path)
                parse_instance(instance)
                n, p, capacity, geometry = path.stem.split("-")[1:]
                self.assertEqual(len(instance["customers"]), int(n))
                self.assertEqual(len(instance["satellites"]), int(p))
                self.assertEqual(instance["truck_capacity"], 1000 * int(capacity))
                self.assertEqual(instance["metadata"]["geometry"], geometry)
                self.assertEqual(instance["distance"], {"type": "euclidean"})
                self.assertLessEqual(sum(c["demand"] for c in instance["customers"]),
                                     instance["truck_capacity"] + instance["trailer_capacity"])

    def test_implicit_ids_and_noninteger_coordinates(self):
        instance = self.convert_text("2 2\n10 20\n0 0\n120.5 -2.25\n1 1 4\n2 3 7\n")
        self.assertEqual(instance["depot"]["id"], 0)
        self.assertEqual(instance["satellites"], [{"id": 1, "x": 120.5, "y": -2.25}])
        self.assertEqual([c["id"] for c in instance["customers"]], [2, 3])

    def test_malformed_input_is_rejected(self):
        correct = "1 2\n10 20\n0 0\n1 1\n2 2 5\n"
        cases = {
            "missing row": correct.rsplit("2 2 5", 1)[0],
            "extra row": correct + "3 3 1\n",
            "blank row": correct.replace("1 1\n", "\n"),
            "extra field": correct.replace("1 1\n", "1 1 99\n"),
            "NaN coordinate": correct.replace("1 1\n", "nan 1\n"),
            "infinite capacity": correct.replace("10 20", "inf 20"),
            "fractional count": correct.replace("1 2\n", "1.0 2\n", 1),
            "oversize customer": correct.replace("2 2 5", "2 2 11"),
            "negative demand": correct.replace("2 2 5", "2 2 -1"),
            "combined capacity": "2 2\n10 0\n0 0\n1 1\n2 2 6\n3 3 6\n",
        }
        for label, text in cases.items():
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.convert_text(text)

    def test_imported_metric_does_not_round(self):
        instance = parse_instance(self.convert_text("1 2\n10 20\n0 0\n1 1\n2 2 5\n"))
        self.assertAlmostEqual(instance.distance(0, 1), math.sqrt(2), places=14)
        self.assertAlmostEqual(instance.distance(0, 2), math.sqrt(8), places=14)


if __name__ == "__main__":
    unittest.main()
