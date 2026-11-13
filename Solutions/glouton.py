"""Glouton le plus simple pour le STTRPSD.

1. On choisit UN satellite s : celui qui minimise la somme des distances aux clients.
2. Tournée principale : 0 -> s -> 0.
3. Tournées camion depuis s, au plus proche voisin :
   on ajoute le client non servi le plus proche qui tient dans la capacité restante ;
   quand plus aucun ne tient, on revient à s et on ouvre une nouvelle tournée.

Utilisation (depuis la racine du projet) :
    python Solutions/glouton.py --instance examples/toy.json --solution output/toy_glouton.json --seed 0 --time-limit 30
"""

import argparse
import json
import math
import os


def distance(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def glouton(inst):
    depot = inst["depot"]
    satellites = inst["satellites"]
    clients = inst["customers"]
    QV = inst["truck_capacity"]

    # 1. choix du satellite
    s = min(satellites, key=lambda sat: sum(distance(sat, c) for c in clients))

    # 2-3. tournées camion au plus proche voisin
    non_servis = list(clients)
    tournees = []
    while non_servis:
        tournee, charge, pos = [], 0, s
        while True:
            candidats = [c for c in non_servis if charge + c["demand"] <= QV]
            if not candidats:
                break
            c = min(candidats, key=lambda c: distance(pos, c))
            tournee.append(c["id"])
            charge += c["demand"]
            pos = c
            non_servis.remove(c)
        tournees.append({"satellite": s["id"], "customers": tournee})

    return {
        "schema_version": 1,
        "instance": inst["name"],
        "main_route": [depot["id"], s["id"], depot["id"]],
        "truck_routes": tournees,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", required=True)
    parser.add_argument("--solution", required=True)
    parser.add_argument("--seed", type=int, default=0)          # inutilisé (méthode déterministe)
    parser.add_argument("--time-limit", type=float, default=30)  # inutilisé (très rapide)
    args = parser.parse_args()

    with open(args.instance, encoding="utf-8-sig") as f:
        instance = json.load(f)

    solution = glouton(instance)

