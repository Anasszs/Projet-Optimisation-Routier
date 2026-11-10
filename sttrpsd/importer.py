"""Import the original Villegas et al. (2010) STTRPSD text instances.

The second value on the first line counts *all* depots, including the main
depot. Original costs are unrounded Euclidean distances. This parser does
not infer node types from coordinates or impose an artificial coordinate box.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re


SOURCE_URL = "https://juangvillegas.com/download/"
_INTEGER = re.compile(r"[+]?[0-9]+\Z")
_NAME = re.compile(r"STTRP-(\d+)-(\d+)-([12])-(c|rd)\Z")


def _number(token: str, line: int, field: str) -> int | float:
    try:
        value = float(token)
    except ValueError as exc:
        raise ValueError(f"line {line}: {field} must be a finite number; got {token!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"line {line}: {field} must be finite; got {token!r}")
    return int(value) if value.is_integer() else value


def _positive_integer(token: str, line: int, field: str) -> int:
    if not _INTEGER.fullmatch(token):
        raise ValueError(f"line {line}: {field} must be a positive integer; got {token!r}")
    value = int(token)
    if value <= 0:
        raise ValueError(f"line {line}: {field} must be positive; got {value}")
    return value


def _fields(lines: list[str], index: int, count: int) -> list[str]:
    values = lines[index].split()
    if len(values) != count:
        raise ValueError(
            f"line {index + 1}: expected {count} fields, found {len(values)}"
        )
    return values


def convert_dat(path: str | Path) -> dict:
    """Return a canonical schema-version-1 instance from an original ``.dat``.

    Reject incorrect row counts, malformed numeric values, impossible demands,
    and misleading original-format filenames. Blank rows are errors; trailing
    whitespace on a nonempty row is accepted. The function does not write files.
    """
    path = Path(path)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path.name}: expected UTF-8/ASCII text") from exc
    lines = text.splitlines()
    if len(lines) < 2:
        raise ValueError("expected at least two header lines")
    n_token, depots_token = _fields(lines, 0, 2)
    n = _positive_integer(n_token, 1, "customer count")
    depot_count = _positive_integer(depots_token, 1, "depot count including main depot")
    if depot_count < 2:
        raise ValueError("line 1: need the main depot and at least one satellite depot")
    p = depot_count - 1
    expected_rows = 2 + depot_count + n
    if len(lines) != expected_rows:
        raise ValueError(
            f"expected exactly {expected_rows} lines (2 headers + {depot_count} "
            f"depots + {n} customers), found {len(lines)}"
        )
    capacity_fields = _fields(lines, 1, 2)
    truck = _number(capacity_fields[0], 2, "truck capacity")
    trailer = _number(capacity_fields[1], 2, "trailer capacity")
    if truck <= 0 or trailer < 0:
        raise ValueError("line 2: truck capacity must be positive and trailer capacity nonnegative")
    depots = []
    for i in range(depot_count):
        row = i + 2
        x, y = _fields(lines, row, 2)
        depots.append({"id": i, "x": _number(x, row + 1, "x"), "y": _number(y, row + 1, "y")})
    customers = []
    for i in range(n):
        row = 2 + depot_count + i
        x, y, q = _fields(lines, row, 3)
        demand = _number(q, row + 1, "demand")
        if demand <= 0 or demand > truck:
            raise ValueError(
                f"line {row + 1}: demand must be positive and no greater than truck capacity {truck}"
            )
        customers.append({"id": depot_count + i, "x": _number(x, row + 1, "x"),
                          "y": _number(y, row + 1, "y"), "demand": demand})
    if math.fsum(c["demand"] for c in customers) > truck + trailer:
        raise ValueError("total customer demand exceeds combined truck and trailer capacity")
    metadata = {
        "source_filename": path.name,
        "source_url": SOURCE_URL,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "provenance": "Villegas et al. 2010 original benchmark",
    }
    name_match = _NAME.fullmatch(path.stem)
    if name_match:
        name_n, name_p, name_q, geometry = name_match.groups()
        if (int(name_n), int(name_p), 1000 * int(name_q)) != (n, p, truck):
            raise ValueError("instance header disagrees with the original-format filename")
        metadata["geometry"] = geometry
    else:
        # An unknown filename may be a renamed original or another compatible
        # dataset. Never label unverified input as an original benchmark file.
        metadata["provenance"] = "Imported from the Villegas STTRPSD text format; origin unverified"
    return {
        "schema_version": 1,
        "name": path.stem,
        "depot": depots[0],
        "satellites": depots[1:],
        "customers": customers,
        "truck_capacity": truck,
        "trailer_capacity": trailer,
        "distance": {"type": "euclidean"},
        "metadata": metadata,
    }
