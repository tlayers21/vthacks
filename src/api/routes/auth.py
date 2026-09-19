"""The role switcher standing in for real authentication.

Whatever lands here is what every other route trusts, which is the point: identity is read from
the session and never from an expense payload.
"""

from flask import Blueprint, jsonify, redirect, request, session
from pydantic import ValidationError

from api.deps import current_user, get_conn, switchable_users
from api.schemas import SwitchIn

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.post("/switch")
def switch():
    raw = request.get_json(silent=True) or request.form.to_dict()
    try:
        payload = SwitchIn.model_validate(raw)
    except ValidationError as exc:
        return jsonify(error="invalid user", detail=exc.errors(include_url=False)), 400

    # Exactly the people the switcher offers, and nobody else. Matching on role = 'Finance'
    # instead would also sign you in as the corporation, which owns the account everything
    # is funded from
    offered = {u["nessie_id"] for u in switchable_users(get_conn())}
    if payload.user_id not in offered:
        return jsonify(error="no such user"), 404

    session["user_id"] = payload.user_id
    if request.form:
        return redirect(request.form.get("next") or "/")
    return jsonify(user_id=payload.user_id)


@bp.get("/me")
def me():
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401
    return jsonify(dict(actor))


@bp.get("/users")
def users():
    return jsonify(users=[dict(u) for u in switchable_users(get_conn())])
