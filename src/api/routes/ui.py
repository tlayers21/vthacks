"""The rendered pages.

Server-rendered rather than the spec's React front end: there is no node toolchain in this repo,
and the pages only need a fetch call or two to feel live.

Every page a role should not reach is guarded here, not just hidden from the nav in base.html.
"""

from pathlib import Path

from flask import Blueprint, current_app, redirect, render_template, request

from api.deps import actor_with_role, current_user, get_conn, switchable_users
from db import budget_requests as request_db
from db import expenses as expense_db
from db.ledger import transaction_ledger
from policy import (
    CATEGORIES,
    RECEIPT_REQUIRED_OVER_CENTS,
    overridden_categories,
    resolved_rules,
)
from services.permissions import can_submit, default_scope, visible_expense_filter

bp = Blueprint("ui", __name__)


@bp.app_context_processor
def inject_user():
    """Every page needs the switcher and the acting user."""
    conn = get_conn()
    actor = current_user()
    return {
        "actor": actor,
        "switchable_users": switchable_users(conn),
        "categories": CATEGORIES,
        "may_submit": actor is not None and can_submit(actor),
    }


@bp.app_context_processor
def inject_brand():
    """Which files are actually sitting in static/brand, by stem.

    Templates check membership before linking one, so an empty folder falls back to the built-in
    mark rather than serving a broken image. Dropping a PNG in is the whole install step.
    """
    folder = Path(current_app.static_folder) / "brand"
    return {
        "brand_assets": {p.stem for p in folder.glob("*.png")}
        if folder.is_dir()
        else set()
    }


@bp.get("/")
def home():
    actor = current_user()
    if actor is None:
        return render_template("index.html")
    if actor["role"] == "Finance":
        return redirect("/finance")
    if actor["role"] == "Manager":
        return redirect("/approvals")
    return redirect("/expenses/new")


@bp.get("/expenses/new")
def new_expense():
    actor = current_user()
    if actor is None or not can_submit(actor):
        return redirect("/")
    budget = expense_db.department_budget(get_conn(), actor["department_id"])
    # Passed through so the form can gate its own submit button without waiting for the
    # debounced preview, and without hardcoding a second copy of the threshold
    return render_template(
        "new_expense.html",
        budget=budget,
        receipt_threshold_cents=RECEIPT_REQUIRED_OVER_CENTS,
    )


@bp.get("/expenses/mine")
def my_expenses():
    actor = current_user()
    if actor is None:
        return redirect("/")
    return render_template(
        "expenses.html", **_expense_view(actor, "mine"), title="My expenses"
    )


@bp.get("/approvals")
def approvals():
    actor = actor_with_role("Manager")
    if actor is None:
        return redirect("/")
    conn = get_conn()
    filters = visible_expense_filter(actor, default_scope(actor))
    rows = expense_db.list_expenses(conn, statuses=("needs_approval",), **filters)
    violations = expense_db.violations_for(conn, [r["expense_id"] for r in rows])
    return render_template(
        "approvals.html",
        expenses=rows,
        violations=violations,
        budget=expense_db.department_budget(conn, actor["department_id"]),
    )


@bp.get("/funding")
def funding():
    """Managers ask here, finance answers here."""
    actor = actor_with_role("Manager", "Finance")
    if actor is None:
        return redirect("/")
    conn = get_conn()
    if actor["role"] == "Finance":
        return render_template(
            "funding.html",
            pending=request_db.list_requests(conn, status="Pending"),
            history=[
                r for r in request_db.list_requests(conn) if r["status"] != "Pending"
            ],
            departments=expense_db.department_spend_summary(conn),
        )
    return render_template(
        "funding.html",
        mine=request_db.list_requests(conn, department_id=actor["department_id"]),
        budget=expense_db.department_budget(conn, actor["department_id"]),
    )


@bp.get("/transactions")
def transactions():
    """Every settled transfer, which is the whole of what finance does besides funding."""
    if actor_with_role("Finance") is None:
        return redirect("/")
    return render_template("transactions.html", ledger=transaction_ledger(get_conn()))


@bp.get("/finance")
def finance():
    """Department budgets against this month's committed spend."""
    if actor_with_role("Finance") is None:
        return redirect("/")
    conn = get_conn()
    return render_template(
        "finance.html",
        departments=expense_db.department_spend_summary(conn),
        categories_spend=expense_db.category_spend_summary(conn),
        pending=expense_db.list_expenses(conn, statuses=("needs_approval",)),
        pending_funding=request_db.list_requests(conn, status="Pending"),
        customers=conn.execute(
            "SELECT c.name AS customer_name, c.role, d.name AS department_name"
            " FROM customers c JOIN departments d ON c.department_id = d.department_id"
        ).fetchall(),
    )


@bp.get("/policies")
def policies_page():
    actor = current_user()
    requested = request.args.get("department_id", type=int)
    department_id = requested or (actor["department_id"] if actor else None) or 1
    conn = get_conn()
    departments = conn.execute(
        "SELECT department_id, name FROM departments ORDER BY name"
    ).fetchall()
    return render_template(
        "policies.html",
        departments=departments,
        department_id=department_id,
        rules=resolved_rules(department_id),
        overrides=overridden_categories(department_id),
    )


@bp.get("/expenses/all")
def all_expenses():
    actor = actor_with_role("Manager", "Finance")
    if actor is None:
        return redirect("/")
    scope = default_scope(actor)
    return render_template(
        "expenses.html", **_expense_view(actor, scope), title="All expenses"
    )


def _expense_view(actor, scope: str) -> dict:
    conn = get_conn()
    rows = expense_db.list_expenses(conn, **visible_expense_filter(actor, scope))
    return {
        "expenses": rows,
        "violations": expense_db.violations_for(conn, [r["expense_id"] for r in rows]),
    }
