"""A manager asking finance for more department money, and finance answering.

Orchestration only: the SQL lives in db/budget_requests.py.

This is the other half of the loop in services/expenses.py. A manager who cannot approve an
expense because the department is out of budget ends up here, and an approval from finance is
what lets them go back and approve it.
"""

import sqlite3

from db import budget_requests as request_db
from db import expenses as expense_db
from db.connect import transaction
from services.permissions import Forbidden, can_decide_funding, can_request_funding


def submit_request(
    conn: sqlite3.Connection,
    actor: sqlite3.Row,
    *,
    amount_cents: int,
    reason: str | None = None,
) -> dict:
    if not can_request_funding(actor):
        raise Forbidden("only a department manager can request funding")

    reason = (reason or "").strip() or None
    with transaction(conn):
        request_id = request_db.insert_request(
            conn,
            customer_id=actor["nessie_id"],
            department_id=actor["department_id"],
            amount_cents=amount_cents,
            reason=reason,
        )
    return {"request_id": request_id, "status": "Pending"}


def decide_request(
    conn: sqlite3.Connection,
    actor: sqlite3.Row,
    request_id: int,
    approve: bool,
    note: str | None = None,
    nessie=None,
) -> dict:
    """Finance's call. Approving moves corporate money and raises the department's budget.

    The transfer id is written and committed before the status becomes 'Approved', so a crash
    between the two leaves a pending row that already carries its id -- the guard below then
    turns the retry into a status flip instead of a second allocation, exactly as
    services/expenses.py:pay_expense does for reimbursements.

    A failed transfer leaves the request Pending and re-raises. There is no 'payout_failed'
    equivalent here on purpose: half an allocation -- a budget raised with no money behind it --
    is worse than an untouched request finance can simply approve again.
    """
    if not can_decide_funding(actor):
        raise Forbidden("only finance can decide funding requests")

    request = request_db.get_request(conn, request_id)
    if request is None:
        raise KeyError(f"no such funding request: {request_id}")

    note = (note or "").strip() or None
    if not approve and note is None:
        raise ValueError("a rejection needs a reason")

    if request["nessie_transfer_id"] is not None:
        if request["status"] != "Approved":
            with transaction(conn):
                request_db.record_decision(
                    conn, request_id, "Approved", actor["nessie_id"], note
                )
        return {"request_id": request_id, "status": "Approved"}

    if request["status"] != "Pending":
        raise Forbidden(f"request is {request['status']}, not awaiting a decision")

    if not approve:
        with transaction(conn):
            request_db.record_decision(
                conn, request_id, "Rejected", actor["nessie_id"], note
            )
        return {"request_id": request_id, "status": "Rejected"}

    if nessie is None:
        from nessie import get_nessie

        nessie = get_nessie()

    payer_id, payee_id = request_db.allocation_accounts(conn, request_id)
    # Outside any transaction: never hold a SQLite write lock across a network call
    transfer = nessie.create_transfer(
        payer_id=payer_id,
        payee_id=payee_id,
        amount_cents=request["amount_cents"],
        description=f"funding request {request_id}",
    )

    with transaction(conn):
        request_db.set_transfer_id(conn, request_id, transfer["id"])
        request_db.raise_budget(conn, request["department_id"], request["amount_cents"])
        request_db.record_decision(
            conn, request_id, "Approved", actor["nessie_id"], note
        )

    budget = expense_db.department_budget(conn, request["department_id"])
    return {
        "request_id": request_id,
        "status": "Approved",
        "monthly_budget_cents": budget.monthly_budget_cents,
        "remaining_cents": budget.remaining_cents,
    }
