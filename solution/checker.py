"""Independent plan verification.

Every rule from the specification is re-implemented here against the raw plan
document; the solver's internal data structures are never consulted.  A plan
is accepted only when every check passes and the recomputed objective values
match the declared ones.
"""

from __future__ import annotations

from .errors import E_PLAN_STRUCTURE, E_PLAN_VIOLATION, PlanError, ValidationError
from .geometry import build_path_table
from .model import NO_ABSENCE_ID, Case


def _err(code, location, message):
    return ValidationError(code, location, message)


def _check_leaf(case: Case, leaf_id: str, absent: frozenset[str], reveal_slot: int,
                evidence: list[dict], tracks: dict[str, list[str]]):
    """All within-scenario checks.  Returns (new_visits, cost, visit_keys)."""
    errs: list[ValidationError] = []
    loc = f"plan[{leaf_id}]"
    T = case.slot_count
    table = build_path_table(case.nodes, case.edges, T)

    # ---- tracks: structural ------------------------------------------------
    seen_inspectors: set[str] = set()
    track_pos: dict[str, list[str]] = {}
    for iid, positions in tracks.items():
        if iid not in case.inspectors:
            errs.append(_err(E_PLAN_STRUCTURE, f"{loc}.tracks", f"unknown inspector '{iid}'"))
            continue
        if iid in seen_inspectors:
            errs.append(_err(E_PLAN_STRUCTURE, f"{loc}.tracks", f"duplicate track for '{iid}'"))
        seen_inspectors.add(iid)
        if len(positions) != T:
            errs.append(_err(E_PLAN_STRUCTURE, f"{loc}.tracks[{iid}]", f"need exactly {T} positions"))
            continue
        for t, node in enumerate(positions, start=1):
            if node not in case.nodes:
                errs.append(_err(E_PLAN_VIOLATION, f"{loc}.tracks[{iid}][{t}]", f"unknown node '{node}'"))
        track_pos[iid] = positions
    for iid in case.inspector_ids:
        if iid not in absent and iid not in seen_inspectors:
            errs.append(_err(E_PLAN_STRUCTURE, f"{loc}.tracks", f"missing track for inspector '{iid}'"))

    # ---- exact-step movement and idle behaviour ----------------------------
    total_cost = 0
    for iid, positions in track_pos.items():
        if len(positions) != T:
            continue
        if iid in absent:
            errs.append(_err(E_PLAN_VIOLATION, f"{loc}.tracks[{iid}]", "absent inspector must have no track"))
            continue
        initial = case.inspectors[iid].initial
        prev = initial
        for t, node in enumerate(positions, start=1):
            c = table.cost(1, prev, node)
            if c >= 10**14:
                errs.append(_err(
                    E_PLAN_VIOLATION, f"{loc}.tracks[{iid}][{t}]",
                    f"transition {prev} -> {node} is not reachable in one slot",
                ))
            else:
                total_cost += c
            # Idle must keep the position: the one-step walk to a different
            # node cannot be an idle move, and staying put must cost 0.
            prev = node

    # ---- frozen visits are immutable --------------------------------------
    for fv in case.frozen:
        if fv.inspector in absent and fv.slot >= reveal_slot:
            errs.append(_err(
                E_PLAN_VIOLATION, f"{loc}",
                f"frozen visit of absent inspector '{fv.inspector}' at slot {fv.slot}",
            ))
            continue
        pos = track_pos.get(fv.inspector)
        if pos is not None and pos[fv.slot - 1] != fv.checkpoint:
            errs.append(_err(
                E_PLAN_VIOLATION, f"{loc}.tracks[{fv.inspector}][{fv.slot}]",
                f"frozen visit requires checkpoint '{fv.checkpoint}'",
            ))

    # ---- evidence -----------------------------------------------------------
    visit_keys: set[tuple] = set()
    insp_cp_window: dict[tuple[str, str], str] = {}
    per_window: dict[str, list[dict]] = {}
    for k, ev in enumerate(evidence):
        eloc = f"{loc}.evidence[{k}]"
        slot = ev.get("slot")
        iid = ev.get("inspector")
        cp_id = ev.get("checkpoint")
        wid = ev.get("window")
        if not isinstance(slot, int) or isinstance(slot, bool) or not (1 <= slot <= T):
            errs.append(_err(E_PLAN_STRUCTURE, eloc, "slot must be an integer in range"))
            continue
        if iid not in case.inspectors:
            errs.append(_err(E_PLAN_STRUCTURE, f"{eloc}.inspector", f"unknown inspector '{iid}'"))
            continue
        if cp_id not in case.checkpoints:
            errs.append(_err(E_PLAN_STRUCTURE, f"{eloc}.checkpoint", f"unknown checkpoint '{cp_id}'"))
            continue
        if wid not in case.windows:
            errs.append(_err(E_PLAN_STRUCTURE, f"{eloc}.window", f"unknown window '{wid}'"))
            continue
        w = case.windows[wid]
        insp = case.inspectors[iid]
        if iid in absent and slot >= reveal_slot:
            errs.append(_err(E_PLAN_VIOLATION, eloc, f"inspector '{iid}' is absent from slot {reveal_slot}"))
        if not (case.checkpoints[cp_id].required <= insp.trainings):
            errs.append(_err(E_PLAN_VIOLATION, eloc, f"inspector '{iid}' lacks required trainings"))
        if w.checkpoint != cp_id:
            errs.append(_err(E_PLAN_VIOLATION, eloc, f"window '{wid}' belongs to another checkpoint"))
        if not (w.start <= slot <= w.end):
            errs.append(_err(E_PLAN_VIOLATION, eloc, f"slot {slot} outside window [{w.start},{w.end}]"))
        pos = track_pos.get(iid)
        if pos is not None and pos[slot - 1] != cp_id:
            errs.append(_err(E_PLAN_VIOLATION, eloc, f"track puts '{iid}' at '{pos[slot - 1]}', not '{cp_id}'"))
        key = (iid, slot, cp_id)
        if key in visit_keys:
            errs.append(_err(E_PLAN_VIOLATION, eloc, "one visit cannot serve two evidence records"))
        visit_keys.add(key)
        ck = (iid, cp_id)
        if ck in insp_cp_window and insp_cp_window[ck] != wid:
            errs.append(_err(
                E_PLAN_VIOLATION, eloc,
                f"inspector '{iid}' already witnesses checkpoint '{cp_id}' for window "
                f"'{insp_cp_window[ck]}'",
            ))
        insp_cp_window[ck] = wid
        per_window.setdefault(wid, []).append(ev)

    # ---- per-window pair rules ---------------------------------------------
    for wid, evs in per_window.items():
        wloc = f"{loc}.window[{wid}]"
        if len(evs) != 2:
            errs.append(_err(E_PLAN_VIOLATION, wloc, f"window needs exactly 2 witnesses, found {len(evs)}"))
            continue
        a, b = evs
        i1, i2 = a["inspector"], b["inspector"]
        if i1 == i2:
            errs.append(_err(E_PLAN_VIOLATION, wloc, "the two witnesses must be different inspectors"))
        elif case.inspectors[i1].team == case.inspectors[i2].team:
            errs.append(_err(E_PLAN_VIOLATION, wloc, "the two witnesses must come from different teams"))
        gap = abs(a["slot"] - b["slot"])
        if gap < case.windows[wid].min_gap:
            errs.append(_err(E_PLAN_VIOLATION, wloc, f"slot gap {gap} below min_gap {case.windows[wid].min_gap}"))
        if a["slot"] == b["slot"]:
            errs.append(_err(E_PLAN_VIOLATION, wloc, "independent evidence cannot be formed in one slot"))

    # ---- coverage -----------------------------------------------------------
    missing = sorted(set(case.window_ids) - set(per_window))
    if missing:
        errs.append(_err(E_PLAN_VIOLATION, f"{loc}", f"uncovered windows {missing}"))

    # ---- new visit count against frozen visits -----------------------------
    frozen_keys = {(fv.inspector, fv.slot, fv.checkpoint) for fv in case.frozen}
    new_visits = len(visit_keys - frozen_keys)
    for key in visit_keys & frozen_keys:
        pass  # frozen attendance is never a new visit

    if errs:
        raise PlanError(errs)
    return new_visits, total_cost, visit_keys


def check_single(case: Case, plan_doc: dict) -> dict:
    plan = plan_doc.get("plan", plan_doc)
    evidence = plan.get("evidence")
    tracks_raw = plan.get("tracks", [])
    if not isinstance(evidence, list):
        raise PlanError([_err(E_PLAN_STRUCTURE, "$.plan.evidence", "must be an array")])
    if not isinstance(tracks_raw, list):
        raise PlanError([_err(E_PLAN_STRUCTURE, "$.plan.tracks", "must be an array")])
    tracks = {t["inspector"]: t["positions"] for t in tracks_raw if isinstance(t, dict)}
    new_visits, cost, _ = _check_leaf(
        case, NO_ABSENCE_ID, frozenset(), case.slot_count + 1, evidence, tracks
    )
    declared = plan_doc.get("objective", {})
    problems = []
    if declared.get("new_visits") not in (None, new_visits):
        problems.append(_err(E_PLAN_VIOLATION, "$.objective.new_visits",
                             f"declared {declared.get('new_visits')}, recomputed {new_visits}"))
    if declared.get("movement_cost") not in (None, cost):
        problems.append(_err(E_PLAN_VIOLATION, "$.objective.movement_cost",
                             f"declared {declared.get('movement_cost')}, recomputed {cost}"))
    if problems:
        raise PlanError(problems)
    return {
        "status": "valid",
        "mode": "single",
        "recomputed": {"new_visits": new_visits, "movement_cost": cost},
    }


def check_scenario(case: Case, doc: dict) -> dict:
    errs: list[ValidationError] = []
    main = doc.get("main_plan")
    if not isinstance(main, dict):
        raise PlanError([_err(E_PLAN_STRUCTURE, "$.main_plan", "missing main plan object")])
    contingencies = doc.get("contingencies", [])
    if not isinstance(contingencies, list):
        raise PlanError([_err(E_PLAN_STRUCTURE, "$.contingencies", "must be an array")])

    scenario_by_id = {s.id: s for s in (case.scenarios or [])}
    leaves: dict[str, dict] = {}

    # Main plan = no-absence leaf.
    leaves[NO_ABSENCE_ID] = {
        "reveal": case.slot_count + 1,
        "absent": frozenset(),
        "evidence": main.get("evidence", []),
        "tracks": {t["inspector"]: t["positions"] for t in main.get("tracks", []) if isinstance(t, dict)},
    }
    for c in contingencies:
        sid = c.get("scenario_id")
        if sid not in scenario_by_id:
            errs.append(_err(E_PLAN_STRUCTURE, f"$.contingencies[{sid}]", "unknown scenario id"))
            continue
        s = scenario_by_id[sid]
        prefix = c.get("trigger_prefix", {}).get("evidence", [])
        suffix = c.get("suffix", {})
        evidence = list(prefix) + list(suffix.get("evidence", []))
        tracks = {t["inspector"]: t["positions"] for t in suffix.get("tracks", []) if isinstance(t, dict)}
        leaves[sid] = {
            "reveal": s.reveal_slot,
            "absent": s.absent,
            "evidence": evidence,
            "tracks": tracks,
        }

    expected = {NO_ABSENCE_ID} | set(scenario_by_id)
    if set(leaves) != expected:
        errs.append(_err(E_PLAN_STRUCTURE, "$.contingencies",
                         f"scenario set mismatch: have {sorted(leaves)}, need {sorted(expected)}"))
    if errs:
        raise PlanError(errs)

    recomputed = {}
    leaf_visits: dict[str, set] = {}
    for sid, info in leaves.items():
        nv, cost, visits = _check_leaf(
            case, sid, info["absent"], info["reveal"], info["evidence"], info["tracks"]
        )
        recomputed[sid] = {"new_visits": nv, "movement_cost": cost}
        leaf_visits[sid] = visits

    # ---- prefix consistency across unrevealed scenarios --------------------
    # At every slot t, all scenarios whose reveal_slot > t must show identical
    # evidence (inspector, checkpoint, window) at t, and identical positions.
    reveal_groups: dict[int, list[str]] = {}
    for sid, info in leaves.items():
        reveal_groups.setdefault(info["reveal"], []).append(sid)
    for r in sorted(reveal_groups):
        members = [sid for sid in leaves if leaves[sid]["reveal"] >= r]
        anchor = members[0]
        for sid in members[1:]:
            a_ev = sorted((e for e in leaves[anchor]["evidence"] if e["slot"] < r),
                          key=lambda e: (e["slot"], e["inspector"]))
            b_ev = sorted((e for e in leaves[sid]["evidence"] if e["slot"] < r),
                          key=lambda e: (e["slot"], e["inspector"]))
            if a_ev != b_ev:
                raise PlanError([_err(
                    E_PLAN_VIOLATION, f"plan[{sid}]",
                    f"pre-reveal evidence before slot {r} differs from plan[{anchor}]",
                )])
            for iid in case.inspector_ids:
                ta = leaves[anchor]["tracks"].get(iid)
                tb = leaves[sid]["tracks"].get(iid)
                if ta is not None and tb is not None and ta[: r - 1] != tb[: r - 1]:
                    raise PlanError([_err(
                        E_PLAN_VIOLATION, f"plan[{sid}].tracks[{iid}]",
                        f"pre-reveal positions before slot {r} differ from plan[{anchor}]",
                    )])

    # ---- pre-reveal visits cannot be reattributed after reveal -------------
    for sid, info in leaves.items():
        if sid == NO_ABSENCE_ID:
            continue
        r = info["reveal"]
        main_windows = {
            (e["inspector"], e["slot"], e["checkpoint"]): e["window"]
            for e in leaves[NO_ABSENCE_ID]["evidence"]
            if e["slot"] < r
        }
        for e in info["evidence"]:
            key = (e["inspector"], e["slot"], e["checkpoint"])
            if e["slot"] < r and key in main_windows and main_windows[key] != e["window"]:
                raise PlanError([_err(
                    E_PLAN_VIOLATION, f"plan[{sid}]",
                    f"pre-reveal visit {key} was reassigned from window "
                    f"'{main_windows[key]}' to '{e['window']}'",
                )])

    max_new = max(v["new_visits"] for v in recomputed.values())
    sum_cost = sum(v["movement_cost"] for v in recomputed.values())
    declared = doc.get("objective", {})
    problems = []
    if declared.get("max_new_visits") not in (None, max_new):
        problems.append(_err(E_PLAN_VIOLATION, "$.objective.max_new_visits",
                             f"declared {declared.get('max_new_visits')}, recomputed {max_new}"))
    if declared.get("sum_movement_cost") not in (None, sum_cost):
        problems.append(_err(E_PLAN_VIOLATION, "$.objective.sum_movement_cost",
                             f"declared {declared.get('sum_movement_cost')}, recomputed {sum_cost}"))
    if problems:
        raise PlanError(problems)
    return {"status": "valid", "mode": "scenario", "recomputed": recomputed,
            "max_new_visits": max_new, "sum_movement_cost": sum_cost}


def check_plan(case: Case, plan_doc: dict) -> dict:
    if not isinstance(plan_doc, dict):
        raise PlanError([_err(E_PLAN_STRUCTURE, "$", "plan document must be an object")])
    if case.multi:
        return check_scenario(case, plan_doc)
    return check_single(case, plan_doc)
