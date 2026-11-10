"""Independent checks of the scorer's contractual and routing semantics."""

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from sttrpsd.baseline import make_solution
from sttrpsd.model import FormatError, load_instance, parse_instance
from sttrpsd.scoring import load_solution, score_solution


def example_data():
    return {
        "schema_version": 1,
        "name": "capacity-example",
        "depot": {"id": 0, "x": 0, "y": 0},
        "satellites": [{"id": 1, "x": 2, "y": 0}, {"id": 2, "x": 8, "y": 0}],
        "customers": [
            {"id": 3, "x": 2, "y": 3, "demand": 6},
            {"id": 4, "x": 4, "y": 3, "demand": 4},
            {"id": 5, "x": 8, "y": 4, "demand": 8},
            {"id": 6, "x": 10, "y": 4, "demand": 7},
        ],
        "truck_capacity": 10,
        "trailer_capacity": 15,
        "distance": {"type": "euclidean"},
    }


def example_solution():
    return {
        "schema_version": 1,
        "instance": "capacity-example",
        "main_route": [0, 1, 2, 0],
        "truck_routes": [
            {"satellite": 1, "customers": [3, 4]},
            {"satellite": 2, "customers": [5]},
            {"satellite": 2, "customers": [6]},
        ],
    }


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.instance = parse_instance(example_data())

    def score(self, solution):
        result = score_solution(self.instance, solution)
        json.dumps(result, allow_nan=False)
        return result

    def assert_invalid(self, solution, text):
        result = self.score(solution)
        self.assertFalse(result["feasible"])
        self.assertIsNone(result["cost"])
        self.assertTrue(any(text in error for error in result["errors"]), result)
        return result

    def test_hand_calculated_cost_and_capacity_boundary(self):
        result = self.score(example_solution())
        self.assertTrue(result["feasible"], result)
        self.assertEqual(result["main_cost"], 16.0)
        self.assertAlmostEqual(result["subroute_cost"], 3 + 2 + math.sqrt(13) + 8 + 2 * math.sqrt(20))
        self.assertAlmostEqual(result["cost"], 41.54982318546315)
        self.assertEqual(result["loads"], [10, 8, 7])
        self.assertEqual(result["n_subroutes"], 3)

    def test_singleton_main_and_customer_arcs_are_charged_twice(self):
        data = example_data()
        data["customers"] = data["customers"][:1]
        instance = parse_instance(data)
        solution = example_solution()
        solution["main_route"] = [0, 1, 0]
        solution["truck_routes"] = [{"satellite": 1, "customers": [3]}]
        result = score_solution(instance, solution)
        self.assertTrue(result["feasible"])
        self.assertEqual(result["main_cost"], 4)
        self.assertEqual(result["subroute_cost"], 6)
        self.assertEqual(result["cost"], 10)

    def test_multiple_trips_at_same_satellite_are_allowed(self):
        solution = example_solution()
        solution["main_route"] = [0, 1, 0]
        for trip in solution["truck_routes"]:
            trip["satellite"] = 1
        self.assertTrue(self.score(solution)["feasible"])

    def test_unused_main_satellite_is_allowed_and_charged(self):
        solution = example_solution()
        for trip in solution["truck_routes"]:
            trip["satellite"] = 1
        result = self.score(solution)
        self.assertTrue(result["feasible"])
        self.assertEqual(result["main_cost"], 16)

    def test_duplicate_and_missing_customers(self):
        solution = example_solution()
        solution["truck_routes"][2]["customers"] = [5]
        result = self.assert_invalid(solution, "more than once")
        self.assertIn("Unserved customers: [6]", result["errors"])

    def test_capacity_overflow(self):
        solution = example_solution()
        solution["truck_routes"][1]["customers"] = [5, 6]
        solution["truck_routes"].pop()
        self.assert_invalid(solution, "exceeds truck capacity")

    def test_main_route_cannot_include_customer_or_depot_inside(self):
        for interior in ([1, 3, 2], [1, 0, 2], [1, 999, 2]):
            with self.subTest(interior=interior):
                solution = example_solution()
                solution["main_route"] = [0] + interior + [0]
                self.assert_invalid(solution, "is not a satellite")

    def test_main_route_must_close_and_visit_distinct_satellites(self):
        for main, message in (([0, 1, 2], "start and end"),
                              ([0, 1, 2, 1, 0], "more than once"),
                              ([0, 0], "at least one satellite")):
            with self.subTest(main=main):
                solution = example_solution()
                solution["main_route"] = main
                self.assert_invalid(solution, message)

    def test_unvisited_satellite_and_cross_satellite_route_rejected(self):
        solution = example_solution()
        solution["main_route"] = [0, 1, 0]
        self.assert_invalid(solution, "absent from main_route")
        solution = example_solution()
        solution["truck_routes"][0]["end_satellite"] = 2
        self.assert_invalid(solution, "exactly satellite and customers")
        solution = example_solution()
        solution["truck_routes"][0]["customers"].append(2)
        self.assert_invalid(solution, "invalid customer ID")

    def test_bool_and_noninteger_node_ids_rejected(self):
        for bad in (True, 1.0, "1", None, {}, []):
            solution = example_solution()
            solution["main_route"][1] = bad
            self.assert_invalid(solution, "integer")
            solution = example_solution()
            solution["truck_routes"][0]["satellite"] = bad
            self.assert_invalid(solution, "existing satellite")
        for bad in (True, 3.0, "3", None, {}, []):
            solution = example_solution()
            solution["truck_routes"][0]["customers"][0] = bad
            self.assert_invalid(solution, "invalid customer ID")

    def test_empty_malformed_and_unknown_fields_rejected(self):
        for bad in (None, [], 1, "solution"):
            self.assert_invalid(bad, "JSON object")
        for bad in ({}, None, [], {"satellite": 1, "customers": []}):
            solution = example_solution()
            solution["truck_routes"].append(bad)
            self.assertFalse(self.score(solution)["feasible"])
        solution = example_solution()
        solution["objective"] = 0
        self.assert_invalid(solution, "Unknown fields")

    def test_instance_name_and_version_required(self):
        solution = example_solution()
        solution["instance"] = "other-instance"
        self.assert_invalid(solution, "instance must equal")
        for value in (True, 1.0, "1", 2):
            solution = example_solution()
            solution["schema_version"] = value
            self.assert_invalid(solution, "schema_version")

    def test_nonfinite_metadata_rejected(self):
        for number in (math.nan, math.inf, -math.inf):
            solution = example_solution()
            solution["metadata"] = {"value": number}
            self.assert_invalid(solution, "finite JSON")

    def test_truck_trip_order_does_not_affect_cost(self):
        solution = example_solution()
        original = self.score(solution)
        solution["truck_routes"].reverse()
        shuffled = self.score(solution)
        self.assertEqual(original["cost"], shuffled["cost"])


class InstanceTests(unittest.TestCase):
    def test_roundtrip_and_any_integer_node_ids(self):
        data = example_data()
        data["depot"]["id"] = -4
        instance = parse_instance(data)
        restored = parse_instance(instance.to_dict())
        self.assertEqual(restored.to_dict(), instance.to_dict())
        self.assertEqual(restored.depot, -4)

    def test_rounded_euclidean_uses_half_up(self):
        data = example_data()
        data["satellites"][0]["x"] = 2.5
        data["distance"] = {"type": "rounded_euclidean"}
        instance = parse_instance(data)
        self.assertEqual(instance.distance(0, 1), 3)
        self.assertEqual(instance.distance(1, 1), 0)

    def test_unrounded_and_zero_distance(self):
        data = example_data()
        data["satellites"][0]["x"] = 2.5
        instance = parse_instance(data)
        self.assertEqual(instance.distance(0, 1), 2.5)
        data["satellites"][0]["x"] = 0
        self.assertEqual(parse_instance(data).distance(0, 1), 0)

    def test_explicit_matrix_respects_order(self):
        data = example_data()
        order = [4, 2, 6, 0, 3, 5, 1]
        matrix = [[0 if i == j else 10 + i + j for j in range(7)] for i in range(7)]
        data["distance"] = {"type": "explicit", "node_order": order, "matrix": matrix}
        instance = parse_instance(data)
        self.assertEqual(instance.distance(4, 0), 13)
        result = score_solution(instance, example_solution())
        self.assertTrue(result["feasible"])
        expected_main = matrix[3][6] + matrix[6][1] + matrix[1][3]
        expected_sub = (matrix[6][4] + matrix[4][0] + matrix[0][6]
                        + 2 * matrix[1][5] + 2 * matrix[1][2])
        self.assertEqual(result["cost"], expected_main + expected_sub)
        matrix[0][1] += 1
        with self.assertRaisesRegex(FormatError, "symmetric"):
            parse_instance(data)

    def test_invalid_capacity_and_duplicate_ids(self):
        data = example_data()
        data["trailer_capacity"] = 14
        with self.assertRaisesRegex(FormatError, "Total demand"):
            parse_instance(data)
        data = example_data()
        data["customers"][0]["demand"] = 11
        with self.assertRaisesRegex(FormatError, "exceeds truck capacity"):
            parse_instance(data)
        data = example_data()
        data["customers"][0]["id"] = 1
        with self.assertRaisesRegex(FormatError, "Duplicate node ID"):
            parse_instance(data)

    def test_bad_numbers_and_ids(self):
        for bad in (math.inf, math.nan, True, "100", 10 ** 1000):
            data = example_data()
            data["satellites"][0]["x"] = bad
            with self.subTest(bad=str(bad)[:20]), self.assertRaises(FormatError):
                parse_instance(data)
        data = example_data()
        data["customers"][0]["id"] = True
        with self.assertRaisesRegex(FormatError, "integer"):
            parse_instance(data)

    def test_load_rejects_duplicate_keys_and_nonstandard_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "solution.json"
            for text in ('{"x": 1, "x": 2}', '{"x": NaN}', '{"x": Infinity}', 'no JSON'):
                path.write_text(text, encoding="utf-8")
                with self.subTest(text=text), self.assertRaises(FormatError):
                    load_solution(path)
            path.write_text('[]', encoding="utf-8")
            with self.assertRaisesRegex(FormatError, "JSON object"):
                load_solution(path)

    def test_overflow_numeric_json_is_rejected_in_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instance.json"
            raw = json.dumps(example_data()).replace('"truck_capacity": 10', '"truck_capacity": 1e999')
            path.write_text(raw, encoding="utf-8")
            with self.assertRaisesRegex(FormatError, "finite"):
                load_instance(path)


class BaselineTests(unittest.TestCase):
    def test_both_baselines_feasible_and_reproducible(self):
        instance = parse_instance(example_data())
        for method in ("nearest", "random"):
            for seed in range(8):
                with self.subTest(method=method, seed=seed):
                    solution = make_solution(instance, seed=seed, method=method)
                    self.assertEqual(solution, make_solution(instance, seed=seed, method=method))
                    self.assertTrue(score_solution(instance, solution)["feasible"])

    def test_one_route_per_customer_when_demands_equal_capacity(self):
        data = example_data()
        for customer in data["customers"]:
            customer["demand"] = 10
        data["trailer_capacity"] = 30
        instance = parse_instance(data)
        solution = make_solution(instance)
        self.assertEqual(len(solution["truck_routes"]), 4)
        self.assertTrue(score_solution(instance, solution)["feasible"])


if __name__ == "__main__":
    unittest.main()
