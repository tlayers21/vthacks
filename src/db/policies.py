"""Every SQL statement that touches spend rules.

Kept out of policy/ so that package stays pure, and out of services/ so the rule that only
db/ executes SQL keeps holding.
"""

import sqlite3

from policy import PolicyRule

_COLUMNS = (
    "policy_id, department_id, category,"
    " per_expense_limit_cents, auto_approve_limit_cents, updated_by, updated_at"
)


def rules_map(
    conn: sqlite3.Connection,
) -> dict[tuple[int | None, str], PolicyRule]:
    """The whole rule set, keyed the way a RuleSource resolves it.

    Loaded in one query rather than per lookup: an expense preview resolves one category, but
    the policy table renders ten, and the set is a couple of dozen rows at most.
    """
    rows = conn.execute(
        "SELECT department_id, category,"
        " per_expense_limit_cents, auto_approve_limit_cents FROM policy_rules"
    ).fetchall()
    return {
        (row["department_id"], row["category"]): PolicyRule(
            per_expense_limit_cents=row["per_expense_limit_cents"],
            auto_approve_limit_cents=row["auto_approve_limit_cents"],
        )
        for row in rows
    }


def list_rules(
    conn: sqlite3.Connection, department_id: int | None = None
) -> list[sqlite3.Row]:
    """Rows written for one department, or the org-wide set when department_id is None.

    `IS ?` rather than `= ?` so NULL matches NULL -- the org-wide rows would otherwise be
    unreachable, since `department_id = NULL` is never true in SQL.
    """
    return conn.execute(
        f"SELECT {_COLUMNS} FROM policy_rules WHERE department_id IS ?"
        " ORDER BY category",
        (department_id,),
    ).fetchall()


def get_rule(
    conn: sqlite3.Connection, department_id: int | None, category: str
) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT {_COLUMNS} FROM policy_rules"
        " WHERE department_id IS ? AND category = ?",
        (department_id, category),
    ).fetchone()


def upsert_rule(
    conn: sqlite3.Connection,
    department_id: int | None,
    category: str,
    per_expense_limit_cents: int,
    auto_approve_limit_cents: int,
    updated_by: str | None,
) -> None:
    """Create the rule or replace it. Adding an override and editing one are the same write.

    ON CONFLICT cannot be used here: the uniqueness is enforced by two partial indexes, and
    SQLite will not match a conflict target against a partial index. An explicit UPDATE then
    INSERT is the honest version, and callers already hold a transaction.
    """
    updated = conn.execute(
        "UPDATE policy_rules SET per_expense_limit_cents = ?,"
        " auto_approve_limit_cents = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP"
        " WHERE department_id IS ? AND category = ?",
        (
            per_expense_limit_cents,
            auto_approve_limit_cents,
            updated_by,
            department_id,
            category,
        ),
    ).rowcount
    if updated:
        return

    conn.execute(
        "INSERT INTO policy_rules (department_id, category,"
        " per_expense_limit_cents, auto_approve_limit_cents, updated_by)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            department_id,
            category,
            per_expense_limit_cents,
            auto_approve_limit_cents,
            updated_by,
        ),
    )


def delete_rule(
    conn: sqlite3.Connection, department_id: int, category: str
) -> bool:
    """Drop a department override so the category falls back to the org-wide rule.

    department_id is not optional: deleting an org-wide rule would drop the category through
    to the hardcoded ORG_FALLBACK, which is a confusing way to change a limit. The service
    refuses that before it reaches here.
    """
    deleted = conn.execute(
        "DELETE FROM policy_rules WHERE department_id IS ? AND category = ?",
        (department_id, category),
    ).rowcount
    return bool(deleted)
