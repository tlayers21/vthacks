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

    row = (
        get_conn()
        .execute(
            "SELECT nessie_id FROM customers WHERE nessie_id = ? AND department_id IS NOT NULL",
            (payload.user_id,),
        )
        .fetchone()
    )
    if row is None:
        # Dana is finance and belongs to no department, so she is allowed explicitly
        row = (
            get_conn()
            .execute(
                "SELECT nessie_id FROM customers WHERE nessie_id = ? AND role = 'Finance'",
                (payload.user_id,),
            )
            .fetchone()
        )
    if row is None:
        return jsonify(error="no such user"), 404

    session["user_id"] = row["nessie_id"]
    if request.form:
        return redirect(request.form.get("next") or "/")
    return jsonify(user_id=row["nessie_id"])


@bp.get("/me")
def me():
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401
    return jsonify(dict(actor))


@bp.get("/users")
def users():
    return jsonify(users=[dict(u) for u in switchable_users(get_conn())])
