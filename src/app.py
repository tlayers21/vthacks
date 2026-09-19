from flask import Flask

from api.deps import close_conn
from config import settings
from db.connect import connect
from nessie import get_nessie
from services.startup import hydrate_mock_accounts


def create_app(conn_factory=None, nessie=None) -> Flask:
    """Build the app. The factory exists so tests can hand in their own database and mock."""
    app = Flask(__name__)
    app.secret_key = settings.secret_key
    app.config["CONN_FACTORY"] = conn_factory
    app.config["NESSIE"] = nessie or get_nessie()
    # Tests pass one connection they keep using after the request ends
    app.config["KEEP_CONN"] = conn_factory is not None

    from api.routes import auth, expenses, policies, ui

    app.register_blueprint(auth.bp)
    app.register_blueprint(expenses.bp)
    app.register_blueprint(policies.bp)
    app.register_blueprint(ui.bp)

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
