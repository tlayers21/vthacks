import sqlite3
from pathlib import Path

import pytest

from app import create_app
from db.connect import connect
from nessie import MockNessie
from services.startup import hydrate_mock_accounts

SQL_DIR = Path(__file__).resolve().parent.parent / "src" / "db"


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    conn.executescript((SQL_DIR / "schema.sql").read_text())
    conn.executescript((SQL_DIR / "seed.sql").read_text())
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def nessie() -> MockNessie:
    # A fresh mock, never get_nessie() -- that singleton leaks balances between tests
    return MockNessie()


@pytest.fixture
def funded_nessie(db, nessie) -> MockNessie:
    hydrate_mock_accounts(db, nessie)
    return nessie


@pytest.fixture
def app(db, funded_nessie):
    return create_app(conn_factory=lambda: db, nessie=funded_nessie)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def people(db) -> dict[str, sqlite3.Row]:
    """Seeded people by first name, so tests read as sentences."""
    rows = db.execute("SELECT * FROM customers").fetchall()
    return {row["name"].split()[0].lower(): row for row in rows}


@pytest.fixture
def sign_in(client, people):
    def _sign_in(first_name: str):
        person = people[first_name.lower()]
        with client.session_transaction() as session:
            session["user_id"] = person["nessie_id"]
        return person

    return _sign_in
