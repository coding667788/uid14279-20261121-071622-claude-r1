"""Independent exhaustive oracle for tiny cases.

The production solver searches a scenario tree of witness actions.  This
oracle uses a deliberately different formulation: it enumerates every choice
of two witness visits per window directly from the (inspector, slot) grid,
rejects pairings that break a hard rule, and asks the exact-step path table
whether a legal track exists through the resulting waypoints (frozen visits
included).  No code or data structure of solver.py is reused.

The enumeration is exponential and guarded by BRUTE_LIMITS; it exists solely
to cross-check the production solver on small hand-built cases.
"""

from __future__ import annotations

from itertools import combinations

from .geometry import build_path_table, waypoint_cost
from .model import Case

# Hard guard: exhaustive enumeration is intentionally unscalable.
BRUTE_LIMITS = {"inspectors": 5, "slots": 8, "windows": 4}


def _check_limits(case: Case) -> None:
    if len(case.inspector_ids) > BRUTE_LIMITS["inspectors"]:
        raise ValueError("brute oracle: too many inspectors")
    if case.slot_count > BRUTE_LIMITS["slots"]:
        raise ValueError("brute oracle: too many slots")
    if len(case.window_ids) > BRUTE_LIMITS["windows"]:
        raise ValueError("brute oracle: too many windows")


def _all_visit_choices(case: Case) -> dict[str, list[tuple[str, int]]]:
    """Every legal (inspector, slot) at which the window's cp can be visited."""
    choices: dict[str, list[tuple[str, int]]] = {}
    for wid, w in case.windows.items():
        opts = []
        for iid in case.inspector_ids:
            insp = case.inspectors[iid]
            if not (case.checkpoints[w.checkpoint].required <= insp.trainings):
                continue
            for slot in range(w.start, w.end + 1):
                opts.append((iid, slot))
        choices[wid] = opts
    return choices


def brute_solve_single(case: Case, active: set[str] | None = None) -> dict | None:
    """Exhaustive optimum for a single-scenario (no absence) case."""
    _check_limits(case)
    if case.multi:
        raise ValueError("brute_solve_single expects a single-scenario case")
    table = build_path_table(case.nodes, case.edges, case.slot_count)
    choices = _all_visit_choices(case)
    team = {iid: insp.team for iid, insp in case.inspectors.items()}
    frozen_by_insp: dict[str, list[tuple[int, str]]] = {iid: [] for iid in case.inspector_ids}
    frozen_keys: set[tuple] = set()
    for fv in case.frozen:
        frozen_by_insp[fv.inspector].append((fv.slot, fv.checkpoint))
        frozen_keys.add((fv.inspector, fv.slot, fv.checkpoint))

    wids = sorted(case.window_ids) if active is None else sorted(active)
    best = None

    def evaluate(pairing: list[tuple[str, tuple, tuple]]):
        nonlocal best
        # Hard rules on the pairing itself.
        used_visits: set[tuple] = set()
        insp_cp: set[tuple[str, str]] = set()
        for wid, a, b in pairing:
            cp = case.windows[wid].checkpoint
            if a[0] == b[0] or team[a[0]] == team[b[0]]:
                return
            if abs(a[1] - b[1]) < case.windows[wid].min_gap:
                return
            for iid, slot in (a, b):
                key = (iid, slot, cp)
                if key in used_visits:
                    return
                if (iid, cp) in insp_cp:
                    return
                used_visits.add(key)
                insp_cp.add((iid, cp))

        # Frozen visits must be honoured: a witness slot cannot collide with
        # a frozen waypoint at a different checkpoint.
        waypoints: dict[str, list[tuple[int, str]]] = {
            iid: list(lst) for iid, lst in frozen_by_insp.items()
        }
        for wid, a, b in pairing:
            cp = case.windows[wid].checkpoint
            for iid, slot in (a, b):
                if any(s == slot and c != cp for s, c in waypoints[iid]):
                    return
                if not any(s == slot for s, _ in waypoints[iid]):
                    waypoints[iid].append((slot, cp))

        total_cost = 0
        for iid, pts in waypoints.items():
            initial = case.inspectors[iid].initial
            c = waypoint_cost(table, sorted(pts), initial)
            if c >= 10**14:
                return
            total_cost += c

        new_visits = len(used_visits - frozen_keys)
        records = []
        for wid, a, b in pairing:
            cp = case.windows[wid].checkpoint
            records.extend([(a[1], a[0], cp, wid), (b[1], b[0], cp, wid)])
        records.sort()
        key = (new_visits, total_cost, tuple(records))
        if best is None or key < best[0]:
            best = (
                key,
                {
                    "new_visits": new_visits,
                    "movement_cost": total_cost,
                    "evidence": records,
                    "waypoints": {iid: sorted(pts) for iid, pts in waypoints.items()},
                },
            )

    def go(idx: int, pairing: list):
        if idx == len(wids):
            evaluate(pairing)
            return
        wid = wids[idx]
        opts = choices[wid]
        # Unordered pairs only; canonical ordering keeps the enumeration total.
        for k in range(len(opts)):
            for j in range(k + 1, len(opts)):
                a, b = opts[k], opts[j]
                if a[0] == b[0]:
                    continue
                go(idx + 1, pairing + [(wid, a, b)])

    go(0, [])
    return None if best is None else best[1]


def brute_feasible(case: Case, active: set[str] | None = None) -> bool:
    return brute_solve_single(case, active) is not None
