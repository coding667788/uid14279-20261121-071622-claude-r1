"""Fixture factory for the 10-inspector / 12-slot / 12-window scale case and
all trap scenarios named in the specification.
"""

from __future__ import annotations


def large_case() -> dict:
    """10 inspectors, 12 slots, 12 windows, 6 checkpoints, two teams."""
    inspectors = []
    teams = ["A", "B"]
    # Five checkpoints c1..c5 plus a hub; trainings t1..t3.  Training sets
    # are interleaved with teams so every multi-training checkpoint keeps
    # qualified inspectors on both teams (otherwise cross-team witnessing is
    # structurally impossible).
    for k in range(1, 11):
        team = teams[(k - 1) % 2]
        trainings = ["t1"]
        if k in (2, 3, 6, 7, 10):
            trainings.append("t2")
        # t3 is spread over both teams and enough inspectors that the
        # t3-gated checkpoints (c5, c6) keep several cross-team candidates.
        if k in (1, 2, 3, 4, 5, 6, 7, 8):
            trainings.append("t3")
        inspectors.append(
            {"id": f"i{k:02d}", "team": team, "trainings": trainings, "initial": "HUB"}
        )

    checkpoints = [
        {"id": "c1", "required_trainings": ["t1"]},
        {"id": "c2", "required_trainings": ["t1"]},
        {"id": "c3", "required_trainings": ["t1", "t2"]},
        {"id": "c4", "required_trainings": ["t1", "t2"]},
        {"id": "c5", "required_trainings": ["t1", "t2", "t3"]},
        {"id": "c6", "required_trainings": ["t1", "t3"]},
    ]
    edges = [
        {"src": "HUB", "dst": "c1", "cost": 1},
        {"src": "c1", "dst": "HUB", "cost": 1},
        {"src": "HUB", "dst": "c2", "cost": 1},
        {"src": "c2", "dst": "HUB", "cost": 1},
        {"src": "HUB", "dst": "c3", "cost": 2},
        {"src": "c3", "dst": "HUB", "cost": 2},
        {"src": "c1", "dst": "c3", "cost": 1},
        {"src": "c3", "dst": "c1", "cost": 1},
        {"src": "c2", "dst": "c4", "cost": 1},
        {"src": "c4", "dst": "c2", "cost": 1},
        {"src": "HUB", "dst": "c4", "cost": 2},
        {"src": "c4", "dst": "HUB", "cost": 2},
        {"src": "c3", "dst": "c5", "cost": 1},
        {"src": "c5", "dst": "c3", "cost": 1},
        {"src": "c4", "dst": "c6", "cost": 1},
        {"src": "c6", "dst": "c4", "cost": 1},
        {"src": "HUB", "dst": "c5", "cost": 4},
        {"src": "c5", "dst": "HUB", "cost": 4},
        {"src": "HUB", "dst": "c6", "cost": 4},
        {"src": "c6", "dst": "HUB", "cost": 4},
    ]
    # Two windows per checkpoint.  The early band (slots 1..4) and late band
    # (slots 9..12) are separated by a wide idle corridor, so the two windows
    # of any single checkpoint never contend for the same inspector/checkpoint
    # witness slot; within a band the checkpoints still share inspectors and
    # the reachability matrix still constrains every transition.  This keeps
    # the full constraint set active while holding the exact search to a small
    # branching structure (it is "small but not a toy": 10 people, 12 slots,
    # 12 windows, real training/team/reachability/frozen interactions).
    layout = [
        # (window, checkpoint, start, end, min_gap)
        ("w00", "c1", 1, 2, 1),
        ("w01", "c2", 1, 2, 1),
        ("w02", "c3", 2, 3, 1),
        ("w03", "c4", 2, 3, 1),
        ("w04", "c5", 3, 4, 1),
        ("w05", "c6", 3, 4, 1),
        ("w06", "c1", 9, 10, 1),
        ("w07", "c2", 9, 10, 1),
        ("w08", "c3", 10, 11, 1),
        ("w09", "c4", 10, 11, 1),
        ("w10", "c5", 11, 12, 1),
        ("w11", "c6", 11, 12, 1),
    ]
    windows = [
        {"id": wid, "checkpoint": cp, "start_slot": lo, "end_slot": hi, "min_gap": gap}
        for wid, cp, lo, hi, gap in layout
    ]
    # The frozen attendance of i02 at c1 slot 1 is a pre-attribution that may
    # serve w00 (c1, slots 1..2); the second frozen visit is unattributed and
    # must simply be preserved as a fixed waypoint.
    frozen = [
        {"inspector": "i02", "slot": 1, "checkpoint": "c1", "window": "w00"},
        {"inspector": "i04", "slot": 2, "checkpoint": "c2", "window": None},
    ]
    return {
        "case_id": "large10x12x12",
        "slot_count": 12,
        "inspectors": inspectors,
        "checkpoints": checkpoints,
        "edges": edges,
        "windows": windows,
        "frozen_visits": frozen,
    }


def chain_trap_case() -> dict:
    """Locally reachable edges but a required exact-step chain that cannot
    be completed inside the window.

    The graph contains every edge individually (S->P and P->R), so a naive
    "is there an edge" check thinks R is reachable.  But reaching R from S is a
    two-transition walk S->P->R.  The window on R opens at slot 2 and the only
    cross-team t2-qualified inspectors start at S: they cannot arrive before
    slot 3, and once paired against the single-slot gap the second witness has
    no legal placement.  The exact-step min-plus table exposes the impossibility
    that per-edge reachability hides.
    """
    return {
        "case_id": "chain_trap",
        "slot_count": 4,
        "inspectors": [
            # Only a1 and b1 hold t2 (required by R); they start at S, two
            # transitions from R.  b2 holds only t1 and can witness P only.
            {"id": "a1", "team": "A", "trainings": ["t1", "t2"], "initial": "S"},
            {"id": "b1", "team": "B", "trainings": ["t1", "t2"], "initial": "S"},
            {"id": "b2", "team": "B", "trainings": ["t1"], "initial": "P"},
        ],
        "checkpoints": [
            {"id": "P", "required_trainings": ["t1"]},
            {"id": "R", "required_trainings": ["t1", "t2"]},
        ],
        "edges": [
            {"src": "S", "dst": "P", "cost": 1},
            {"src": "P", "dst": "R", "cost": 1},
            {"src": "R", "dst": "P", "cost": 1},
        ],
        "windows": [
            # R needs two cross-team t2 inspectors.  a1 and b1 are the only
            # pair; from S they reach R no earlier than slot 3.  A window of
            # slots 2..3 with min_gap 2 would require slots differing by >=2,
            # but the only mutually reachable slot for both is slot 3, so the
            # exact-step table makes the pairing impossible.
            {"id": "w1", "checkpoint": "R", "start_slot": 2, "end_slot": 3, "min_gap": 2},
        ],
        "frozen_visits": [],
    }


def frozen_contention_case() -> dict:
    """One frozen visit is hinted by two windows; it can serve only one."""
    doc = {
        "case_id": "frozen_contention",
        "slot_count": 4,
        "inspectors": [
            {"id": "a1", "team": "A", "trainings": ["t1"], "initial": "H"},
            {"id": "b1", "team": "B", "trainings": ["t1"], "initial": "H"},
            {"id": "b2", "team": "B", "trainings": ["t1"], "initial": "H"},
        ],
        "checkpoints": [{"id": "P", "required_trainings": ["t1"]}],
        "edges": [
            {"src": "H", "dst": "P", "cost": 1},
            {"src": "P", "dst": "H", "cost": 1},
        ],
        "windows": [
            {"id": "w1", "checkpoint": "P", "start_slot": 1, "end_slot": 2, "min_gap": 1},
            {"id": "w2", "checkpoint": "P", "start_slot": 1, "end_slot": 4, "min_gap": 1},
        ],
        "frozen_visits": [
            {"inspector": "b1", "slot": 1, "checkpoint": "P", "window": "w1"}
        ],
    }
    return doc


def same_team_trap_case() -> dict:
    """Only one team is qualified, so no window can get two valid witnesses."""
    return {
        "case_id": "same_team_trap",
        "slot_count": 3,
        "inspectors": [
            {"id": "a1", "team": "A", "trainings": ["t1"], "initial": "H"},
            {"id": "a2", "team": "A", "trainings": ["t1"], "initial": "H"},
            {"id": "b1", "team": "B", "trainings": [], "initial": "H"},
        ],
        "checkpoints": [{"id": "P", "required_trainings": ["t1"]}],
        "edges": [
            {"src": "H", "dst": "P", "cost": 1},
            {"src": "P", "dst": "H", "cost": 1},
        ],
        "windows": [
            {"id": "w1", "checkpoint": "P", "start_slot": 1, "end_slot": 3, "min_gap": 1}
        ],
        "frozen_visits": [],
    }


def equal_cost_tie_case() -> dict:
    """Two equally costly optima; the canonical sequence decides."""
    return {
        "case_id": "equal_cost_tie",
        "slot_count": 3,
        "inspectors": [
            {"id": "a1", "team": "A", "trainings": ["t1"], "initial": "H"},
            {"id": "b1", "team": "B", "trainings": ["t1"], "initial": "H"},
        ],
        "checkpoints": [{"id": "P", "required_trainings": ["t1"]}],
        "edges": [
            {"src": "H", "dst": "P", "cost": 1},
            {"src": "P", "dst": "H", "cost": 1},
        ],
        "windows": [
            {"id": "w1", "checkpoint": "P", "start_slot": 1, "end_slot": 3, "min_gap": 1}
        ],
        "frozen_visits": [],
    }


def idle_position_case() -> dict:
    """Idle slots must keep the exact previous position at zero cost."""
    return {
        "case_id": "idle_position",
        "slot_count": 4,
        "inspectors": [
            {"id": "a1", "team": "A", "trainings": ["t1"], "initial": "H"},
            {"id": "b1", "team": "B", "trainings": ["t1"], "initial": "H"},
        ],
        "checkpoints": [{"id": "P", "required_trainings": ["t1"]}],
        "edges": [
            {"src": "H", "dst": "P", "cost": 3},
            {"src": "P", "dst": "H", "cost": 3},
        ],
        "windows": [
            {"id": "w1", "checkpoint": "P", "start_slot": 1, "end_slot": 4, "min_gap": 2}
        ],
        "frozen_visits": [],
    }


# --------------------------------------------------------------------------- #
# Multi-scenario (blind / reveal) cases
# --------------------------------------------------------------------------- #
def scenario_base() -> dict:
    """4 inspectors, 5 slots, two absence scenarios plus the no-absence leaf.

    Scenario eA reveals at slot 3 and removes one team-A inspector; eB reveals
    at slot 4 and removes one team-B inspector.  The early windows force a
    shared prefix, and the late windows are where each branch must re-plan
    without touching pre-reveal evidence.
    """
    doc = {
        "case_id": "scenario_base",
        "slot_count": 5,
        "inspectors": [
            {"id": "a1", "team": "A", "trainings": ["t1"], "initial": "H"},
            {"id": "a2", "team": "A", "trainings": ["t1"], "initial": "H"},
            {"id": "b1", "team": "B", "trainings": ["t1"], "initial": "H"},
            {"id": "b2", "team": "B", "trainings": ["t1"], "initial": "H"},
        ],
        "checkpoints": [{"id": "P", "required_trainings": ["t1"]}],
        "edges": [
            {"src": "H", "dst": "P", "cost": 1},
            {"src": "P", "dst": "H", "cost": 1},
        ],
        "windows": [
            # Early window: fully inside the shared (pre-reveal) prefix.
            {"id": "w1", "checkpoint": "P", "start_slot": 1, "end_slot": 2, "min_gap": 1},
            # Late window: after every reveal, each branch covers it with the
            # inspectors that remain available in that scenario.
            {"id": "w2", "checkpoint": "P", "start_slot": 4, "end_slot": 5, "min_gap": 1},
        ],
        "frozen_visits": [
            {"inspector": "a1", "slot": 1, "checkpoint": "P", "window": "w1"}
        ],
        "scenarios": [
            {"id": "eA", "reveal_slot": 3, "absent": ["a2"]},
            {"id": "eB", "reveal_slot": 4, "absent": ["b2"]},
        ],
    }
    return doc


def scenario_no_common_prefix_case() -> dict:
    """Each scenario is alone schedulable, but no shared pre-reveal prefix
    can satisfy the early window.

    Four inspectors, two per team, all qualified.  Both scenarios reveal at
    slot 1, so there is no pre-reveal horizon at all: every decision is branch
    specific.  eA removes one A inspector, eB removes the other A inspector.
    Each branch still keeps one A and both B inspectors, so taken alone it can
    cover both windows.  But the inspectors surviving *every* branch are only
    the two B inspectors, leaving no cross-team pair for the early window that
    a common prefix would have to commit.  The minimal unsatisfiable window set
    of the blind problem is exactly [w1].
    """
    doc = {
        "case_id": "scenario_no_common_prefix",
        "slot_count": 5,
        "inspectors": [
            {"id": "a1", "team": "A", "trainings": ["t1"], "initial": "H"},
            {"id": "a2", "team": "A", "trainings": ["t1"], "initial": "H"},
            {"id": "b1", "team": "B", "trainings": ["t1"], "initial": "H"},
            {"id": "b2", "team": "B", "trainings": ["t1"], "initial": "H"},
        ],
        "checkpoints": [
            {"id": "P", "required_trainings": ["t1"]},
            {"id": "R", "required_trainings": ["t1"]},
        ],
        "edges": [
            {"src": "H", "dst": "P", "cost": 1},
            {"src": "P", "dst": "H", "cost": 1},
            {"src": "H", "dst": "R", "cost": 1},
            {"src": "R", "dst": "H", "cost": 1},
        ],
        "windows": [
            # Narrow early window on R; distinct checkpoint keeps it separate
            # from the later P window under the per-checkpoint reuse rule.
            {"id": "w1", "checkpoint": "R", "start_slot": 1, "end_slot": 2, "min_gap": 1},
            # Later window on P; each branch covers it with its surviving core.
            {"id": "w2", "checkpoint": "P", "start_slot": 4, "end_slot": 5, "min_gap": 1},
        ],
        "frozen_visits": [],
        "scenarios": [
            # Survivors: a2 + b1,b2 (cross-team, branch feasible).
            {"id": "eA", "reveal_slot": 1, "absent": ["a1"]},
            # Survivors: a1 + b1,b2 (cross-team, branch feasible), but the
            # intersection with eA survivors is {b1,b2}: B only, so no common
            # cross-team pair exists for the early window.
            {"id": "eB", "reveal_slot": 1, "absent": ["a2"]},
        ],
    }
    return doc


def scenario_same_reveal_case() -> dict:
    """Two branches and the no-absence leaf diverge at the same reveal slot.

    Six inspectors (three per team) keep a universal cross-team core a1+b1 that
    never gets removed, so the shared pre-reveal window is always coverable.
    Three scenarios all reveal at slot 3, each removing a different *spare*
    inspector; afterwards every branch independently covers the late window.
    This exercises simultaneous reveals with divergent suffixes while staying
    feasible, including the implicit no-absence scenario.
    """
    doc = {
        "case_id": "scenario_same_reveal",
        "slot_count": 6,
        "inspectors": [
            {"id": "a1", "team": "A", "trainings": ["t1"], "initial": "H"},
            {"id": "a2", "team": "A", "trainings": ["t1"], "initial": "H"},
            {"id": "a3", "team": "A", "trainings": ["t1"], "initial": "H"},
            {"id": "b1", "team": "B", "trainings": ["t1"], "initial": "H"},
            {"id": "b2", "team": "B", "trainings": ["t1"], "initial": "H"},
            {"id": "b3", "team": "B", "trainings": ["t1"], "initial": "H"},
        ],
        "checkpoints": [{"id": "P", "required_trainings": ["t1"]}],
        "edges": [
            {"src": "H", "dst": "P", "cost": 1},
            {"src": "P", "dst": "H", "cost": 1},
        ],
        "windows": [
            {"id": "w1", "checkpoint": "P", "start_slot": 1, "end_slot": 2, "min_gap": 1},
            # Narrow post-reveal window keeps every branch's exact search small
            # while still forcing distinct suffix decisions per scenario.
            {"id": "w2", "checkpoint": "P", "start_slot": 5, "end_slot": 6, "min_gap": 1},
        ],
        "frozen_visits": [],
        "scenarios": [
            # The cross-team core a1 (A) + b1 (B) is never removed, so the
            # shared pre-reveal window is always coverable; each scenario only
            # removes spare inspectors and all reveal at the same slot 3.
            {"id": "eA", "reveal_slot": 3, "absent": ["a2"]},
            {"id": "eB", "reveal_slot": 3, "absent": ["b2"]},
            {"id": "eC", "reveal_slot": 3, "absent": ["a3", "b3"]},
        ],
    }
    return doc


def scenario_long_route_case() -> dict:
    """A farther main-plan route is what lets the reserve chain transitions.

    The main (no-absence) plan must take a longer, costlier route early so that
    after a reveal the remaining reserve inspectors can still form a legal
    exact-step chain into the late checkpoint.  Taking the cheap main route
    strands them; the solver has to prefer the farther route to keep every
    branch feasible.
    """
    return {
        "case_id": "scenario_long_route",
        "slot_count": 6,
        "inspectors": [
            {"id": "a1", "team": "A", "trainings": ["t1"], "initial": "H"},
            {"id": "a2", "team": "A", "trainings": ["t1"], "initial": "H"},
            {"id": "b1", "team": "B", "trainings": ["t1"], "initial": "H"},
            {"id": "b2", "team": "B", "trainings": ["t1"], "initial": "H"},
        ],
        "checkpoints": [
            {"id": "P", "required_trainings": ["t1"]},
            {"id": "Q", "required_trainings": ["t1"]},
        ],
        "edges": [
            # Cheap direct route H->P; the long route H->Q->P costs more but
            # leaves the reserve positioned at Q for the post-reveal chain.
            {"src": "H", "dst": "P", "cost": 1},
            {"src": "P", "dst": "H", "cost": 1},
            {"src": "H", "dst": "Q", "cost": 2},
            {"src": "Q", "dst": "H", "cost": 2},
            {"src": "Q", "dst": "P", "cost": 1},
            {"src": "P", "dst": "Q", "cost": 1},
        ],
        "windows": [
            {"id": "w1", "checkpoint": "P", "start_slot": 1, "end_slot": 2, "min_gap": 1},
            {"id": "w2", "checkpoint": "Q", "start_slot": 5, "end_slot": 6, "min_gap": 1},
        ],
        "frozen_visits": [],
        "scenarios": [
            {"id": "eA", "reveal_slot": 3, "absent": ["a1"]},
            {"id": "eB", "reveal_slot": 3, "absent": ["b1"]},
        ],
    }


def scenario_frozen_conflict_case() -> dict:
    """An absence directly contradicts a frozen post-reveal visit."""
    doc = scenario_base()
    doc["case_id"] = "scenario_frozen_conflict"
    # Freeze a1 at P in slot 4, then make a1 absent from slot 3 onward in eA.
    doc["frozen_visits"].append(
        {"inspector": "a1", "slot": 4, "checkpoint": "P", "window": None}
    )
    doc["scenarios"] = [
        {"id": "eA", "reveal_slot": 3, "absent": ["a1"]},
    ]
    return doc
