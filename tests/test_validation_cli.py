"""Structural validation, CLI contract and SQLite persistence tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

from solution.errors import InputError
from solution.model import load_case

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(args):
    return subprocess.run(
        [sys.executable, "-m", "solution", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


class ValidationTest(unittest.TestCase):
    def _base(self):
        return {
            "case_id": "v",
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

    def test_missing_required_field_is_locatable(self):
        raw = self._base()
        del raw["slot_count"]
        with self.assertRaises(InputError) as ctx:
            load_case(raw)
        codes = {e.code for e in ctx.exception.errors}
        self.assertIn("E_REQUIRED", codes)
        self.assertTrue(any(e.location == "$" for e in ctx.exception.errors))

    def test_unknown_reference_points_at_field(self):
        raw = self._base()
        raw["windows"][0]["checkpoint"] = "GHOST"
        with self.assertRaises(InputError) as ctx:
            load_case(raw)
        self.assertTrue(
            any(e.code == "E_UNKNOWN_REF" and "checkpoint" in e.location for e in ctx.exception.errors)
        )

    def test_negative_cost_rejected(self):
        raw = self._base()
        raw["edges"][0]["cost"] = -3
        with self.assertRaises(InputError) as ctx:
            load_case(raw)
        self.assertTrue(any(e.code == "E_VALUE_RANGE" for e in ctx.exception.errors))

    def test_duplicate_id_rejected(self):
        raw = self._base()
        raw["inspectors"].append(dict(raw["inspectors"][0]))
        with self.assertRaises(InputError) as ctx:
            load_case(raw)
        self.assertTrue(any(e.code == "E_DUPLICATE_ID" for e in ctx.exception.errors))

    def test_training_gap_on_frozen_visit_rejected(self):
        raw = self._base()
        raw["frozen_visits"] = [{"inspector": "b1", "slot": 1, "checkpoint": "P"}]
        raw["inspectors"][1]["trainings"] = []  # b1 no longer qualified
        with self.assertRaises(InputError) as ctx:
            load_case(raw)
        self.assertTrue(any(e.code == "E_INCONSISTENT" for e in ctx.exception.errors))


class CliTest(unittest.TestCase):
    def test_schedule_then_check_roundtrip_with_db(self):
        case_path = os.path.join(ROOT, "examples", "tiny_case.json")
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "store.sqlite")
            r = _run(["schedule", case_path, "--db", db])
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["status"], "feasible")
            self.assertTrue(os.path.exists(db))
            # check via the stored plan in the database
            r2 = _run(["check", case_path, "--db", db])
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertEqual(json.loads(r2.stdout)["status"], "valid")
            # listing the stored plans works
            r3 = _run(["list", "--db", db])
            self.assertEqual(r3.returncode, 0)
            self.assertEqual(json.loads(r3.stdout)["plans"][0]["case_id"], "tiny4x5")

    def test_check_explicit_plan_file(self):
        case_path = os.path.join(ROOT, "examples", "tiny_case.json")
        with tempfile.TemporaryDirectory() as tmp:
            plan = os.path.join(tmp, "plan.json")
            r = _run(["schedule", case_path])
            with open(plan, "w", encoding="utf-8") as fh:
                fh.write(r.stdout)
            r2 = _run(["check", case_path, plan])
            self.assertEqual(r2.returncode, 0, r2.stderr)

    def test_deterministic_output(self):
        case_path = os.path.join(ROOT, "examples", "equal_cost_tie_case.json")
        a = _run(["schedule", case_path]).stdout
        b = _run(["schedule", case_path]).stdout
        self.assertEqual(a, b)

    def test_bad_json_returns_error_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.json")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            r = _run(["schedule", bad])
            self.assertNotEqual(r.returncode, 0)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["error_code"], "JSON_PARSE_ERROR")


if __name__ == "__main__":
    unittest.main()
