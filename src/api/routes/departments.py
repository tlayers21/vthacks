"""Department budgets. Finance writes, everyone signed in can read.

The role is checked here, not inferred from the finance dashboard being the only page that
renders the control.
"""

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from api.deps import actor_with_role, current_user, get_conn
from api.schemas import DepartmentBudgetIn
from db import departments as department_db
from services import departments as department_service
from services.permissions import Forbidden

bp = Blueprint("departments", __name__, url_prefix="/api/departments")


@bp.get("")
def list_departments():
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401
    return jsonify(
        departments=[dict(row) for row in department_db.list_departments(get_conn())]
    )


@bp.put("/<int:department_id>/budget")
def set_budget(department_id: int):
    actor = actor_with_role("Finance")
    if actor is None:
        return jsonify(error="only finance can change department budgets"), 403
    try:
        payload = DepartmentBudgetIn.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify(
            error="invalid budget",
            detail=exc.errors(include_url=False, include_context=False),
        ), 400

    try:
        result = department_service.set_budget(
            get_conn(),
            actor,
            department_id=department_id,
            monthly_budget_cents=payload.monthly_budget_cents,
        )
    except Forbidden as exc:
        return jsonify(error=str(exc)), 403
    except KeyError as exc:
        return jsonify(error=str(exc).strip("'")), 404
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(result)
