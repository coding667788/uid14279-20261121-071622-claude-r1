"""Exact-step reachability and shortest movement cost.

Idle means keeping the current position, modelled as an implicit zero-cost
self-loop on every node (including initial-position-only nodes that are not
checkpoints).  Costs are computed with a min-plus DP so the cost of going from
``a`` to ``b`` in *exactly* ``d`` slot transitions is available in O(1).
This is what makes a locally reachable but chaining-impossible transition
visible: ``dist[d][a][b] == INF`` means no length-d walk exists.

Predecessors are kept for deterministic reconstruction: ties are broken by
node id, hence the same logical input always yields the same plan.
"""

from __future__ import annotations

from dataclasses import dataclass

INF = 10**15


@dataclass
class ExactPathTable:
    nodes: list[str]
    index: dict[str, int]
    # dist[d][i][j]: minimum cost of an exact d-step walk i -> j.
    dist: list[list[list[int]]]
    # pred[d][i][j]: node reached after the FIRST step of the chosen shortest
    # exact-d walk from i to j.
    pred: list[list[list[int]]]
    # one-step neighbour lists per node index, in deterministic order.
    adjacency: list[list[tuple[int, int]]]
    max_steps: int

    def cost(self, steps: int, src: str, dst: str) -> int:
        v = self.dist[steps][self.index[src]][self.index[dst]]
        return INF if v >= INF else v

    def feasible(self, steps: int, src: str, dst: str) -> bool:
        return self.cost(steps, src, dst) < INF

    def _segment(self, src_idx: int, dst_idx: int, steps: int) -> list[int]:
        """Node indices visited after each of the ``steps`` transitions.

        Runs a dedicated forward DP for this single segment and backtracks
        the per-step predecessor, so the chain never crosses between two
        different source problems (the source stays fixed within a segment).
        """
        if steps == 0:
            return []
        n = len(self.nodes)
        dmat = [[INF] * n for _ in range(steps + 1)]
        pmat = [[-1] * n for _ in range(steps + 1)]
        dmat[0][src_idx] = 0
        for d in range(1, steps + 1):
            for u in range(n):
                base = dmat[d - 1][u]
                if base >= INF:
                    continue
                for v, ec in self.adjacency[u]:
                    cand = base + ec
                    if cand < dmat[d][v]:
                        dmat[d][v] = cand
                        pmat[d][v] = u
        if dmat[steps][dst_idx] >= INF:
            raise ValueError("no exact-step walk for segment")
        chain = [dst_idx]
        for d in range(steps, 0, -1):
            chain.append(pmat[d][chain[-1]])
        chain.reverse()  # src, step1, ..., dst
        return chain[1:]

    def reconstruct(self, steps: int, src: str, dst: str) -> list[str]:
        """Deterministic exact-step walk; nodes after each transition."""
        i, j = self.index[src], self.index[dst]
        if self.dist[steps][i][j] >= INF:
            raise ValueError(f"no exact-{steps} walk from {src} to {dst}")
        return [self.nodes[k] for k in self._segment(i, j, steps)]


def build_path_table(nodes: frozenset[str], edges, max_steps: int) -> ExactPathTable:
    node_list = sorted(nodes)
    index = {n: k for k, n in enumerate(node_list)}
    n = len(node_list)

    # Adjacency with implicit zero-cost self loops.  Explicit edges with the
    # same endpoints are deduplicated; costs are non-negative so the implicit
    # loop wins self-loop ties at zero.
    adj: list[dict[int, int]] = [dict() for _ in range(n)]
    for k in range(n):
        adj[k][k] = 0
    for e in edges:
        a, b = index[e.src], index[e.dst]
        old = adj[a].get(b)
        if old is None or e.cost < old:
            adj[a][b] = e.cost
    adj_list: list[list[tuple[int, int]]] = [
        sorted(d.items(), key=lambda t: (node_list[t[0]], t[1])) for d in adj
    ]

    # d = 0: identity.
    dist0 = [[INF] * n for _ in range(n)]
    pred0 = [[-1] * n for _ in range(n)]
    for i in range(n):
        dist0[i][i] = 0
        pred0[i][i] = i
    dist = [dist0]
    pred = [pred0]

    for _d in range(1, max_steps + 1):
        prev = dist[-1]
        dmat = [[INF] * n for _ in range(n)]
        pmat = [[-1] * n for _ in range(n)]
        for u in range(n):
            row, prow = dmat[u], pmat[u]
            for mid, ec in adj_list[u]:
                pv = prev[mid]
                for v in range(n):
                    cand = ec + pv[v]
                    if cand < row[v]:
                        row[v] = cand
                        prow[v] = mid
        dist.append(dmat)
        pred.append(pmat)

    return ExactPathTable(node_list, index, dist, pred, adj_list, max_steps)


def waypoint_cost(table: ExactPathTable, waypoints: list[tuple[int, str]], initial: str) -> int:
    """Minimum exact-step cost of a track pinned at given (slot, node) pairs.

    ``waypoints`` need not be sorted; the initial position is slot 0.
    Returns INF when some segment admits no exact-step walk.
    """
    pts = sorted(waypoints)
    total = 0
    prev_slot, prev_node = 0, initial
    for slot, node in pts:
        c = table.cost(slot - prev_slot, prev_node, node)
        if c >= INF:
            return INF
        total += c
        prev_slot, prev_node = slot, node
    return total


def reconstruct_track(
    table: ExactPathTable,
    waypoints: list[tuple[int, str]],
    initial: str,
    slot_count: int,
) -> list[str]:
    """Build a full deterministic position-per-slot track from waypoints."""
    pts = sorted(waypoints)
    track: list[str] = []
    prev_slot, prev_node = 0, initial
    for slot, node in pts:
        track.extend(table.reconstruct(slot - prev_slot, prev_node, node))
        prev_slot, prev_node = slot, node
    if prev_slot < slot_count:
        track.extend(table.reconstruct(slot_count - prev_slot, prev_node, prev_node))
    return track
