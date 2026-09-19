"""Work the app does once, before it serves anything."""

import logging
import sqlite3

from db.funding import opening_balances

log = logging.getLogger(__name__)


def hydrate_mock_accounts(conn: sqlite3.Connection, nessie) -> int:
    """Teach the in-memory mock about the accounts already sitting in app.db.

    db/seed.py creates those accounts in its own process and then exits, and db/init_db.py
    never calls Nessie at all -- so without this the Flask process starts with a mock that has
    never heard of them, and the first auto-approved expense fails its payout.

    A no-op against the real client, which already knows its own accounts.
    """
    if not hasattr(nessie, "seed_account"):
        return 0

    accounts = conn.execute("SELECT * FROM accounts").fetchall()
    departments = conn.execute("SELECT * FROM departments").fetchall()
    customers = conn.execute("SELECT * FROM customers").fetchall()
    names = {c["nessie_id"]: c["name"] for c in customers}

    # Transfer ids already in the database would otherwise be minted again from scratch
    nessie.reserve_ids(
        row["nessie_transfer_id"]
        for row in conn.execute(
            "SELECT nessie_transfer_id FROM expenses WHERE nessie_transfer_id IS NOT NULL"
        )
    )

    balances = opening_balances(accounts, departments, customers)
    spent = _already_paid_out(conn)

    for account in accounts:
        account_id = account["nessie_id"]
        nessie.seed_account(
            account_id=account_id,
            customer_id=account["customer_id"],
            nickname=names.get(account["customer_id"], ""),
            # Replay what the seeded payouts already moved, so a restart does not hand a
            # department back money it has spent
            balance_cents=balances[account_id] + spent.get(account_id, 0),
        )

    log.info("hydrated mock nessie with %d accounts", len(accounts))
    return len(accounts)


def _already_paid_out(conn: sqlite3.Connection) -> dict[str, int]:
    """Net effect of every settled reimbursement, by account."""
    rows = conn.execute(
        "SELECT d.account_id AS payer_id, a.nessie_id AS payee_id, e.amount_cents"
        " FROM expenses e"
        " JOIN departments d ON d.department_id = e.department_id"
        " JOIN accounts a ON a.customer_id = e.customer_id"
        " WHERE e.nessie_transfer_id IS NOT NULL"
    ).fetchall()

    net: dict[str, int] = {}
    for row in rows:
        net[row["payer_id"]] = net.get(row["payer_id"], 0) - row["amount_cents"]
        net[row["payee_id"]] = net.get(row["payee_id"], 0) + row["amount_cents"]
    return net
