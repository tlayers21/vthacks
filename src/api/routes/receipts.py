"""Serving receipt files.

Receipts are deliberately not in Flask's static directory. They are evidence attached to
someone's spending, so every read goes through the same visibility check as the expense
itself -- static hosting would hand the file to anyone who guessed the URL.
"""

from flask import Blueprint, abort, jsonify, send_file

from api.deps import current_user, get_conn
from db import expenses as expense_db
from services import receipts as receipt_service
from services.permissions import can_view_expense

bp = Blueprint("receipts", __name__, url_prefix="/receipts")


@bp.get("/<int:expense_id>")
def receipt(expense_id: int):
    actor = current_user()
    if actor is None:
        return jsonify(error="not signed in"), 401

    expense = expense_db.get_expense(get_conn(), expense_id)
    if expense is None:
        return jsonify(error="no such expense"), 404
    if not can_view_expense(actor, expense):
        return jsonify(error="not yours"), 403
    if not expense["receipt_path"]:
        return jsonify(error="no receipt on that expense"), 404

    try:
        path = receipt_service.resolve(expense["receipt_path"])
    except receipt_service.RejectedReceipt:
        abort(404)
    if not path.exists():
        # The row outlived its file -- a wiped data/receipts, usually
        return jsonify(error="receipt file is missing"), 410

    return send_file(
        path,
        mimetype=expense["receipt_mime"] or "application/octet-stream",
        download_name=expense["receipt_filename"] or path.name,
    )
