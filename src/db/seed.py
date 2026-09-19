"""Build the fake organization through the Nessie API.

seed.sql is the single source of truth for who exists. This script loads it into a
throwaway in-memory database, replays that org through Nessie (mock or real), and writes
the ids Nessie hands back into app.db. Nobody maintains the org in two places.

    python db/seed.py                  # NESSIE_MODE from .env (defaults to mock)
    python db/seed.py --mode real      # create real customers/accounts in the sandbox
    python db/seed.py --reset          # rebuild app.db, and reclaim the sandbox first

`--reset` also deletes the accounts a previous run left in the Nessie sandbox and reuses
its customers, so re-seeding does not strand a fresh set every time. See reclaim_sandbox.

Offline alternative, no Nessie at all:

    python db/init_db.py               # loads schema.sql + seed.sql verbatim
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from db.connect import connect, transaction  # noqa: E402
from db.funding import opening_balances  # noqa: E402
from nessie import get_nessie  # noqa: E402
from services.receipts import install_samples  # noqa: E402

SQL_DIR = Path(__file__).parent
SCHEMA = SQL_DIR / "schema.sql"
SEED = SQL_DIR / "seed.sql"


def load_reference_org() -> dict:
    """Run schema.sql + seed.sql into :memory: and read the org back out."""
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    mem.execute("PRAGMA foreign_keys = ON")
    mem.executescript(SCHEMA.read_text())
    mem.executescript(SEED.read_text())

    org = {
        "customers": [dict(r) for r in mem.execute("SELECT * FROM customers")],
        "accounts": [dict(r) for r in mem.execute("SELECT * FROM accounts")],
        "departments": [dict(r) for r in mem.execute("SELECT * FROM departments")],
        "budget_requests": [
            dict(r) for r in mem.execute("SELECT * FROM budget_requests")
        ],
        "expenses": [dict(r) for r in mem.execute("SELECT * FROM expenses")],
        "expense_violations": [
            dict(r) for r in mem.execute("SELECT * FROM expense_violations")
        ],
<<<<<<< HEAD
        "receipt_readings": [
            dict(r) for r in mem.execute("SELECT * FROM receipt_readings")
        ],
        "expense_flags": [dict(r) for r in mem.execute("SELECT * FROM expense_flags")],
=======
        "policy_rules": [dict(r) for r in mem.execute("SELECT * FROM policy_rules")],
>>>>>>> 08d74469fe20bb43266181098afee88b8f061d86
    }
    mem.close()
    return org


def split_name(full_name: str) -> tuple[str, str]:
    first, _, last = full_name.partition(" ")
    return first, last or first


def opening_balance(account_id: str, org: dict) -> int:
    """Department accounts open at their monthly budget; corporate covers them all."""
    balances = opening_balances(org["accounts"], org["departments"], org["customers"])
    return balances[account_id]


def reclaim_sandbox(nessie, org: dict) -> dict[tuple[str, str], str]:
    """Delete accounts left by previous runs and return reusable customers, keyed by name.

    The sandbox is shared and append-only: it has no delete route for customers, so every
    re-seed used to strand another 18 of them (we found 130, seven copies of each name).
    Accounts *can* be deleted, and they are what actually carries state -- balance,
    nickname, transfers -- so we drop those and adopt the existing customer shells.
    Net effect: customers stop multiplying and accounts stay at exactly one per customer.
    """
    wanted = {split_name(c["name"]) for c in org["customers"]}
    reusable: dict[tuple[str, str], str] = {}
    deleted = 0

    for customer in nessie.list_customers():
        key = (customer["first_name"], customer["last_name"])
        if key not in wanted:
            continue
        for account in nessie.list_accounts(customer["id"]):
            nessie.delete_account(account["id"])
            deleted += 1
        # First match wins; later duplicates are stranded but now account-free
        reusable.setdefault(key, customer["id"])

    if deleted or reusable:
        print(
            f"reclaimed sandbox: deleted {deleted} accounts, reusing {len(reusable)} customers"
        )
    return reusable


def seed(mode: str | None = None, reset: bool = False) -> None:
    org = load_reference_org()
    install_samples()
    nessie = get_nessie(mode)

    if reset and settings.db_path.exists():
        settings.db_path.unlink()
        print(f"removed {settings.db_path}")

    conn = connect()
    fresh = not conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='customers'"
    ).fetchone()
    if fresh:
        conn.executescript(SCHEMA.read_text())
    elif conn.execute("SELECT 1 FROM customers LIMIT 1").fetchone():
        print("app.db already has customers; nothing to do. Re-run with --reset.")
        conn.close()
        return

    # seed.sql id -> the id Nessie actually issued
    customer_ids: dict[str, str] = {}
    account_ids: dict[str, str] = {}

    reusable = reclaim_sandbox(nessie, org) if reset else {}

    with transaction(conn):
        for customer in org["customers"]:
            first, last = split_name(customer["name"])
            existing = reusable.get((first, last))
            created = (
                {"id": existing} if existing else nessie.create_customer(first, last)
            )
            customer_ids[customer["nessie_id"]] = created["id"]
            conn.execute(
                "INSERT INTO customers (nessie_id, name, role, department_id)"
                " VALUES (?, ?, ?, NULL)",
                (created["id"], customer["name"], customer["role"]),
            )

        for account in org["accounts"]:
            owner = customer_ids[account["customer_id"]]
            owner_name = next(
                c["name"]
                for c in org["customers"]
                if c["nessie_id"] == account["customer_id"]
            )
            created = nessie.create_account(
                customer_id=owner,
                nickname=owner_name,
                balance_cents=opening_balance(account["nessie_id"], org),
            )
            account_ids[account["nessie_id"]] = created["id"]
            conn.execute(
                "INSERT INTO accounts (nessie_id, customer_id) VALUES (?, ?)",
                (created["id"], owner),
            )

        for department in org["departments"]:
            conn.execute(
                "INSERT INTO departments"
                " (department_id, name, monthly_budget_cents, account_id)"
                " VALUES (?, ?, ?, ?)",
                (
                    department["department_id"],
                    department["name"],
                    department["monthly_budget_cents"],
                    account_ids[department["account_id"]],
                ),
            )

        # Departments exist now, so people can be attached to them.
        for customer in org["customers"]:
            if customer["department_id"] is not None:
                conn.execute(
                    "UPDATE customers SET department_id = ? WHERE nessie_id = ?",
                    (customer["department_id"], customer_ids[customer["nessie_id"]]),
                )

        # No seeded request is Approved, so none of them carries a transfer to replay
        for request in org["budget_requests"]:
            conn.execute(
                "INSERT INTO budget_requests"
                " (request_id, customer_id, department_id, amount_cents, reason, status,"
                "  decided_by, decided_at, decision_note)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request["request_id"],
                    customer_ids[request["customer_id"]],
                    request["department_id"],
                    request["amount_cents"],
                    request["reason"],
                    request["status"],
                    customer_ids[request["decided_by"]]
                    if request["decided_by"]
                    else None,
                    request["decided_at"],
                    request["decision_note"],
                ),
            )

        # department_id and expense_id stay verbatim: department ids are explicit integers that
        # are never remapped, and expense_violations references expense_id.
        # submitted_at is left to default so seeded rows always land in the current month.
        for expense in org["expenses"]:
            conn.execute(
                "INSERT INTO expenses"
                " (expense_id, customer_id, department_id, amount_cents, category, merchant,"
                "  description, status, policy_decision, decided_by, decided_at,"
                "  decision_note, receipt_check,"
                "  receipt_path, receipt_filename, receipt_mime, receipt_hash)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    expense["expense_id"],
                    customer_ids[expense["customer_id"]],
                    expense["department_id"],
                    expense["amount_cents"],
                    expense["category"],
                    expense["merchant"],
                    expense["description"],
                    expense["status"],
                    expense["policy_decision"],
                    customer_ids[expense["decided_by"]]
                    if expense["decided_by"]
                    else None,
                    expense["decided_at"],
                    expense["decision_note"],
                    expense["receipt_check"],
                    expense["receipt_path"],
                    expense["receipt_filename"],
                    expense["receipt_mime"],
                    expense["receipt_hash"],
                ),
            )

<<<<<<< HEAD
        # Keyed by receipt_hash, which is never remapped -- it is the file's own sha256
        for reading in org["receipt_readings"]:
            conn.execute(
                "INSERT INTO receipt_readings"
                " (receipt_hash, status, merchant, total_cents, receipt_date, line_items,"
                "  model) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    reading["receipt_hash"],
                    reading["status"],
                    reading["merchant"],
                    reading["total_cents"],
                    reading["receipt_date"],
                    reading["line_items"],
                    reading["model"],
                ),
            )

        for flag in org["expense_flags"]:
            conn.execute(
                "INSERT INTO expense_flags (flag_id, expense_id, flag, message)"
                " VALUES (?, ?, ?, ?)",
                (
                    flag["flag_id"],
                    flag["expense_id"],
                    flag["flag"],
                    flag["message"],
=======
        # department_id is an explicit integer that is never remapped, and updated_by is NULL
        # on seeded rows -- nobody edited them, they are what the database ships with
        for rule in org["policy_rules"]:
            conn.execute(
                "INSERT INTO policy_rules (department_id, category,"
                " per_expense_limit_cents, auto_approve_limit_cents) VALUES (?, ?, ?, ?)",
                (
                    rule["department_id"],
                    rule["category"],
                    rule["per_expense_limit_cents"],
                    rule["auto_approve_limit_cents"],
>>>>>>> 08d74469fe20bb43266181098afee88b8f061d86
                ),
            )

        for violation in org["expense_violations"]:
            conn.execute(
                "INSERT INTO expense_violations"
                " (violation_id, expense_id, rule, severity, message) VALUES (?, ?, ?, ?, ?)",
                (
                    violation["violation_id"],
                    violation["expense_id"],
                    violation["rule"],
                    violation["severity"],
                    violation["message"],
                ),
            )

    _replay_payouts(conn, org, nessie, customer_ids, account_ids)

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"foreign key violations after seeding: {violations}")

    print(
        f"seeded via nessie ({mode or settings.nessie_mode}): "
        f"{len(org['customers'])} customers, {len(org['accounts'])} accounts, "
        f"{len(org['departments'])} departments, "
        f"{len(org['budget_requests'])} budget requests, "
        f"{len(org['expenses'])} expenses, "
        f"{len(org['expense_violations'])} violations, "
<<<<<<< HEAD
        f"{len(org['expense_flags'])} receipt flags -> {settings.db_path}"
=======
        f"{len(org['policy_rules'])} policy rules -> {settings.db_path}"
>>>>>>> 08d74469fe20bb43266181098afee88b8f061d86
    )
    conn.close()


def _replay_payouts(
    conn, org: dict, nessie, customer_ids: dict, account_ids: dict
) -> None:
    """Move the money behind every seeded `paid` expense.

    Without this a paid row would carry a transfer id Nessie never issued, and both the retry
    guard and the transfer log would be lying about money that never moved.
    """
    account_by_customer = {a["customer_id"]: a["nessie_id"] for a in org["accounts"]}
    department_accounts = {
        d["department_id"]: d["account_id"] for d in org["departments"]
    }

    with transaction(conn):
        for expense in org["expenses"]:
            if expense["status"] != "paid":
                continue
            payer = account_ids[department_accounts[expense["department_id"]]]
            payee = account_ids[account_by_customer[expense["customer_id"]]]
            transfer = nessie.create_transfer(
                payer_id=payer,
                payee_id=payee,
                amount_cents=expense["amount_cents"],
                description=f"expense {expense['expense_id']}",
            )
            conn.execute(
                "UPDATE expenses SET nessie_transfer_id = ? WHERE expense_id = ?",
                (transfer["id"], expense["expense_id"]),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["mock", "real"], default=None)
    parser.add_argument(
        "--reset", action="store_true", help="delete app.db and rebuild from scratch"
    )
    args = parser.parse_args()
    seed(mode=args.mode, reset=args.reset)


if __name__ == "__main__":
    main()
