"""Decides what happens to a submitted expense.

Pure: no SQL, no Flask, no Nessie. Values in, values out. That is what lets the same call back
both `POST /expenses` and the live preview the submit form runs on every keystroke.

Every rule runs -- none of them short-circuit. A submitter should see every reason their expense
was held up at once, not just the first one to trip.

All comparisons are strictly greater-than: an expense exactly at a limit passes.
"""

from .models import (
    Decision,
    DepartmentBudget,
    ExpenseDraft,
    PolicyResult,
    Violation,
)
from .rules import RuleSource, default_rule_source


def _dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def evaluate_expense(
    expense: ExpenseDraft,
    budget: DepartmentBudget,
    rules: RuleSource | None = None,
) -> PolicyResult:
    rule = (rules or default_rule_source()).rule_for(
        expense.department_id, expense.category
    )
    amount = expense.amount_cents
    violations: list[Violation] = []

    if amount > rule.per_expense_limit_cents:
        violations.append(
            Violation(
                rule="per_expense_cap",
                severity="block",
                message=(
                    f"{_dollars(amount)} is over the {_dollars(rule.per_expense_limit_cents)} "
                    f"limit for {expense.category}"
                ),
            )
        )

    if budget.committed_cents + amount > budget.monthly_budget_cents:
        # Warn, not block: an over-budget department still spends, a human just signs off
        violations.append(
            Violation(
                rule="department_budget",
                severity="warn",
                message=(
                    f"{_dollars(amount)} exceeds the "
                    f"{_dollars(max(budget.remaining_cents, 0))} left of this month's "
                    f"{_dollars(budget.monthly_budget_cents)} budget"
                ),
            )
        )

    if amount > rule.auto_approve_limit_cents:
        violations.append(
            Violation(
                rule="approval_threshold",
                severity="warn",
                message=(
                    f"{_dollars(amount)} is over the "
                    f"{_dollars(rule.auto_approve_limit_cents)} auto-approve limit for "
                    f"{expense.category}"
                ),
            )
        )

    return PolicyResult(decision=_decide(violations), violations=tuple(violations))


def _decide(violations: list[Violation]) -> Decision:
    """Worst severity wins. Deriving it this way is what keeps 'over budget escalates but never
    blocks' a property of the severity table rather than a special case."""
    if any(v.severity == "block" for v in violations):
        return "blocked"
    if violations:
        return "needs_approval"
    return "auto_approved"


# How the engine's verdict maps onto the expense lifecycle at insert time.
#
# Nothing here refuses a submission. A 'blocked' expense is routed to its manager like any other,
# wearing the block-severity violation that got it there -- only a person can reject spend, and
# 'rejected' is reserved for what a person did. The verdict itself survives untouched in
# expenses.policy_decision, so the engine's opinion is still on the record.
DECISION_TO_STATUS: dict[Decision, str] = {
    "auto_approved": "approved",  # then 'paid' (or 'payout_failed') once the transfer settles
    "needs_approval": "needs_approval",
    "blocked": "needs_approval",
}
