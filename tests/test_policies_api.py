"""Editing spend policy: who may, and what the edits actually do.

The role checks are the point. A limit is the difference between an expense paying itself out
and an expense waiting on a person, so "only finance can change spend policy" has to hold
against the API directly, not just against a hidden button.
"""

import pytest

from db import policies as policy_db
from services.policies import rule_source

# Seeded in seed.sql: Engineering(1) overrides software, Marketing(2) overrides marketing,
# Sales(3) overrides nothing
ENGINEERING, MARKETING, SALES = 1, 2, 3


def put(client, category, **body):
    return client.put(f"/api/policies/{category}", json=body)


def org_rule(db, category):
    return rule_source(db).rule_for(999, category)  # a department that cannot exist


# -- permissions -----------------------------------------------------------


@pytest.mark.parametrize("who", ["marcus", "alex"])  # a manager and an employee
def test_only_finance_may_save(client, sign_in, who):
    sign_in(who)
    response = put(
        client,
        "food",
        department_id=ENGINEERING,
        per_expense_limit_cents=999_00,
        auto_approve_limit_cents=1_00,
    )
    assert response.status_code == 403


@pytest.mark.parametrize("who", ["marcus", "alex"])
def test_only_finance_may_remove(client, sign_in, who):
    sign_in(who)
    response = client.delete(f"/api/policies/software?department_id={ENGINEERING}")
    assert response.status_code == 403


def test_signed_out_is_rejected(client):
    assert put(client, "food", per_expense_limit_cents=100, auto_approve_limit_cents=1).status_code == 403


def test_a_refused_save_changes_nothing(client, sign_in, db):
    before = rule_source(db).rule_for(ENGINEERING, "food")
    sign_in("marcus")
    put(
        client,
        "food",
        department_id=ENGINEERING,
        per_expense_limit_cents=999_00,
        auto_approve_limit_cents=1_00,
    )
    assert rule_source(db).rule_for(ENGINEERING, "food") == before


# -- adding and editing ----------------------------------------------------


def test_finance_adds_a_department_override(client, sign_in, db):
    sign_in("dana")
    assert "food" not in {
        r["category"] for r in policy_db.list_rules(db, SALES)
    }

    response = put(
        client,
        "food",
        department_id=SALES,
        per_expense_limit_cents=80_000,
        auto_approve_limit_cents=40_000,
    )

    assert response.status_code == 200
    assert response.get_json()["is_override"] is True
    rule = rule_source(db).rule_for(SALES, "food")
    assert rule.per_expense_limit_cents == 80_000
    assert rule.auto_approve_limit_cents == 40_000


def test_editing_is_the_same_request_as_adding(client, sign_in, db):
    """PUT is an upsert, so a second save updates rather than duplicating."""
    sign_in("dana")
    for cap in (80_000, 90_000):
        put(
            client,
            "food",
            department_id=SALES,
            per_expense_limit_cents=cap,
            auto_approve_limit_cents=1_000,
        )

    rows = [r for r in policy_db.list_rules(db, SALES) if r["category"] == "food"]
    assert len(rows) == 1
    assert rows[0]["per_expense_limit_cents"] == 90_000


def test_editing_an_org_wide_default_moves_departments_without_an_override(
    client, sign_in, db
):
    sign_in("dana")
    response = put(
        client,
        "travel",
        department_id=None,
        per_expense_limit_cents=444_000,
        auto_approve_limit_cents=44_000,
    )

    assert response.status_code == 200
    assert response.get_json()["is_override"] is False
    # No department overrides travel, so all of them follow
    for department in (ENGINEERING, MARKETING, SALES):
        assert rule_source(db).rule_for(department, "travel").per_expense_limit_cents == 444_000


def test_an_override_survives_an_org_wide_edit(client, sign_in, db):
    """Engineering overrides software, so changing the default must not touch it."""
    sign_in("dana")
    before = rule_source(db).rule_for(ENGINEERING, "software")
    put(
        client,
        "software",
        department_id=None,
        per_expense_limit_cents=1_000,
        auto_approve_limit_cents=500,
    )
    assert rule_source(db).rule_for(ENGINEERING, "software") == before
    assert org_rule(db, "software").per_expense_limit_cents == 1_000


def test_saving_records_who_changed_it(client, sign_in, db):
    dana = sign_in("dana")
    put(
        client,
        "food",
        department_id=SALES,
        per_expense_limit_cents=80_000,
        auto_approve_limit_cents=1_000,
    )
    row = policy_db.get_rule(db, SALES, "food")
    assert row["updated_by"] == dana["nessie_id"]


# -- removing --------------------------------------------------------------


def test_removing_an_override_reverts_to_the_org_wide_rule(client, sign_in, db):
    sign_in("dana")
    inherited = org_rule(db, "software")
    assert rule_source(db).rule_for(ENGINEERING, "software") != inherited

    response = client.delete(f"/api/policies/software?department_id={ENGINEERING}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["is_override"] is False
    assert body["per_expense_limit_cents"] == inherited.per_expense_limit_cents
    assert rule_source(db).rule_for(ENGINEERING, "software") == inherited


def test_removing_an_org_wide_rule_is_refused(client, sign_in, db):
    """It would drop the category to a hidden fallback instead of a limit you can see."""
    sign_in("dana")
    response = client.delete("/api/policies/software")
    assert response.status_code == 400
    assert org_rule(db, "software") is not None
    assert policy_db.get_rule(db, None, "software") is not None


def test_removing_a_rule_that_is_not_there_is_404(client, sign_in):
    sign_in("dana")
    assert client.delete(f"/api/policies/food?department_id={SALES}").status_code == 404


# -- validation ------------------------------------------------------------


def test_inverted_limits_are_refused_with_a_message(client, sign_in):
    """A 400 from validation, never a 500 from the CHECK constraint."""
    sign_in("dana")
    response = put(
        client,
        "food",
        department_id=SALES,
        per_expense_limit_cents=1_000,
        auto_approve_limit_cents=5_000,
    )
    assert response.status_code == 400


@pytest.mark.parametrize("cap", [0, -1])
def test_non_positive_caps_are_refused(client, sign_in, cap):
    sign_in("dana")
    assert put(
        client, "food", department_id=SALES,
        per_expense_limit_cents=cap, auto_approve_limit_cents=0,
    ).status_code == 400


def test_unknown_category_is_refused(client, sign_in):
    sign_in("dana")
    assert put(
        client, "yachts", department_id=SALES,
        per_expense_limit_cents=1_000, auto_approve_limit_cents=100,
    ).status_code == 400


def test_unknown_department_is_refused(client, sign_in):
    sign_in("dana")
    assert put(
        client, "food", department_id=9999,
        per_expense_limit_cents=1_000, auto_approve_limit_cents=100,
    ).status_code == 404


# -- the point of all this -------------------------------------------------


def test_raising_a_limit_changes_the_next_verdict(client, sign_in, db):
    """An edit has to reach the engine, or none of this does anything."""
    sign_in("alex")  # Engineering
    before = client.post(
        "/api/policies/preview",
        json={"amount_cents": 150_000, "category": "software", "has_receipt": True},
    ).get_json()
    assert before["decision"] == "needs_approval"

    sign_in("dana")
    put(
        client,
        "software",
        department_id=ENGINEERING,
        per_expense_limit_cents=1_000_000,
        auto_approve_limit_cents=200_000,
    )

    sign_in("alex")
    after = client.post(
        "/api/policies/preview",
        json={"amount_cents": 150_000, "category": "software", "has_receipt": True},
    ).get_json()
    assert after["decision"] == "auto_approved"


def test_an_edit_leaves_already_decided_expenses_alone(client, sign_in, db):
    """policy_decision is the record of what the engine said then, not a live calculation."""
    before = {
        r["expense_id"]: r["policy_decision"]
        for r in db.execute("SELECT expense_id, policy_decision FROM expenses")
    }

    sign_in("dana")
    put(
        client,
        "software",
        department_id=None,
        per_expense_limit_cents=100,
        auto_approve_limit_cents=50,
    )

    after = {
        r["expense_id"]: r["policy_decision"]
        for r in db.execute("SELECT expense_id, policy_decision FROM expenses")
    }
    assert after == before
