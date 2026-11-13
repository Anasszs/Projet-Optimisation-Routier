"""Glouton "tous les satellites" pour le STTRPSD.

1. Tournée principale : on visite TOUS les satellites, dans l'ordre du plus
   proche voisin depuis le dépôt : 0 -> s1 -> s2 -> ... -> sk -> 0.
2. Chaque client est affecté à son satellite le plus proche.
3. Depuis chaque satellite, tournées camion au plus proche voisin :
   on ajoute le client non servi le plus proche qui tient dans la capacité
   restante ; quand plus aucun ne tient, on revient au satellite et on ouvre
   une nouvelle tournée.

Un satellite qui ne reçoit aucun client reste visité : c'est autorisé, mais
son trajet est compté dans le coût.

Utilisation (depuis la racine du projet) :
    python Solutions/glouton_tous_satellites.py --instance examples/toy.json --solution output/toy_tous.json
"""

import argparse
import json
import math
import os


def distance(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def tournees_plus_proche_voisin(s, clients, QV):
    """Découpe la liste `clients` en tournées camion partant du satellite s."""
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
    return tournees


def glouton_tous_satellites(inst):
    depot = inst["depot"]
    satellites = inst["satellites"]
    clients = inst["customers"]
    QV = inst["truck_capacity"]

    # 1. ordre de visite de tous les satellites (plus proche voisin depuis le dépôt)
    ordre, restants, pos = [], list(satellites), depot
    while restants:
        s = min(restants, key=lambda s: distance(pos, s))
        ordre.append(s)
        restants.remove(s)
        pos = s

    # 2. affectation de chaque client à son satellite le plus proche
    affectation = {s["id"]: [] for s in satellites}
    for c in clients:
        s = min(satellites, key=lambda s: distance(s, c))
        affectation[s["id"]].append(c)

    # 3. tournées camion depuis chaque satellite
    tournees = []
    for s in ordre:
        tournees += tournees_plus_proche_voisin(s, affectation[s["id"]], QV)

    return {
        "schema_version": 1,
        "instance": inst["name"],
        "main_route": [depot["id"]] + [s["id"] for s in ordre] + [depot["id"]],
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

    solution = glouton_tous_satellites(instance)
