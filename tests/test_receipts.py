"""Who can read a receipt, and what the upload path will accept.

A receipt is evidence attached to someone's spending, so the access rules matter more than
anything else in this feature. The cross-department cases below are the ones that would
silently leak if the route ever started trusting the URL instead of the session.
"""

import io

import pytest

from services import receipts as receipt_service

# Seeded by seed.sql: expense 2 belongs to Omar (Sales), expense 4 to Sam (Marketing)
SALES_EXPENSE = 2
MARKETING_EXPENSE = 4


def upload(name: str, data: bytes) -> dict:
    return {"receipt": (io.BytesIO(data), name)}


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff" + b"\x00" * 64
PDF = b"%PDF-1.7" + b"\x00" * 64


# -- reading ---------------------------------------------------------------


def test_submitter_can_read_their_own_receipt(client, sign_in):
    sign_in("omar")
    assert client.get(f"/receipts/{SALES_EXPENSE}").status_code == 200


def test_manager_can_read_a_receipt_in_their_department(client, sign_in):
    sign_in("tomas")  # Sales manager, and expense 2 is a Sales expense
    response = client.get(f"/receipts/{SALES_EXPENSE}")
    assert response.status_code == 200
    assert response.mimetype == "image/svg+xml"


def test_manager_cannot_read_another_departments_receipt(client, sign_in):
    sign_in("tomas")  # Sales manager reaching for a Marketing expense
    assert client.get(f"/receipts/{MARKETING_EXPENSE}").status_code == 403


def test_employee_cannot_read_someone_elses_receipt(client, sign_in):
    sign_in("alex")  # Engineering employee, neither the submitter nor a Sales manager
    assert client.get(f"/receipts/{SALES_EXPENSE}").status_code == 403


def test_finance_can_read_any_receipt(client, sign_in):
    sign_in("dana")
    assert client.get(f"/receipts/{MARKETING_EXPENSE}").status_code == 200


def test_signed_out_is_rejected(client):
    assert client.get(f"/receipts/{SALES_EXPENSE}").status_code == 401


def test_unknown_expense_is_404(client, sign_in):
    sign_in("dana")
    assert client.get("/receipts/99999").status_code == 404


# -- uploading -------------------------------------------------------------


def test_submitting_with_a_receipt_stores_it(client, sign_in, db):
    sign_in("alex")
    response = client.post(
        "/api/expenses",
        data={"amount_cents": "4000", "category": "food", **upload("lunch.png", PNG)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    expense_id = response.get_json()["expense_id"]

    row = db.execute(
        "SELECT * FROM expenses WHERE expense_id = ?", (expense_id,)
    ).fetchone()
    assert row["receipt_filename"] == "lunch.png"
    assert row["receipt_mime"] == "image/png"
    assert row["receipt_path"] == f"{row['receipt_hash']}.png"
    assert receipt_service.resolve(row["receipt_path"]).exists()


def test_over_threshold_without_a_receipt_is_blocked(client, sign_in):
    sign_in("alex")
    response = client.post(
        "/api/expenses",
        data={"amount_cents": "4000", "category": "food"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201  # the row is written either way
    body = response.get_json()
    assert body["decision"] == "blocked"
    assert any(v["rule"] == "missing_receipt" for v in body["violations"])


def test_under_threshold_without_a_receipt_is_fine(client, sign_in):
    sign_in("alex")
    response = client.post(
        "/api/expenses",
        data={"amount_cents": "1500", "category": "food"},
        content_type="multipart/form-data",
    )
    assert response.get_json()["decision"] == "auto_approved"


@pytest.mark.parametrize(
    "name, data",
    [
        ("shell.exe", b"MZ\x90\x00" + b"\x00" * 32),
        ("notes.txt", b"just text"),
        ("payload.svg", b"<svg onload='alert(1)'></svg>"),
    ],
)
def test_disallowed_extensions_are_refused(client, sign_in, name, data):
    sign_in("alex")
    response = client.post(
        "/api/expenses",
        data={"amount_cents": "4000", "category": "food", **upload(name, data)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_a_renamed_file_is_caught_by_its_magic_bytes(client, sign_in):
    """The extension is attacker-controlled, so it cannot be the only check."""
    sign_in("alex")
    response = client.post(
        "/api/expenses",
        data={
            "amount_cents": "4000",
            "category": "food",
            **upload("totally.png", b"MZ\x90\x00not a png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert "not really" in response.get_json()["error"]


def test_identical_files_are_stored_once(client, sign_in, db):
    sign_in("alex")
    ids = []
    for _ in range(2):
        response = client.post(
            "/api/expenses",
            data={"amount_cents": "1000", "category": "food", **upload("same.pdf", PDF)},
            content_type="multipart/form-data",
        )
        ids.append(response.get_json()["expense_id"])

    paths = {
        db.execute(
            "SELECT receipt_path FROM expenses WHERE expense_id = ?", (i,)
        ).fetchone()["receipt_path"]
        for i in ids
    }
    assert len(paths) == 1  # same bytes, one file on disk


def test_json_submission_still_works(client, sign_in):
    """The JSON path predates uploads and other callers may still use it."""
    sign_in("alex")
    response = client.post(
        "/api/expenses", json={"amount_cents": 1000, "category": "food"}
    )
    assert response.status_code == 201


# -- path safety -----------------------------------------------------------


@pytest.mark.parametrize("escape", ["../secrets.env", "..\\..\\app.db", "/etc/passwd"])
def test_resolve_refuses_paths_outside_the_receipts_directory(escape):
    with pytest.raises(receipt_service.RejectedReceipt):
        receipt_service.resolve(escape)


def test_stored_name_ignores_the_client_filename():
    stored = receipt_service.store("../../evil.png", PNG)
    assert stored.path == f"{stored.hash}.png"
    assert "/" not in stored.path and "\\" not in stored.path
    assert stored.filename == "evil.png"  # kept for display only
