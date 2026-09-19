import sqlite3
from pathlib import Path

import pytest

from app import create_app
from config import settings
from db.connect import connect
from llm import MockReceiptReader
from nessie import MockNessie
from services.startup import hydrate_mock_accounts

SQL_DIR = Path(__file__).resolve().parent.parent / "src" / "db"


@pytest.fixture(autouse=True)
def receipts_dir(tmp_path, monkeypatch):
    """Send uploads to a temp directory so tests never litter data/receipts/.

    Autouse because an upload test that forgot it would write into the repo, and the
    sample receipts are copied in so seeded rows still resolve to a real file.
    """
    target = tmp_path / "receipts"
    monkeypatch.setattr(settings, "receipts_dir", target)
    from services.receipts import install_samples

    install_samples()
    return target


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


class ScriptedReader:
    """A receipt reader a test can put words in the mouth of.

    Set `.answer` to a reading and every call returns it; leave it None and the offline
    mock reader answers instead, so a test that does not care about the model gets the
    same behaviour it had before there was one. Failure is injected by setting `.raises`,
    which is how the real reader behaves when the endpoint is down.
    """

    model = "scripted"

    def __init__(self):
        self.answer = None
        self.raises = None
        self.calls = 0
        self._fallback = MockReceiptReader()

    def read(self, content, **kwargs):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        if self.answer is not None:
            return dict(self.answer)
        return self._fallback.read(content, **kwargs)


@pytest.fixture
def reader() -> ScriptedReader:
    return ScriptedReader()


@pytest.fixture
def app(db, funded_nessie, reader):
    return create_app(conn_factory=lambda: db, nessie=funded_nessie, reader=reader)


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
