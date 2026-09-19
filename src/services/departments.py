"""Changing a department's monthly budget.

The budget is a *spending ceiling*, not cash. Editing it does not move money: that is what
funding requests are for, and they raise the budget and fire the corporate transfer together
(services/budget_requests.py). Finance can therefore set a ceiling above what the department
account actually holds -- the expense payout path already handles a short account through
`payout_failed` and retry.

Lowering a budget below what is already committed is allowed on purpose. It is a real thing
finance does, and the department simply shows as over budget, which is the same state the
seeded Marketing department demonstrates. The manager guard in services/expenses.py then
refuses further approvals until finance funds it.
"""

import sqlite3

from db import departments as department_db
from db import expenses as expense_db
from db.connect import transaction
from services.permissions import Forbidden

# A ceiling this high is more likely a typo than a budget
MAX_BUDGET_CENTS = 1_000_000_000


def set_budget(
    conn: sqlite3.Connection,
    actor: sqlite3.Row,
    *,
    department_id: int,
    monthly_budget_cents: int,
) -> dict:
    if actor["role"] != "Finance":
        raise Forbidden("only finance can change department budgets")
    if monthly_budget_cents < 0:
        raise ValueError("a budget cannot be negative")
    if monthly_budget_cents > MAX_BUDGET_CENTS:
        raise ValueError("that budget is implausibly large")

    if department_db.get_department(conn, department_id) is None:
        raise KeyError(f"no such department: {department_id}")

    with transaction(conn):
        department_db.set_budget(
            conn, department_id, monthly_budget_cents, actor["nessie_id"]
        )

    budget = expense_db.department_budget(conn, department_id)
    return {
        "department_id": department_id,
        "monthly_budget_cents": budget.monthly_budget_cents,
        "committed_cents": budget.committed_cents,
        "remaining_cents": budget.remaining_cents,
        # The caller redraws its bar from this rather than guessing at the threshold
        "over_budget": budget.remaining_cents < 0,
    }
