"""Small reproducible constructors to establish a feasible reference.

The nearest method chooses one satellite by a star-distance estimate, then
packs nearest-neighbour routes up to truck capacity. It deliberately omits
local search so that students retain substantial scope for improvement.
"""

from __future__ import annotations

import random
from typing import Any

from .model import Instance, capacity_tolerance


def make_solution(instance: Instance, seed: int = 0, method: str = "nearest") -> dict[str, Any]:
    if method not in ("nearest", "random"):
        raise ValueError("method must be nearest or random")
    rng = random.Random(seed)
    satellites = sorted(instance.satellites)
    if method == "random":
        satellite = rng.choice(satellites)
    else:
        satellite = min(satellites, key=lambda s: (
            2 * instance.distance(instance.depot, s)
            + 2 * sum(instance.distance(s, c) for c in instance.customers), s))
    remaining = set(instance.customers)
    trips = []
    while remaining:
        route = []
        load = 0.0
        current = satellite
        while True:
            fitting = sorted(c for c in remaining
                             if load + instance.customers[c].demand
                             <= instance.truck_capacity + capacity_tolerance(instance.truck_capacity))
            if not fitting:
                break
            if method == "random":
                chosen = rng.choice(fitting)
            else:
                chosen = min(fitting, key=lambda c: (instance.distance(current, c), c))
            route.append(chosen)
            remaining.remove(chosen)
            load += instance.customers[chosen].demand
            current = chosen
        if not route:
            raise ValueError("No customer fits an empty truck route; instance is infeasible")
        trips.append({"satellite": satellite, "customers": route})
    return {
        "schema_version": 1,
        "instance": instance.name,
        "main_route": [instance.depot, satellite, instance.depot],
        "truck_routes": trips,
        "metadata": {"method": f"baseline_{method}", "seed": seed},
    }
