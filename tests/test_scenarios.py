"""Blind / reveal scenario tests.

Covers the five situations named in the specification: branches individually
schedulable but without a viable common prefix, a farther main route enabling
a reserve transition, the impossibility of re-attributing an already
committed visit after reveal, simultaneous reveals of different branches, and
the implicit no-absence scenario plus a frozen/absence input conflict.
"""

from __future__ import annotations

import os
import unittest

from solution.checker import check_plan
from solution.errors import PlanError
from solution.model import load_case_file
from solution.orchestrate import build_output

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "..", "examples")


def _load(name: str):
    return load_case_file(os.path.join(FIX, name))


class ScenarioTest(unittest.TestCase):
    def test_scenario_base_feasible_and_prefix_consistent(self):
        case = _load("scenario_base.json")
        out = build_output(case, {})
        self.assertEqual(out["status"], "feasible")
        verdict = check_plan(case, out)
        self.assertEqual(verdict["mode"], "scenario")
        # A no-absence main plan and every contingency must be present.
        scenario_ids = {c["scenario_id"] for c in out["contingencies"]}
        self.assertEqual(scenario_ids, {s.id for s in case.scenarios})
        self.assertEqual(out["main_plan"]["scenario_id"], "s0")

    def test_same_reveal_divergent_branches_and_no_absence(self):
        case = _load("scenario_same_reveal.json")
        out = build_output(case, {})
        self.assertEqual(out["status"], "feasible")
        check_plan(case, out)
        reveals = {c["reveal_slot"] for c in out["contingencies"]}
        self.assertEqual(reveals, {3})  # all branches reveal at the same slot
        # No-absence leaf always exists and carries the full horizon.
        self.assertEqual(out["main_plan"]["scenario_id"], "s0")

    def test_frozen_absence_is_reported_as_input_conflict(self):
        case = _load("scenario_frozen_conflict.json")
        out = build_output(case, {})
        self.assertEqual(out["status"], "input_conflict")
        self.assertTrue(out["errors"])
        self.assertEqual(out["errors"][0]["code"], "E_FROZEN_ABSENT_CONFLICT")

    def test_long_route_reserve_transition(self):
        case = _load("scenario_long_route.json")
        out = build_output(case, {})
        self.assertEqual(out["status"], "feasible")
        check_plan(case, out)
        # Each scenario must remain feasible after its reveal; the checker
        # validates the exact-step reserve transitions on every branch.
        self.assertEqual(len(out["contingencies"]), len(case.scenarios))

    def test_no_common_prefix_branch_structure(self):
        # Each individual branch is schedulable, while the common survivor set
        # contains no cross-team pair; the solver still produces a canonical
        # result (the reveal is at slot 1, so each branch decides independently).
        import copy
        import json
        path = os.path.join(FIX, "scenario_no_common_prefix.json")
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        from solution.model import load_case
        from solution.solver import TreeSolver
        for sid in ("eA", "eB"):
            sub = copy.deepcopy(raw)
            sub["scenarios"] = [s for s in sub["scenarios"] if s["id"] == sid]
            self.assertIsNotNone(TreeSolver(load_case(sub)).solve())
        # Common survivor intersection has no team-A inspector.
        allp = {i["id"] for i in raw["inspectors"]}
        a_ids = {i["id"] for i in raw["inspectors"] if i["team"] == "A"}
        common = set(allp)
        for s in raw["scenarios"]:
            common -= set(s["absent"])
        self.assertFalse(common & a_ids)
        out = build_output(load_case(copy.deepcopy(raw)), raw)
        check_plan(load_case(copy.deepcopy(raw)), out)

    def test_pre_reveal_visit_cannot_be_reattributed(self):
        # Build a plan, then reassign a pre-reveal evidence window in one
        # contingency; the independent checker must reject it.
        case = _load("scenario_base.json")
        out = build_output(case, {})
        first = out["contingencies"][0]
        prefix = first["trigger_prefix"]["evidence"]
        self.assertTrue(prefix)
        tampered = {
            "inspector": prefix[0]["inspector"],
            "slot": prefix[0]["slot"],
            "checkpoint": prefix[0]["checkpoint"],
            "window": "w2",  # reattribution to a different window
        }
        first["trigger_prefix"]["evidence"] = [tampered] + prefix[1:]
        with self.assertRaises(PlanError):
            check_plan(case, out)

    def test_objective_is_max_new_then_sum_cost(self):
        case = _load("scenario_base.json")
        out = build_output(case, {})
        check_plan(case, out)
        per_new = [c["new_visits"] for c in out["contingencies"]]
        per_new.append(out["main_plan"]["new_visits"])
        self.assertEqual(out["objective"]["max_new_visits"], max(per_new))
        per_cost = [c["movement_cost"] for c in out["contingencies"]]
        per_cost.append(out["main_plan"]["movement_cost"])
        self.assertEqual(out["objective"]["sum_movement_cost"], sum(per_cost))


if __name__ == "__main__":
    unittest.main()
