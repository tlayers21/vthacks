"""Every transfer the app has caused, as one list.

Money moves in exactly two shapes -- corporate funding a department, and a department
reimbursing a person -- and they live in two tables. This is the only place they are read
together, which is what makes it the page finance actually watches.

Nessie is the audit trail, not the source of truth (docs/spec.md section 6), so the rows come
from our own tables and carry the Nessie transfer id rather than being read back out of it.
"""

import sqlite3

from db.funding import corporate_account_id

_LEDGER_SQL = """
SELECT 'allocation' AS kind,
       r.decided_at AS moved_at,
       ? AS payer_name,
       d.name AS payee_name,
       r.amount_cents AS amount_cents,
       'funding request ' || r.request_id AS reference,
       r.nessie_transfer_id AS nessie_transfer_id
FROM budget_requests r
JOIN departments d ON d.department_id = r.department_id
WHERE r.nessie_transfer_id IS NOT NULL

UNION ALL

-- An auto-approved expense has no decided_at, having never been decided by anyone
SELECT 'reimbursement' AS kind,
       COALESCE(e.decided_at, e.submitted_at) AS moved_at,
       d.name AS payer_name,
       c.name AS payee_name,
       e.amount_cents AS amount_cents,
       'expense ' || e.expense_id AS reference,
       e.nessie_transfer_id AS nessie_transfer_id
FROM expenses e
JOIN departments d ON d.department_id = e.department_id
JOIN customers c ON c.nessie_id = e.customer_id
WHERE e.nessie_transfer_id IS NOT NULL

ORDER BY moved_at DESC, nessie_transfer_id DESC
"""


def transaction_ledger(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every settled transfer, newest first."""
    return conn.execute(_LEDGER_SQL, (_corporate_name(conn),)).fetchall()


def _corporate_name(conn: sqlite3.Connection) -> str:
    """Whoever owns the corporate account, so the ledger never hardcodes the company name."""
    accounts = conn.execute("SELECT * FROM accounts").fetchall()
    customers = conn.execute("SELECT * FROM customers").fetchall()
    account_id = corporate_account_id(
        accounts, conn.execute("SELECT * FROM departments").fetchall(), customers
    )
    owners = {c["nessie_id"]: c["name"] for c in customers}
    for account in accounts:
        if account["nessie_id"] == account_id:
            return owners.get(account["customer_id"], "Corporate")
    return "Corporate"
