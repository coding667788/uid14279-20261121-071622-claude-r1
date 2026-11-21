"""Error types with locatable error codes.

All structural problems found in an input document are collected first and
reported together so that a single run can point at every broken field.
"""

from __future__ import annotations

from dataclasses import dataclass


# Error codes (stable part of the CLI contract).
E_ROOT_TYPE = "E_ROOT_TYPE"
E_REQUIRED = "E_REQUIRED"
E_FIELD_TYPE = "E_FIELD_TYPE"
E_DUPLICATE_ID = "E_DUPLICATE_ID"
E_UNKNOWN_REF = "E_UNKNOWN_REF"
E_VALUE_RANGE = "E_VALUE_RANGE"
E_INCONSISTENT = "E_INCONSISTENT"
E_FROZEN_ABSENT_CONFLICT = "E_FROZEN_ABSENT_CONFLICT"
E_PLAN_STRUCTURE = "E_PLAN_STRUCTURE"
E_PLAN_VIOLATION = "E_PLAN_VIOLATION"
E_NOT_FOUND = "E_NOT_FOUND"


@dataclass(frozen=True)
class ValidationError:
    code: str
    location: str
    message: str

    def to_dict(self) -> dict:
        return {"code": self.code, "location": self.location, "message": self.message}


class InputError(Exception):
    """The input document is structurally or semantically invalid."""

    def __init__(self, errors: list[ValidationError]):
        assert errors
        self.errors = errors
        super().__init__("; ".join(f"{e.code} @ {e.location}: {e.message}" for e in errors))


class PlanError(Exception):
    """A plan handed to ``check`` is invalid."""

    def __init__(self, errors: list[ValidationError]):
        assert errors
        self.errors = errors
        super().__init__("; ".join(f"{e.code} @ {e.location}: {e.message}" for e in errors))


class UsageError(Exception):
    """Bad command line usage."""
