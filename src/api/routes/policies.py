"""Reading the rules, and dry-running them.

Rules are code, so there is no write route here -- changing a limit is a deploy.
"""

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from api.deps import current_user, get_conn
from api.schemas import ExpenseIn
from db import expenses as expense_db
from policy import ExpenseDraft, resolved_rules
from services.expenses import preview_expense

bp = Blueprint("policies", __name__, url_prefix="/api/policies")


@bp.get("")
def list_policies():
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401

    requested = request.args.get("department_id", type=int)
    department_id = requested if requested is not None else actor["department_id"]
    if department_id is None:
        return jsonify(error="specify a department_id"), 400

    return jsonify(
        department_id=department_id,
        source="code",  # policy/rules.py, not a table
        rules=[
            {
                "category": category,
                "per_expense_limit_cents": rule.per_expense_limit_cents,
                "auto_approve_limit_cents": rule.auto_approve_limit_cents,
            }
            for category, rule in resolved_rules(department_id).items()
        ],
    )


@bp.post("/preview")
def preview():
    """What would happen to this expense, without writing a row."""
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401
    if actor["department_id"] is None:
        return jsonify(error="this account cannot submit expenses"), 403
    try:
        payload = ExpenseIn.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify(
            error="invalid expense", detail=exc.errors(include_url=False)
        ), 400

    draft = ExpenseDraft(
        customer_id=actor["nessie_id"],
        department_id=actor["department_id"],
        amount_cents=payload.amount_cents,
        category=payload.category,
        merchant=payload.merchant,
        description=payload.description,
    )
    result = preview_expense(get_conn(), draft)
    return jsonify(
        decision=result.decision,
        violations=[v.as_dict() for v in result.violations],
    )


@bp.get("/budgets")
def budgets():
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401
    rows = expense_db.department_spend_summary(get_conn())
    return jsonify(departments=[dict(r) for r in rows])
