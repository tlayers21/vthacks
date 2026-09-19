"""Changing a spend rule.

Only finance gets here -- the routes check the role, and this layer checks the rule stays
coherent, so a bad pair comes back as a message rather than an IntegrityError from the CHECK.
"""

import sqlite3

from db import policies as policy_db
from db.connect import transaction
from policy import CATEGORIES, DbRuleSource, PolicyRule
from services.permissions import Forbidden


def rule_source(conn: sqlite3.Connection) -> DbRuleSource:
    """The live rule set. Every evaluation and every policy page goes through this."""
    return DbRuleSource(policy_db.rules_map(conn))


def save_rule(
    conn: sqlite3.Connection,
    actor: sqlite3.Row,
    *,
    department_id: int | None,
    category: str,
    per_expense_limit_cents: int,
    auto_approve_limit_cents: int,
) -> dict:
    _require_finance(actor)
    if category not in CATEGORIES:
        raise ValueError(f"unknown category: {category}")
    if auto_approve_limit_cents > per_expense_limit_cents:
        raise ValueError(
            "the auto-approve limit cannot exceed the per-expense limit, or nothing"
            " in between would ever reach a manager"
        )
    if department_id is not None:
        _require_department(conn, department_id)

    with transaction(conn):
        policy_db.upsert_rule(
            conn,
            department_id=department_id,
            category=category,
            per_expense_limit_cents=per_expense_limit_cents,
            auto_approve_limit_cents=auto_approve_limit_cents,
            updated_by=actor["nessie_id"],
        )

    return {
        "department_id": department_id,
        "category": category,
        "per_expense_limit_cents": per_expense_limit_cents,
        "auto_approve_limit_cents": auto_approve_limit_cents,
        "is_override": department_id is not None,
    }


def remove_rule(
    conn: sqlite3.Connection,
    actor: sqlite3.Row,
    *,
    department_id: int | None,
    category: str,
) -> dict:
    """Drop a department override. The category then inherits the org-wide rule again."""
    _require_finance(actor)
    if department_id is None:
        raise ValueError(
            "org-wide rules cannot be removed, only edited -- removing one would drop the"
            " category to a hidden fallback instead of a limit you can see"
        )

    with transaction(conn):
        removed = policy_db.delete_rule(conn, department_id, category)
    if not removed:
        raise KeyError(f"{category} has no override for department {department_id}")

    # What the category falls back to, so the caller can redraw the row without a reload
    inherited: PolicyRule = rule_source(conn).rule_for(department_id, category)
    return {
        "department_id": department_id,
        "category": category,
        "per_expense_limit_cents": inherited.per_expense_limit_cents,
        "auto_approve_limit_cents": inherited.auto_approve_limit_cents,
        "is_override": False,
    }


def _require_finance(actor: sqlite3.Row) -> None:
    if actor["role"] != "Finance":
        raise Forbidden("only finance can change spend policy")


def _require_department(conn: sqlite3.Connection, department_id: int) -> None:
    exists = conn.execute(
        "SELECT 1 FROM departments WHERE department_id = ?", (department_id,)
    ).fetchone()
    if exists is None:
        raise KeyError(f"no such department: {department_id}")
