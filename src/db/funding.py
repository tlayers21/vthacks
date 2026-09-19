"""Where each account's opening balance comes from.

One definition, two callers: db/seed.py opens accounts through Nessie with these balances, and
the app hydrates the in-memory mock with the same numbers at startup. If the rule lived in both
places they would drift and the mock would disagree with the database about who can afford what.

Works on any rows with the seed.sql column names -- the reference org loaded from seed.sql and
the rows read back out of app.db are shaped identically.
"""

from collections.abc import Sequence
from typing import Any

# The corporate account funds every department account, several times over
CORPORATE_FUNDING_MULTIPLE = 3


def corporate_account_id(
    accounts: Sequence[Any], departments: Sequence[Any], customers: Sequence[Any]
) -> str | None:
    """The account owned by the corporation itself -- not a department, not a person."""
    department_accounts = {d["account_id"] for d in departments}
    owners = {c["nessie_id"]: c for c in customers}
    for account in accounts:
        if account["nessie_id"] in department_accounts:
            continue
        owner = owners.get(account["customer_id"])
        if owner is None:
            continue
        if (
            owner["role"] == "Finance"
            and owner["department_id"] is None
            and "Corporation" in owner["name"]
        ):
            return account["nessie_id"]
    return None


def opening_balances(
    accounts: Sequence[Any], departments: Sequence[Any], customers: Sequence[Any]
) -> dict[str, int]:
    """account id -> opening balance in cents."""
    by_account = {d["account_id"]: d for d in departments}
    total_budgets = sum(d["monthly_budget_cents"] for d in departments)
    corporate = corporate_account_id(accounts, departments, customers)

    balances: dict[str, int] = {}
    for account in accounts:
        account_id = account["nessie_id"]
        if account_id in by_account:
            balances[account_id] = by_account[account_id]["monthly_budget_cents"]
        elif account_id == corporate:
            balances[account_id] = total_budgets * CORPORATE_FUNDING_MULTIPLE
        else:
            balances[account_id] = (
                0  # personal accounts start empty; reimbursements fund them
            )
    return balances
