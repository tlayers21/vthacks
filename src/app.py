from flask import Flask, jsonify

from api.deps import close_conn
from config import settings
from db.connect import connect
from llm import get_reader
from nessie import get_nessie
from services.startup import hydrate_mock_accounts


def create_app(conn_factory=None, nessie=None, reader=None) -> Flask:
    """Build the app. The factory exists so tests can hand in their own database and mock."""
    app = Flask(__name__)
    app.secret_key = settings.secret_key
    # Rejected by Werkzeug before the route runs, so an oversized upload never reaches disk
    app.config["MAX_CONTENT_LENGTH"] = settings.max_receipt_bytes
    app.config["CONN_FACTORY"] = conn_factory
    app.config["NESSIE"] = nessie or get_nessie()
    app.config["READER"] = reader or get_reader()
    # Tests pass one connection they keep using after the request ends
    app.config["KEEP_CONN"] = conn_factory is not None
    # The receipt check goes on a thread only when it can open a connection of its own.
    # Tests hand in one connection and want the verdict before they assert on it.
    app.config["CHECK_ASYNC"] = conn_factory is None

    from api.routes import (
        auth,
        departments,
        expenses,
        funding,
        policies,
        receipts,
        ui,
    )

    app.register_blueprint(auth.bp)
    app.register_blueprint(departments.bp)
    app.register_blueprint(expenses.bp)
    app.register_blueprint(funding.bp)
    app.register_blueprint(policies.bp)
    app.register_blueprint(receipts.bp)
    app.register_blueprint(ui.bp)

    @app.errorhandler(413)
    def too_large(_exc):
        # Default is an HTML page, which the fetch() callers cannot parse
        limit_mb = settings.max_receipt_bytes // (1024 * 1024)
        return jsonify(error=f"receipts must be under {limit_mb}MB"), 413

    app.teardown_appcontext(close_conn)

    conn = (conn_factory or connect)()
    try:
        hydrate_mock_accounts(conn, app.config["NESSIE"])
    finally:
        if conn_factory is None:
            conn.close()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
