"""A manager asking finance for money, and finance moving it.

The other half of the loop in test_expenses_api.py: these cover the funding side on its own,
where the money leaves the corporate account instead of a department's.
"""

from db import budget_requests as request_db
from db import expenses as expense_db
from db.ledger import transaction_ledger


def ask(client, amount_cents=2_000_000, reason="Campaigns ran long"):
    return client.post(
        "/api/funding", json={"amount_cents": amount_cents, "reason": reason}
    )


def corporate_account(db):
    return db.execute(
        "SELECT a.nessie_id FROM accounts a JOIN customers c ON c.nessie_id = a.customer_id"
        " WHERE c.name = 'Nessence Corporation'"
    ).fetchone()["nessie_id"]


# -- who may ask, who may answer -------------------------------------------


def test_manager_can_request_funding(client, sign_in, db):
    sign_in("priya")
    response = ask(client)

    assert response.status_code == 201
    request_id = response.get_json()["request_id"]
    stored = request_db.get_request(db, request_id)
    assert stored["status"] == "Pending"
    assert stored["department_id"] == 2  # from the session, never the request body


def test_employee_cannot_request_funding(client, sign_in):
    sign_in("alex")
    assert ask(client).status_code == 403


def test_finance_cannot_request_funding(client, sign_in):
    sign_in("dana")
    assert ask(client).status_code == 403


def test_manager_cannot_decide_a_funding_request(client, sign_in):
    sign_in("priya")
    request_id = ask(client).get_json()["request_id"]

    assert (
        client.post(
            f"/api/funding/{request_id}/decision", json={"approve": True}
        ).status_code
        == 403
    )


def test_a_manager_only_sees_their_own_departments_requests(client, sign_in):
    sign_in("priya")
    rows = client.get("/api/funding").get_json()["requests"]
    assert {r["department_id"] for r in rows} == {2}


def test_finance_sees_every_departments_requests(client, sign_in):
    sign_in("dana")
    rows = client.get("/api/funding").get_json()["requests"]
    assert len({r["department_id"] for r in rows}) > 1


# -- approving moves money and raises the budget ---------------------------


def test_approval_transfers_from_corporate_and_raises_the_budget(
    client, sign_in, db, funded_nessie
):
    before_budget = expense_db.department_budget(db, 2).monthly_budget_cents
    payer = corporate_account(db)
    payee = db.execute(
        "SELECT account_id FROM departments WHERE department_id = 2"
    ).fetchone()["account_id"]
    before_payer = funded_nessie.get_balance(payer)
    before_payee = funded_nessie.get_balance(payee)

    sign_in("priya")
    request_id = ask(client).get_json()["request_id"]
    sign_in("dana")
    response = client.post(
        f"/api/funding/{request_id}/decision", json={"approve": True}
    )

    assert response.get_json()["status"] == "Approved"
    assert (
        expense_db.department_budget(db, 2).monthly_budget_cents
        == before_budget + 2_000_000
    )
    assert funded_nessie.get_balance(payer) == before_payer - 2_000_000
    assert funded_nessie.get_balance(payee) == before_payee + 2_000_000
    assert request_db.get_request(db, request_id)["nessie_transfer_id"] is not None


def test_deciding_twice_funds_the_department_once(client, sign_in, db, funded_nessie):
    payee = db.execute(
        "SELECT account_id FROM departments WHERE department_id = 2"
    ).fetchone()["account_id"]

    sign_in("priya")
    request_id = ask(client).get_json()["request_id"]
    sign_in("dana")
    client.post(f"/api/funding/{request_id}/decision", json={"approve": True})
    budget_after_first = expense_db.department_budget(db, 2).monthly_budget_cents
    client.post(f"/api/funding/{request_id}/decision", json={"approve": True})

    assert len(funded_nessie.list_transfers(payee)) == 1
    assert (
        expense_db.department_budget(db, 2).monthly_budget_cents == budget_after_first
    )


# -- declining --------------------------------------------------------------


def test_declining_needs_a_reason(client, sign_in, db):
    sign_in("priya")
    request_id = ask(client).get_json()["request_id"]

    sign_in("dana")
    response = client.post(
        f"/api/funding/{request_id}/decision", json={"approve": False}
    )

    assert response.status_code == 400
    assert request_db.get_request(db, request_id)["status"] == "Pending"


def test_declining_records_the_reason_and_moves_no_money(
    client, sign_in, db, funded_nessie
):
    payee = db.execute(
        "SELECT account_id FROM departments WHERE department_id = 2"
    ).fetchone()["account_id"]
    before = funded_nessie.get_balance(payee)
    budget_before = expense_db.department_budget(db, 2).monthly_budget_cents

    sign_in("priya")
    request_id = ask(client).get_json()["request_id"]
    sign_in("dana")
    client.post(
        f"/api/funding/{request_id}/decision",
        json={"approve": False, "note": "Cut the retargeting spend instead."},
    )

    stored = request_db.get_request(db, request_id)
    assert stored["status"] == "Rejected"
    assert stored["decision_note"] == "Cut the retargeting spend instead."
    assert stored["nessie_transfer_id"] is None
    assert funded_nessie.get_balance(payee) == before
    assert expense_db.department_budget(db, 2).monthly_budget_cents == budget_before


def test_a_decided_request_cannot_be_decided_again(client, sign_in):
    sign_in("priya")
    request_id = ask(client).get_json()["request_id"]
    sign_in("dana")
    client.post(
        f"/api/funding/{request_id}/decision", json={"approve": False, "note": "no"}
    )

    assert (
        client.post(
            f"/api/funding/{request_id}/decision", json={"approve": True}
        ).status_code
        == 403
    )


# -- the ledger -------------------------------------------------------------


def test_an_approved_request_shows_up_in_the_ledger(client, sign_in, db):
    sign_in("priya")
    request_id = ask(client).get_json()["request_id"]
    sign_in("dana")
    client.post(f"/api/funding/{request_id}/decision", json={"approve": True})

    allocations = [r for r in transaction_ledger(db) if r["kind"] == "allocation"]
    assert len(allocations) == 1
    assert allocations[0]["payer_name"] == "Nessence Corporation"
    assert allocations[0]["payee_name"] == "Marketing"
    assert allocations[0]["amount_cents"] == 2_000_000
    assert allocations[0]["nessie_transfer_id"] is not None


def test_the_ledger_only_lists_transfers_that_actually_happened(db):
    """Every row carries a Nessie id, because Nessie is the audit trail behind the claim."""
    for row in transaction_ledger(db):
        assert row["nessie_transfer_id"] is not None
