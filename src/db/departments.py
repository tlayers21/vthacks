"""SQL for departments themselves.

Spend *against* a department lives in db/expenses.py -- this is the department row.
"""

import sqlite3


def list_departments(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT d.*, editor.name AS budget_updated_by_name"
        " FROM departments d"
        " LEFT JOIN customers editor ON editor.nessie_id = d.budget_updated_by"
        " ORDER BY d.name"
    ).fetchall()


def get_department(conn: sqlite3.Connection, department_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM departments WHERE department_id = ?", (department_id,)
    ).fetchone()


def set_budget(
    conn: sqlite3.Connection,
    department_id: int,
    monthly_budget_cents: int,
    updated_by: str | None,
) -> None:
    """Set the ceiling outright.

    An absolute value, not a delta -- unlike raise_budget in db/budget_requests.py, which
    adds an approved allocation. Finance is stating what the budget now is.
    """
    conn.execute(
        "UPDATE departments SET monthly_budget_cents = ?, budget_updated_by = ?,"
        " budget_updated_at = CURRENT_TIMESTAMP WHERE department_id = ?",
        (monthly_budget_cents, updated_by, department_id),
    )
