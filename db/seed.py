"""Build the fake organization through the Nessie API.

seed.sql is the single source of truth for who exists. This script loads it into a
throwaway in-memory database, replays that org through Nessie (mock or real), and writes
the ids Nessie hands back into app.db. Nobody maintains the org in two places.

    python db/seed.py                  # NESSIE_MODE from .env (defaults to mock)
    python db/seed.py --mode real      # create real customers/accounts in the sandbox
    python db/seed.py --reset          # drop and rebuild app.db first

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
from nessie import get_nessie  # noqa: E402

SQL_DIR = Path(__file__).parent
SCHEMA = SQL_DIR / "schema.sql"
SEED = SQL_DIR / "seed.sql"

# The corporate account funds the department accounts, so it starts with enough to cover
# every department's monthly budget several times over.
CORPORATE_FUNDING_MULTIPLE = 3


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
        "budget_requests": [dict(r) for r in mem.execute("SELECT * FROM budget_requests")],
    }
    mem.close()
    return org


def split_name(full_name: str) -> tuple[str, str]:
    first, _, last = full_name.partition(" ")
    return first, last or first


def opening_balance(account_id: str, org: dict) -> int:
    """Department accounts open at their monthly budget; corporate covers them all."""
    by_account = {d["account_id"]: d for d in org["departments"]}
    if account_id in by_account:
        return by_account[account_id]["monthly_budget_cents"]

    total_budgets = sum(d["monthly_budget_cents"] for d in org["departments"])
    corporate_account = _corporate_account_id(org)
    if account_id == corporate_account:
        return total_budgets * CORPORATE_FUNDING_MULTIPLE
    return 0  # personal accounts start empty; reimbursements fund them


def _corporate_account_id(org: dict) -> str | None:
    """The account whose owner is the corporation itself (not a department, not a person)."""
    department_accounts = {d["account_id"] for d in org["departments"]}
    owners = {c["nessie_id"]: c for c in org["customers"]}
    for account in org["accounts"]:
        if account["nessie_id"] in department_accounts:
            continue
        owner = owners[account["customer_id"]]
        if owner["role"] == "Finance" and owner["department_id"] is None:
            if "Corporation" in owner["name"]:
                return account["nessie_id"]
    return None


def seed(mode: str | None = None, reset: bool = False) -> None:
    org = load_reference_org()
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

    with transaction(conn):
        for customer in org["customers"]:
            first, last = split_name(customer["name"])
            created = nessie.create_customer(first, last)
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

        for request in org["budget_requests"]:
            conn.execute(
                "INSERT INTO budget_requests"
                " (request_id, customer_id, amount_cents, status) VALUES (?, ?, ?, ?)",
                (
                    request["request_id"],
                    customer_ids[request["customer_id"]],
                    request["amount_cents"],
                    request["status"],
                ),
            )

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"foreign key violations after seeding: {violations}")

    print(
        f"seeded via nessie ({mode or settings.nessie_mode}): "
        f"{len(org['customers'])} customers, {len(org['accounts'])} accounts, "
        f"{len(org['departments'])} departments, "
        f"{len(org['budget_requests'])} budget requests -> {settings.db_path}"
    )
    conn.close()


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
