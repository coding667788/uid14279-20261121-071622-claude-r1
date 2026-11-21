"""Constraint-trap tests for the single-scenario solver and checker.

Each test maps directly to a situation named in the specification: locally
reachable but chaining-impossible transitions, a frozen visit contended by
two windows, two same-team inspectors that cannot co-witness, equal-cost
canonical tie-breaking, and idle keeping the previous position.
"""

from __future__ import annotations

import json
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


class TrapTest(unittest.TestCase):
    def test_chain_trap_is_infeasible_with_minimal_set(self):
        # Every edge exists individually, but the exact-step walk cannot place
        # two cross-team witnesses inside the early window.
        case = _load("chain_trap_case.json")
        out = build_output(case, {})
        self.assertEqual(out["status"], "infeasible")
        self.assertEqual(out["minimum_unsatisfiable_windows"], ["w1"])
        # The witness after removing w1 must be valid on the reduced case that
        # no longer contains w1 (frozen visits and personnel stay fixed).
        import copy
        import json as _json
        raw_path = os.path.join(FIX, "chain_trap_case.json")
        with open(raw_path, encoding="utf-8") as fh:
            reduced_raw = _json.load(fh)
        reduced_raw["windows"] = [w for w in reduced_raw["windows"] if w["id"] != "w1"]
        from solution.model import load_case
        reduced_case = load_case(reduced_raw)
        witness = out["feasible_witnesses"]["w1"]
        plan_doc = {
            "status": "feasible",
            "mode": "single",
            "plan": {
                "scenario_id": "s0",
                "evidence": witness["evidence"],
                "tracks": witness["tracks"],
            },
        }
        check_plan(reduced_case, plan_doc)

    def test_widened_chain_window_becomes_feasible(self):
        # Proves the infeasibility is the exact-step chain, not some static
        # structural impossibility: widening the window restores feasibility.
        import json as _json
        path = os.path.join(FIX, "chain_trap_case.json")
        with open(path, encoding="utf-8") as fh:
            raw = _json.load(fh)
        raw["case_id"] = "chain_ok"
        raw["windows"][0]["end_slot"] = 4
        from solution.model import load_case
        out = build_output(load_case(raw), raw)
        self.assertEqual(out["status"], "feasible")

    def test_frozen_visit_contention(self):
        # One frozen attendance is hinted to w1 but cannot also serve w2.
        out = build_output(_load("frozen_contention_case.json"), {})
        self.assertEqual(out["status"], "infeasible")
        self.assertEqual(out["minimum_unsatisfiable_windows"], ["w1"])

    def test_same_team_cannot_co_witness(self):
        out = build_output(_load("same_team_trap_case.json"), {})
        self.assertEqual(out["status"], "infeasible")
        self.assertEqual(out["minimum_unsatisfiable_windows"], ["w1"])

    def test_equal_cost_tie_breaks_canonically_and_is_deterministic(self):
        case = _load("equal_cost_tie_case.json")
        out1 = build_output(case, {})
        out2 = build_output(case, {})
        self.assertEqual(out1, out2)  # same logical input -> same result
        self.assertEqual(out1["status"], "feasible")
        # Canonical evidence ordering: lowest inspector/slot pair wins.
        ev = out1["plan"]["evidence"]
        self.assertEqual(ev[0]["inspector"], "a1")

    def test_idle_keeps_position_at_zero_cost(self):
        case = _load("idle_position_case.json")
        out = build_output(case, {})
        self.assertEqual(out["status"], "feasible")
        check_plan(case, out)
        tracks = {t["inspector"]: t["positions"] for t in out["plan"]["tracks"]}
        # Any repeated node in a track must be a zero-cost idle self-loop; the
        # checker already validates transitions, here we assert idle runs exist.
        idle_seen = any(len(set(pos)) < len(pos) for pos in tracks.values())
        self.assertTrue(idle_seen)

    def test_checker_rejects_mutated_evidence(self):
        case = _load("equal_cost_tie_case.json")
        out = build_output(case, {})
        # Tamper with a team assignment: force two same-team witnesses.
        for ev in out["plan"]["evidence"]:
            ev["inspector"] = "a1"
        with self.assertRaises(PlanError):
            check_plan(case, out)

    def test_large_case_scale_and_independent_check(self):
        # Required scale: at least 10 inspectors, 12 slots, 12 windows.
        case = _load("large_case.json")
        self.assertGreaterEqual(len(case.inspector_ids), 10)
        self.assertGreaterEqual(case.slot_count, 12)
        self.assertGreaterEqual(len(case.window_ids), 12)
        out = build_output(case, {})
        self.assertEqual(out["status"], "feasible")
        verdict = check_plan(case, out)
        self.assertEqual(verdict["status"], "valid")
        self.assertEqual(verdict["recomputed"]["new_visits"], out["objective"]["new_visits"])
        self.assertEqual(verdict["recomputed"]["movement_cost"], out["objective"]["movement_cost"])


if __name__ == "__main__":
    unittest.main()
