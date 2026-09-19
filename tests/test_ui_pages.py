"""Every page renders for a role that can reach it. Templates fail at render time, not import
time, so without these a broken page only shows up in the browser."""

import pytest

from db import expenses as expense_db

PAGES_BY_ROLE = [
    ("alex", ["/expenses/new", "/expenses/mine", "/policies"]),
    ("marcus", ["/approvals", "/funding", "/expenses/all", "/policies"]),
    ("dana", ["/finance", "/funding", "/transactions", "/policies"]),
]

# Each role has exactly one job, so every page outside it is a redirect, not a hidden nav link
PAGES_OFF_LIMITS = [
    ("alex", ["/approvals", "/funding", "/finance", "/transactions", "/expenses/all"]),
    ("marcus", ["/expenses/new", "/finance", "/transactions"]),
    ("dana", ["/expenses/new", "/approvals"]),
]


@pytest.mark.parametrize(("person", "paths"), PAGES_BY_ROLE)
def test_pages_render(client, sign_in, person, paths):
    sign_in(person)
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, f"{person} could not load {path}"


ROLE_HOMES = [("alex", "/expenses/new"), ("marcus", "/approvals"), ("dana", "/finance")]


@pytest.mark.parametrize(("person", "paths"), PAGES_OFF_LIMITS)
def test_pages_outside_a_role_redirect_home(client, sign_in, person, paths):
    home = dict(ROLE_HOMES)[person]
    sign_in(person)
    for path in paths:
        response = client.get(path)
        assert response.status_code == 302, f"{person} could still load {path}"
        assert response.headers["Location"] == home


def test_finance_overview_is_not_readable_signed_out(client):
    assert client.get("/finance").status_code == 302


def test_a_page_a_signed_out_visitor_cannot_see_sends_them_to_the_landing_page(client):
    assert client.get("/finance").headers["Location"] == "/"


def test_landing_page_renders_signed_out(client):
    assert client.get("/").status_code == 200


@pytest.mark.parametrize(("person", "destination"), ROLE_HOMES)
def test_the_landing_page_stays_put_when_signed_in(
    client, sign_in, person, destination
):
    """The brand mark points at `/`, so `/` cannot redirect -- it offers the way on instead."""
    sign_in(person)
    page = client.get("/")

    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Manage your business's money" in body
    assert f'href="{destination}"' in body


@pytest.mark.parametrize(("person", "destination"), ROLE_HOMES)
def test_signing_in_lands_on_the_role_home(client, people, person, destination):
    """The picker sends no `next`, so the switch itself decides where each role starts."""
    response = client.post(
        "/auth/switch", data={"user_id": people[person]["nessie_id"]}
    )
    assert response.headers["Location"] == destination


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
    assert "Nessence Corporation" not in body
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


def test_finance_page_breaks_spend_down_by_category(client, sign_in):
    sign_in("dana")
    body = client.get("/finance").get_data(as_text=True)
    # Marketing is the seeded over-budget category, so it leads the breakdown.
    # Categories are stored lower-case and capitalized for display only
    assert "Spend by category" in body
    assert "Marketing" in body


def test_policy_page_marks_a_department_override(client, sign_in):
    sign_in("marcus")  # Engineering, which overrides the software rule
    engineering = client.get("/policies?department_id=1").get_data(as_text=True)
    # The attribute, not the word: every row carries a hidden override badge for the
    # finance editor to unhide, so the bare substring is present either way
    assert 'data-override="true"' in engineering
    # Sales has no rule of its own, so nothing is marked
    assert 'data-override="true"' not in client.get(
        "/policies?department_id=3"
    ).get_data(as_text=True)


def test_approvals_posts_decisions_to_the_api_route(client, sign_in):
    """The queue used to POST /expenses/<id>/decision, which 404s -- it must hit /api."""
    sign_in("priya")
    body = client.get("/approvals").get_data(as_text=True)
    assert "/api/expenses/${id}/decision" in body


# -- nav count badges -------------------------------------------------------


def test_a_manager_sees_a_count_of_what_is_waiting_on_them(client, sign_in, db):
    tomas = sign_in("tomas")
    waiting = expense_db.pending_count(db, tomas["department_id"])
    assert waiting  # the seed plants some, or this asserts nothing

    page = client.get("/approvals").get_data(as_text=True)
    assert f'class="nav-count" aria-label="{waiting} waiting">{waiting}<' in page


def test_the_count_falls_as_the_work_is_done(client, sign_in, db):
    """No 'seen' state anywhere: the badge is the backlog, so deciding clears it."""
    tomas = sign_in("tomas")
    before = expense_db.pending_count(db, tomas["department_id"])
    expense_id = expense_db.list_expenses(
        db, department_id=tomas["department_id"], statuses=("needs_approval",)
    )[0]["expense_id"]

    client.post(
        f"/api/expenses/{expense_id}/decision",
        json={"approve": False, "note": "Not this month."},
    )

    assert expense_db.pending_count(db, tomas["department_id"]) == before - 1


def test_finance_is_counted_on_funding_rather_than_approvals(client, sign_in, db):
    from db import budget_requests as request_db

    sign_in("dana")
    waiting = request_db.pending_count(db)
    page = client.get("/finance").get_data(as_text=True)

    funding_link = page.split('href="/funding"')[1].split("</a>")[0]
    assert (
        f'class="nav-count" aria-label="{waiting} waiting">{waiting}<' in funding_link
    )


def test_an_employee_has_nothing_waiting_on_them(client, sign_in):
    sign_in("omar")
    # The class is in the stylesheet either way; what must be absent is a badge
    assert 'class="nav-count"' not in client.get("/expenses/mine").get_data(
        as_text=True
    )


# -- the mark goes home -----------------------------------------------------


def test_the_logo_links_home_without_swallowing_the_close_button(client, sign_in):
    """An <a> around the close button made closing the menu navigate away."""
    sign_in("omar")
    page = client.get("/expenses/mine").get_data(as_text=True)

    assert (
        page.count('<a href="/" class="flex items-center gap') == 2
    )  # sidebar and mobile bar
    opened = page.split('<a href="/" class="flex items-center gap')[1]
    assert "data-sidebar-close" not in opened.split("</a>")[0]
