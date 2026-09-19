"""JSON routes for expenses. Every one resolves the actor from the session."""

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from api.deps import current_user, get_conn, get_nessie
from api.schemas import DecisionIn, ExpenseIn
from db import expenses as expense_db
from services import expenses as expense_service
from services import receipts as receipt_service
from services.permissions import (
    Forbidden,
    can_view_expense,
    default_scope,
    visible_expense_filter,
)

bp = Blueprint("expenses", __name__, url_prefix="/api/expenses")


@bp.post("")
def create_expense():
    """Accepts multipart (with an optional `receipt` file) or plain JSON."""
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401

    if request.files or request.form:
        fields = dict(request.form)
    else:
        fields = request.get_json(silent=True) or {}
    try:
        payload = ExpenseIn.model_validate(fields)
    except ValidationError as exc:
        return jsonify(
            error="invalid expense", detail=exc.errors(include_url=False)
        ), 400

    # Written to disk before the row so the transaction never spans filesystem I/O
    upload = request.files.get("receipt")
    receipt = None
    if upload is not None and upload.filename:
        try:
            receipt = receipt_service.store(upload.filename, upload.read())
        except receipt_service.RejectedReceipt as exc:
            return jsonify(error=str(exc)), 400

    try:
        result = expense_service.submit_expense(
            get_conn(),
            actor,
            amount_cents=payload.amount_cents,
            category=payload.category,
            merchant=payload.merchant,
            description=payload.description,
            receipt=receipt,
            nessie=get_nessie(),
        )
    except Forbidden as exc:
        return jsonify(error=str(exc)), 403

    # 201 even when blocked: the row was written and the caller needs the violations
    return jsonify(result), 201


@bp.get("")
def list_expenses():
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401
    scope = request.args.get("scope") or default_scope(actor)
    try:
        filters = visible_expense_filter(actor, scope)
    except Forbidden as exc:
        return jsonify(error=str(exc)), 403

    conn = get_conn()
    rows = expense_db.list_expenses(conn, **filters)
    violations = expense_db.violations_for(conn, [r["expense_id"] for r in rows])
    return jsonify(
        scope=scope,
        expenses=[
            {**dict(row), "violations": violations.get(row["expense_id"], [])}
            for row in rows
        ],
    )


@bp.post("/<int:expense_id>/decision")
def decide(expense_id: int):
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401
    try:
        payload = DecisionIn.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify(
            error="invalid decision", detail=exc.errors(include_url=False)
        ), 400

    try:
        result = expense_service.decide_expense(
            get_conn(), actor, expense_id, payload.approve, nessie=get_nessie()
        )
    except KeyError:
        return jsonify(error="no such expense"), 404
    except Forbidden as exc:
        return jsonify(error=str(exc)), 403
    return jsonify(result)


@bp.post("/<int:expense_id>/retry-payout")
def retry_payout(expense_id: int):
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401

    conn = get_conn()
    expense = expense_db.get_expense(conn, expense_id)
    if expense is None:
        return jsonify(error="no such expense"), 404
    if not can_view_expense(actor, expense):
        return jsonify(error="not yours"), 403
    if expense["status"] != "payout_failed":
        return jsonify(error=f"expense is {expense['status']}, not payout_failed"), 409

    status = expense_service.pay_expense(conn, expense_id, get_nessie())
    return jsonify(expense_id=expense_id, status=status)


@bp.get("/<int:expense_id>")
def get_one(expense_id: int):
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401
    conn = get_conn()
    expense = expense_db.get_expense(conn, expense_id)
    if expense is None:
        return jsonify(error="no such expense"), 404
    if not can_view_expense(actor, expense):
        return jsonify(error="not yours"), 403
    violations = expense_db.violations_for(conn, [expense_id]).get(expense_id, [])
    return jsonify({**dict(expense), "violations": violations})
