"""Independent feasibility checking and objective reconstruction.

A truck route stores its satellite once. Its return to that same satellite is
implicit, which rules out open routes and transfers between satellites. Both
the outbound and return arcs are always charged, even for singleton routes.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from .model import FormatError, Instance, capacity_tolerance, load_json


def load_solution(path: str | Path) -> dict[str, Any]:
    data = load_json(path)
    if not isinstance(data, dict):
        raise FormatError("Solution must be a JSON object")
    return data


def score_solution(instance: Instance, solution: Any) -> dict[str, Any]:
    """Check a solution and return JSON-serializable diagnostics.

    Invalid solutions always have ``cost=None``. No penalty distance is used
    to disguise infeasibility. Names must exactly match the input instance.
    Capacity tolerance is 1e-9 * max(1, capacity). An unused satellite may
    appear on the main route, but a satellite may not be visited twice.
    """
    result: dict[str, Any] = {
        "feasible": False,
        "cost": None,
        "main_cost": None,
        "subroute_cost": None,
        "errors": [],
        "n_customers": len(instance.customers),
        "n_satellites_used": 0,
        "n_subroutes": 0,
        "loads": [],
    }
    errors: list[str] = result["errors"]
    if not isinstance(solution, dict):
        errors.append("Solution must be a JSON object")
        return result
    required = {"schema_version", "instance", "main_route", "truck_routes"}
    allowed = required | {"metadata"}
    missing = required - solution.keys()
    extra = solution.keys() - allowed
    if missing:
        errors.append(f"Missing fields: {', '.join(sorted(missing))}")
    if extra:
        errors.append(f"Unknown fields: {', '.join(sorted(map(str, extra)))}")
    if type(solution.get("schema_version")) is not int or solution.get("schema_version") != 1:
        errors.append("schema_version must be the integer 1")
    if solution.get("instance") != instance.name:
        errors.append(f"instance must equal {instance.name!r}")
    if "metadata" in solution:
        if not isinstance(solution["metadata"], dict):
            errors.append("metadata must be an object")
        else:
            try:
                json.dumps(solution["metadata"], allow_nan=False)
            except (ValueError, TypeError, RecursionError):
                errors.append("metadata must contain finite JSON values")

    main = solution.get("main_route")
    visited: set[int] = set()
    if not isinstance(main, list):
        errors.append("main_route must be an array")
    elif len(main) < 3:
        errors.append("main_route must visit at least one satellite between depot endpoints")
    elif any(type(value) is not int for value in main):
        errors.append("Every main_route node ID must be an integer (not a Boolean)")
    else:
        if main[0] != instance.depot or main[-1] != instance.depot:
            errors.append(f"main_route must start and end at depot {instance.depot}")
        for node in main[1:-1]:
            if node not in instance.satellites:
                errors.append(f"Main route interior node {node} is not a satellite")
            elif node in visited:
                errors.append(f"Satellite {node} is visited more than once on main_route")
            else:
                visited.add(node)
    result["n_satellites_used"] = len(visited)

    trips = solution.get("truck_routes")
    customer_count: Counter[int] = Counter()
    good_trips: list[tuple[int, list[int]]] = []
    if not isinstance(trips, list):
        errors.append("truck_routes must be an array")
    else:
        result["n_subroutes"] = len(trips)
        for index, trip in enumerate(trips):
            label = f"truck_routes[{index}]"
            if not isinstance(trip, dict):
                errors.append(f"{label} must be an object")
                continue
            if set(trip) != {"satellite", "customers"}:
                errors.append(f"{label} must contain exactly satellite and customers")
            satellite = trip.get("satellite")
            valid_satellite = type(satellite) is int and satellite in instance.satellites
            if not valid_satellite:
                errors.append(f"{label}.satellite must name an existing satellite with an integer ID")
            elif satellite not in visited:
                errors.append(f"{label} uses satellite {satellite}, absent from main_route")
            customers = trip.get("customers")
            if not isinstance(customers, list) or not customers:
                errors.append(f"{label}.customers must be a nonempty array")
                continue
            route_demands = []
            valid_customers = True
            for customer in customers:
                if type(customer) is not int or customer not in instance.customers:
                    errors.append(f"{label} contains an invalid customer ID: {customer!r}")
                    valid_customers = False
                else:
                    customer_count[customer] += 1
                    route_demands.append(instance.customers[customer].demand)
            try:
                load = math.fsum(route_demands)
            except OverflowError:
                load = math.inf
            # Partial loads are not meaningful for a malformed route.
            result["loads"].append(load if valid_customers and math.isfinite(load) else None)
            if load > instance.truck_capacity + capacity_tolerance(instance.truck_capacity):
                errors.append(f"{label} load {load:g} exceeds truck capacity {instance.truck_capacity:g}")
            if valid_satellite and valid_customers:
                good_trips.append((satellite, customers))
    missing_customers = sorted(set(instance.customers) - customer_count.keys())
    duplicates = sorted(customer for customer, count in customer_count.items() if count > 1)
    if missing_customers:
        errors.append(f"Unserved customers: {missing_customers}")
    if duplicates:
        errors.append(f"Customers served more than once: {duplicates}")
    if errors:
        return result
    try:
        main_cost = math.fsum(instance.distance(a, b) for a, b in zip(main, main[1:]))
        subroute_cost = math.fsum(
            instance.distance(a, b)
            for satellite, customers in good_trips
            for a, b in zip([satellite] + customers, customers + [satellite])
        )
        cost = math.fsum((main_cost, subroute_cost))
    except (OverflowError, ValueError):
        errors.append("Objective calculation overflowed")
        return result
    if not all(math.isfinite(value) for value in (main_cost, subroute_cost, cost)):
        errors.append("Objective must be finite")
        return result
    result.update(feasible=True, cost=cost, main_cost=main_cost, subroute_cost=subroute_cost)
    return result

