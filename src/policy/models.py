"""Value types the policy engine takes in and hands back.

Literal aliases rather than Enum: they go straight into a SQLite TEXT column with no `.value`,
and they match the TypedDict idiom already used in nessie/protocol.py.
"""

from dataclasses import dataclass
from typing import Literal

Decision = Literal["auto_approved", "needs_approval", "blocked"]
Severity = Literal["block", "warn"]
RuleName = Literal[
    "per_expense_cap", "department_budget", "approval_threshold", "missing_receipt"
]

# Mirrored by the CHECK constraint on expenses.category in db/schema.sql
CATEGORIES: tuple[str, ...] = (
    "travel",
    "food",
    "client meals",
    "software",
    "equipment",
    "marketing",
    "training",
    "office supplies",
    "shipping",
    "other",
)


@dataclass(frozen=True, slots=True)
class PolicyRule:
    per_expense_limit_cents: int
    auto_approve_limit_cents: int


@dataclass(frozen=True, slots=True)
class ExpenseDraft:
    """An expense as submitted, before it has been evaluated or persisted."""

    customer_id: str
    department_id: int
    amount_cents: int
    category: str
    merchant: str | None = None
    description: str | None = None
    # Whether a receipt is attached, not the receipt itself -- the engine stays pure
    has_receipt: bool = False


@dataclass(frozen=True, slots=True)
class DepartmentBudget:
    monthly_budget_cents: int
    # This month's committed spend, excluding the expense being evaluated
    committed_cents: int

    @property
    def remaining_cents(self) -> int:
        return self.monthly_budget_cents - self.committed_cents


@dataclass(frozen=True, slots=True)
class Violation:
    rule: RuleName
    severity: Severity
    message: str

    def as_dict(self) -> dict:
        # slots=True means no __dict__, so vars() does not work on these
        return {"rule": self.rule, "severity": self.severity, "message": self.message}


@dataclass(frozen=True, slots=True)
class PolicyResult:
    decision: Decision
    violations: tuple[Violation, ...]

    @property
    def blocked_by(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity == "block")
