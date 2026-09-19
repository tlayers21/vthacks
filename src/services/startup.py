"""Work the app does once, before it serves anything."""

import logging
import sqlite3

from db.budget_requests import allocated_cents
from db.funding import corporate_account_id, opening_balances

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
    departments = _departments_at_their_original_budget(conn)
    customers = conn.execute("SELECT * FROM customers").fetchall()
    names = {c["nessie_id"]: c["name"] for c in customers}

    # Transfer ids already in the database would otherwise be minted again from scratch
    nessie.reserve_ids(_settled_transfer_ids(conn))

    balances = opening_balances(accounts, departments, customers)
    moved = _already_transferred(
        conn, corporate_account_id(accounts, departments, customers)
    )

    for account in accounts:
        account_id = account["nessie_id"]
        nessie.seed_account(
            account_id=account_id,
            customer_id=account["customer_id"],
            nickname=names.get(account["customer_id"], ""),
            # Replay what the seeded transfers already moved, so a restart does not hand a
            # department back money it has spent
            balance_cents=balances[account_id] + moved.get(account_id, 0),
        )

    log.info("hydrated mock nessie with %d accounts", len(accounts))
    return len(accounts)


def _departments_at_their_original_budget(conn: sqlite3.Connection) -> list[dict]:
    """Department rows with finance's approved top-ups taken back out of the budget.

    monthly_budget_cents already contains every allocation finance has approved, and
    _already_transferred replays those same allocations as money arriving. Opening from the
    raised figure would count them twice, so the replay has to start where the month did.
    """
    allocated = allocated_cents(conn)
    return [
        {
            **dict(row),
            "monthly_budget_cents": row["monthly_budget_cents"]
            - allocated.get(row["department_id"], 0),
        }
        for row in conn.execute("SELECT * FROM departments")
    ]


def _settled_transfer_ids(conn: sqlite3.Connection):
    for table in ("expenses", "budget_requests"):
        for row in conn.execute(
            f"SELECT nessie_transfer_id FROM {table} WHERE nessie_transfer_id IS NOT NULL"
        ):
            yield row["nessie_transfer_id"]


def _already_transferred(
    conn: sqlite3.Connection, corporate_id: str | None
) -> dict[str, int]:
    """Net effect of every settled transfer, by account.

    Both shapes money moves in: a department reimbursing a person, and the corporation funding
    a department.
    """
    moves = list(
        conn.execute(
            "SELECT d.account_id AS payer_id, a.nessie_id AS payee_id, e.amount_cents"
            " FROM expenses e"
            " JOIN departments d ON d.department_id = e.department_id"
            " JOIN accounts a ON a.customer_id = e.customer_id"
            " WHERE e.nessie_transfer_id IS NOT NULL"
        )
    )
    if corporate_id is not None:
        moves += [
            {**dict(row), "payer_id": corporate_id}
            for row in conn.execute(
                "SELECT d.account_id AS payee_id, r.amount_cents FROM budget_requests r"
                " JOIN departments d ON d.department_id = r.department_id"
                " WHERE r.nessie_transfer_id IS NOT NULL"
            )
        ]

    net: dict[str, int] = {}
    for row in moves:
        net[row["payer_id"]] = net.get(row["payer_id"], 0) - row["amount_cents"]
        net[row["payee_id"]] = net.get(row["payee_id"], 0) + row["amount_cents"]
    return net
