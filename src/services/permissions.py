"""Who can see and decide what.

Enforced here in code, never by asking the LLM or by trusting the request body.

Each role has exactly one job, and the checks below are the whole of it:
employees submit, managers decide and ask for funding, finance funds departments and watches.
Nobody does two of those.
"""

import sqlite3

Scope = str


class Forbidden(Exception):
    """The actor's role does not permit what they asked for."""


class InsufficientBudget(Exception):
    """The department cannot cover this without finance topping it up first."""

    def __init__(self, shortfall_cents: int) -> None:
        super().__init__(
            f"department is short {shortfall_cents} cents for this approval"
        )
        self.shortfall_cents = shortfall_cents


def visible_expense_filter(actor: sqlite3.Row, scope: Scope) -> dict:
    """Keyword arguments narrowing db.expenses.list_expenses to what `actor` may see."""
    role = actor["role"]

    if scope == "mine":
        return {"customer_id": actor["nessie_id"]}

    if scope == "dept":
        if role == "Finance":
            return {}  # finance has no department of its own, so dept means everything
        if role not in ("Manager", "Finance"):
            raise Forbidden("only managers and finance can see a whole department")
        return {"department_id": actor["department_id"]}

    if scope == "all":
        if role != "Finance":
            raise Forbidden("only finance can see every department")
        return {}

    raise Forbidden(f"unknown scope: {scope}")


def can_decide(actor: sqlite3.Row, expense: sqlite3.Row) -> bool:
    """Only the submitter's own manager. Finance funds departments and never judges a receipt."""
    if actor["role"] != "Manager":
        return False
    return actor["department_id"] == expense["department_id"]


def can_view(actor: sqlite3.Row, expense: sqlite3.Row) -> bool:
    """Finance sees every row without being able to act on one, so this is wider than can_decide."""
    return (
        actor["role"] == "Finance"
        or actor["nessie_id"] == expense["customer_id"]
        or can_decide(actor, expense)
    )


def can_submit(actor: sqlite3.Row) -> bool:
    """Only employees spend. A manager who could also submit would approve their own expenses."""
    return actor["role"] == "Employee" and actor["department_id"] is not None


def can_request_funding(actor: sqlite3.Row) -> bool:
    return actor["role"] == "Manager" and actor["department_id"] is not None


def can_decide_funding(actor: sqlite3.Row) -> bool:
    return actor["role"] == "Finance"


def default_scope(actor: sqlite3.Row) -> Scope:
    return {"Finance": "all", "Manager": "dept"}.get(actor["role"], "mine")
