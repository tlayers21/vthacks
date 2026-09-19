"""Every SQL statement that touches expenses.

Kept out of services/ so the rule that only db/ executes SQL keeps holding.
"""

import sqlite3

from policy import DepartmentBudget, ExpenseDraft, PolicyResult

# Everything except 'rejected'. Wider than "approved and paid" on purpose: a pending approval is
# committed exposure, and payout_failed money is still owed because it will be retried.
COMMITTED_STATUSES = ("needs_approval", "approved", "paid", "payout_failed")

_BUDGET_SQL = f"""
SELECT d.monthly_budget_cents AS monthly_budget_cents,
       COALESCE(SUM(
           CASE WHEN e.status IN ({",".join("?" * len(COMMITTED_STATUSES))})
                 AND strftime('%Y-%m', e.submitted_at) = strftime('%Y-%m', 'now')
                THEN e.amount_cents END
       ), 0) AS committed_cents
FROM departments d
LEFT JOIN expenses e ON e.department_id = d.department_id
WHERE d.department_id = ?
GROUP BY d.department_id
"""


def department_budget(conn: sqlite3.Connection, department_id: int) -> DepartmentBudget:
    """This month's committed spend against the department's budget.

    The status and month filters live inside the CASE, not in a WHERE clause -- in a WHERE they
    would quietly turn the LEFT JOIN into an inner join, and a department with no expenses yet
    would return no row at all instead of its budget.
    """
    row = conn.execute(_BUDGET_SQL, (*COMMITTED_STATUSES, department_id)).fetchone()
    if row is None:
        raise KeyError(f"no such department: {department_id}")
    return DepartmentBudget(
        monthly_budget_cents=row["monthly_budget_cents"],
        committed_cents=row["committed_cents"],
    )


def insert_expense(
    conn: sqlite3.Connection,
    draft: ExpenseDraft,
    result: PolicyResult,
    status: str,
    receipt=None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO expenses"
        " (customer_id, department_id, amount_cents, category, merchant, description,"
        "  status, policy_decision,"
        "  receipt_path, receipt_filename, receipt_mime, receipt_hash)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            draft.customer_id,
            draft.department_id,
            draft.amount_cents,
            draft.category,
            draft.merchant,
            draft.description,
            status,
            result.decision,
            receipt.path if receipt else None,
            receipt.filename if receipt else None,
            receipt.mime if receipt else None,
            receipt.hash if receipt else None,
        ),
    )
    expense_id = cursor.lastrowid
    assert expense_id is not None
    conn.executemany(
        "INSERT INTO expense_violations (expense_id, rule, severity, message)"
        " VALUES (?, ?, ?, ?)",
        [(expense_id, v.rule, v.severity, v.message) for v in result.violations],
    )
    return expense_id


def get_expense(conn: sqlite3.Connection, expense_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM expenses WHERE expense_id = ?", (expense_id,)
    ).fetchone()


def violations_for(
    conn: sqlite3.Connection, expense_ids: list[int]
) -> dict[int, list[dict]]:
    if not expense_ids:
        return {}
    placeholders = ",".join("?" * len(expense_ids))
    rows = conn.execute(
        f"SELECT expense_id, rule, severity, message FROM expense_violations"
        f" WHERE expense_id IN ({placeholders}) ORDER BY violation_id",
        expense_ids,
    ).fetchall()
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["expense_id"], []).append(dict(row))
    return grouped


def payout_accounts(conn: sqlite3.Connection, expense_id: int) -> tuple[str, str]:
    """(department account, employee account) for an expense's reimbursement transfer."""
    row = conn.execute(
        "SELECT d.account_id AS payer_id, a.nessie_id AS payee_id"
        " FROM expenses e"
        " JOIN departments d ON d.department_id = e.department_id"
        " JOIN accounts a ON a.customer_id = e.customer_id"
        " WHERE e.expense_id = ?",
        (expense_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"no payout accounts for expense {expense_id}")
    return row["payer_id"], row["payee_id"]


def set_transfer_id(
    conn: sqlite3.Connection, expense_id: int, transfer_id: str
) -> None:
    # The NULL guard makes a concurrent second payout a no-op rather than an overwrite
    conn.execute(
        "UPDATE expenses SET nessie_transfer_id = ?"
        " WHERE expense_id = ? AND nessie_transfer_id IS NULL",
        (transfer_id, expense_id),
    )


def set_status(conn: sqlite3.Connection, expense_id: int, status: str) -> None:
    conn.execute(
        "UPDATE expenses SET status = ? WHERE expense_id = ?", (status, expense_id)
    )


def record_decision(
    conn: sqlite3.Connection,
    expense_id: int,
    status: str,
    decided_by: str,
    note: str | None = None,
) -> None:
    conn.execute(
        "UPDATE expenses SET status = ?, decided_by = ?, decided_at = CURRENT_TIMESTAMP,"
        " decision_note = ? WHERE expense_id = ?",
        (status, decided_by, note, expense_id),
    )


_LIST_SQL = """
SELECT e.*, c.name AS submitter_name, d.name AS department_name,
       decider.name AS decider_name
FROM expenses e
JOIN customers c ON c.nessie_id = e.customer_id
JOIN departments d ON d.department_id = e.department_id
LEFT JOIN customers decider ON decider.nessie_id = e.decided_by
"""


def list_expenses(
    conn: sqlite3.Connection,
    customer_id: str | None = None,
    department_id: int | None = None,
    statuses: tuple[str, ...] | None = None,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list = []
    if customer_id is not None:
        clauses.append("e.customer_id = ?")
        params.append(customer_id)
    if department_id is not None:
        clauses.append("e.department_id = ?")
        params.append(department_id)
    if statuses:
        clauses.append(f"e.status IN ({','.join('?' * len(statuses))})")
        params.extend(statuses)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return conn.execute(
        f"{_LIST_SQL}{where} ORDER BY e.expense_id DESC", params
    ).fetchall()


def category_spend_summary(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """This month's committed spend per category, biggest first. Backs the finance breakdown."""
    return conn.execute(
        f"SELECT category, SUM(amount_cents) AS spent_cents, COUNT(*) AS expense_count"
        f" FROM expenses"
        f" WHERE status IN ({','.join('?' * len(COMMITTED_STATUSES))})"
        f" AND strftime('%Y-%m', submitted_at) = strftime('%Y-%m', 'now')"
        f" GROUP BY category ORDER BY spent_cents DESC",
        COMMITTED_STATUSES,
    ).fetchall()


def department_spend_summary(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Budget vs. committed spend for every department. Backs the finance overview."""
    return conn.execute(
        f"SELECT d.department_id, d.name, d.monthly_budget_cents,"
        f" COALESCE(SUM("
        f"   CASE WHEN e.status IN ({','.join('?' * len(COMMITTED_STATUSES))})"
        f"         AND strftime('%Y-%m', e.submitted_at) = strftime('%Y-%m', 'now')"
        f"        THEN e.amount_cents END"
        f" ), 0) AS committed_cents"
        f" FROM departments d"
        f" LEFT JOIN expenses e ON e.department_id = d.department_id"
        f" GROUP BY d.department_id ORDER BY d.name",
        COMMITTED_STATUSES,
    ).fetchall()
