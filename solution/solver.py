"""Exact tree-CSP solver.

The search is a depth-first branch-and-bound over witness assignments.  Every
feasible assignment is enumerated implicitly; pruning uses only *lower bounds*
on the lexicographic objectives, so no pruning rule can discard the optimum
(see README "Why the pruning is complete").

Completeness argument in brief:
  * MRV only chooses the *order* of variables; it never removes a value.
  * A candidate action is rejected only when it already contradicts a hard
    constraint (slot occupancy, same inspector/checkpoint reuse, training,
    absence, frozen waypoint, team difference, gap, exact-step reachability).
  * Branch-and-bound prunes a partial assignment only when every completion is
    lexicographically worse than the incumbent (new-visit count already above
    the bound, or equal counts with movement cost above the bound).
  * The tie-break sequence is compared only on complete plans, in a fixed
    enumeration order, so the first kept optimum is the canonical one.

Performance machinery (soundness-preserving only):
  * Static per (node, window) visit and pair domains are computed once;
    dynamic filtering reuses them instead of rebuilding O(n^2) pair lists.
  * Reachability of a waypoint insertion checks only the two path segments
    adjacent to the insertion point against the exact-step table; segments
    not touching the new waypoint are unchanged and need no re-evaluation.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from .geometry import INF, ExactPathTable, build_path_table, reconstruct_track, waypoint_cost
from .model import Case
from .tree import Tree, build_tree

# Action: (window_id, node_id, (inspector1, slot1), (inspector2, slot2)).
Action = tuple[str, str, tuple[str, int], tuple[str, int]]


@dataclass
class SolveResult:
    feasible: bool
    evidence: dict[str, list[tuple]]
    waypoints: dict[str, dict[str, list[tuple[int, str]]]]
    tracks: dict[str, dict[str, list[str]]]
    new_visits: dict[str, int]
    costs: dict[str, int]
    max_new: int
    total_cost: int
    new_visit_registry: dict[str, set]
    tree: Tree
    table: ExactPathTable


class TreeSolver:
    def __init__(self, case: Case, active_windows: set[str] | None = None):
        self.case = case
        self.T = case.slot_count
        self.tree = build_tree(case)
        self.active: set[str] = set(case.window_ids) if active_windows is None else set(active_windows)
        self.table = build_path_table(case.nodes, case.edges, self.T)
        self._precompute()

    # ------------------------------------------------------------------ #
    # Static precomputation
    # ------------------------------------------------------------------ #
    def _precompute(self) -> None:
        case = self.case
        self.eligible: dict[str, list[str]] = {}
        for cp_id, cp in case.checkpoints.items():
            self.eligible[cp_id] = sorted(
                iid for iid in case.inspector_ids if cp.required <= case.inspectors[iid].trainings
            )

        self.frozen_waypoints: dict[str, dict[str, list[tuple[int, str]]]] = {}
        for leaf in self.tree.leaves:
            per: dict[str, list[tuple[int, str]]] = {iid: [] for iid in case.inspector_ids}
            for nid in leaf.node_ids:
                for fv in self.tree.frozen_by_node.get(nid, []):
                    if fv.inspector in leaf.absent and fv.slot >= leaf.reveal_slot:
                        continue
                    bisect.insort(per[fv.inspector], (fv.slot, fv.checkpoint))
            self.frozen_waypoints[leaf.scenario_id] = per

        self.frozen_lookup: dict[str, dict[tuple[str, int], str]] = {
            nid: {(fv.inspector, fv.slot): fv.checkpoint for fv in fvs}
            for nid, fvs in self.tree.frozen_by_node.items()
        }
        self.team = {iid: insp.team for iid, insp in case.inspectors.items()}

        self.window_nodes: dict[str, list[str]] = {}
        for wid in case.window_ids:
            w = case.windows[wid]
            self.window_nodes[wid] = [
                node.nid for node in self.tree.nodes if any(w.start <= s <= w.end for s in node.slots)
            ]

        # Static domains: visits and cross-team/gap-valid pairs that satisfy
        # every state-independent rule (eligibility, absence, frozen cp, team,
        # min_gap).  Search-time filtering only adds dynamic constraints.
        self.static_visits: dict[tuple[str, str], list[tuple[str, int]]] = {}
        self.static_pairs: dict[tuple[str, str], list[tuple]] = {}
        self.hint_key: dict[tuple[str, str], tuple[str, int] | None] = {}
        for wid in case.window_ids:
            w = case.windows[wid]
            for nid in self.window_nodes[wid]:
                node = self.tree.node_index[nid]
                visits = self._static_visits(node, wid)
                self.static_visits[(nid, wid)] = visits
                pairs = []
                for k in range(len(visits)):
                    for j in range(k + 1, len(visits)):
                        a, b = visits[k], visits[j]
                        if a[0] == b[0] or self.team[a[0]] == self.team[b[0]]:
                            continue
                        if abs(a[1] - b[1]) < w.min_gap:
                            continue
                        x, y = (a, b) if (a[1], a[0]) <= (b[1], b[0]) else (b, a)
                        pairs.append((x, y))
                self.static_pairs[(nid, wid)] = pairs
                self.hint_key[(nid, wid)] = self._compute_hint(wid, nid)

    def _static_visits(self, node, wid: str) -> list[tuple[str, int]]:
        w = self.case.windows[wid]
        lo = max(w.start, node.slots[0])
        hi = min(w.end, node.slots[-1])
        # A decision on a shared node must survive every leaf that passes
        # through it.  An inspector is blocked at slot t only when some such
        # leaf has them absent from a reveal slot no later than t; an absence
        # revealed after t does not invalidate this pre-reveal visit.
        leaf_absence = [
            (self.tree.leaves[k].reveal_slot, self.tree.leaves[k].absent)
            for k in node.leaves
        ]
        out = []
        for iid in self.eligible[w.checkpoint]:
            for slot in range(lo, hi + 1):
                if any(iid in absent and slot >= reveal for reveal, absent in leaf_absence):
                    continue
                frozen = self.frozen_lookup[node.nid].get((iid, slot))
                if frozen is not None and frozen != w.checkpoint:
                    continue
                out.append((iid, slot))
        return out

    def _compute_hint(self, wid: str, nid: str) -> tuple[str, int] | None:
        for fv in self.case.frozen:
            if fv.window == wid and (fv.inspector, fv.slot) in self.frozen_lookup.get(nid, {}):
                return fv.inspector, fv.slot
        return None

    # ------------------------------------------------------------------ #
    # Mutable search state
    # ------------------------------------------------------------------ #
    def _init_state(self):
        tree = self.tree
        self.node_visit_cp = {n.nid: {} for n in tree.nodes}
        self.node_pairs = {n.nid: {} for n in tree.nodes}
        # Inspector/checkpoint witness reuse is constrained over the WHOLE
        # leaf path (an inspector witnesses a checkpoint for at most one
        # window), not per tree node, so it is tracked per leaf.
        self.leaf_insp_cps = {
            leaf.scenario_id: {iid: set() for iid in self.case.inspector_ids}
            for leaf in tree.leaves
        }
        self.waypoints = {
            leaf.scenario_id: {iid: list(lst) for iid, lst in per.items()}
            for leaf in tree.leaves
            for per in [self.frozen_waypoints[leaf.scenario_id]]
        }
        self.covered = {leaf.scenario_id: set() for leaf in tree.leaves}
        self.new_registry = {n.nid: set() for n in tree.nodes}
        self._undo_stack: list[list] = []
        # Incremental domain cache: (nid, wid) -> live action list or None
        # when dirty.  An action only constrains domains on the same node
        # (occupancy) and the same leaves (reuse/reachability), so applying
        # one dirties exactly the other windows of that node.
        self._domain_cache: dict[tuple[str, str], list | None] = {
            (nid, wid): None for wid in self.active for nid in self.window_nodes[wid]
        }

    # ------------------------------------------------------------------ #
    # Dynamic hard-constraint checks
    # ------------------------------------------------------------------ #
    def _slot_ok(self, node, inspector: str, slot: int, cp_id: str) -> bool:
        nid = node.nid
        visits = self.node_visit_cp[nid]
        cur = visits.get((inspector, slot))
        if cur is not None and cur != cp_id:
            return False
        # Cross-node, whole-leaf witness-reuse rule.
        for leaf_idx in node.leaves:
            lid = self.tree.leaves[leaf_idx].scenario_id
            cps = self.leaf_insp_cps[lid].get(inspector)
            if cps is not None and cp_id in cps:
                return False
        return True

    def _insertion_ok(self, leaf_id: str, inspector: str, slot: int, cp_id: str) -> bool:
        """O(log n) reachability check using only the adjacent segments."""
        lst = self.waypoints[leaf_id].get(inspector, [])
        # Waypoint tuples are ordered by (slot, checkpoint); bisect on the
        # slot sentinel avoids allocating a separate slot list each call.
        pos = bisect.bisect_left(lst, (slot, ""))
        if pos < len(lst) and lst[pos][0] == slot:
            return lst[pos][1] == cp_id  # existing waypoint at the same slot
        initial = self.case.inspectors[inspector].initial
        prev_slot, prev_node = (0, initial) if pos == 0 else lst[pos - 1]
        if self.table.cost(slot - prev_slot, prev_node, cp_id) >= INF:
            return False
        if pos < len(lst):
            next_slot, next_node = lst[pos]
            if self.table.cost(next_slot - slot, cp_id, next_node) >= INF:
                return False
        return True

    def _pair_live(self, node, wid: str, x: tuple[str, int], y: tuple[str, int]) -> bool:
        cp_id = self.case.windows[wid].checkpoint
        p1, t1 = x
        p2, t2 = y
        # Cheapest state lookups first, reachability (table walks) last.
        if not self._slot_ok(node, p1, t1, cp_id) or not self._slot_ok(node, p2, t2, cp_id):
            return False
        for leaf_idx in node.leaves:
            lid = self.tree.leaves[leaf_idx].scenario_id
            if wid in self.covered[lid]:
                return False
            if not self._insertion_ok(lid, p1, t1, cp_id):
                return False
            if not self._insertion_ok(lid, p2, t2, cp_id):
                return False
        return True

    def _build_actions(self, node, wid: str) -> list[Action]:
        nid = node.nid
        hint = self.hint_key[(nid, wid)]
        out = []
        for x, y in self.static_pairs[(nid, wid)]:
            if not self._pair_live(node, wid, x, y):
                continue
            uses_hint = 0 if hint is not None and (x == hint or y == hint) else 1
            out.append(((uses_hint, x[1], y[1], x[0], y[0]), (wid, nid, x, y)))
        out.sort(key=lambda t: t[0])
        return [act for _, act in out]

    def _cached_actions(self, node, wid: str) -> list[Action]:
        key = (node.nid, wid)
        cached = self._domain_cache.get(key)
        if cached is None:
            cached = self._build_actions(node, wid)
            self._domain_cache[key] = cached
        return cached

    def _cached_domain_size(self, node, wid: str) -> int:
        return len(self._cached_actions(node, wid))

    # ------------------------------------------------------------------ #
    # State changes with undo logging
    # ------------------------------------------------------------------ #
    def _dirty_affected(self, nid: str) -> None:
        """Invalidate cached domains that depend on the changed node.

        Occupancy changes are local to the node, but the whole-leaf witness
        reuse rule links every node sharing a leaf path: committing an
        inspector/checkpoint on one node removes pairs using that inspector on
        every other node the leaf traverses.  Domains of nodes with no leaf in
        common are unaffected and stay cached.
        """
        changed = self.tree.node_index[nid]
        affected_nodes = {n.nid for k in changed.leaves for n in self.tree.leaves[k].path}
        for other_nid in affected_nodes:
            for wid in self.active:
                key = (other_nid, wid)
                if key in self._domain_cache:
                    self._domain_cache[key] = None

    def _apply(self, action: Action) -> None:
        wid, nid, x, y = action
        node = self.tree.node_index[nid]
        cp_id = self.case.windows[wid].checkpoint
        log: list = []
        self._undo_stack.append(log)
        self._dirty_affected(nid)
        log.append(("dirty", nid))

        for inspector, slot in (x, y):
            visits = self.node_visit_cp[nid]
            key = (inspector, slot)
            if key not in visits:
                visits[key] = cp_id
                log.append(("visit", nid, key))
                if self.frozen_lookup[nid].get(key) is None:
                    self.new_registry[nid].add(key)
                    log.append(("new", nid, key))
            for leaf_idx in node.leaves:
                lid = self.tree.leaves[leaf_idx].scenario_id
                cps = self.leaf_insp_cps[lid].setdefault(inspector, set())
                if cp_id not in cps:
                    cps.add(cp_id)
                    log.append(("inspcp", lid, inspector, cp_id))
                per = self.waypoints[lid].setdefault(inspector, [])
                if not any(s == slot for s, _ in per):
                    bisect.insort(per, (slot, cp_id))
                    log.append(("wp", lid, inspector, (slot, cp_id)))

        self.node_pairs[nid][wid] = (x, y)
        log.append(("pair", nid, wid))
        for leaf_idx in node.leaves:
            lid = self.tree.leaves[leaf_idx].scenario_id
            self.covered[lid].add(wid)
            log.append(("covered", lid, wid))

    def _undo(self) -> None:
        for entry in reversed(self._undo_stack.pop()):
            kind = entry[0]
            if kind == "dirty":
                self._dirty_affected(entry[1])
            elif kind == "visit":
                del self.node_visit_cp[entry[1]][entry[2]]
            elif kind == "new":
                self.new_registry[entry[1]].discard(entry[2])
            elif kind == "inspcp":
                _, lid, inspector, cp_id = entry
                self.leaf_insp_cps[lid][inspector].discard(cp_id)
            elif kind == "wp":
                _, lid, inspector, point = entry
                self.waypoints[lid][inspector].remove(point)
            elif kind == "pair":
                del self.node_pairs[entry[1]][entry[2]]
            elif kind == "covered":
                self.covered[entry[1]].discard(entry[2])

    # ------------------------------------------------------------------ #
    # Objectives and bounds
    # ------------------------------------------------------------------ #
    def _leaf_new_visits(self, lid: str) -> int:
        leaf = self.tree.leaves[self.tree.leaf_index[lid]]
        return sum(len(self.new_registry[nid]) for nid in leaf.node_ids)

    def _leaf_cost(self, lid: str) -> int:
        total = 0
        for iid, per in self.waypoints[lid].items():
            c = waypoint_cost(self.table, per, self.case.inspectors[iid].initial)
            if c >= INF:
                return INF
            total += c
        return total

    def _current_bounds(self):
        """Monotone lower bounds: created visits never disappear and waypoint
        costs are exact minima over the remaining movement freedom."""
        news = [self._leaf_new_visits(lid) for lid in self.tree.leaf_index]
        costs = [self._leaf_cost(lid) for lid in self.tree.leaf_index]
        return max(news), sum(costs)

    def _is_new_visit(self, nid: str, inspector: str, slot: int) -> bool:
        return (inspector, slot) not in self.node_visit_cp[nid] and \
            self.frozen_lookup[nid].get((inspector, slot)) is None

    def _analyse(self):
        """Single sweep producing MRV target, dead-domain flag and the new
        visit lower bound together, so the static pairs are scanned once."""
        extra_per_leaf = {lid: 0 for lid in self.tree.leaf_index}
        best_key = None
        best = None
        best_actions = None
        dead = False
        for wid in sorted(self.active):
            for nid in self.window_nodes[wid]:
                node = self.tree.node_index[nid]
                if all(
                    wid in self.covered[self.tree.leaves[k].scenario_id] for k in node.leaves
                ):
                    continue
                actions = self._cached_actions(node, wid)
                if not actions:
                    dead = True
                    continue
                key = (len(actions), wid, nid)
                if best_key is None or key < best_key:
                    best_key, best, best_actions = key, (wid, nid), actions
                best_new = 2
                for act in actions:
                    _, _, x, y = act
                    created = (
                        (1 if self._is_new_visit(nid, x[0], x[1]) else 0)
                        + (1 if self._is_new_visit(nid, y[0], y[1]) else 0)
                    )
                    if created < best_new:
                        best_new = created
                        if best_new == 0:
                            break
                for k in node.leaves:
                    extra_per_leaf[self.tree.leaves[k].scenario_id] += best_new
        if dead:
            new_lb = INF
        else:
            new_lb = max(
                self._leaf_new_visits(lid) + extra_per_leaf[lid]
                for lid in self.tree.leaf_index
            )
        return best, best_actions, new_lb

    def _select_target(self):
        # MRV over cached domains.  Applying an action dirties only the other
        # windows of the same tree node, so after the first full evaluation
        # most domains are served from cache in O(1).
        best_key = None
        best = None
        for wid in sorted(self.active):
            for nid in self.window_nodes[wid]:
                node = self.tree.node_index[nid]
                if all(
                    wid in self.covered[self.tree.leaves[k].scenario_id] for k in node.leaves
                ):
                    continue
                size = self._cached_domain_size(node, wid)
                if size == 0:
                    return (wid, nid), []
                key = (size, wid, nid)
                if best_key is None or key < best_key:
                    best_key, best = key, (wid, nid)
        if best is None:
            return None, None
        node = self.tree.node_index[best[1]]
        return best, self._cached_actions(node, best[0])

    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #
    def _greedy_warm_start(self) -> dict | None:
        """Build one feasible assignment greedily to seed a tight upper bound.

        Always picks the first (canonically best) live action of the MRV
        variable.  It never affects completeness: the exhaustive DFS still
        explores every alternative afterwards and replaces the seed if better.
        """
        depth = 0
        while True:
            target, actions = self._select_target()
            if target is None:
                snap = {
                    "node_visit_cp": {k: dict(v) for k, v in self.node_visit_cp.items()},
                    "leaf_insp_cps": {lid: {i: set(cps) for i, cps in d.items()} for lid, d in self.leaf_insp_cps.items()},
                    "node_pairs": {k: dict(v) for k, v in self.node_pairs.items()},
                    "waypoints": {lid: {i: list(lst) for i, lst in per.items()} for lid, per in self.waypoints.items()},
                    "covered": {lid: set(s) for lid, s in self.covered.items()},
                    "new_registry": {k: set(v) for k, v in self.new_registry.items()},
                }
                for _ in range(depth):
                    self._undo()
                return snap
            if not actions:
                for _ in range(depth):
                    self._undo()
                return None
            self._apply(actions[0])
            depth += 1

    def solve(self) -> SolveResult | None:
        """Exact lexicographic optimum in two exhaustive phases.

        Phase 1 finds the minimum achievable max-new-visit count with a capped
        feasibility search (the cap starts at the root lower bound, so only
        attainable caps are ever explored).  Phase 2 fixes that cap and runs a
        single branch-and-bound that minimises movement cost, then breaks ties
        by the canonical evidence sequence.  Both phases enumerate every value
        consistent with their cap, so the composition is the exact lexicographic
        optimum; no feasible plan is excluded.
        """
        self._init_state()
        seed = self._greedy_warm_start()
        if seed is None:
            return None
        _, _, seed_max_new, seed_cost = self._snap_objectives(seed)

        def snapshot():
            return {
                "node_visit_cp": {k: dict(v) for k, v in self.node_visit_cp.items()},
                "leaf_insp_cps": {lid: {i: set(cps) for i, cps in d.items()} for lid, d in self.leaf_insp_cps.items()},
                "node_pairs": {k: dict(v) for k, v in self.node_pairs.items()},
                "waypoints": {lid: {i: list(lst) for i, lst in per.items()} for lid, per in self.waypoints.items()},
                "covered": {lid: set(s) for lid, s in self.covered.items()},
                "new_registry": {k: set(v) for k, v in self.new_registry.items()},
            }

        def signature():
            # Constraint-relevant occupancy only.  Movement waypoints are a
            # deterministic function of these occupied visits plus the immutable
            # frozen waypoints, so including them would only split otherwise
            # equivalent states and weaken domination pruning.
            covered_part = tuple(
                (lid, tuple(sorted(self.covered[lid]))) for lid in sorted(self.covered)
            )
            visit_part = tuple(
                (nid, tuple(sorted(self.node_visit_cp[nid].items())))
                for nid in sorted(self.node_visit_cp) if self.node_visit_cp[nid]
            )
            reuse_part = tuple(
                (lid, tuple(sorted((i, tuple(sorted(cps))) for i, cps in d.items())))
                for lid, d in sorted(self.leaf_insp_cps.items()) if d
            )
            return (covered_part, visit_part, reuse_part)

        # ---- Phase 1: feasibility DFS under a hard new-visit cap. ----------
        def feasibility_dfs(cap_new: int):
            depth = [0]

            def dfs() -> bool:
                target, actions, new_lb = self._analyse()
                if new_lb >= INF or new_lb > cap_new:
                    return False
                if target is None:
                    return True  # every window covered and no dead domain
                if self._current_bounds()[0] > cap_new:
                    return False
                for action in actions:
                    self._apply(action)
                    depth[0] += 1
                    if self._current_bounds()[0] <= cap_new and dfs():
                        return True
                    self._undo()
                    depth[0] -= 1
                return False

            ok = dfs()
            for _ in range(depth[0]):
                self._undo()
            return ok

        self._init_state()
        _, _, root_new_lb = self._analyse()
        if root_new_lb >= INF:
            return None
        opt_new = None
        for cap in range(root_new_lb, seed_max_new + 1):
            self._init_state()
            if feasibility_dfs(cap):
                opt_new = cap
                break
        if opt_new is None:
            return None

        # ---- Phase 2: B&B on (cost, canonical sequence) under the cap. -----
        # One tree traversal; each complete leaf tightens the incumbent, which
        # then prunes every sibling whose cost lower bound already exceeds it.
        best = {"snap": None, "cost": INF, "seq": None}

        def cost_dfs() -> None:
            target, actions, new_lb = self._analyse()
            if new_lb >= INF or new_lb > opt_new:
                return
            if target is None:
                snap = snapshot()
                _, _, max_new, total_cost = self._snap_objectives(snap)
                if max_new > opt_new:
                    return
                seq = self._sequence_key_snap(snap, max_new, total_cost)
                if best["snap"] is None or (total_cost, seq[2]) < (best["cost"], best["seq"][2]):
                    best["snap"] = snap
                    best["cost"] = total_cost
                    best["seq"] = seq
                return

            cur_max, cur_cost = self._current_bounds()
            if cur_max > opt_new:
                return
            if best["snap"] is not None and cur_cost > best["cost"]:
                return  # monotone cost lower bound cannot recover
            memo_sig = signature()
            prev = cost_memo.get(memo_sig)
            if prev is not None and prev <= cur_cost:
                return
            cost_memo[memo_sig] = cur_cost

            for action in actions:
                self._apply(action)
                lb_max, lb_cost = self._current_bounds()
                if lb_max <= opt_new and not (best["snap"] is not None and lb_cost > best["cost"]):
                    cost_dfs()
                self._undo()

        # Seed phase 2 with a greedy plan that respects the new-visit cap.
        # _greedy_warm_start returns its snapshot *and* leaves the state empty
        # (all actions undone), so the returned object is the only valid seed.
        cost_memo: dict = {}
        self._init_state()
        greedy_snap = self._greedy_warm_start()
        if greedy_snap is not None:
            _, _, mn, tc = self._snap_objectives(greedy_snap)
            if mn <= opt_new:
                best["snap"], best["cost"], best["seq"] = (
                    greedy_snap, tc, self._sequence_key_snap(greedy_snap, mn, tc)
                )
        self._init_state()
        cost_dfs()
        if best["snap"] is None:
            return None

        self._init_state()
        final_snap = best["snap"]
        incumbent = {"snap": final_snap, "seq": self._sequence_key_snap(
            final_snap, *self._snap_objectives(final_snap)[2:])}
        return self._build_result(incumbent)

    def _snap_objectives(self, snap):
        news, costs = {}, {}
        for leaf in self.tree.leaves:
            lid = leaf.scenario_id
            news[lid] = sum(len(snap["new_registry"][nid]) for nid in leaf.node_ids)
            total = 0
            for iid in self.case.inspector_ids:
                if iid in leaf.absent:
                    continue
                per = snap["waypoints"][lid].get(iid, [])
                c = waypoint_cost(self.table, per, self.case.inspectors[iid].initial)
                if c >= INF:
                    total = INF
                    break
                total += c
            costs[lid] = total
        return news, costs, max(news.values()), sum(costs.values())

    def _sequence_key_snap(self, snap, max_new: int, total_cost: int):
        plan_lists = []
        for leaf in self.tree.leaves:
            records = []
            for nid in leaf.node_ids:
                cp_of = snap["node_visit_cp"][nid]
                for wid, pair in sorted(snap["node_pairs"][nid].items()):
                    for inspector, slot in pair:
                        records.append((slot, inspector, cp_of[(inspector, slot)], wid))
            records.sort()
            plan_lists.append((leaf.scenario_id, tuple(records)))
        return (max_new, total_cost, tuple(plan_lists))

    def _build_result(self, incumbent) -> SolveResult:
        snap = incumbent["snap"]
        news, costs, max_new, total_cost = self._snap_objectives(snap)
        evidence, tracks = {}, {}
        for leaf in self.tree.leaves:
            lid = leaf.scenario_id
            records = []
            for nid in leaf.node_ids:
                cp_of = snap["node_visit_cp"][nid]
                for wid, pair in snap["node_pairs"][nid].items():
                    for inspector, slot in pair:
                        records.append((slot, inspector, cp_of[(inspector, slot)], wid))
            records.sort()
            evidence[lid] = records
            tracks[lid] = {}
            for iid in self.case.inspector_ids:
                if iid in leaf.absent:
                    continue
                per = snap["waypoints"][lid].get(iid, [])
                tracks[lid][iid] = reconstruct_track(
                    self.table, per, self.case.inspectors[iid].initial, self.T
                )
        return SolveResult(
            feasible=True,
            evidence=evidence,
            waypoints=snap["waypoints"],
            tracks=tracks,
            new_visits=news,
            costs=costs,
            max_new=max_new,
            total_cost=total_cost,
            new_visit_registry=snap["new_registry"],
            tree=self.tree,
            table=self.table,
        )
