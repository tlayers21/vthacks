"""The boundaries are the point. Every limit is strictly greater-than, so an expense sitting
exactly on a limit passes -- that is the thing a future reader will second-guess."""

import pytest

from policy import (
    DepartmentBudget,
    ExpenseDraft,
    PolicyRule,
    StaticRuleSource,
    evaluate_expense,
)

CAP = 50_000
AUTO = 10_000
BUDGET = 1_000_000

RULES = StaticRuleSource(
    rules={},
    fallback=PolicyRule(per_expense_limit_cents=CAP, auto_approve_limit_cents=AUTO),
)


def draft(
    amount_cents: int, category: str = "food", has_receipt: bool = True
) -> ExpenseDraft:
    """Defaults to having a receipt so the other rules can be tested on their own.

    Without that, every amount over $25 would also trip missing_receipt and these tests
    would all be asserting on the receipt rule by accident.
    """
    return ExpenseDraft(
        customer_id="c1",
        department_id=1,
        amount_cents=amount_cents,
        category=category,
        has_receipt=has_receipt,
    )


def budget(
    committed_cents: int = 0, monthly_budget_cents: int = BUDGET
) -> DepartmentBudget:
    return DepartmentBudget(
        monthly_budget_cents=monthly_budget_cents,
        committed_cents=committed_cents,
    )


def rules_fired(result) -> set[str]:
    return {v.rule for v in result.violations}


# -- auto-approve threshold -------------------------------------------------


def test_exactly_at_auto_approve_limit_is_clean():
    result = evaluate_expense(draft(AUTO), budget(), RULES)
    assert result.decision == "auto_approved"
    assert result.violations == ()


def test_one_cent_over_auto_approve_limit_needs_approval():
    result = evaluate_expense(draft(AUTO + 1), budget(), RULES)
    assert result.decision == "needs_approval"
    assert rules_fired(result) == {"approval_threshold"}


# -- per-expense cap --------------------------------------------------------


def test_exactly_at_cap_is_not_blocked():
    result = evaluate_expense(draft(CAP), budget(), RULES)
    assert result.decision == "needs_approval"
    assert rules_fired(result) == {"approval_threshold"}


def test_one_cent_over_cap_blocks_and_still_reports_the_threshold():
    # Proves violations accumulate instead of short-circuiting on the first hit
    result = evaluate_expense(draft(CAP + 1), budget(), RULES)
    assert result.decision == "blocked"
    assert rules_fired(result) == {"per_expense_cap", "approval_threshold"}


# -- department budget ------------------------------------------------------


def test_exactly_at_budget_does_not_fire():
    result = evaluate_expense(draft(AUTO), budget(committed_cents=BUDGET - AUTO), RULES)
    assert result.decision == "auto_approved"
    assert result.violations == ()


def test_over_budget_escalates_but_never_blocks():
    result = evaluate_expense(
        draft(AUTO), budget(committed_cents=BUDGET - AUTO + 1), RULES
    )
    assert result.decision == "needs_approval"
    assert rules_fired(result) == {"department_budget"}
    assert result.blocked_by == ()


def test_over_budget_suppresses_auto_approve_on_a_tiny_expense():
    result = evaluate_expense(draft(1), budget(committed_cents=BUDGET), RULES)
    assert result.decision == "needs_approval"


def test_zero_budget_department_escalates_everything():
    result = evaluate_expense(draft(1), budget(monthly_budget_cents=0), RULES)
    assert result.decision == "needs_approval"


# -- combinations -----------------------------------------------------------


def test_cap_breach_outranks_budget_breach():
    result = evaluate_expense(draft(CAP + 1), budget(committed_cents=BUDGET), RULES)
    assert result.decision == "blocked"
    assert rules_fired(result) == {
        "per_expense_cap",
        "department_budget",
        "approval_threshold",
    }


def test_violation_order_is_stable():
    result = evaluate_expense(draft(CAP + 1), budget(committed_cents=BUDGET), RULES)
    assert [v.rule for v in result.violations] == [
        "per_expense_cap",
        "department_budget",
        "approval_threshold",
    ]


def test_violation_messages_render_dollars():
    result = evaluate_expense(draft(CAP + 1), budget(), RULES)
    assert "$500.01" in result.violations[0].message


@pytest.mark.parametrize("severity", ["block", "warn"])
def test_every_violation_carries_a_known_severity(severity):
    result = evaluate_expense(draft(CAP + 1), budget(committed_cents=BUDGET), RULES)
    assert all(v.severity in {"block", "warn"} for v in result.violations)


def test_injected_rule_source_changes_the_outcome():
    generous = StaticRuleSource(
        rules={},
        fallback=PolicyRule(
            per_expense_limit_cents=10**9, auto_approve_limit_cents=10**9
        ),
    )
    assert (
        evaluate_expense(draft(CAP + 1), budget(), generous).decision == "auto_approved"
    )


def test_department_specific_rule_is_used():
    """Against the shipped defaults, which is what a fresh database is seeded with."""
    # Engineering's software ceiling is higher than the org default
    defaults = StaticRuleSource()

    amount = 400_000
    eng = evaluate_expense(draft(amount, "software"), budget(), defaults)
    sales = ExpenseDraft(
        customer_id="c1",
        department_id=3,
        amount_cents=amount,
        category="software",
        has_receipt=True,
    )
    assert eng.decision == "needs_approval"
    assert evaluate_expense(sales, budget(), defaults).decision == "blocked"


# -- receipts (spec 7.2) ---------------------------------------------------


def test_over_the_threshold_without_a_receipt_is_blocked():
    result = evaluate_expense(draft(2_501, has_receipt=False), budget(), RULES)
    assert result.decision == "blocked"
    assert "missing_receipt" in rules_fired(result)


def test_over_the_threshold_with_a_receipt_is_not_blocked_by_it():
    result = evaluate_expense(draft(2_501, has_receipt=True), budget(), RULES)
    assert "missing_receipt" not in rules_fired(result)
    assert result.decision == "auto_approved"


def test_exactly_at_the_threshold_needs_no_receipt():
    """Strictly greater-than, like every other limit in the engine."""
    result = evaluate_expense(draft(2_500, has_receipt=False), budget(), RULES)
    assert "missing_receipt" not in rules_fired(result)
    assert result.decision == "auto_approved"


def test_under_the_threshold_needs_no_receipt():
    result = evaluate_expense(draft(500, has_receipt=False), budget(), RULES)
    assert result.decision == "auto_approved"
    assert result.violations == ()


def test_missing_receipt_reports_alongside_the_other_rules():
    """Rules do not short-circuit, so a big receiptless expense explains itself fully."""
    result = evaluate_expense(draft(CAP + 1, has_receipt=False), budget(), RULES)
    assert {"missing_receipt", "per_expense_cap", "approval_threshold"} <= rules_fired(result)
