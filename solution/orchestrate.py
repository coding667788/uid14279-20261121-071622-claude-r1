"""High-level orchestration: solve, minimum-unsatisfiable sets, output shapes."""

from __future__ import annotations

from itertools import combinations

from .model import NO_ABSENCE_ID, Case
from .solver import SolveResult, TreeSolver


def _evidence_dicts(records: list[tuple]) -> list[dict]:
    return [
        {"slot": slot, "inspector": inspector, "checkpoint": cp_id, "window": wid}
        for slot, inspector, cp_id, wid in records
    ]


def _track_dicts(tracks: dict[str, list[str]]) -> list[dict]:
    return [
        {"inspector": iid, "positions": positions}
        for iid, positions in sorted(tracks.items())
    ]


def _leaf_plan(result: SolveResult, lid: str) -> dict:
    return {
        "scenario_id": lid,
        "new_visits": result.new_visits[lid],
        "movement_cost": result.costs[lid],
        "evidence": _evidence_dicts(result.evidence[lid]),
        "tracks": _track_dicts(result.tracks[lid]),
    }


def solve_full(case: Case) -> SolveResult | None:
    solver = TreeSolver(case)
    return solver.solve()


def removal_sets_in_order(window_ids: list[str]):
    """Yield removal sets in ascending lexicographic order of id lists."""
    for k in range(1, len(window_ids) + 1):
        for combo in combinations(sorted(window_ids), k):
            yield list(combo)


def minimum_unsatisfiable(case: Case) -> dict:
    """Find the lexicographically smallest minimum-cardinality removal set.

    Removal sets are enumerated in (size, sorted-id-tuple) order, so the first
    set whose remaining windows are all coverable is the required answer.
    Every proper prefix of size k has already been proven infeasible.
    """
    window_ids = sorted(case.window_ids)
    for removal in removal_sets_in_order(window_ids):
        active = set(window_ids) - set(removal)
        solver = TreeSolver(case, active_windows=active)
        result = solver.solve()
        if result is not None:
            return {"removal": removal, "result": result}
    # Removing everything is always feasible (no windows left).
    raise RuntimeError("unreachable: empty window set must be feasible")


def build_output(case: Case, raw_input: dict) -> dict:
    solver_probe = TreeSolver(case)
    conflicts = solver_probe.tree.conflicts
    if conflicts:
        return {
            "status": "input_conflict",
            "case_id": case.case_id,
            "errors": [e.to_dict() for e in conflicts],
        }

    result = solve_full(case)

    if result is not None:
        return _feasible_output(case, result)

    unsat = minimum_unsatisfiable(case)
    return _infeasible_output(case, unsat)


def _feasible_output(case: Case, result: SolveResult) -> dict:
    if not case.multi:
        lid = NO_ABSENCE_ID
        plan = _leaf_plan(result, lid)
        return {
            "status": "feasible",
            "case_id": case.case_id,
            "mode": "single",
            "objective": {
                "new_visits": result.new_visits[lid],
                "movement_cost": result.costs[lid],
            },
            "plan": plan,
        }

    leaves = {leaf.scenario_id: leaf for leaf in result.tree.leaves}
    main_lid = NO_ABSENCE_ID
    main_leaf = leaves[main_lid]
    main_plan = _leaf_plan(result, main_lid)

    contingency = []
    for leaf in result.tree.leaves:
        lid = leaf.scenario_id
        if lid == main_lid:
            continue
        reveal = leaf.reveal_slot
        full = result.evidence[lid]
        prefix_records = [r for r in full if r[0] < reveal]
        suffix_records = [r for r in full if r[0] >= reveal]
        contingency.append(
            {
                "scenario_id": lid,
                "reveal_slot": reveal,
                "absent": sorted(leaf.absent),
                "new_visits": result.new_visits[lid],
                "movement_cost": result.costs[lid],
                "trigger_prefix": {
                    "slots": [1, reveal - 1],
                    "evidence": _evidence_dicts(prefix_records),
                },
                "suffix": {
                    "slots": [reveal, case.slot_count],
                    "evidence": _evidence_dicts(suffix_records),
                    "tracks": _track_dicts(result.tracks[lid]),
                },
            }
        )
    contingency.sort(key=lambda d: d["scenario_id"])

    # Prefix consistency is structural in the tree; expose shared prefixes
    # grouped by reveal slot for direct inspection by checkers and humans.
    prefix_by_reveal: dict[int, list[dict]] = {}
    for leaf in result.tree.leaves:
        if leaf.scenario_id == main_lid:
            continue
        prefix_by_reveal.setdefault(leaf.reveal_slot, []).append(leaf.scenario_id)

    return {
        "status": "feasible",
        "case_id": case.case_id,
        "mode": "scenario",
        "objective": {
            "max_new_visits": result.max_new,
            "sum_movement_cost": result.total_cost,
        },
        "main_plan": main_plan,
        "contingencies": contingency,
        "shared_prefix_groups": [
            {"reveal_slot": r, "scenario_ids": sorted(prefix_by_reveal[r])}
            for r in sorted(prefix_by_reveal)
        ],
    }


def _infeasible_output(case: Case, unsat: dict) -> dict:
    result: SolveResult = unsat["result"]
    witnesses = {}
    for removed in unsat["removal"]:
        # One feasible covering of every window except `removed`; frozen
        # visits and all personnel constraints stay fixed inside the solver.
        if not case.multi:
            lid = NO_ABSENCE_ID
            witnesses[removed] = {
                "evidence": _evidence_dicts(result.evidence[lid]),
                "tracks": _track_dicts(result.tracks[lid]),
            }
        else:
            witnesses[removed] = {
                leaf.scenario_id: {
                    "evidence": _evidence_dicts(result.evidence[leaf.scenario_id]),
                    "tracks": _track_dicts(result.tracks[leaf.scenario_id]),
                }
                for leaf in result.tree.leaves
            }
    return {
        "status": "infeasible",
        "case_id": case.case_id,
        "mode": "scenario" if case.multi else "single",
        "minimum_unsatisfiable_windows": unsat["removal"],
        "feasible_witnesses": witnesses,
    }
