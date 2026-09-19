"""Per-request wiring: the database connection, the Nessie client, and who is asking."""

import sqlite3

from flask import current_app, g, session

from db.connect import connect


def get_conn() -> sqlite3.Connection:
    if "conn" not in g:
        factory = current_app.config.get("CONN_FACTORY") or connect
        g.conn = factory()
    return g.conn


def get_nessie():
    return current_app.config["NESSIE"]


def close_conn(_exc=None) -> None:
    conn = g.pop("conn", None)
    # Tests hand in a shared connection they still need afterwards
    if conn is not None and not current_app.config.get("KEEP_CONN"):
        conn.close()


def current_user() -> sqlite3.Row | None:
    """The acting user, from the session cookie only -- never from the request body."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return (
        get_conn()
        .execute("SELECT * FROM customers WHERE nessie_id = ?", (user_id,))
        .fetchone()
    )


def switchable_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """People the role switcher offers. Excludes the corporate and department pseudo-customers."""
    return conn.execute(
        "SELECT c.*, d.name AS department_name FROM customers c"
        " LEFT JOIN departments d ON d.department_id = c.department_id"
        " WHERE c.department_id IS NOT NULL OR c.name = 'Dana Whitfield'"
        " ORDER BY CASE c.role WHEN 'Finance' THEN 0 WHEN 'Manager' THEN 1 ELSE 2 END, c.name"
    ).fetchall()
