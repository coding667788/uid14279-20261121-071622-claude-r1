"""Input model, parsing and structural validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .errors import (
    E_DUPLICATE_ID,
    E_FIELD_TYPE,
    E_INCONSISTENT,
    E_REQUIRED,
    E_ROOT_TYPE,
    E_UNKNOWN_REF,
    E_VALUE_RANGE,
    InputError,
    ValidationError,
)

NO_ABSENCE_ID = "s0"  # reserved id of the implicit no-absence scenario


@dataclass(frozen=True)
class Inspector:
    id: str
    team: str
    trainings: frozenset[str]
    initial: str


@dataclass(frozen=True)
class Checkpoint:
    id: str
    required: frozenset[str]


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    cost: int


@dataclass(frozen=True)
class Window:
    id: str
    checkpoint: str
    start: int
    end: int
    min_gap: int


@dataclass(frozen=True)
class FrozenVisit:
    inspector: str
    slot: int
    checkpoint: str
    window: str | None


@dataclass(frozen=True)
class Scenario:
    id: str
    reveal_slot: int
    absent: frozenset[str]


@dataclass
class Case:
    case_id: str
    slot_count: int
    inspectors: dict[str, Inspector]
    inspector_ids: list[str]
    checkpoints: dict[str, Checkpoint]
    checkpoint_ids: list[str]
    nodes: frozenset[str]
    edges: list[Edge]
    windows: dict[str, Window]
    window_ids: list[str]
    frozen: list[FrozenVisit]
    scenarios: list[Scenario] | None  # None => single-scenario mode

    @property
    def multi(self) -> bool:
        return self.scenarios is not None


# --------------------------------------------------------------------------- #
#  Validation helpers
# --------------------------------------------------------------------------- #


def _is_str(x) -> bool:
    return isinstance(x, str)


def _is_int(x) -> bool:
    # bool is a subclass of int; reject it explicitly.
    return isinstance(x, int) and not isinstance(x, bool)


def _require(errs, raw, key, loc, typ, *, nonempty=False):
    if not isinstance(raw, dict) or key not in raw:
        errs.append(ValidationError(E_REQUIRED, loc, f"missing required field '{key}'"))
        return False
    val = raw[key]
    ok = isinstance(val, typ)
    if typ is int:
        ok = _is_int(val)
    if ok and nonempty and (val == "" or val == [] or val == {}):
        ok = False
    if not ok:
        want = typ.__name__ if not isinstance(typ, tuple) else "/".join(t.__name__ for t in typ)
        errs.append(ValidationError(E_FIELD_TYPE, loc, f"field '{key}' must be {want}"))
        return False
    return True


def _str_list(errs, val, loc) -> list[str] | None:
    if not isinstance(val, list):
        errs.append(ValidationError(E_FIELD_TYPE, loc, "must be an array of strings"))
        return None
    out = []
    for i, item in enumerate(val):
        if not _is_str(item):
            errs.append(ValidationError(E_FIELD_TYPE, f"{loc}[{i}]", "must be a string"))
        else:
            out.append(item)
    return out


def _unique(errs, ids, loc):
    seen: set[str] = set()
    dups: set[str] = set()
    for x in ids:
        if x in seen:
            dups.add(x)
        seen.add(x)
    for d in sorted(dups):
        errs.append(ValidationError(E_DUPLICATE_ID, loc, f"duplicate id '{d}'"))


def load_case(raw) -> Case:
    errs: list[ValidationError] = []
    if not isinstance(raw, dict):
        raise InputError([ValidationError(E_ROOT_TYPE, "$", "top-level document must be a JSON object")])

    case_id = "case"
    if "case_id" in raw:
        if _is_str(raw["case_id"]):
            case_id = raw["case_id"]
        else:
            errs.append(ValidationError(E_FIELD_TYPE, "$.case_id", "must be a string"))

    if not _require(errs, raw, "slot_count", "$", int):
        raise InputError(errs)
    T = raw["slot_count"]
    if T < 1:
        errs.append(ValidationError(E_VALUE_RANGE, "$.slot_count", "must be >= 1"))
        raise InputError(errs)

    inspectors: dict[str, Inspector] = {}
    inspector_ids: list[str] = []
    if not _require(errs, raw, "inspectors", "$", list):
        raise InputError(errs)
    for i, item in enumerate(raw["inspectors"]):
        loc = f"$.inspectors[{i}]"
        if not isinstance(item, dict):
            errs.append(ValidationError(E_FIELD_TYPE, loc, "must be an object"))
            continue
        if not _require(errs, item, "id", loc, str):
            continue
        iid = item["id"]
        team = item.get("team", "")
        if not _is_str(team):
            errs.append(ValidationError(E_FIELD_TYPE, f"{loc}.team", "must be a string"))
            team = ""
        trainings = frozenset()
        if "trainings" in item:
            tl = _str_list(errs, item["trainings"], f"{loc}.trainings")
            if tl is not None:
                trainings = frozenset(tl)
        if not _require(errs, item, "initial", loc, str):
            continue
        if iid in inspectors:
            errs.append(ValidationError(E_DUPLICATE_ID, loc, f"duplicate inspector id '{iid}'"))
            continue
        inspector_ids.append(iid)
        inspectors[iid] = Inspector(iid, team, trainings, item["initial"])

    checkpoints: dict[str, Checkpoint] = {}
    checkpoint_ids: list[str] = []
    if not _require(errs, raw, "checkpoints", "$", list):
        raise InputError(errs)
    for i, item in enumerate(raw["checkpoints"]):
        loc = f"$.checkpoints[{i}]"
        if not isinstance(item, dict):
            errs.append(ValidationError(E_FIELD_TYPE, loc, "must be an object"))
            continue
        if not _require(errs, item, "id", loc, str):
            continue
        cid = item["id"]
        required = frozenset()
        if "required_trainings" in item:
            rl = _str_list(errs, item["required_trainings"], f"{loc}.required_trainings")
            if rl is not None:
                required = frozenset(rl)
        if cid in checkpoints:
            errs.append(ValidationError(E_DUPLICATE_ID, loc, f"duplicate checkpoint id '{cid}'"))
            continue
        checkpoint_ids.append(cid)
        checkpoints[cid] = Checkpoint(cid, required)

    nodes: set[str] = set(checkpoint_ids)
    for insp in inspectors.values():
        nodes.add(insp.initial)

    edges: list[Edge] = []
    if not _require(errs, raw, "edges", "$", list):
        raise InputError(errs)
    edge_pairs: set[tuple[str, str]] = set()
    for i, item in enumerate(raw["edges"]):
        loc = f"$.edges[{i}]"
        if not isinstance(item, dict):
            errs.append(ValidationError(E_FIELD_TYPE, loc, "must be an object"))
            continue
        ok = (
            _require(errs, item, "src", loc, str)
            and _require(errs, item, "dst", loc, str)
            and _require(errs, item, "cost", loc, int)
        )
        if not ok:
            continue
        src, dst, cost = item["src"], item["dst"], item["cost"]
        if cost < 0:
            errs.append(ValidationError(E_VALUE_RANGE, f"{loc}.cost", "movement cost must be >= 0"))
        if src not in nodes:
            errs.append(ValidationError(E_UNKNOWN_REF, f"{loc}.src", f"unknown node '{src}'"))
        if dst not in nodes:
            errs.append(ValidationError(E_UNKNOWN_REF, f"{loc}.dst", f"unknown node '{dst}'"))
        if (src, dst) in edge_pairs:
            errs.append(ValidationError(E_DUPLICATE_ID, loc, f"duplicate edge {src}->{dst}"))
        edge_pairs.add((src, dst))
        edges.append(Edge(src, dst, cost))

    windows: dict[str, Window] = {}
    window_ids: list[str] = []
    if not _require(errs, raw, "windows", "$", list):
        raise InputError(errs)
    for i, item in enumerate(raw["windows"]):
        loc = f"$.windows[{i}]"
        if not isinstance(item, dict):
            errs.append(ValidationError(E_FIELD_TYPE, loc, "must be an object"))
            continue
        if not _require(errs, item, "id", loc, str):
            continue
        wid = item["id"]
        if not _require(errs, item, "checkpoint", loc, str):
            continue
        cpid = item["checkpoint"]
        if cpid not in checkpoints:
            errs.append(ValidationError(E_UNKNOWN_REF, f"{loc}.checkpoint", f"unknown checkpoint '{cpid}'"))
        ok = (
            _require(errs, item, "start_slot", loc, int)
            and _require(errs, item, "end_slot", loc, int)
        )
        start = item.get("start_slot")
        end = item.get("end_slot")
        if ok and not (1 <= start <= end <= T):
            errs.append(
                ValidationError(E_VALUE_RANGE, f"{loc}", f"window slots must satisfy 1 <= start <= end <= {T}")
            )
        min_gap = 1
        if "min_gap" in item:
            if _is_int(item["min_gap"]) and item["min_gap"] >= 1:
                min_gap = item["min_gap"]
            else:
                errs.append(ValidationError(E_VALUE_RANGE, f"{loc}.min_gap", "must be an integer >= 1"))
        if wid in windows:
            errs.append(ValidationError(E_DUPLICATE_ID, loc, f"duplicate window id '{wid}'"))
            continue
        window_ids.append(wid)
        windows[wid] = Window(wid, cpid, start if _is_int(start) else 1, end if _is_int(end) else 1, min_gap)

    frozen: list[FrozenVisit] = []
    if "frozen_visits" in raw:
        if not isinstance(raw["frozen_visits"], list):
            errs.append(ValidationError(E_FIELD_TYPE, "$.frozen_visits", "must be an array"))
        else:
            frozen_slots: set[tuple[str, int]] = set()
            for i, item in enumerate(raw["frozen_visits"]):
                loc = f"$.frozen_visits[{i}]"
                if not isinstance(item, dict):
                    errs.append(ValidationError(E_FIELD_TYPE, loc, "must be an object"))
                    continue
                ok = (
                    _require(errs, item, "inspector", loc, str)
                    and _require(errs, item, "slot", loc, int)
                    and _require(errs, item, "checkpoint", loc, str)
                )
                if not ok:
                    continue
                iid, slot, cpid = item["inspector"], item["slot"], item["checkpoint"]
                if iid not in inspectors:
                    errs.append(ValidationError(E_UNKNOWN_REF, f"{loc}.inspector", f"unknown inspector '{iid}'"))
                if not (1 <= slot <= T):
                    errs.append(ValidationError(E_VALUE_RANGE, f"{loc}.slot", f"must be in [1,{T}]"))
                if cpid not in checkpoints:
                    errs.append(ValidationError(E_UNKNOWN_REF, f"{loc}.checkpoint", f"unknown checkpoint '{cpid}'"))
                elif iid in inspectors:
                    missing = checkpoints[cpid].required - inspectors[iid].trainings
                    if missing:
                        errs.append(
                            ValidationError(
                                E_INCONSISTENT,
                                loc,
                                f"inspector '{iid}' lacks required trainings {sorted(missing)} for '{cpid}'",
                            )
                        )
                wid = item.get("window")
                if wid is not None:
                    if not _is_str(wid):
                        errs.append(ValidationError(E_FIELD_TYPE, f"{loc}.window", "must be a string or null"))
                    elif wid not in windows:
                        errs.append(ValidationError(E_UNKNOWN_REF, f"{loc}.window", f"unknown window '{wid}'"))
                    elif cpid in checkpoints and windows[wid].checkpoint != cpid:
                        errs.append(
                            ValidationError(
                                E_INCONSISTENT,
                                f"{loc}.window",
                                f"window '{wid}' belongs to checkpoint '{windows[wid].checkpoint}', not '{cpid}'",
                            )
                        )
                if (iid, slot) in frozen_slots:
                    errs.append(
                        ValidationError(E_INCONSISTENT, loc, f"inspector '{iid}' has two frozen visits at slot {slot}")
                    )
                frozen_slots.add((iid, slot))
                frozen.append(FrozenVisit(iid, slot, cpid, wid if _is_str(wid) else None))

    scenarios: list[Scenario] | None = None
    if "scenarios" in raw:
        if not isinstance(raw["scenarios"], list):
            errs.append(ValidationError(E_FIELD_TYPE, "$.scenarios", "must be an array"))
        else:
            scenarios = []
            seen_ids: set[str] = set()
            for i, item in enumerate(raw["scenarios"]):
                loc = f"$.scenarios[{i}]"
                if not isinstance(item, dict):
                    errs.append(ValidationError(E_FIELD_TYPE, loc, "must be an object"))
                    continue
                if not _require(errs, item, "id", loc, str):
                    continue
                sid = item["id"]
                if sid == NO_ABSENCE_ID:
                    errs.append(
                        ValidationError(E_DUPLICATE_ID, f"{loc}.id", f"'{NO_ABSENCE_ID}' is reserved for no-absence")
                    )
                if sid in seen_ids:
                    errs.append(ValidationError(E_DUPLICATE_ID, loc, f"duplicate scenario id '{sid}'"))
                seen_ids.add(sid)
                if not _require(errs, item, "reveal_slot", loc, int):
                    continue
                r = item["reveal_slot"]
                if not (1 <= r <= T + 1):
                    errs.append(ValidationError(E_VALUE_RANGE, f"{loc}.reveal_slot", f"must be in [1,{T + 1}]"))
                absent = frozenset()
                if "absent" in item:
                    al = _str_list(errs, item["absent"], f"{loc}.absent")
                    if al is not None:
                        absent = frozenset(al)
                        for a in sorted(absent):
                            if a not in inspectors:
                                errs.append(
                                    ValidationError(E_UNKNOWN_REF, f"{loc}.absent", f"unknown inspector '{a}'")
                                )
                scenarios.append(Scenario(sid, r, absent))

    if errs:
        raise InputError(errs)

    _unique(errs, inspector_ids, "$.inspectors")
    _unique(errs, checkpoint_ids, "$.checkpoints")
    _unique(errs, window_ids, "$.windows")
    if errs:
        raise InputError(errs)

    return Case(
        case_id=case_id,
        slot_count=T,
        inspectors=inspectors,
        inspector_ids=inspector_ids,
        checkpoints=checkpoints,
        checkpoint_ids=checkpoint_ids,
        nodes=frozenset(nodes),
        edges=edges,
        windows=windows,
        window_ids=window_ids,
        frozen=frozen,
        scenarios=scenarios,
    )


def load_case_file(path: str) -> Case:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return load_case(raw)


def canonical_hash(raw) -> str:
    """Deterministic hash of the logical input (key order independent)."""
    blob = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]
