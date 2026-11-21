"""Independent exhaustive cross-check on the 4-inspector / 5-slot case.

The production tree solver and the deliberately independent brute oracle
(see solution/brute.py) must agree on the exact lexicographic optimum for
every small case, including infeasible ones.  This is the required
"independent exhaustive check on a 4-person 5-slot case".
"""

from __future__ import annotations

import copy
import unittest

from solution.brute import brute_solve_single
from solution.model import load_case
from solution.solver import TreeSolver


def _tiny_variants():
    base = {
        "case_id": "v",
        "slot_count": 5,
        "inspectors": [
            {"id": "i1", "team": "A", "trainings": ["t1", "t2"], "initial": "H"},
            {"id": "i2", "team": "B", "trainings": ["t1"], "initial": "H"},
            {"id": "i3", "team": "A", "trainings": ["t1", "t2"], "initial": "H"},
            {"id": "i4", "team": "B", "trainings": ["t1", "t2"], "initial": "X"},
        ],
        "checkpoints": [
            {"id": "P", "required_trainings": ["t1"]},
            {"id": "Q", "required_trainings": ["t1", "t2"]},
        ],
        "edges": [
            {"src": "H", "dst": "P", "cost": 1},
            {"src": "P", "dst": "H", "cost": 1},
            {"src": "P", "dst": "Q", "cost": 2},
            {"src": "Q", "dst": "P", "cost": 2},
            {"src": "X", "dst": "P", "cost": 1},
        ],
        "windows": [
            {"id": "w1", "checkpoint": "P", "start_slot": 1, "end_slot": 4, "min_gap": 1},
            {"id": "w2", "checkpoint": "Q", "start_slot": 3, "end_slot": 5, "min_gap": 1},
        ],
        "frozen_visits": [
            {"inspector": "i2", "slot": 1, "checkpoint": "P", "window": "w1"}
        ],
    }
    variants = [base]
    # Drop each window in turn and toggle the frozen attribution to widen the
    # cross-check coverage without leaving the brute oracle's size guard.
    for keep in ({"w1"}, {"w2"}, {"w1", "w2"}):
        v = copy.deepcopy(base)
        v["windows"] = [w for w in v["windows"] if w["id"] in keep]
        # Frozen attributions may only name windows that still exist; drop the
        # hint (the frozen attendance itself is always retained).
        for fv in v["frozen_visits"]:
            if fv.get("window") not in keep:
                fv["window"] = None
        variants.append(v)
    no_frozen = copy.deepcopy(base)
    no_frozen["frozen_visits"] = []
    variants.append(no_frozen)
    return variants


class BruteCrossCheckTest(unittest.TestCase):
    def test_solver_matches_brute_oracle(self):
        for raw in _tiny_variants():
            with self.subTest(case=raw["case_id"], windows=[w["id"] for w in raw["windows"]],
                              frozen=bool(raw["frozen_visits"])):
                case = load_case(copy.deepcopy(raw))
                result = TreeSolver(case).solve()
                brute = brute_solve_single(case)
                if result is None:
                    self.assertIsNone(brute)
                    continue
                self.assertIsNotNone(brute)
                lid = "s0"
                self.assertEqual(result.new_visits[lid], brute["new_visits"])
                self.assertEqual(result.costs[lid], brute["movement_cost"])
                self.assertEqual(result.evidence[lid], brute["evidence"])

    def test_infeasible_small_case_agrees(self):
        raw = {
            "case_id": "infeas",
            "slot_count": 5,
            "inspectors": [
                {"id": "i1", "team": "A", "trainings": ["t1", "t2"], "initial": "H"},
                {"id": "i2", "team": "B", "trainings": ["t1"], "initial": "H"},
                {"id": "i3", "team": "A", "trainings": ["t1", "t2"], "initial": "H"},
                {"id": "i4", "team": "B", "trainings": ["t1", "t2"], "initial": "X"},
            ],
            "checkpoints": [
                {"id": "P", "required_trainings": ["t1"]},
                {"id": "Q", "required_trainings": ["t1", "t2"]},
            ],
            "edges": [
                {"src": "H", "dst": "P", "cost": 1},
                {"src": "P", "dst": "H", "cost": 1},
                {"src": "P", "dst": "Q", "cost": 2},
                {"src": "Q", "dst": "P", "cost": 2},
                {"src": "X", "dst": "P", "cost": 1},
            ],
            "windows": [
                {"id": "w3", "checkpoint": "Q", "start_slot": 1, "end_slot": 2, "min_gap": 1},
            ],
            "frozen_visits": [],
        }
        case = load_case(raw)
        self.assertIsNone(TreeSolver(case).solve())
        self.assertIsNone(brute_solve_single(case))


if __name__ == "__main__":
    unittest.main()
