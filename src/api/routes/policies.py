"""Reading the rules, dry-running them, and -- for finance only -- changing them.

Every write checks the role here in the route. The policies page hides its Save buttons from
everyone else, but hiding a control is decoration, not a permission.
"""

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from api.deps import actor_with_role, current_user, get_conn
from api.schemas import ExpenseIn, PolicyRuleIn
from db import expenses as expense_db
from db import policies as policy_db
from policy import ExpenseDraft, resolved_rules
from services import policies as policy_service
from services.expenses import preview_expense
from services.permissions import Forbidden

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

    conn = get_conn()
    overrides = {r["category"] for r in policy_db.list_rules(conn, department_id)}
    return jsonify(
        department_id=department_id,
        source="database",  # policy_rules, editable by finance
        rules=[
            {
                "category": category,
                "per_expense_limit_cents": rule.per_expense_limit_cents,
                "auto_approve_limit_cents": rule.auto_approve_limit_cents,
                "is_override": category in overrides,
            }
            for category, rule in resolved_rules(
                department_id, policy_service.rule_source(conn)
            ).items()
        ],
    )


@bp.put("/<category>")
def save_policy(category: str):
    """Upsert, which is what makes add and edit the same request with different prior state."""
    actor = actor_with_role("Finance")
    if actor is None:
        return jsonify(error="only finance can change spend policy"), 403
    try:
        payload = PolicyRuleIn.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        # include_context=False matters: a model_validator puts the raw ValueError in the
        # context, and jsonify cannot serialize it -- the 400 would come back as a 500
        return jsonify(
            error="invalid policy",
            detail=exc.errors(include_url=False, include_context=False),
        ), 400

    try:
        result = policy_service.save_rule(
            get_conn(),
            actor,
            department_id=payload.department_id,
            category=category,
            per_expense_limit_cents=payload.per_expense_limit_cents,
            auto_approve_limit_cents=payload.auto_approve_limit_cents,
        )
    except Forbidden as exc:
        return jsonify(error=str(exc)), 403
    except KeyError as exc:
        return jsonify(error=str(exc).strip("'")), 404
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(result)


@bp.delete("/<category>")
def remove_policy(category: str):
    """Drop a department override so the category inherits the org-wide rule again."""
    actor = actor_with_role("Finance")
    if actor is None:
        return jsonify(error="only finance can change spend policy"), 403

    try:
        result = policy_service.remove_rule(
            get_conn(),
            actor,
            department_id=request.args.get("department_id", type=int),
            category=category,
        )
    except Forbidden as exc:
        return jsonify(error=str(exc)), 403
    except KeyError as exc:
        return jsonify(error=str(exc).strip("'")), 404
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(result)


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
        has_receipt=payload.has_receipt,
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
