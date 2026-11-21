"""Scenario tree construction.

Each node owns a disjoint slot interval on every root-to-leaf path that
contains it.  Shared nodes sit on the paths of every scenario that has not
revealed yet; branch nodes belong to exactly one revealed scenario.  Because
all decisions taken inside a node are made once, two scenarios that are both
unrevealed at a slot automatically take identical decisions there.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import E_FROZEN_ABSENT_CONFLICT, ValidationError
from .model import NO_ABSENCE_ID, Case, Scenario


@dataclass
class TNode:
    nid: str
    slots: list[int]
    leaves: list[int]  # leaf indices whose path contains this node
    absent: frozenset[str]
    shared: bool
    slot_set: frozenset[int] = field(default_factory=frozenset)


@dataclass
class TLeaf:
    scenario_id: str
    reveal_slot: int
    absent: frozenset[str]
    path: list[TNode]
    node_ids: frozenset[str]


@dataclass
class Tree:
    nodes: list[TNode]
    node_index: dict[str, TNode]
    leaves: list[TLeaf]
    leaf_index: dict[str, int]
    # frozen visits grouped by node id (frozen waypoints are never moved).
    frozen_by_node: dict[str, list]
    conflicts: list[ValidationError]


def _all_scenarios(case: Case) -> list[Scenario]:
    if case.scenarios is None:
        return [Scenario(NO_ABSENCE_ID, case.slot_count + 1, frozenset())]
    out = list(case.scenarios)
    out.append(Scenario(NO_ABSENCE_ID, case.slot_count + 1, frozenset()))
    out.sort(key=lambda s: (s.reveal_slot, s.id))
    return out


def build_tree(case: Case) -> Tree:
    T = case.slot_count
    scenarios = _all_scenarios(case)
    leaf_ids = [s.id for s in scenarios]
    leaf_index = {sid: k for k, sid in enumerate(leaf_ids)}
    leaf_by_id = {s.id: s for s in scenarios}

    nodes: list[TNode] = []
    node_index: dict[str, TNode] = {}
    leaf_paths: dict[str, list[TNode]] = {sid: [] for sid in leaf_ids}

    reveals = sorted({s.reveal_slot for s in scenarios})

    def add_node(nid: str, lo: int, hi: int, leaves: list[int], absent: frozenset[str], shared: bool) -> TNode | None:
        if lo > hi:
            return None
        node = TNode(
            nid=nid,
            slots=list(range(lo, hi + 1)),
            leaves=leaves,
            absent=absent,
            shared=shared,
            slot_set=frozenset(range(lo, hi + 1)),
        )
        nodes.append(node)
        node_index[nid] = node
        return node

    # Shared segments between consecutive reveal instants.
    boundary = 1
    for m, r in enumerate(reveals):
        remaining = [leaf_index[s.id] for s in scenarios if s.reveal_slot >= r]
        g = add_node(f"G{m}", boundary, r - 1, remaining, frozenset(), True)
        if g is not None:
            for s in scenarios:
                if s.reveal_slot >= r:
                    leaf_paths[s.id].append(g)
        # Every scenario revealing at r diverges into its own branch node.
        for s in [x for x in scenarios if x.reveal_slot == r]:
            L = leaf_index[s.id]
            b = add_node(f"B:{s.id}", r, T, [L], s.absent, False)
            if b is not None:
                leaf_paths[s.id].append(b)
        boundary = r
    # Trailing shared segment for scenarios still unrevealed at the last r.
    remaining = [leaf_index[s.id] for s in scenarios if s.reveal_slot > reveals[-1]]
    g = add_node(f"G{len(reveals)}", boundary, T, remaining, frozenset(), True)
    if g is not None:
        for s in scenarios:
            if s.reveal_slot > reveals[-1]:
                leaf_paths[s.id].append(g)

    leaves = [
        TLeaf(
            scenario_id=sid,
            reveal_slot=leaf_by_id[sid].reveal_slot,
            absent=leaf_by_id[sid].absent,
            path=leaf_paths[sid],
            node_ids=frozenset(n.nid for n in leaf_paths[sid]),
        )
        for sid in leaf_ids
    ]

    # Distribute frozen visits to the node owning their slot on each leaf,
    # and detect direct conflicts with post-reveal absences.
    frozen_by_node: dict[str, list] = {n.nid: [] for n in nodes}
    conflicts: list[ValidationError] = []
    for fv in case.frozen:
        for leaf in leaves:
            owner = next(n for n in leaf.path if fv.slot in n.slot_set)
            if fv.inspector in leaf.absent and fv.slot >= leaf.reveal_slot:
                conflicts.append(
                    ValidationError(
                        E_FROZEN_ABSENT_CONFLICT,
                        f"$.scenarios[{leaf.scenario_id}]",
                        f"frozen visit of inspector '{fv.inspector}' at slot {fv.slot} "
                        f"conflicts with absence revealed at slot {leaf.reveal_slot}",
                    )
                )
            if owner.nid in frozen_by_node:
                bucket = frozen_by_node[owner.nid]
                if not any(
                    x.inspector == fv.inspector and x.slot == fv.slot and x.checkpoint == fv.checkpoint
                    for x in bucket
                ):
                    bucket.append(fv)

    return Tree(nodes, node_index, leaves, leaf_index, frozen_by_node, conflicts)
