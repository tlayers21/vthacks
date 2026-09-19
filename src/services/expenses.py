"""Submitting an expense, and paying one out.

Orchestration only: the SQL lives in db/expenses.py, the rules in policy/.
"""

import logging
import sqlite3

from db import expenses as expense_db
from db.connect import transaction
from policy import DECISION_TO_STATUS, ExpenseDraft, PolicyResult, evaluate_expense
from services import policies as policy_service
from services.permissions import (
    Forbidden,
    InsufficientBudget,
    can_decide,
    can_submit,
)

log = logging.getLogger(__name__)


def submit_expense(
    conn: sqlite3.Connection,
    actor: sqlite3.Row,
    *,
    amount_cents: int,
    category: str,
    merchant: str | None = None,
    description: str | None = None,
    receipt=None,
    nessie=None,
    reader=None,
    background: bool = False,
) -> dict:
    """`receipt` is a services.receipts.StoredReceipt, already written to disk."""
    if not can_submit(actor):
        raise Forbidden("this account cannot submit expenses")

    draft = ExpenseDraft(
        customer_id=actor["nessie_id"],
        department_id=actor["department_id"],
        amount_cents=amount_cents,
        category=category,
        merchant=merchant,
        description=description,
        has_receipt=receipt is not None,
    )
    result = preview_expense(conn, draft)
    status = DECISION_TO_STATUS[result.decision]

    # A blocked expense keeps its receipt, the same way it keeps its violations: the
    # submitter has to be able to see what they actually sent.
    with transaction(conn):
        expense_id = expense_db.insert_expense(conn, draft, result, status, receipt)

    # Outside the transaction above: never hold a SQLite write lock across a network call.
    # An auto-approved expense is not paid here any more. The receipt check settles it, and
    # money that moved before anyone read the receipt could not be held back by a flag.
    check_receipt(conn, expense_id, reader=reader, nessie=nessie, background=background)

    return {
        "expense_id": expense_id,
        "status": status,
        "decision": result.decision,
        "violations": [v.as_dict() for v in result.violations],
    }


def check_receipt(
    conn: sqlite3.Connection,
    expense_id: int,
    reader=None,
    nessie=None,
    background: bool = False,
) -> None:
    """Hand the expense to the receipt check, on a thread or not.

    Threaded in the real app so the submit form returns at once; inline under tests, which
    hold one connection and need the verdict to exist by the time they assert on it.
    """
    from services import expense_flags

    if background:
        expense_flags.check_expense_async(expense_id, reader, nessie)
    else:
        expense_flags.check_expense_safely(conn, expense_id, reader, nessie)


def preview_expense(conn: sqlite3.Connection, draft: ExpenseDraft) -> PolicyResult:
    """Evaluate without writing anything. Backs the live preview on the submit form.

    The single funnel for real evaluation, which is why it is the one place that loads the
    live rule set -- a submission can never be judged against a stale copy.
    """
    budget = expense_db.department_budget(conn, draft.department_id)
    return evaluate_expense(draft, budget, policy_service.rule_source(conn))


def pay_expense(conn: sqlite3.Connection, expense_id: int, nessie=None) -> str:
    """Move the money for an approved expense. Safe to call more than once.

    The transfer id is written and committed before the status becomes 'paid', so a crash
    between the two leaves an approved row that already carries its id -- the guard below then
    turns the retry into a status flip instead of a second transfer. The UNIQUE constraint on
    nessie_transfer_id is the backstop if that ever slips.
    """
    if nessie is None:
        from nessie import get_nessie

        nessie = get_nessie()

    expense = expense_db.get_expense(conn, expense_id)
    if expense is None:
        raise KeyError(f"no such expense: {expense_id}")

    if expense["nessie_transfer_id"] is not None:
        if expense["status"] != "paid":
            with transaction(conn):
                expense_db.set_status(conn, expense_id, "paid")
        return "paid"

    payer_id, payee_id = expense_db.payout_accounts(conn, expense_id)
    try:
        transfer = nessie.create_transfer(
            payer_id=payer_id,
            payee_id=payee_id,
            amount_cents=expense["amount_cents"],
            description=f"expense {expense_id}",
        )
    except Exception as exc:  # noqa: BLE001
        # Broad on purpose: InsufficientFunds, an unknown account, and any HTTP failure from the
        # real client all mean the same thing here. Not re-raised -- the expense was validly
        # accepted, only the money did not move, and payout_failed is retryable.
        with transaction(conn):
            expense_db.set_status(conn, expense_id, "payout_failed")
        log.warning("payout failed for expense %s: %s", expense_id, exc)
        return "payout_failed"

    with transaction(conn):
        expense_db.set_transfer_id(conn, expense_id, transfer["id"])
        expense_db.set_status(conn, expense_id, "paid")
    return "paid"


def decide_expense(
    conn: sqlite3.Connection,
    actor: sqlite3.Row,
    expense_id: int,
    approve: bool,
    note: str | None = None,
    nessie=None,
) -> dict:
    """A manager's call on an expense the engine routed to them."""
    expense = expense_db.get_expense(conn, expense_id)
    if expense is None:
        raise KeyError(f"no such expense: {expense_id}")
    if not can_decide(actor, expense):
        raise Forbidden("not your department")
    if expense["status"] != "needs_approval":
        raise Forbidden(f"expense is {expense['status']}, not awaiting a decision")

    note = (note or "").strip() or None
    if not approve and note is None:
        raise ValueError("a rejection needs a reason")
    if approve:
        _require_funds(conn, expense["department_id"])

    status = "approved" if approve else "rejected"
    with transaction(conn):
        expense_db.record_decision(conn, expense_id, status, actor["nessie_id"], note)

    if approve:
        status = pay_expense(conn, expense_id, nessie)
    return {"expense_id": expense_id, "status": status}


def _require_funds(conn: sqlite3.Connection, department_id: int) -> None:
    """A manager cannot approve past the department's budget -- finance has to top it up first.

    The expense being decided is already inside committed_cents (needs_approval counts as
    exposure), so the whole test is whether the department is still in the black. That is the
    same number the budget bar on /finance draws, which is the point: what the manager is told
    and what finance is looking at can never disagree.
    """
    budget = expense_db.department_budget(conn, department_id)
    if budget.remaining_cents < 0:
        raise InsufficientBudget(-budget.remaining_cents)
