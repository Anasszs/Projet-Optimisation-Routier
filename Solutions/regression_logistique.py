"""STTRPSD : glouton guidé par régression logistique (+ recherche locale).

Idée
----
Le glouton classique affecte chaque client à son satellite le plus proche et
visite tous les satellites. On remplace cette règle fixe par une règle APPRISE :

    P(client c servi depuis le satellite s) = sigma(w . x(c, s) + b)

où x(c, s) est un petit vecteur de caractéristiques (distances normalisées,
rang du satellite pour ce client, demande, attractivité du satellite, ...).

  * Apprentissage : sur des instances d'entraînement (différentes des instances
    de test), on résout chaque instance avec notre meilleure méthode
    (glouton + relocalisation + 2-opt) : c'est le "professeur". Chaque couple
    (client, satellite candidat) devient un exemple, étiqueté 1 si le client est
    servi depuis ce satellite dans la solution du professeur, 0 sinon.
    Les poids sont appris par descente de gradient (log-vraisemblance + L2).
  * Utilisation : glouton RL = chaque client va au satellite de plus forte
    probabilité ; seuls les satellites qui reçoivent des clients sont visités
    (ordre plus proche voisin) ; tournées camion au plus proche voisin
    (même règle que notre glouton). On peut ensuite appliquer la même
    recherche locale que d'habitude.

Utilisation
-----------
    # 1) apprentissage (une seule fois, hors du budget de 30 s)
    python regression_logistique.py train --instances instances/train --modele modele_rl.json

    # 2) résolution (même interface que glouton_2opt_reloc.py)
    python regression_logistique.py solve --instance examples/toy.json \
        --solution output/toy_rl.json --modele modele_rl.json --mode rl_reloc

Uniquement la bibliothèque standard de Python.
"""

import argparse
import glob
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glouton_2opt_reloc import (preparer, d, cout_total, verifier, glouton,   # noqa: E402
                                recherche_locale, ecrire_solution)

NOMS_CARAC = [
    "dist_cs",          # d(c, s) / L
    "regret",           # (d(c, s) - d(c, satellite le plus proche)) / L
    "rang",             # rang de s parmi les satellites pour c, ramené dans [0, 1]
    "plus_proche",      # 1 si s est le satellite le plus proche de c
    "dist_s_depot",     # d(s, dépôt) / L
    "dist_c_depot",     # d(c, dépôt) / L
    "demande",          # q_c / QV
    "attractivite",     # part de la demande totale dont s est le plus proche satellite
    "ratio_depot",      # d(c, s) / (d(c, dépôt) + d(c, s))
]


# --------------------------------------------------------------------------
# Caractéristiques
# --------------------------------------------------------------------------

def caracteristiques(inst, coord, demande):
    """Renvoie {(c, s): [x1, ..., x9]} pour tous les couples client-satellite."""
    depot = inst["depot"]["id"]
    sats = [s["id"] for s in inst["satellites"]]
    clients = [c["id"] for c in inst["customers"]]
    QV = inst["truck_capacity"]
    p = len(sats)

    # échelle de l'instance : distance moyenne dépôt-client (rend les poids
    # transposables d'une instance à l'autre)
    L = sum(d(coord, depot, c) for c in clients) / len(clients) or 1.0

    plus_proche = {c: min(sats, key=lambda s: d(coord, s, c)) for c in clients}
    total = sum(demande.values())
    attract = {s: 0.0 for s in sats}
    for c in clients:
        attract[plus_proche[c]] += demande[c] / total

    X = {}
    for c in clients:
        tri = sorted(sats, key=lambda s: d(coord, s, c))
        dmin = d(coord, tri[0], c)
        dcd = d(coord, c, depot)
        for r, s in enumerate(tri):
            dcs = d(coord, c, s)
            X[(c, s)] = [
                dcs / L,
                (dcs - dmin) / L,
                r / (p - 1) if p > 1 else 0.0,
                1.0 if r == 0 else 0.0,
                d(coord, s, depot) / L,
                dcd / L,
                demande[c] / QV,
                attract[s],
                dcs / (dcd + dcs) if dcd + dcs > 0 else 0.5,
            ]
    return X


# --------------------------------------------------------------------------
# Régression logistique (descente de gradient, sans numpy)
# --------------------------------------------------------------------------

def sigmoide(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


class RegressionLogistique:
    def __init__(self, poids=None, biais=0.0, moyennes=None, ecarts=None):
        self.poids, self.biais = poids, biais
        self.moyennes, self.ecarts = moyennes, ecarts

    def _standardiser(self, x):
        return [(v - m) / e for v, m, e in zip(x, self.moyennes, self.ecarts)]

    def entrainer(self, X, y, l2=1e-3, pas=0.5, iterations=1500, poids_classe=True, verbeux=True):
        """Descente de gradient sur la log-vraisemblance pénalisée (L2).

        poids_classe : les positifs sont rares (1 satellite sur p), on les
        repondère pour que les deux classes pèsent autant dans la perte.
        """
        n, k = len(X), len(X[0])
        self.moyennes = [sum(x[j] for x in X) / n for j in range(k)]
        self.ecarts = [math.sqrt(sum((x[j] - self.moyennes[j]) ** 2 for x in X) / n) or 1.0
                       for j in range(k)]
        Z = [self._standardiser(x) for x in X]
        n_pos = sum(y)
        w_pos = (n / (2 * n_pos)) if poids_classe and n_pos else 1.0
        w_neg = (n / (2 * (n - n_pos))) if poids_classe and n > n_pos else 1.0
        poids_ex = [w_pos if yi else w_neg for yi in y]
        somme_poids = sum(poids_ex)

        self.poids, self.biais = [0.0] * k, 0.0
        for it in range(iterations):
            gw, gb, perte = [0.0] * k, 0.0, 0.0
            for z, yi, pi in zip(Z, y, poids_ex):
                s = self.biais + sum(wj * zj for wj, zj in zip(self.poids, z))
                prob = sigmoide(s)
                err = (prob - yi) * pi
                gb += err
                for j in range(k):
                    gw[j] += err * z[j]
                prob = min(max(prob, 1e-12), 1 - 1e-12)
                perte -= pi * (yi * math.log(prob) + (1 - yi) * math.log(1 - prob))
            for j in range(k):
                self.poids[j] -= pas * (gw[j] / somme_poids + l2 * self.poids[j])
            self.biais -= pas * gb / somme_poids
            if verbeux and (it % 300 == 0 or it == iterations - 1):
                print(f"  itération {it:4d}  perte moyenne {perte / somme_poids:.4f}")
        return self

    def proba(self, x):
        z = self._standardiser(x)
        return sigmoide(self.biais + sum(w * v for w, v in zip(self.poids, z)))

    def sauver(self, chemin):
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump({"caracteristiques": NOMS_CARAC, "poids": self.poids, "biais": self.biais,
                       "moyennes": self.moyennes, "ecarts": self.ecarts}, f, indent=2)

    @classmethod
    def charger(cls, chemin):
        with open(chemin, encoding="utf-8") as f:
            m = json.load(f)
        return cls(m["poids"], m["biais"], m["moyennes"], m["ecarts"])


# --------------------------------------------------------------------------
# Construction du jeu d'apprentissage
# --------------------------------------------------------------------------

def solution_professeur(inst, coord, demande, budget=25.0, departs=0, rng=None):
    """Solution de référence servant d'étiquettes.

    departs = 0 : notre méthode actuelle (glouton + relocalisation + 2-opt).
    departs > 0 : multi-départs. On part aussi de `departs` affectations
    aléatoires (chaque client tiré vers un satellite avec une probabilité qui
    décroît avec la distance), on applique la même recherche locale et on
    garde la meilleure solution. Les étiquettes s'éloignent ainsi de la règle
    "satellite le plus proche" quand c'est rentable.
    """
    fin = time.time() + budget
    meilleure = recherche_locale(glouton(inst, coord, demande), inst, coord, demande,
                                 fin, relocaliser=True)
    meilleur_cout = cout_total(meilleure, coord)
    rng = rng or random.Random(0)
    for _ in range(departs):
        if time.time() > fin:
            break
        sol = glouton_aleatoire(inst, coord, demande, rng)
        sol = recherche_locale(sol, inst, coord, demande, fin, relocaliser=True)
        c = cout_total(sol, coord)
        if c < meilleur_cout - 1e-9:
            meilleure, meilleur_cout = sol, c
    return meilleure


def glouton_aleatoire(inst, coord, demande, rng, temperature=None):
    """Comme le glouton, mais affectation client -> satellite tirée au hasard
    (softmax sur -distance) et sous-ensemble aléatoire de satellites autorisés."""
    sats = [s["id"] for s in inst["satellites"]]
    k = rng.randint(1, len(sats))
    autorises = rng.sample(sats, k)
    affect = {}
    for c in demande:
        ds = [d(coord, s, c) for s in autorises]
        T = temperature or (0.15 * (sum(ds) / len(ds)) + 1e-9)
        m = min(ds)
        poids = [math.exp(-(x - m) / T) for x in ds]
        affect[c] = rng.choices(autorises, weights=poids)[0]
    return construire(inst, coord, demande, affect)


def construire(inst, coord, demande, affect):
    """Solution à partir d'une affectation client -> satellite : satellites
    utilisés en plus proche voisin, tournées camion au plus proche voisin."""
    depot = inst["depot"]["id"]
    QV = inst["truck_capacity"]
    groupes = {}
    for c in sorted(affect):
        groupes.setdefault(affect[c], []).append(c)
    ordre, restants, pos = [], sorted(groupes), depot
    while restants:
        s = min(restants, key=lambda s: d(coord, pos, s))
        ordre.append(s)
        restants.remove(s)
        pos = s
    tournees = []
    for s in ordre:
        non_servis = list(groupes[s])
        while non_servis:
            tournee, charge, pos = [], 0, s
            while True:
                cand = [c for c in non_servis if charge + demande[c] <= QV]
                if not cand:
                    break
                c = min(cand, key=lambda c: d(coord, pos, c))
                tournee.append(c)
                charge += demande[c]
                pos = c
                non_servis.remove(c)
            tournees.append({"satellite": s, "customers": tournee})
    return {"schema_version": 1, "instance": inst["name"],
            "main_route": [depot] + ordre + [depot], "truck_routes": tournees}


def exemples_instance(inst, sol):
    coord, demande = preparer(inst)
    X = caracteristiques(inst, coord, demande)
    sat_de = {c: r["satellite"] for r in sol["truck_routes"] for c in r["customers"]}
    lignes, etiquettes = [], []
    for (c, s), x in X.items():
        lignes.append(x)
        etiquettes.append(1 if sat_de[c] == s else 0)
    return lignes, etiquettes


# --------------------------------------------------------------------------
# Glouton guidé par la régression logistique
# --------------------------------------------------------------------------

def glouton_rl(inst, coord, demande, modele):
    depot = inst["depot"]["id"]
    sats = [s["id"] for s in inst["satellites"]]
    QV = inst["truck_capacity"]
    X = caracteristiques(inst, coord, demande)

    # 1. affectation : satellite de plus forte probabilité apprise
    affectation = {s: [] for s in sats}
    for c in inst["customers"]:
        cid = c["id"]
        s = max(sats, key=lambda s: modele.proba(X[(cid, s)]))
        affectation[s].append(cid)

    # 2. tournée principale : seulement les satellites utilisés, plus proche voisin
    utilises = [s for s in sats if affectation[s]]
    ordre, restants, pos = [], list(utilises), depot
    while restants:
        s = min(restants, key=lambda s: d(coord, pos, s))
        ordre.append(s)
        restants.remove(s)
        pos = s

    # 3. tournées camion au plus proche voisin (même règle que notre glouton)
    tournees = []
    for s in ordre:
        non_servis = list(affectation[s])
        while non_servis:
            tournee, charge, pos = [], 0, s
            while True:
                cand = [c for c in non_servis if charge + demande[c] <= QV]
                if not cand:
                    break
                c = min(cand, key=lambda c: d(coord, pos, c))
                tournee.append(c)
                charge += demande[c]
                pos = c
                non_servis.remove(c)
            tournees.append({"satellite": s, "customers": tournee})

    return {"schema_version": 1, "instance": inst["name"],
            "main_route": [depot] + ordre + [depot], "truck_routes": tournees}


# --------------------------------------------------------------------------
# Commandes
# --------------------------------------------------------------------------

def cmd_train(args):
    fichiers = sorted(glob.glob(os.path.join(args.instances, "*.json")))
    X, y = [], []
    for f in fichiers:
        with open(f, encoding="utf-8-sig") as fh:
            inst = json.load(fh)
        coord, demande = preparer(inst)
        t0 = time.time()
        sol = solution_professeur(inst, coord, demande, args.budget_professeur,
                                  departs=args.departs, rng=random.Random(len(X)))
        assert not verifier(inst, sol, demande)
        lx, ly = exemples_instance(inst, sol)
        X += lx
        y += ly
        print(f"{inst['name']:<28} coût professeur {cout_total(sol, coord):10.3f}  "
              f"({len(lx)} exemples, {time.time() - t0:.1f} s)")
    print(f"\n{len(X)} exemples, {sum(y)} positifs. Apprentissage...")
    modele = RegressionLogistique().entrainer(X, y, l2=args.l2, iterations=args.iterations)
    modele.sauver(args.modele)
    print(f"\nModèle écrit dans {args.modele}")
    print("Poids (variables standardisées) :")
    for nom, w in sorted(zip(NOMS_CARAC, modele.poids), key=lambda t: -abs(t[1])):
        print(f"  {nom:<14} {w:+.3f}")
    print(f"  {'biais':<14} {modele.biais:+.3f}")


def cmd_solve(args):
    debut = time.time()
    with open(args.instance, encoding="utf-8-sig") as f:
        inst = json.load(f)
    coord, demande = preparer(inst)
    modele = RegressionLogistique.charger(args.modele)

    sol = glouton_rl(inst, coord, demande, modele)
    cout_init = cout_total(sol, coord)
    if args.mode in ("rl_2opt", "rl_reloc"):
        marge = min(1.0, 0.1 * args.time_limit)
        sol = recherche_locale(sol, inst, coord, demande, debut + args.time_limit - marge,
                               relocaliser=(args.mode == "rl_reloc"))
    erreurs = verifier(inst, sol, demande)
    ecrire_solution(sol, args.solution)
    print(f"instance : {inst['name']}")
    print(f"coût glouton RL : {cout_init:.6f}")
    if args.mode != "rl":
        print(f"coût après {args.mode} : {cout_total(sol, coord):.6f}")
    print(f"faisable : {'oui' if not erreurs else 'NON'}")
    for e in erreurs:
        print("  erreur :", e)
    print(f"temps : {time.time() - debut:.3f} s")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("train", help="apprend les poids sur des instances d'entraînement")
    t.add_argument("--instances", required=True, help="dossier d'instances JSON")
    t.add_argument("--modele", default="modele_rl.json")
    t.add_argument("--l2", type=float, default=1e-3)
    t.add_argument("--iterations", type=int, default=1500)
    t.add_argument("--budget-professeur", type=float, default=25.0)
    t.add_argument("--departs", type=int, default=0,
                   help="0 = professeur glouton+reloc ; >0 = multi-départs (meilleures étiquettes)")
    t.set_defaults(func=cmd_train)

    s = sub.add_parser("solve", help="résout une instance (interface du projet)")
    s.add_argument("--instance", required=True)
    s.add_argument("--solution", required=True)
    s.add_argument("--modele", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "modele_rl.json"))
    s.add_argument("--seed", type=int, default=0)          # inutilisé (déterministe)
    s.add_argument("--time-limit", type=float, default=30)
    s.add_argument("--mode", choices=["rl", "rl_2opt", "rl_reloc"], default="rl_reloc")
    s.set_defaults(func=cmd_solve)

    args = ap.parse_args()
    random.seed(getattr(args, "seed", 0))
    args.func(args)


if __name__ == "__main__":
    main()
