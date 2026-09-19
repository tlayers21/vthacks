"""Who can see and decide what.

Enforced here in code, never by asking the LLM or by trusting the request body.
"""

import sqlite3

Scope = str


class Forbidden(Exception):
    """The actor's role does not permit what they asked for."""


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
    """Managers decide within their own department; finance decides anywhere."""
    if actor["role"] == "Finance":
        return True
    if actor["role"] != "Manager":
        return False
    return actor["department_id"] == expense["department_id"]


def can_view_expense(actor: sqlite3.Row, expense: sqlite3.Row) -> bool:
    """Its submitter, or anyone who could decide it. Also gates the receipt file."""
    return actor["nessie_id"] == expense["customer_id"] or can_decide(actor, expense)


def can_submit(actor: sqlite3.Row) -> bool:
    # The corporation and the department customers hold accounts but never submit anything
    return actor["department_id"] is not None


def default_scope(actor: sqlite3.Row) -> Scope:
    return {"Finance": "all", "Manager": "dept"}.get(actor["role"], "mine")
