"""SQLite persistence for produced plans.

Only the ``schedule`` command writes; ``check`` may read the latest stored
plan for a given logical input when no explicit plan file is supplied.
"""

from __future__ import annotations

import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_hash TEXT NOT NULL,
    case_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    input_json TEXT NOT NULL,
    plan_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plans_hash ON plans(case_hash);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def store_plan(conn: sqlite3.Connection, case_hash: str, case_id: str,
               created_at: str, raw_input: dict, plan_doc: dict) -> int:
    cur = conn.execute(
        "INSERT INTO plans (case_hash, case_id, created_at, input_json, plan_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            case_hash,
            case_id,
            created_at,
            json.dumps(raw_input, sort_keys=True, ensure_ascii=False),
            json.dumps(plan_doc, sort_keys=True, ensure_ascii=False),
        ),
    )
    conn.commit()
    return cur.lastrowid


def load_latest(conn: sqlite3.Connection, case_hash: str) -> dict | None:
    row = conn.execute(
        "SELECT plan_json FROM plans WHERE case_hash = ? ORDER BY id DESC LIMIT 1",
        (case_hash,),
    ).fetchone()
    return None if row is None else json.loads(row[0])


def list_plans(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, case_hash, case_id, created_at FROM plans ORDER BY id"
    ).fetchall()
    return [
        {"id": r[0], "case_hash": r[1], "case_id": r[2], "created_at": r[3]}
        for r in rows
    ]
