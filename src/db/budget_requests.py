"""Every SQL statement that touches funding requests.

Kept out of services/ so the rule that only db/ executes SQL keeps holding. The shape mirrors
db/expenses.py on purpose -- a funding request is the same story one level up, with the
corporation paying a department instead of a department paying a person.
"""

import sqlite3

from db.funding import corporate_account_id

_LIST_SQL = """
SELECT r.*, c.name AS requester_name, d.name AS department_name,
       d.monthly_budget_cents, decider.name AS decider_name
FROM budget_requests r
JOIN customers c ON c.nessie_id = r.customer_id
JOIN departments d ON d.department_id = r.department_id
LEFT JOIN customers decider ON decider.nessie_id = r.decided_by
"""


def insert_request(
    conn: sqlite3.Connection,
    customer_id: str,
    department_id: int,
    amount_cents: int,
    reason: str | None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO budget_requests"
        " (customer_id, department_id, amount_cents, reason, status)"
        " VALUES (?, ?, ?, ?, 'Pending')",
        (customer_id, department_id, amount_cents, reason),
    )
    request_id = cursor.lastrowid
    assert request_id is not None
    return request_id


def get_request(conn: sqlite3.Connection, request_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM budget_requests WHERE request_id = ?", (request_id,)
    ).fetchone()


def list_requests(
    conn: sqlite3.Connection,
    status: str | None = None,
    department_id: int | None = None,
    customer_id: str | None = None,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list = []
    if status is not None:
        clauses.append("r.status = ?")
        params.append(status)
    if department_id is not None:
        clauses.append("r.department_id = ?")
        params.append(department_id)
    if customer_id is not None:
        clauses.append("r.customer_id = ?")
        params.append(customer_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return conn.execute(
        f"{_LIST_SQL}{where} ORDER BY r.request_id DESC", params
    ).fetchall()


def pending_count(conn: sqlite3.Connection) -> int:
    """Requests waiting on finance. Backs the count badge on the finance nav."""
    return conn.execute(
        "SELECT COUNT(*) AS n FROM budget_requests WHERE status = 'Pending'"
    ).fetchone()["n"]


def record_decision(
    conn: sqlite3.Connection,
    request_id: int,
    status: str,
    decided_by: str,
    note: str | None = None,
) -> None:
    conn.execute(
        "UPDATE budget_requests SET status = ?, decided_by = ?,"
        " decided_at = CURRENT_TIMESTAMP, decision_note = ? WHERE request_id = ?",
        (status, decided_by, note, request_id),
    )


def set_transfer_id(
    conn: sqlite3.Connection, request_id: int, transfer_id: str
) -> None:
    # The NULL guard makes a concurrent second approval a no-op rather than an overwrite
    conn.execute(
        "UPDATE budget_requests SET nessie_transfer_id = ?"
        " WHERE request_id = ? AND nessie_transfer_id IS NULL",
        (transfer_id, request_id),
    )


def raise_budget(
    conn: sqlite3.Connection, department_id: int, amount_cents: int
) -> None:
    conn.execute(
        "UPDATE departments SET monthly_budget_cents = monthly_budget_cents + ?"
        " WHERE department_id = ?",
        (amount_cents, department_id),
    )


def allocation_accounts(conn: sqlite3.Connection, request_id: int) -> tuple[str, str]:
    """(corporate account, department account) for a request's allocation transfer."""
    row = conn.execute(
        "SELECT d.account_id AS payee_id FROM budget_requests r"
        " JOIN departments d ON d.department_id = r.department_id"
        " WHERE r.request_id = ?",
        (request_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"no allocation accounts for request {request_id}")

    payer_id = corporate_account_id(
        conn.execute("SELECT * FROM accounts").fetchall(),
        conn.execute("SELECT * FROM departments").fetchall(),
        conn.execute("SELECT * FROM customers").fetchall(),
    )
    if payer_id is None:
        raise KeyError("no corporate account to fund departments from")
    return payer_id, row["payee_id"]


def allocated_cents(conn: sqlite3.Connection) -> dict[int, int]:
    """department_id -> money finance has added to its budget through approved requests.

    Subtracting this from monthly_budget_cents recovers the budget the department started with,
    which is what a balance replay has to open from -- see services/startup.py.
    """
    rows = conn.execute(
        "SELECT department_id, SUM(amount_cents) AS allocated_cents"
        " FROM budget_requests WHERE status = 'Approved' AND nessie_transfer_id IS NOT NULL"
        " GROUP BY department_id"
    ).fetchall()
    return {row["department_id"]: row["allocated_cents"] for row in rows}
