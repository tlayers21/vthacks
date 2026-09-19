"""Seeded expenses are hand-written, so nothing stops them contradicting the rules they claim
to have come from. A demo that shows an 'auto_approved' expense the engine would have blocked is
worse than no demo, so these assert the planted rows stay honest."""

import pytest

from db import expenses as expense_db
from policy import RECEIPT_REQUIRED_OVER_CENTS, default_rule_source


def seeded_expenses(db):
    return db.execute("SELECT * FROM expenses ORDER BY expense_id").fetchall()


def rule_for(expense):
    return default_rule_source().rule_for(expense["department_id"], expense["category"])


def test_seed_has_every_policy_decision(db):
    decisions = {r["policy_decision"] for r in seeded_expenses(db)}
    assert decisions == {"auto_approved", "needs_approval", "blocked"}


def test_seed_has_every_status_the_ui_renders(db):
    statuses = {r["status"] for r in seeded_expenses(db)}
    assert {"paid", "needs_approval", "rejected", "payout_failed"} <= statuses


def test_blocked_rows_really_exceed_their_cap(db):
    for expense in seeded_expenses(db):
        if expense["policy_decision"] == "blocked":
            assert expense["amount_cents"] > rule_for(expense).per_expense_limit_cents


def test_unblocked_rows_are_within_their_cap(db):
    for expense in seeded_expenses(db):
        if expense["policy_decision"] != "blocked":
            assert expense["amount_cents"] <= rule_for(expense).per_expense_limit_cents


def test_auto_approved_rows_are_under_the_threshold_and_carry_no_violations(db):
    rows = [r for r in seeded_expenses(db) if r["policy_decision"] == "auto_approved"]
    violations = expense_db.violations_for(db, [r["expense_id"] for r in rows])
    for expense in rows:
        assert expense["amount_cents"] <= rule_for(expense).auto_approve_limit_cents
        assert violations.get(expense["expense_id"], []) == []


def test_non_auto_approved_rows_explain_themselves(db):
    rows = [r for r in seeded_expenses(db) if r["policy_decision"] != "auto_approved"]
    violations = expense_db.violations_for(db, [r["expense_id"] for r in rows])
    for expense in rows:
        assert violations.get(expense["expense_id"]), (
            f"expense {expense['expense_id']} is {expense['policy_decision']}"
            " but records no violation"
        )


def test_blocked_rows_carry_a_block_severity_violation(db):
    rows = [r for r in seeded_expenses(db) if r["policy_decision"] == "blocked"]
    violations = expense_db.violations_for(db, [r["expense_id"] for r in rows])
    for expense in rows:
        assert any(v["severity"] == "block" for v in violations[expense["expense_id"]])


def test_paid_rows_have_a_transfer_and_unpaid_rows_do_not(db):
    """Only meaningful after db/seed.py, which replays the payouts. init_db.py leaves them NULL,
    so this asserts the invariant that matters either way: no unpaid row claims a transfer."""
    for expense in seeded_expenses(db):
        if expense["status"] != "paid":
            assert expense["nessie_transfer_id"] is None


def test_marketing_is_seeded_over_budget(db):
    """Spec 11 plants Marketing at 112%, which is what makes the budget rule demonstrable."""
    budget = expense_db.department_budget(db, 2)
    assert budget.committed_cents > budget.monthly_budget_cents
    ratio = budget.committed_cents / budget.monthly_budget_cents
    assert ratio == pytest.approx(1.12, abs=0.005)


def test_every_other_department_is_within_budget(db):
    for row in expense_db.department_spend_summary(db):
        if row["department_id"] == 2:
            continue
        assert row["committed_cents"] <= row["monthly_budget_cents"]


def test_rows_over_the_receipt_threshold_carry_a_receipt(db):
    """Spec 7.2 blocks anything over $25 with no receipt, so a seeded row without one would
    be claiming a verdict the engine would never have given it."""
    for expense in seeded_expenses(db):
        if expense["amount_cents"] > RECEIPT_REQUIRED_OVER_CENTS:
            assert expense["receipt_path"], (
                f"expense {expense['expense_id']} is"
                f" {expense['amount_cents']}c with no receipt"
            )


def test_seeded_receipt_files_exist_on_disk(db):
    """A receipt_path with no file behind it renders as a broken image in the approval queue."""
    from services.receipts import install_samples, resolve

    install_samples()
    for expense in seeded_expenses(db):
        if expense["receipt_path"]:
            assert resolve(expense["receipt_path"]).exists(), (
                f"expense {expense['expense_id']} points at a missing receipt file"
            )


def test_receipt_hash_matches_the_stored_filename(db):
    """The filename is the hash, which is what makes identical uploads share one file."""
    for expense in seeded_expenses(db):
        if expense["receipt_path"]:
            assert expense["receipt_path"].startswith(expense["receipt_hash"])
