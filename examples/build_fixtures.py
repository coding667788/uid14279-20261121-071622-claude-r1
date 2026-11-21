"""Generate all local fictitious fixtures used by examples and tests.

Run from the repository root:  python examples/build_fixtures.py
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = HERE


def write(name: str, doc: dict) -> None:
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"wrote {path}")


# --------------------------------------------------------------------------- #
# Tiny case: 4 inspectors, 5 slots — brute-force oracle cross-check target.
# Sparse on purpose: the independent brute oracle enumerates full track
# combinations, so each node keeps at most two outgoing moves and the
# exhaustive space stays small enough to enumerate completely.
# --------------------------------------------------------------------------- #
def tiny_case() -> dict:
    return {
        "case_id": "tiny4x5",
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


def tiny_infeasible_case() -> dict:
    doc = tiny_case()
    doc["case_id"] = "tiny4x5_infeasible"
    # w3 needs two differently-teamed, t1+t2 qualified inspectors in slots
    # 1-2.  Only i3(A) and i4(B) qualify for Q; i4 starts at X, whose only
    # exit X->P cannot reach Q within two transitions, so w3 is uncoverable.
    doc["windows"].append(
        {"id": "w3", "checkpoint": "Q", "start_slot": 1, "end_slot": 2, "min_gap": 1}
    )
    return doc


def main() -> None:
    from fixture_factory import (
        chain_trap_case,
        equal_cost_tie_case,
        frozen_contention_case,
        idle_position_case,
        large_case,
        same_team_trap_case,
        scenario_base,
        scenario_frozen_conflict_case,
        scenario_long_route_case,
        scenario_no_common_prefix_case,
        scenario_same_reveal_case,
    )

    write("tiny_case.json", tiny_case())
    write("tiny_infeasible_case.json", tiny_infeasible_case())
    write("large_case.json", large_case())
    write("chain_trap_case.json", chain_trap_case())
    write("frozen_contention_case.json", frozen_contention_case())
    write("same_team_trap_case.json", same_team_trap_case())
    write("equal_cost_tie_case.json", equal_cost_tie_case())
    write("idle_position_case.json", idle_position_case())
    write("scenario_base.json", scenario_base())
    write("scenario_no_common_prefix.json", scenario_no_common_prefix_case())
    write("scenario_long_route.json", scenario_long_route_case())
    write("scenario_same_reveal.json", scenario_same_reveal_case())
    write("scenario_frozen_conflict.json", scenario_frozen_conflict_case())


if __name__ == "__main__":
    main()
