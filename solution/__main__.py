"""Command line entry point: python -m solution <command> CASE.json [--db DB] [PLAN.json]"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from . import db as dbmod
from .checker import check_plan
from .errors import InputError, PlanError, UsageError
from .model import canonical_hash, load_case_file
from .orchestrate import build_output

EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_PLAN_ERROR = 3
EXIT_USAGE = 64


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False))
    sys.stdout.write("\n")


def _emit_error(code: str, message: str, errors: list | None = None) -> None:
    payload = {"status": "error", "error_code": code, "message": message}
    if errors:
        payload["errors"] = errors
    _emit(payload)


def cmd_schedule(args) -> int:
    with open(args.case, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    case = load_case_file(args.case)
    output = build_output(case, raw)

    stored = None
    if args.db:
        conn = dbmod.connect(args.db)
        try:
            case_hash = canonical_hash(raw)
            stored = dbmod.store_plan(
                conn,
                case_hash,
                case.case_id,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                raw,
                output,
            )
        finally:
            conn.close()
        output["persistence"] = {"db": args.db, "row_id": stored, "case_hash": case_hash}
    _emit(output)
    return EXIT_OK


def cmd_check(args) -> int:
    case = load_case_file(args.case)
    if args.plan:
        with open(args.plan, "r", encoding="utf-8") as fh:
            plan_doc = json.load(fh)
    elif args.db:
        with open(args.case, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        conn = dbmod.connect(args.db)
        try:
            plan_doc = dbmod.load_latest(conn, canonical_hash(raw))
        finally:
            conn.close()
        if plan_doc is None:
            raise UsageError("no stored plan for this case in the given database")
    else:
        raise UsageError("check requires either a PLAN.json argument or --db DB.sqlite")

    verdict = check_plan(case, plan_doc)
    _emit(verdict)
    return EXIT_OK


def cmd_list(args) -> int:
    if not args.db:
        raise UsageError("list requires --db DB.sqlite")
    conn = dbmod.connect(args.db)
    try:
        _emit({"status": "ok", "plans": dbmod.list_plans(conn)})
    finally:
        conn.close()
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m solution", description="Blind patrol scheduler")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sched = sub.add_parser("schedule", help="produce an optimal plan")
    p_sched.add_argument("case")
    p_sched.add_argument("--db")
    p_sched.set_defaults(func=cmd_schedule)

    p_check = sub.add_parser("check", help="independently verify a complete plan")
    p_check.add_argument("case")
    p_check.add_argument("plan", nargs="?")
    p_check.add_argument("--db")
    p_check.set_defaults(func=cmd_check)

    p_list = sub.add_parser("list", help="list plans stored in a database")
    p_list.add_argument("case", nargs="?")
    p_list.add_argument("--db")
    p_list.set_defaults(func=cmd_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except InputError as exc:
        _emit_error("INPUT_STRUCTURE_ERROR", "input document failed validation",
                    [e.to_dict() for e in exc.errors])
        return EXIT_INPUT_ERROR
    except PlanError as exc:
        _emit_error("PLAN_INVALID", "plan failed independent verification",
                    [e.to_dict() for e in exc.errors])
        return EXIT_PLAN_ERROR
    except UsageError as exc:
        _emit_error("USAGE_ERROR", str(exc))
        return EXIT_USAGE
    except FileNotFoundError as exc:
        _emit_error("FILE_NOT_FOUND", str(exc))
        return EXIT_USAGE
    except json.JSONDecodeError as exc:
        _emit_error("JSON_PARSE_ERROR", f"{exc.msg} at line {exc.lineno} column {exc.colno}")
        return EXIT_INPUT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
