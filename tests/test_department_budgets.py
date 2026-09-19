"""Editing a department's monthly budget.

The budget is the ceiling the policy engine and the manager guard both measure against, so
who may move it, and what moves with it, are the things worth pinning down.
"""

import pytest

from db import departments as department_db
from db import expenses as expense_db

ENGINEERING, MARKETING = 1, 2


def set_budget(client, department_id, cents):
    return client.put(
        f"/api/departments/{department_id}/budget",
        json={"monthly_budget_cents": cents},
    )


# -- permissions -----------------------------------------------------------


@pytest.mark.parametrize("who", ["marcus", "alex"])  # a manager and an employee
def test_only_finance_may_set_a_budget(client, sign_in, who):
    sign_in(who)
    assert set_budget(client, ENGINEERING, 99_999_00).status_code == 403


def test_signed_out_is_rejected(client):
    assert set_budget(client, ENGINEERING, 99_999_00).status_code == 403


def test_a_refused_edit_changes_nothing(client, sign_in, db):
    before = department_db.get_department(db, ENGINEERING)["monthly_budget_cents"]
    sign_in("marcus")
    set_budget(client, ENGINEERING, 1_00)
    assert (
        department_db.get_department(db, ENGINEERING)["monthly_budget_cents"] == before
    )


def test_a_manager_cannot_raise_their_own_departments_budget(client, sign_in, db):
    """The obvious abuse: the guard that blocks a manager's approvals is this number."""
    sign_in("marcus")  # Engineering's manager
    assert set_budget(client, ENGINEERING, 999_999_00).status_code == 403


# -- editing ---------------------------------------------------------------


def test_finance_sets_an_absolute_figure(client, sign_in, db):
    """Not a delta, unlike an approved funding request, which adds to the budget."""
    sign_in("dana")
    response = set_budget(client, ENGINEERING, 150_000_00)

    assert response.status_code == 200
    assert response.get_json()["monthly_budget_cents"] == 150_000_00
    assert (
        expense_db.department_budget(db, ENGINEERING).monthly_budget_cents
        == 150_000_00
    )


def test_the_response_carries_what_the_card_needs_to_redraw(client, sign_in, db):
    sign_in("dana")
    body = set_budget(client, ENGINEERING, 150_000_00).get_json()
    committed = expense_db.department_budget(db, ENGINEERING).committed_cents
    assert body["committed_cents"] == committed
    assert body["remaining_cents"] == 150_000_00 - committed
    assert body["over_budget"] is False


def test_editing_records_who_changed_it(client, sign_in, db):
    dana = sign_in("dana")
    set_budget(client, ENGINEERING, 150_000_00)
    row = department_db.get_department(db, ENGINEERING)
    assert row["budget_updated_by"] == dana["nessie_id"]
    assert row["budget_updated_at"] is not None


def test_a_budget_can_be_cut_below_committed_spend(client, sign_in, db):
    """Allowed on purpose -- finance cuts budgets, and the department shows as over."""
    sign_in("dana")
    committed = expense_db.department_budget(db, MARKETING).committed_cents
    assert committed > 0

    response = set_budget(client, MARKETING, committed - 1_00)

    assert response.status_code == 200
    assert response.get_json()["over_budget"] is True
    assert expense_db.department_budget(db, MARKETING).remaining_cents < 0


def test_zero_is_allowed_and_freezes_the_department(client, sign_in, db):
    sign_in("dana")
    assert set_budget(client, ENGINEERING, 0).status_code == 200
    assert expense_db.department_budget(db, ENGINEERING).monthly_budget_cents == 0


# -- validation ------------------------------------------------------------


@pytest.mark.parametrize("cents", [-1, -100_00])
def test_negative_budgets_are_refused(client, sign_in, cents):
    sign_in("dana")
    assert set_budget(client, ENGINEERING, cents).status_code == 400


def test_an_implausible_budget_is_refused(client, sign_in):
    sign_in("dana")
    assert set_budget(client, ENGINEERING, 10_000_000_000_00).status_code == 400


def test_unknown_department_is_404(client, sign_in):
    sign_in("dana")
    assert set_budget(client, 9999, 1_000_00).status_code == 404


# -- what the ceiling actually controls ------------------------------------


def test_raising_the_budget_clears_the_budget_violation(client, sign_in, db):
    """Marketing is seeded over budget, which is what makes the rule demonstrable."""
    sign_in("sam")  # Marketing
    before = client.post(
        "/api/policies/preview",
        json={"amount_cents": 100_00, "category": "marketing", "has_receipt": True},
    ).get_json()
    assert any(v["rule"] == "department_budget" for v in before["violations"])

    sign_in("dana")
    set_budget(client, MARKETING, 500_000_00)

    sign_in("sam")
    after = client.post(
        "/api/policies/preview",
        json={"amount_cents": 100_00, "category": "marketing", "has_receipt": True},
    ).get_json()
    assert not any(v["rule"] == "department_budget" for v in after["violations"])


def test_raising_the_budget_lets_a_blocked_manager_approve_again(
    client, sign_in, db, funded_nessie
):
    """Over-budget departments cannot approve; funding is one fix, an edit is the other."""
    pending = expense_db.list_expenses(
        db, department_id=MARKETING, statuses=("needs_approval",)
    )
    assert pending, "seed no longer has a pending Marketing expense"
    expense_id = pending[0]["expense_id"]

    sign_in("priya")  # Marketing's manager
    blocked = client.post(f"/api/expenses/{expense_id}/decision", json={"approve": True})
    assert blocked.status_code == 409

    sign_in("dana")
    set_budget(client, MARKETING, 500_000_00)

    sign_in("priya")
    allowed = client.post(f"/api/expenses/{expense_id}/decision", json={"approve": True})
    assert allowed.status_code == 200


def test_editing_a_budget_moves_no_money(client, sign_in, db, funded_nessie):
    """The budget is a ceiling. Funding requests are what actually transfer cash."""
    account = department_db.get_department(db, ENGINEERING)["account_id"]
    before = funded_nessie.get_balance(account)

    sign_in("dana")
    set_budget(client, ENGINEERING, 999_999_00)

    assert funded_nessie.get_balance(account) == before
