"""JSON routes for funding requests. Every one resolves the actor from the session."""

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from api.deps import current_user, get_conn, get_nessie
from api.schemas import FundingDecisionIn, FundingIn
from db import budget_requests as request_db
from services import budget_requests as funding_service
from services.permissions import Forbidden

bp = Blueprint("funding", __name__, url_prefix="/api/funding")


@bp.post("")
def create_request():
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401
    try:
        payload = FundingIn.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify(
            error="invalid funding request", detail=exc.errors(include_url=False)
        ), 400

    try:
        result = funding_service.submit_request(
            get_conn(),
            actor,
            amount_cents=payload.amount_cents,
            reason=payload.reason,
        )
    except Forbidden as exc:
        return jsonify(error=str(exc)), 403
    return jsonify(result), 201


@bp.get("")
def list_funding_requests():
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401

    # Finance decides every department's requests; a manager only ever sees their own
    filters = (
        {} if actor["role"] == "Finance" else {"department_id": actor["department_id"]}
    )
    rows = request_db.list_requests(get_conn(), **filters)
    return jsonify(requests=[dict(row) for row in rows])


@bp.post("/<int:request_id>/decision")
def decide(request_id: int):
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401
    try:
        payload = FundingDecisionIn.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify(
            error="invalid decision", detail=exc.errors(include_url=False)
        ), 400

    try:
        result = funding_service.decide_request(
            get_conn(),
            actor,
            request_id,
            payload.approve,
            payload.note,
            nessie=get_nessie(),
        )
    except KeyError:
        return jsonify(error="no such funding request"), 404
    except Forbidden as exc:
        return jsonify(error=str(exc)), 403
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception as exc:  # noqa: BLE001
        # The allocation transfer failed. Nothing was written, so the request is still Pending
        # and finance can simply try again -- unlike a reimbursement there is no half state
        return jsonify(error=f"the allocation transfer failed: {exc}"), 502
    return jsonify(result)
