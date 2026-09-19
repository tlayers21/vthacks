"""Every page renders for a role that can reach it. Templates fail at render time, not import
time, so without these a broken page only shows up in the browser."""

import pytest

PAGES_BY_ROLE = [
    ("alex", ["/expenses/new", "/expenses/mine", "/policies"]),
    ("marcus", ["/approvals", "/expenses/all", "/policies"]),
    ("dana", ["/finance", "/expenses/all", "/policies"]),
]


@pytest.mark.parametrize(("person", "paths"), PAGES_BY_ROLE)
def test_pages_render(client, sign_in, person, paths):
    sign_in(person)
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, f"{person} could not load {path}"


def test_landing_page_renders_signed_out(client):
    assert client.get("/").status_code == 200


def test_home_sends_each_role_somewhere_useful(client, sign_in):
    for person, destination in [
        ("alex", "/expenses/new"),
        ("marcus", "/approvals"),
        ("dana", "/finance"),
    ]:
        sign_in(person)
        assert client.get("/").headers["Location"] == destination


def test_approval_queue_shows_the_violations_that_sent_it_there(client, sign_in):
    sign_in("priya")  # Marketing manager; expense 6 is seeded over budget
    body = client.get("/approvals").get_data(as_text=True)
    assert "exceeds the" in body
    assert "auto-approve limit" in body


def test_finance_page_shows_marketing_over_budget(client, sign_in):
    sign_in("dana")
    body = client.get("/finance").get_data(as_text=True)
    assert "over budget" in body
    assert "bar over" in body


def test_switcher_offers_people_but_not_pseudo_customers(client, sign_in):
    sign_in("alex")
    body = client.get("/expenses/new").get_data(as_text=True)
    assert "Alex Chen" in body
    assert "Acme Corporation" not in body
    assert "Engineering Department" not in body


def test_role_switch_changes_the_acting_user(client, people):
    response = client.post(
        "/auth/switch",
        data={"user_id": people["alex"]["nessie_id"], "next": "/expenses/mine"},
    )
    assert response.status_code == 302
    assert client.get("/auth/me").get_json()["name"] == "Alex Chen"


def test_switching_to_an_unknown_user_is_refused(client):
    assert client.post("/auth/switch", json={"user_id": "nope"}).status_code == 404
