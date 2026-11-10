"""Validated instances and their authoritative distance convention.

The canonical JSON format is deliberately independent of a benchmark's text
format. The metric must be stated explicitly. ``rounded_euclidean`` means
floor(hypot(dx, dy) + 0.5), not Python's ties-to-even ``round``.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class FormatError(ValueError):
    """An input file does not satisfy the course's data contract."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FormatError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise FormatError(f"Non-finite JSON constant is forbidden: {value}")


def _finite_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise FormatError(f"JSON number is outside the finite range: {token[:80]}")
    return value


def describe_path(path: str | Path) -> str:
    """Describe one native path without searching for or substituting a file."""
    requested = Path(path)
    try:
        resolved = requested.resolve()
    except (OSError, RuntimeError, ValueError):
        # Still give useful context if a malformed path or a symlink loop
        # prevents canonicalization. Opening the requested path reports why.
        resolved = requested.absolute()
    # Use literal native paths, not repr(): repr would double every Windows
    # backslash even after a caller decodes the surrounding JSON response.
    return (f'requested path "{requested}"; resolved path "{resolved}"; '
            f'working directory "{Path.cwd()}"')


def load_json(path: str | Path, max_bytes: int = 16 * 1024 * 1024) -> Any:
    """Read UTF-8 JSON (an optional BOM is accepted), with strict validation.

    The size guard prevents an accidentally huge submission from exhausting
    the evaluator. It is a data guard, not a security sandbox.
    Relative paths use the process's current working directory. Native path
    separators are left untouched; no alternative file is selected on failure.
    """
    path = Path(path)
    try:
        with path.open("rb") as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise FormatError(f"JSON file exceeds {max_bytes} bytes: {path.name}")
        return json.loads(
            raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
            parse_float=_finite_float, parse_constant=_reject_constant,
        )
    except FileNotFoundError as exc:
        raise FormatError(
            f"JSON file not found ({describe_path(path)}). "
            "Check the exact filename and current working directory; "
            "relative paths are resolved from that directory."
        ) from exc
    except IsADirectoryError as exc:
        raise FormatError(f"Expected a JSON file, but the path is a directory ({describe_path(path)})") from exc
    except FormatError as exc:
        raise FormatError(f"Invalid JSON ({describe_path(path)}): {exc}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise FormatError(f"Cannot read JSON ({describe_path(path)}): {exc}") from exc


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FormatError(f"{where} must be an object")
    return value


def _keys(value: dict[str, Any], required: set[str], optional: set[str], where: str) -> None:
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing:
        raise FormatError(f"{where} is missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise FormatError(f"{where} has unknown fields: {', '.join(sorted(map(str, extra)))}")


def _integer(value: Any, where: str) -> int:
    if type(value) is not int:
        raise FormatError(f"{where} must be an integer (not a Boolean)")
    return value


def _number(value: Any, where: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FormatError(f"{where} must be a finite number")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise FormatError(f"{where} must be a finite number") from exc
    if not math.isfinite(result):
        raise FormatError(f"{where} must be a finite number")
    if positive and result <= 0:
        raise FormatError(f"{where} must be positive")
    if nonnegative and result < 0:
        raise FormatError(f"{where} must be nonnegative")
    return result


def capacity_tolerance(capacity: float) -> float:
    """Tolerance used only for floating point capacity comparisons."""
    return 1e-9 * max(1.0, capacity)


def _check_json_metadata(value: Any, where: str) -> dict[str, Any]:
    result = _object(value, where)
    try:
        # Also validates nested metadata supplied directly through the Python API.
        json.dumps(result, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise FormatError(f"{where} must contain finite JSON values: {exc}") from exc
    return copy.deepcopy(result)


@dataclass(frozen=True)
class Node:
    id: int
    x: float
    y: float
    demand: float = 0.0

    def to_dict(self, customer: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {"id": self.id, "x": self.x, "y": self.y}
        if customer:
            result["demand"] = self.demand
        return result


@dataclass
class Instance:
    name: str
    depot: int
    satellites: dict[int, Node]
    customers: dict[int, Node]
    truck_capacity: float
    trailer_capacity: float
    distance_type: str
    nodes: dict[int, Node]
    metadata: dict[str, Any] = field(default_factory=dict)
    _matrix: tuple[tuple[float, ...], ...] | None = field(default=None, repr=False)
    _node_order: tuple[int, ...] = field(default=(), repr=False)
    _index: dict[int, int] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Instance":
        return parse_instance(data)

    @property
    def total_demand(self) -> float:
        return math.fsum(node.demand for node in self.customers.values())

    def distance(self, a: int, b: int) -> float:
        """Return the specified arc cost, including zero on the diagonal."""
        if a not in self.nodes or b not in self.nodes:
            raise KeyError(f"Unknown node in arc ({a}, {b})")
        if self._matrix is not None:
            return self._matrix[self._index[a]][self._index[b]]
        if a == b:
            return 0.0
        u, v = self.nodes[a], self.nodes[b]
        cost = math.hypot(u.x - v.x, u.y - v.y)
        if self.distance_type == "rounded_euclidean":
            return float(math.floor(cost + 0.5))
        return cost

    def to_dict(self) -> dict[str, Any]:
        distance: dict[str, Any] = {"type": self.distance_type}
        if self._matrix is not None:
            distance["node_order"] = list(self._node_order)
            distance["matrix"] = [list(row) for row in self._matrix]
        result: dict[str, Any] = {
            "schema_version": 1,
            "name": self.name,
            "depot": self.nodes[self.depot].to_dict(),
            "satellites": [node.to_dict() for node in self.satellites.values()],
            "customers": [node.to_dict(customer=True) for node in self.customers.values()],
            "truck_capacity": self.truck_capacity,
            "trailer_capacity": self.trailer_capacity,
            "distance": distance,
        }
        if self.metadata:
            result["metadata"] = copy.deepcopy(self.metadata)
        return result


def parse_instance(data: Any) -> Instance:
    """Validate a nonempty, individually feasible classical STTRPSD instance."""
    data = _object(data, "instance")
    _keys(data, {"schema_version", "name", "depot", "satellites", "customers",
                 "truck_capacity", "trailer_capacity", "distance"}, {"metadata"}, "instance")
    if _integer(data["schema_version"], "schema_version") != 1:
        raise FormatError("Unsupported schema_version (expected 1)")
    if not isinstance(data["name"], str) or not data["name"].strip():
        raise FormatError("name must be a nonempty string")
    truck_capacity = _number(data["truck_capacity"], "truck_capacity", positive=True)
    trailer_capacity = _number(data["trailer_capacity"], "trailer_capacity", nonnegative=True)
    if not math.isfinite(truck_capacity + trailer_capacity):
        raise FormatError("Combined truck and trailer capacity must be finite")
    nodes: dict[int, Node] = {}

    def read_node(raw: Any, where: str, customer: bool = False) -> Node:
        raw = _object(raw, where)
        required = {"id", "x", "y"} | ({"demand"} if customer else set())
        _keys(raw, required, set(), where)
        identifier = _integer(raw["id"], f"{where}.id")
        if identifier in nodes:
            raise FormatError(f"Duplicate node ID: {identifier}")
        demand = _number(raw["demand"], f"{where}.demand", positive=True) if customer else 0.0
        if demand > truck_capacity + capacity_tolerance(truck_capacity):
            raise FormatError(f"Customer {identifier} demand exceeds truck capacity")
        node = Node(identifier, _number(raw["x"], f"{where}.x"),
                    _number(raw["y"], f"{where}.y"), demand)
        nodes[identifier] = node
        return node

    depot_node = read_node(data["depot"], "depot")
    categories: dict[str, dict[int, Node]] = {}
    for category in ("satellites", "customers"):
        raw_nodes = data[category]
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise FormatError(f"{category} must be a nonempty array")
        categories[category] = {}
        for index, raw_node in enumerate(raw_nodes):
            node = read_node(raw_node, f"{category}[{index}]", category == "customers")
            categories[category][node.id] = node
    try:
        total = math.fsum(node.demand for node in categories["customers"].values())
    except OverflowError as exc:
        raise FormatError("Total demand must be finite") from exc
    combined = truck_capacity + trailer_capacity
    if total > combined + capacity_tolerance(combined):
        raise FormatError("Total demand exceeds combined truck and trailer capacity")

    specification = _object(data["distance"], "distance")
    _keys(specification, {"type"}, {"matrix", "node_order"}, "distance")
    metric = specification["type"]
    if metric not in ("euclidean", "rounded_euclidean", "explicit"):
        raise FormatError("distance.type must be euclidean, rounded_euclidean or explicit")
    matrix = None
    order: tuple[int, ...] = ()
    matrix_index: dict[int, int] = {}
    if metric == "explicit":
        if "matrix" not in specification or "node_order" not in specification:
            raise FormatError("Explicit distances require matrix and node_order")
        raw_order = specification["node_order"]
        if not isinstance(raw_order, list):
            raise FormatError("distance.node_order must be an array")
        order = tuple(_integer(value, "distance.node_order entry") for value in raw_order)
        if len(order) != len(nodes) or set(order) != set(nodes):
            raise FormatError("distance.node_order must contain each node ID exactly once")
        raw_matrix = specification["matrix"]
        if not isinstance(raw_matrix, list) or len(raw_matrix) != len(nodes):
            raise FormatError("distance.matrix must have one row per node")
        rows = []
        for i, row in enumerate(raw_matrix):
            if not isinstance(row, list) or len(row) != len(nodes):
                raise FormatError(f"distance.matrix row {i} must have one entry per node")
            rows.append(tuple(_number(value, f"distance.matrix[{i}][{j}]", nonnegative=True)
                              for j, value in enumerate(row)))
        matrix = tuple(rows)
        for i in range(len(nodes)):
            if matrix[i][i] != 0:
                raise FormatError("Explicit distance matrix diagonal must be zero")
            for j in range(i):
                if matrix[i][j] != matrix[j][i]:
                    raise FormatError("The classical course variant requires symmetric distances")
        matrix_index = {node: index for index, node in enumerate(order)}
    else:
        if "matrix" in specification or "node_order" in specification:
            raise FormatError("matrix and node_order are only allowed for explicit distances")
        span_x = max(node.x for node in nodes.values()) - min(node.x for node in nodes.values())
        span_y = max(node.y for node in nodes.values()) - min(node.y for node in nodes.values())
        if not math.isfinite(math.hypot(span_x, span_y)):
            raise FormatError("Coordinates produce non-finite Euclidean distances")

    return Instance(data["name"], depot_node.id, categories["satellites"], categories["customers"],
                    truck_capacity, trailer_capacity, metric, nodes,
                    _check_json_metadata(data.get("metadata", {}), "metadata"),
                    matrix, order, matrix_index)


def load_instance(path: str | Path) -> Instance:
    return parse_instance(load_json(path))

