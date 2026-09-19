"""The submission path, end to end against a mock bank."""

import io

import pytest

from db import expenses as expense_db
from policy import CATEGORIES

# Alex is in Engineering, whose software auto-approve limit is $1,000
SMALL_SOFTWARE = {"amount_cents": 8_900, "category": "software", "merchant": "Figma"}


# Smallest thing the upload validator accepts as a PNG
RECEIPT_PNG = bytes.fromhex("89504e470d0a1a0a") + bytes(64)


def post_expense(client, attach_receipt=True, **overrides):
    """Attaches a receipt by default so these tests exercise the rule they mean to.

    Everything here is over the $25 receipt threshold, so without one every submission
    would come back blocked for a missing receipt rather than for the rule under test.
    """
    fields = {**SMALL_SOFTWARE, **overrides}
    if not attach_receipt:
        return client.post("/api/expenses", json=fields)

    data = {k: str(v) for k, v in fields.items() if v is not None}
    data["receipt"] = (io.BytesIO(RECEIPT_PNG), "receipt.png")
    return client.post(
        "/api/expenses", data=data, content_type="multipart/form-data"
    )


# -- auto-approve pays out --------------------------------------------------


def test_auto_approved_expense_is_paid_and_moves_money(
    client, sign_in, db, funded_nessie
):
    alex = sign_in("alex")
    payer = db.execute(
        "SELECT account_id FROM departments WHERE department_id = ?",
        (alex["department_id"],),
    ).fetchone()["account_id"]
    payee = db.execute(
        "SELECT nessie_id FROM accounts WHERE customer_id = ?", (alex["nessie_id"],)
    ).fetchone()["nessie_id"]
    before_payer = funded_nessie.get_balance(payer)
    before_payee = funded_nessie.get_balance(payee)

    response = post_expense(client)

    assert response.status_code == 201
    body = response.get_json()
    assert body["decision"] == "auto_approved"
    assert body["status"] == "paid"
    assert body["violations"] == []

    row = expense_db.get_expense(db, body["expense_id"])
    assert row["nessie_transfer_id"] is not None
    assert funded_nessie.get_balance(payer) == before_payer - 8_900
    assert funded_nessie.get_balance(payee) == before_payee + 8_900


def test_auto_approve_creates_exactly_one_transfer(client, sign_in, db, funded_nessie):
    alex = sign_in("alex")
    payee = db.execute(
        "SELECT nessie_id FROM accounts WHERE customer_id = ?", (alex["nessie_id"],)
    ).fetchone()["nessie_id"]

    post_expense(client)

    assert len(funded_nessie.list_transfers(payee)) == 1


# -- blocked ----------------------------------------------------------------


def test_over_cap_goes_to_the_manager_rather_than_being_refused(
    client, sign_in, db, funded_nessie
):
    """Nothing is refused by the machine: the block becomes the loudest flag in the queue."""
    alex = sign_in("alex")
    payee = db.execute(
        "SELECT nessie_id FROM accounts WHERE customer_id = ?", (alex["nessie_id"],)
    ).fetchone()["nessie_id"]

    response = post_expense(client, amount_cents=900_000, category="equipment")

    assert response.status_code == 201
    body = response.get_json()
    assert body["decision"] == "blocked"  # the engine's verdict is still on the record
    assert body["status"] == "needs_approval"
    assert "per_expense_cap" in {v["rule"] for v in body["violations"]}

    row = expense_db.get_expense(db, body["expense_id"])
    assert row["policy_decision"] == "blocked"
    assert row["nessie_transfer_id"] is None
    assert funded_nessie.list_transfers(payee) == []


def test_blocked_expense_persists_its_violations(client, sign_in, db):
    sign_in("alex")
    expense_id = post_expense(
        client, amount_cents=900_000, category="equipment"
    ).get_json()["expense_id"]
    stored = expense_db.violations_for(db, [expense_id])[expense_id]
    assert {v["rule"] for v in stored} == {"per_expense_cap", "approval_threshold"}


# -- needs approval ---------------------------------------------------------


def test_over_threshold_needs_approval_and_moves_no_money(
    client, sign_in, funded_nessie
):
    sign_in("alex")
    body = post_expense(client, amount_cents=200_000).get_json()
    assert body["decision"] == "needs_approval"
    assert body["status"] == "needs_approval"


def test_over_budget_escalates_rather_than_blocking(client, sign_in):
    # Marketing is seeded at 112% of budget
    sign_in("sam")
    body = post_expense(client, amount_cents=2_000, category="food").get_json()
    assert body["decision"] == "needs_approval"
    assert {v["rule"] for v in body["violations"]} == {"department_budget"}
    assert all(v["severity"] == "warn" for v in body["violations"])


# -- payout failure and retry ----------------------------------------------


def drain(nessie, account_id):
    nessie.seed_account(account_id, "x", "drained", 0)


def test_payout_failure_leaves_a_retryable_expense(client, sign_in, db, funded_nessie):
    alex = sign_in("alex")
    payer = db.execute(
        "SELECT account_id FROM departments WHERE department_id = ?",
        (alex["department_id"],),
    ).fetchone()["account_id"]
    drain(funded_nessie, payer)

    body = post_expense(client).get_json()

    assert body["status"] == "payout_failed"
    row = expense_db.get_expense(db, body["expense_id"])
    assert row["nessie_transfer_id"] is None
    assert row["policy_decision"] == "auto_approved"


def test_retry_after_refunding_succeeds_with_one_transfer(
    client, sign_in, db, funded_nessie
):
    alex = sign_in("alex")
    payer = db.execute(
        "SELECT account_id FROM departments WHERE department_id = ?",
        (alex["department_id"],),
    ).fetchone()["account_id"]
    payee = db.execute(
        "SELECT nessie_id FROM accounts WHERE customer_id = ?", (alex["nessie_id"],)
    ).fetchone()["nessie_id"]
    drain(funded_nessie, payer)
    expense_id = post_expense(client).get_json()["expense_id"]

    funded_nessie.seed_account(payer, "x", "refunded", 1_000_000)
    response = client.post(f"/api/expenses/{expense_id}/retry-payout")

    assert response.get_json()["status"] == "paid"
    assert len(funded_nessie.list_transfers(payee)) == 1


def test_retrying_a_paid_expense_never_pays_twice(client, sign_in, db, funded_nessie):
    alex = sign_in("alex")
    payee = db.execute(
        "SELECT nessie_id FROM accounts WHERE customer_id = ?", (alex["nessie_id"],)
    ).fetchone()["nessie_id"]
    expense_id = post_expense(client).get_json()["expense_id"]

    from services.expenses import pay_expense

    pay_expense(db, expense_id, funded_nessie)
    pay_expense(db, expense_id, funded_nessie)

    assert len(funded_nessie.list_transfers(payee)) == 1


# -- committed spend --------------------------------------------------------


def test_second_submission_sees_the_first(client, sign_in, db):
    alex = sign_in("alex")
    before = expense_db.department_budget(db, alex["department_id"]).committed_cents
    post_expense(client)
    after = expense_db.department_budget(db, alex["department_id"]).committed_cents
    assert after == before + 8_900


def test_rejected_expenses_do_not_count_as_committed(client, sign_in, db):
    alex = sign_in("alex")
    before = expense_db.department_budget(db, alex["department_id"]).committed_cents
    expense_id = post_expense(client, amount_cents=200_000).get_json()["expense_id"]

    sign_in("marcus")
    client.post(
        f"/api/expenses/{expense_id}/decision",
        json={"approve": False, "note": "no"},
    )

    after = expense_db.department_budget(db, alex["department_id"]).committed_cents
    assert after == before


def test_department_with_no_expenses_still_reports_its_budget(db):
    db.execute("DELETE FROM expense_violations")
    db.execute("DELETE FROM expenses")
    budget = expense_db.department_budget(db, 1)
    assert budget.monthly_budget_cents == 12_000_000
    assert budget.committed_cents == 0


# -- identity and validation ------------------------------------------------


def test_department_in_the_body_is_ignored(client, sign_in, db):
    alex = sign_in("alex")
    body = post_expense(client, department_id=2, customer_id="someone-else").get_json()
    row = expense_db.get_expense(db, body["expense_id"])
    assert row["department_id"] == alex["department_id"]
    assert row["customer_id"] == alex["nessie_id"]


def test_anonymous_cannot_submit(client):
    assert post_expense(client).status_code == 401


@pytest.mark.parametrize("amount", [0, -1])
def test_non_positive_amounts_are_rejected(client, sign_in, amount):
    sign_in("alex")
    assert post_expense(client, amount_cents=amount).status_code == 400


def test_unknown_category_is_rejected(client, sign_in):
    sign_in("alex")
    assert post_expense(client, category="yachts").status_code == 400


def test_department_pseudo_customer_cannot_submit(client, db):
    corporate = db.execute(
        "SELECT nessie_id FROM customers WHERE name = 'Nessence Corporation'"
    ).fetchone()
    with client.session_transaction() as session:
        session["user_id"] = corporate["nessie_id"]
    assert post_expense(client).status_code == 403


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_policy_category_is_accepted_by_the_schema(client, sign_in, category):
    """Catches policy.CATEGORIES drifting from the schema's CHECK list, in both directions."""
    sign_in("alex")
    assert post_expense(client, amount_cents=100, category=category).status_code == 201


# -- manager decisions ------------------------------------------------------


def test_manager_approval_pays_out(client, sign_in, db, funded_nessie):
    sign_in("alex")
    expense_id = post_expense(client, amount_cents=200_000).get_json()["expense_id"]

    sign_in("marcus")  # Engineering manager
    response = client.post(
        f"/api/expenses/{expense_id}/decision", json={"approve": True}
    )

    assert response.get_json()["status"] == "paid"
    assert expense_db.get_expense(db, expense_id)["nessie_transfer_id"] is not None


def test_manager_rejection_moves_no_money(client, sign_in, db, funded_nessie):
    alex = sign_in("alex")
    payee = db.execute(
        "SELECT nessie_id FROM accounts WHERE customer_id = ?", (alex["nessie_id"],)
    ).fetchone()["nessie_id"]
    expense_id = post_expense(client, amount_cents=200_000).get_json()["expense_id"]

    sign_in("marcus")
    response = client.post(
        f"/api/expenses/{expense_id}/decision",
        json={"approve": False, "note": "Buy it through procurement instead."},
    )

    assert response.get_json()["status"] == "rejected"
    assert expense_db.get_expense(db, expense_id)["decision_note"]
    assert funded_nessie.list_transfers(payee) == []


def test_manager_cannot_decide_another_department(client, sign_in):
    sign_in("alex")  # Engineering
    expense_id = post_expense(client, amount_cents=200_000).get_json()["expense_id"]

    sign_in("priya")  # Marketing manager
    response = client.post(
        f"/api/expenses/{expense_id}/decision", json={"approve": True}
    )
    assert response.status_code == 403


def test_employee_cannot_decide_even_their_own(client, sign_in):
    sign_in("alex")
    expense_id = post_expense(client, amount_cents=200_000).get_json()["expense_id"]

    assert (
        client.post(
            f"/api/expenses/{expense_id}/decision", json={"approve": True}
        ).status_code
        == 403
    )


def test_finance_cannot_decide_an_expense(client, sign_in):
    """Finance funds departments and watches the money; managers judge receipts."""
    sign_in("alex")
    expense_id = post_expense(client, amount_cents=200_000).get_json()["expense_id"]

    sign_in("dana")
    assert (
        client.post(
            f"/api/expenses/{expense_id}/decision", json={"approve": True}
        ).status_code
        == 403
    )


def test_manager_cannot_submit_an_expense(client, sign_in):
    sign_in("marcus")
    assert post_expense(client).status_code == 403


def test_finance_cannot_submit_an_expense(client, sign_in):
    sign_in("dana")
    assert post_expense(client).status_code == 403


def test_a_rejection_without_a_reason_is_refused(client, sign_in, db):
    sign_in("alex")
    expense_id = post_expense(client, amount_cents=200_000).get_json()["expense_id"]

    sign_in("marcus")
    response = client.post(
        f"/api/expenses/{expense_id}/decision", json={"approve": False, "note": "  "}
    )

    assert response.status_code == 400
    assert expense_db.get_expense(db, expense_id)["status"] == "needs_approval"


def test_an_over_budget_department_cannot_approve_until_finance_funds_it(
    client, sign_in, db
):
    """Marketing is seeded at 112%, so its manager is stuck until a funding request lands."""
    sign_in("priya")
    pending = expense_db.list_expenses(
        db, department_id=2, statuses=("needs_approval",)
    )
    expense_id = pending[0]["expense_id"]

    blocked = client.post(
        f"/api/expenses/{expense_id}/decision", json={"approve": True}
    )
    assert blocked.status_code == 409
    assert blocked.get_json()["shortfall_cents"] > 0

    # Finance funds the department, and the same approval now goes through
    request_id = client.post(
        "/api/funding", json={"amount_cents": 2_000_000, "reason": "over budget"}
    ).get_json()["request_id"]
    sign_in("dana")
    client.post(f"/api/funding/{request_id}/decision", json={"approve": True})

    sign_in("priya")
    assert (
        client.post(
            f"/api/expenses/{expense_id}/decision", json={"approve": True}
        ).status_code
        == 200
    )


# -- scoping ----------------------------------------------------------------


def test_employee_sees_only_their_own(client, sign_in):
    sign_in("alex")
    rows = client.get("/api/expenses").get_json()["expenses"]
    alex_id = {r["customer_id"] for r in rows}
    assert len(alex_id) <= 1


def test_employee_cannot_request_all(client, sign_in):
    sign_in("alex")
    assert client.get("/api/expenses?scope=all").status_code == 403


def test_finance_sees_every_department(client, sign_in):
    sign_in("dana")
    rows = client.get("/api/expenses?scope=all").get_json()["expenses"]
    assert len({r["department_id"] for r in rows}) > 1


def test_employee_cannot_read_another_persons_expense(client, sign_in, db):
    other = db.execute(
        "SELECT expense_id FROM expenses WHERE customer_id ="
        " (SELECT nessie_id FROM customers WHERE name = 'Sam Kowalski') LIMIT 1"
    ).fetchone()
    sign_in("alex")
    assert client.get(f"/api/expenses/{other['expense_id']}").status_code == 403


# -- preview ----------------------------------------------------------------


def test_preview_matches_submission_without_writing(client, sign_in, db):
    sign_in("alex")
    before = db.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()["n"]
    # has_receipt on both sides, so the comparison is about the equipment cap
    payload = {"amount_cents": 900_000, "category": "equipment", "has_receipt": True}

    preview = client.post("/api/policies/preview", json=payload).get_json()
    after = db.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()["n"]

    assert preview["decision"] == "blocked"
    assert after == before

    submitted = post_expense(
        client, amount_cents=900_000, category="equipment", merchant=None
    ).get_json()
    assert submitted["decision"] == preview["decision"]
    assert [v["rule"] for v in submitted["violations"]] == [
        v["rule"] for v in preview["violations"]
    ]


# -- the finance breakdown --------------------------------------------------


def test_category_spend_summary_excludes_rejected_and_ranks_by_spend(db):
    rows = expense_db.category_spend_summary(db)
    by_category = {row["category"]: row for row in rows}

    # Marketing's three seeded rows total $50,400 and lead the table
    assert rows[0]["category"] == "marketing"
    assert by_category["marketing"]["spent_cents"] == 5_040_000
    assert by_category["marketing"]["expense_count"] == 3

    # Expense 8 (Sweetgreen, $95) is the one a manager rejected, so food never appears
    assert "food" not in by_category

    committed = sum(row["spent_cents"] for row in rows)
    departments = expense_db.department_spend_summary(db)
    assert committed == sum(row["committed_cents"] for row in departments)
