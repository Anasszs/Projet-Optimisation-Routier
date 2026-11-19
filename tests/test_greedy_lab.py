"""Offline greedy-lab contract and independent Python/JavaScript parity checks.

Only the pure engine script is executed, in Node's VM; no browser or package
dependencies are needed. All JavaScript cases share one Node subprocess.
"""

from __future__ import annotations

import copy
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import shutil
import subprocess
import unittest

from sttrpsd.model import FormatError, parse_instance
from sttrpsd.scoring import score_solution


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "interactive" / "greedy_lab.html"
POLICIES = ("nearest", "cheapest", "per_demand", "largest_demand", "farthest", "savings")
RULES = ("single_best", "nearest_all")


class BundleParser(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self.scripts = {}
        self.resources = []
        self._script = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self._script = attrs.get("id", "script-" + str(len(self.scripts)))
            self.scripts[self._script] = {"attrs": attrs, "text": ""}
        resource_attributes = {"script": "src", "img": "src", "iframe": "src",
                               "link": "href", "source": "src", "video": "src",
                               "audio": "src", "object": "data", "embed": "src"}
        if tag in resource_attributes and resource_attributes[tag] in attrs:
            self.resources.append((tag, attrs[resource_attributes[tag]]))

    def handle_endtag(self, tag):
        if tag == "script":
            self._script = None

    def handle_data(self, data):
        if self._script is not None:
            self.scripts[self._script]["text"] += data


def fixtures():
    toy = json.loads((ROOT / "examples" / "toy.json").read_text(encoding="utf-8"))
    solution = json.loads((ROOT / "examples" / "toy_solution.json").read_text(encoding="utf-8"))
    public = [json.loads(path.read_text(encoding="utf-8"))
              for path in sorted((ROOT / "instances" / "public").glob("*.json"))]
    score_cases = [{"name": "worked example", "solution": solution}]

    def solution_case(name, change):
        data = copy.deepcopy(solution)
        change(data)
        score_cases.append({"name": name, "solution": data})

    solution_case("partial", lambda s: s["truck_routes"].pop())
    solution_case("duplicate customer", lambda s: s["truck_routes"][2].update(customers=[5]))
    solution_case("over capacity", lambda s: s["truck_routes"][1].update(customers=[5, 6]))
    solution_case("unvisited root", lambda s: s.update(main_route=[0, 1, 0]))
    solution_case("repeated satellite", lambda s: s.update(main_route=[0, 1, 2, 1, 0]))
    solution_case("customer on main", lambda s: s.update(main_route=[0, 3, 2, 0]))
    solution_case("open main route", lambda s: s.update(main_route=[0, 1, 2]))
    solution_case("empty main route", lambda s: s.update(main_route=[0, 0]))
    solution_case("unknown field", lambda s: s.update(objective=0))
    solution_case("missing field", lambda s: s.pop("schema_version"))
    solution_case("wrong instance", lambda s: s.update(instance="another instance"))
    solution_case("wrong version", lambda s: s.update(schema_version=True))
    solution_case("boolean node", lambda s: s["main_route"].__setitem__(1, True))
    solution_case("malformed ID object", lambda s: s["main_route"].__setitem__(1, {"toString": None, "valueOf": None}))
    solution_case("string customer", lambda s: s["truck_routes"][0].update(customers=["3", 4]))
    solution_case("empty trip", lambda s: s["truck_routes"].append({"satellite": 1, "customers": []}))
    solution_case("null trip", lambda s: s["truck_routes"].append(None))
    solution_case("null trips", lambda s: s.update(truck_routes=None))
    solution_case("unknown customer", lambda s: s["truck_routes"][0].update(customers=[999, 4]))
    solution_case("cross satellite", lambda s: s["truck_routes"][0].update(end_satellite=2))
    solution_case("bad metadata", lambda s: s.update(metadata=[]))
    solution_case("unused main satellite", lambda s: [r.update(satellite=1) for r in s["truck_routes"]])
    for bad in (None, [], "solution", 3):
        score_cases.append({"name": "non-object " + repr(bad), "solution": bad})

    instance_cases = [{"name": "valid", "value": toy, "valid": True}]

    def instance_case(name, change, valid=False):
        data = copy.deepcopy(toy)
        change(data)
        instance_cases.append({"name": name, "value": data, "valid": valid})

    instance_case("unknown instance field", lambda d: d.update(extra=0))
    instance_case("unknown node field", lambda d: d["depot"].update(demand=0))
    instance_case("unknown distance field", lambda d: d["distance"].update(extra=0))
    instance_case("boolean ID", lambda d: d["depot"].update(id=False))
    instance_case("string ID", lambda d: d["depot"].update(id="0"))
    instance_case("fractional ID", lambda d: d["depot"].update(id=0.5))
    instance_case("duplicate ID", lambda d: d["customers"][0].update(id=1))
    instance_case("boolean coordinate", lambda d: d["depot"].update(x=True))
    instance_case("string demand", lambda d: d["customers"][0].update(demand="6"))
    instance_case("zero demand", lambda d: d["customers"][0].update(demand=0))
    instance_case("truck overload", lambda d: d["customers"][0].update(demand=11))
    instance_case("total overload", lambda d: d.update(trailer_capacity=14))
    instance_case("empty customers", lambda d: d.update(customers=[]))
    instance_case("empty satellites", lambda d: d.update(satellites=[]))
    instance_case("negative capacity", lambda d: d.update(trailer_capacity=-1))
    instance_case("metadata array", lambda d: d.update(metadata=[]))
    instance_case("unknown metric", lambda d: d.update(distance={"type": "manhattan"}))
    instance_case("stray matrix", lambda d: d["distance"].update(matrix=[]))
    instance_case("negative ID", lambda d: d["depot"].update(id=-10), valid=True)
    instance_case("safe integer boundary", lambda d: d["depot"].update(id=2 ** 53 - 1), valid=True)
    # Python has arbitrary-size integers, but the browser's documented ID domain
    # is Number.isSafeInteger. This is an intentional domain restriction.
    instance_case("unsafe integer", lambda d: d["depot"].update(id=2 ** 53))

    rounded = copy.deepcopy(toy)
    rounded["distance"] = {"type": "rounded_euclidean"}
    rounded["satellites"][0]["x"] = 2.5
    explicit = copy.deepcopy(toy)
    order = [4, 2, 6, 0, 3, 5, 1]
    matrix = [[0 if i == j else 10 + i + j for j in range(7)] for i in range(7)]
    explicit["distance"] = {"type": "explicit", "node_order": order, "matrix": matrix}
    asymmetric = copy.deepcopy(explicit)
    asymmetric["distance"]["matrix"][0][1] += 1
    instance_cases.append({"name": "asymmetric matrix", "value": asymmetric, "valid": False})
    for name, change in (
        ("matrix diagonal", lambda d: d["distance"]["matrix"][0].__setitem__(0, 1)),
        ("matrix negative", lambda d: d["distance"]["matrix"][0].__setitem__(1, -1)),
        ("matrix missing row", lambda d: d["distance"]["matrix"].pop()),
        ("matrix duplicate order", lambda d: d["distance"]["node_order"].__setitem__(0, 2)),
    ):
        data = copy.deepcopy(explicit)
        change(data)
        instance_cases.append({"name": name, "value": data, "valid": False})

    ties = copy.deepcopy(toy)
    ties["name"] = "deterministic ties"
    ties["truck_capacity"], ties["trailer_capacity"] = 2, 2
    for node in [ties["depot"], *ties["satellites"], *ties["customers"]]:
        node["x"] = node["y"] = 0
        if "demand" in node:
            node["demand"] = 1
    ties["customers"].reverse()  # Numerical IDs, not input array order, break ties.
    ties["satellites"].reverse()

    text = json.dumps(toy, ensure_ascii=True)
    text_cases = [
        {"name": "UTF-8 BOM", "text": "\ufeff" + text, "valid": True},
        {"name": "duplicate key", "text": text.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'), "valid": False},
        {"name": "escaped duplicate key", "text": '{"x":1,"\\u0078":2}', "json_only": True, "valid": False},
        {"name": "nested duplicate", "text": '{"a":{"x":1,"x":2}}', "json_only": True, "valid": False},
        {"name": "NaN", "text": '{"x":NaN}', "json_only": True, "valid": False},
        {"name": "Infinity", "text": '{"x":Infinity}', "json_only": True, "valid": False},
        {"name": "overflow", "text": '{"x":1e999}', "json_only": True, "valid": False},
        {"name": "fractional lexical ID", "text": text.replace('"id": 0', '"id": 0.0', 1), "valid": False},
        {"name": "exponent lexical version", "text": text.replace('"schema_version": 1', '"schema_version": 1e0', 1), "valid": False},
        {"name": "valid decimal coordinate", "text": text.replace('"x": 0', '"x": 0.0', 1), "valid": True},
        {"name": "trailing content", "text": text + "false", "valid": False},
    ]
    dat = "4 3\n10 15\n0 0\n2 0\n8 0\n2 3 6\n4 3 4\n8 4 8\n10 4 7\n"
    return {"toy": toy, "solution": solution, "public": public, "score_cases": score_cases,
            "instance_cases": instance_cases, "text_cases": text_cases,
            "metrics": [toy, rounded, explicit], "ties": ties, "dat": dat}


NODE_BATCH = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const context = vm.createContext({payloadText: JSON.stringify(input.payload)});
vm.runInContext(input.source, context, {timeout: 10000});
const result = vm.runInContext(`
(() => {
  'use strict';
  const E = globalThis.STTRPSD, P = JSON.parse(payloadText);
  const clone = x => JSON.parse(JSON.stringify(x));
  const attempt = fn => {try {return {ok:true,value:fn()};} catch(e) {return {ok:false,error:String(e.message || e)};}};
  const deepFrozen = x => x === null || typeof x !== 'object' ||
    (Object.isFrozen(x) && Object.keys(x).every(k => deepFrozen(x[k])));
  const out = {policies:E.POLICIES.map(p=>p.id),constructs:[],metrics:[],candidates:[]};
  out.instances = P.instance_cases.map(c=>({name:c.name,...attempt(()=>E.parseInstance(c.value))}));
  out.texts = P.text_cases.map(c=>({name:c.name,...attempt(()=>c.json_only?E.parseJSON(c.text):E.parseInstance(c.text))}));
  const I = E.parseInstance(P.toy);
  out.scores = P.score_cases.map(c=>({name:c.name,...attempt(()=>E.scoreSolution(I,c.solution))}));
  out.empty = {solution:E.emptySolution(I),analysis:E.analyze(I,E.emptySolution(I)),score:E.scoreSolution(I,E.emptySolution(I))};
  for (const raw of P.public) {
    const parsed = E.parseInstance(raw), before = JSON.stringify(parsed), original = JSON.stringify(raw);
    for (const policy of out.policies) for (const satelliteRule of ['single_best','nearest_all']) {
      out.constructs.push({name:raw.name,policy,satelliteRule,...attempt(()=>E.construct(parsed,{policy,satelliteRule}))});
    }
    if (before !== JSON.stringify(parsed) || original !== JSON.stringify(raw)) throw Error('Constructor mutated instance '+raw.name);
  }
  for (const raw of P.metrics) {
    const parsed=E.parseInstance(raw),ids=[raw.depot.id,...raw.satellites.map(x=>x.id),...raw.customers.map(x=>x.id)];
    out.metrics.push({type:raw.distance.type,distances:ids.map(a=>ids.map(b=>E.distance(parsed,a,b))),
      score:E.scoreSolution(parsed,P.solution),constructs:out.policies.map(policy=>E.construct(parsed,{policy,satelliteRule:'nearest_all'}))});
  }
  const draft = {schema_version:1,instance:I.name,main_route:[0,1,0],truck_routes:[{satellite:1,customers:[3]}]};
  for (const policy of out.policies) out.candidates.push({policy,rows:E.candidates(I,draft,0,policy)});
  out.draftAnalysis = E.analyze(I,draft);
  out.invalidTripCandidates = [-1,1,100].map(index=>E.candidates(I,draft,index,'nearest'));
  out.emptyTripCandidates = E.candidates(I,{...draft,truck_routes:[{satellite:1,customers:[]}]},0,'nearest');
  out.mainInsertion = E.bestMainInsertion(I,draft,2);
  out.withSatellite = E.insertSatellite(I,draft,2);
  out.draftAfter = draft;
  const T=E.parseInstance(P.ties);
  out.ties=out.policies.map(policy=>({policy,first:E.construct(T,{policy,satelliteRule:'nearest_all'}),
    repeat:E.construct(T,{policy,satelliteRule:'nearest_all'}),single:E.construct(T,{policy,satelliteRule:'single_best'})}));
  const original = clone(P.toy); original.metadata.nested={items:[{value:7}]};
  const parsed = E.parseInstance(original), before=JSON.stringify(parsed);
  original.metadata.nested.items[0].value=9;
  out.immutable = {deep:deepFrozen(parsed),detached:parsed.metadata.nested.items[0].value===7,
    mutationRejected:!attempt(()=>{parsed.customers[0].demand=999;}).ok,
    unchanged:before===JSON.stringify(parsed)};
  const attack=clone(P.toy);
  attack.name='</script><img src=x onerror="globalThis.polluted=1">';
  attack.metadata=E.parseJSON('{"__proto__":{"polluted":true},"constructor":{"prototype":{"polluted":true}}}');
  out.prototype = attempt(()=>{
    const imported=E.parseInstance(JSON.stringify(attack));
    return {name:imported.name,own:Object.prototype.hasOwnProperty.call(imported.metadata,'__proto__'),
      clean:({}).polluted===undefined && globalThis.polluted===undefined,solution:E.construct(imported).solution};
  });
  const specials = [NaN,Infinity,-Infinity,true,'1'];
  out.nonfinite=specials.map(value=>{const bad=clone(P.toy);bad.depot.x=value;return attempt(()=>E.parseInstance(bad));});
  out.badMetadata=[NaN,Infinity,undefined,()=>0].map(value=>{const bad=clone(P.toy);bad.metadata={value};return attempt(()=>E.parseInstance(bad));});
  out.dat=attempt(()=>E.parseDat('\\ufeff'+P.dat,'toy.dat'));
  out.badDat=[P.dat+'0 0\\n',P.dat.replace('4 3','4 1'),P.dat.replace('2 3 6','2 3 11'),P.dat.replace('4 3 4','4 3 NaN'),P.dat.replace('2 0\\n','\\n')]
    .map(text=>attempt(()=>E.parseDat(text,'toy.dat')));
  return JSON.stringify(out);
})()
`, context, {timeout: 90000});
process.stdout.write(result);
"""


def run_engine_batch(source, payload):
    process = subprocess.run(
        [shutil.which("node"), "-e", NODE_BATCH],
        input=json.dumps({"source": source, "payload": payload}, ensure_ascii=True).encode("ascii"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=105, check=False,
    )
    if process.returncode:
        raise AssertionError("Node engine batch failed:\n" + process.stderr.decode("utf-8", errors="replace"))
    return json.loads(process.stdout.decode("utf-8"))


class GreedyLabEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("Node.js is not installed; pure JavaScript engine checks skipped")
        cls.payload = fixtures()
        cls.bundle = BundleParser(HTML_PATH.read_text(encoding="utf-8"))
        cls.result = run_engine_batch(cls.bundle.scripts["sttrpsd-engine"]["text"], cls.payload)

    def assert_score_equal(self, python, javascript):
        self.assertEqual(javascript["feasible"], python["feasible"])
        for field in ("cost", "main_cost", "subroute_cost"):
            if python[field] is None:
                self.assertIsNone(javascript[field])
            else:
                self.assertTrue(math.isclose(javascript[field], python[field], rel_tol=1e-11, abs_tol=1e-9), field)
        self.assertEqual(javascript["loads"], python["loads"])
        for field in ("n_customers", "n_satellites_used", "n_subroutes"):
            self.assertEqual(javascript[field], python[field], field)
        self.assertEqual(bool(javascript["errors"]), bool(python["errors"]))

    def test_all_public_constructors_are_independently_feasible(self):
        self.assertEqual(set(self.result["policies"]), set(POLICIES))
        self.assertEqual(len(self.payload["public"]), 10)
        self.assertEqual(len(self.result["constructs"]), 120)
        instances = {data["name"]: parse_instance(data) for data in self.payload["public"]}
        seen = set()
        for row in self.result["constructs"]:
            with self.subTest(instance=row["name"], policy=row["policy"], rule=row["satelliteRule"]):
                self.assertTrue(row["ok"], row)
                seen.add((row["name"], row["policy"], row["satelliteRule"]))
                built = row["value"]
                score = score_solution(instances[row["name"]], built["solution"])
                self.assertTrue(score["feasible"], score)
                self.assertTrue(math.isclose(built["analysis"]["cost"], score["cost"], rel_tol=1e-11))
                self.assertEqual(len(built["trace"]), len(instances[row["name"]].customers))
        self.assertEqual(len(seen), 120)

    def test_worked_example_invalid_and_partial_scoring_parity(self):
        instance = parse_instance(self.payload["toy"])
        for case, result in zip(self.payload["score_cases"], self.result["scores"]):
            with self.subTest(case=case["name"]):
                self.assertTrue(result["ok"], result)
                self.assert_score_equal(score_solution(instance, case["solution"]), result["value"])
        self.assertAlmostEqual(self.result["scores"][0]["value"]["cost"], 41.54982318546315)
        self.assertFalse(self.result["empty"]["score"]["feasible"])
        self.assertIsNone(self.result["empty"]["score"]["cost"])
        self.assertEqual(self.result["empty"]["analysis"]["cost"], 0)

    def test_instance_validation_and_strict_json(self):
        for case, result in zip(self.payload["instance_cases"], self.result["instances"]):
            with self.subTest(case=case["name"]):
                self.assertEqual(result["ok"], case["valid"], result)
                if case["valid"]:
                    self.assertEqual(parse_instance(result["value"]).to_dict(), parse_instance(case["value"]).to_dict())
                elif case["name"] != "unsafe integer":
                    with self.assertRaises((FormatError, TypeError)):
                        parse_instance(case["value"])
        for case, result in zip(self.payload["text_cases"], self.result["texts"]):
            with self.subTest(case=case["name"]):
                self.assertEqual(result["ok"], case["valid"], result)
        for result in self.result["nonfinite"] + self.result["badMetadata"]:
            self.assertFalse(result["ok"], result)

    def test_declared_metrics_match_python(self):
        for raw, result in zip(self.payload["metrics"], self.result["metrics"]):
            with self.subTest(metric=raw["distance"]["type"]):
                instance = parse_instance(raw)
                ids = [raw["depot"]["id"], *[n["id"] for n in raw["satellites"]], *[n["id"] for n in raw["customers"]]]
                for i, a in enumerate(ids):
                    for j, b in enumerate(ids):
                        self.assertAlmostEqual(result["distances"][i][j], instance.distance(a, b))
                self.assert_score_equal(score_solution(instance, self.payload["solution"]), result["score"])
                for built in result["constructs"]:
                    self.assertTrue(score_solution(instance, built["solution"])["feasible"])
        self.assertEqual(self.result["metrics"][1]["distances"][0][1], 3)

    def test_candidates_respect_capacity_and_exact_increment(self):
        instance = parse_instance(self.payload["toy"])
        for group in self.result["candidates"]:
            with self.subTest(policy=group["policy"]):
                rows = group["rows"]
                self.assertEqual({row["id"] for row in rows}, {4, 5, 6})
                self.assertEqual({row["id"] for row in rows if row["eligible"]}, {4})
                self.assertEqual([r["rank"] for r in rows], [1, 2, 3])
                self.assertTrue(rows[0]["eligible"])
                for row in rows:
                    delta = instance.distance(3, row["id"]) + instance.distance(row["id"], 1) - instance.distance(3, 1)
                    self.assertAlmostEqual(row["fromTail"], instance.distance(3, row["id"]))
                    self.assertAlmostEqual(row["fromRoot"], instance.distance(1, row["id"]))
                    self.assertAlmostEqual(row["delta"], delta)
                    self.assertAlmostEqual(row["deltaPerDemand"], delta / instance.customers[row["id"]].demand)
                    self.assertAlmostEqual(row["savings"], 2 * instance.distance(1, row["id"]) - delta)
                    self.assertEqual(row["loadAfter"], 6 + instance.customers[row["id"]].demand)
                    self.assertEqual(row["remaining"], 10 - row["loadAfter"])
                    self.assertEqual(bool(row["reason"]), not row["eligible"])
                def order(row):
                    values = {"nearest": row["fromTail"], "cheapest": row["delta"],
                              "per_demand": row["deltaPerDemand"], "largest_demand": -row["demand"],
                              "farthest": -row["fromRoot"], "savings": -row["savings"]}
                    return (not row["eligible"], values[group["policy"]], row["id"])
                self.assertEqual(rows, sorted(rows, key=order))
        self.assertEqual(self.result["invalidTripCandidates"], [[], [], []])
        for row in self.result["emptyTripCandidates"]:
            self.assertAlmostEqual(row["delta"], 2 * instance.distance(1, row["id"]))
        self.assertEqual(self.result["draftAfter"]["main_route"], [0, 1, 0])
        self.assertEqual(self.result["draftAfter"]["truck_routes"][0]["customers"], [3])
        draft = self.result["draftAnalysis"]
        self.assertEqual((draft["served"], draft["unserved"], draft["servedDemand"]), ([3], [4, 5, 6], 6))
        self.assertEqual((draft["main_cost"], draft["subroute_cost"], draft["cost"]), (4, 6, 10))
        self.assertFalse(draft["complete"])
        insertion = self.result["mainInsertion"]
        self.assertEqual(insertion, {"index": 1, "delta": 12, "after": 0, "before": 1})
        main = self.result["withSatellite"]["main_route"]
        main_cost = math.fsum(instance.distance(a, b) for a, b in zip(main, main[1:]))
        self.assertEqual(main_cost - draft["main_cost"], insertion["delta"])

    def test_constructive_traces_rebuild_the_actual_routes(self):
        instances = {d["name"]: parse_instance(d) for d in self.payload["public"]}
        for row in self.result["constructs"]:
            with self.subTest(instance=row["name"], policy=row["policy"], rule=row["satelliteRule"]):
                self.assertTrue(row["ok"], row)
                instance, built = instances[row["name"]], row["value"]
                routes = {}
                running_cost = built["analysis"]["main_cost"]
                for step in built["trace"]:
                    route = routes.setdefault(step["tripIndex"], {"satellite": step["root"], "customers": []})
                    self.assertEqual(route["satellite"], step["root"])
                    tail = route["customers"][-1] if route["customers"] else route["satellite"]
                    expected = (instance.distance(tail, step["customer"])
                                + instance.distance(step["customer"], step["root"])
                                - instance.distance(tail, step["root"]))
                    self.assertAlmostEqual(step["delta"], expected)
                    running_cost += expected
                    self.assertTrue(math.isclose(step["cost"], running_cost, rel_tol=1e-11, abs_tol=1e-9))
                    route["customers"].append(step["customer"])
                    self.assertAlmostEqual(step["load"], math.fsum(instance.customers[c].demand for c in route["customers"]))
                self.assertEqual([routes[i] for i in sorted(routes)], built["solution"]["truck_routes"])

    def test_equal_scores_break_ties_by_id_and_repeat_exactly(self):
        instance = parse_instance(self.payload["ties"])
        for row in self.result["ties"]:
            with self.subTest(policy=row["policy"]):
                self.assertEqual(row["first"], row["repeat"])
                for key in ("first", "single"):
                    built = row[key]
                    self.assertEqual([step["customer"] for step in built["trace"]], [3, 4, 5, 6])
                    self.assertEqual({trip["satellite"] for trip in built["solution"]["truck_routes"]}, {1})
                    score = score_solution(instance, built["solution"])
                    self.assertTrue(score["feasible"], score)
                    self.assertEqual(score["cost"], 0)

    def test_parsed_instances_are_detached_readonly_and_prototype_safe(self):
        self.assertTrue(all(self.result["immutable"].values()), self.result["immutable"])
        result = self.result["prototype"]
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["value"]["clean"])
        self.assertTrue(result["value"]["own"])
        self.assertEqual(result["value"]["solution"]["instance"], result["value"]["name"])
        self.assertIn("</script>", result["value"]["name"])

    def test_original_dat_parser_preserves_node_capacity_and_metric_semantics(self):
        result = self.result["dat"]
        self.assertTrue(result["ok"], result)
        actual = parse_instance(result["value"]).to_dict()
        expected = parse_instance(self.payload["toy"]).to_dict()
        actual.pop("metadata", None)
        expected.pop("metadata", None)
        self.assertEqual(actual, expected)
        for result in self.result["badDat"]:
            self.assertFalse(result["ok"], result)


class GreedyLabBundleTests(unittest.TestCase):
    def test_html_is_offline_and_contains_the_engine(self):
        text = HTML_PATH.read_text(encoding="utf-8")
        bundle = BundleParser(text)
        self.assertIn("sttrpsd-engine", bundle.scripts)
        for tag, value in bundle.resources:
            self.assertTrue(value.startswith(("data:", "#")), (tag, value))
        for script in bundle.scripts.values():
            self.assertNotIn("src", script["attrs"])
            self.assertNotRegex(script["text"], r"\b(?:fetch|importScripts)\s*\(")
            self.assertNotRegex(script["text"], r"\bnew\s+(?:XMLHttpRequest|WebSocket|EventSource)\b")
        self.assertNotRegex(text, r"@import\s+(?:url|['\"])")
        self.assertNotRegex(text, r"url\(\s*['\"]?https?://")

    def test_embedded_data_is_escaped_and_matches_all_eleven_source_instances(self):
        bundle = BundleParser(HTML_PATH.read_text(encoding="utf-8"))
        self.assertIn("lab-data", bundle.scripts)
        script = bundle.scripts["lab-data"]
        self.assertEqual(script["attrs"].get("type"), "application/json")
        # The document builder escapes characters which could terminate a
        # script element or form HTML, even though today's instance names are
        # benign. Decoding must recover the exact canonical benchmark data.
        self.assertNotRegex(script["text"], r"[<>&]")
        data = json.loads(script["text"])
        self.assertEqual(len(data["instances"]), 11)
        self.assertIs(data["instances"][0]["public"], False)
        self.assertEqual(sum(row["public"] is True for row in data["instances"]), 10)
        expected = fixtures()
        canonical = {d["name"]: parse_instance(d).to_dict()
                     for d in [expected["toy"], *expected["public"]]}
        self.assertEqual(len(canonical), 11)
        actual = {row["data"]["name"]: parse_instance(row["data"]).to_dict()
                  for row in data["instances"]}
        self.assertEqual(actual, canonical)
        score = score_solution(parse_instance(expected["toy"]), data["worked"])
        self.assertTrue(score["feasible"], score)
        self.assertAlmostEqual(score["cost"], 41.54982318546315)


if __name__ == "__main__":
    unittest.main()
