"""The mock is in-memory and per-process, so everything it knows at startup comes from app.db.
These cover the seams where that reconstruction can go wrong -- all of which broke the running
app while the rest of the suite stayed green."""

from db import expenses as expense_db
from nessie import MockNessie
from services.expenses import pay_expense
from services.startup import hydrate_mock_accounts


def test_hydration_registers_every_account(db):
    nessie = MockNessie()
    count = hydrate_mock_accounts(db, nessie)
    accounts = db.execute("SELECT nessie_id FROM accounts").fetchall()
    assert count == len(accounts)
    for account in accounts:
        nessie.get_balance(account["nessie_id"])  # raises if it was never registered


def test_departments_open_at_their_budget(db):
    nessie = MockNessie()
    hydrate_mock_accounts(db, nessie)
    for department in db.execute("SELECT * FROM departments"):
        assert (
            nessie.get_balance(department["account_id"])
            == department["monthly_budget_cents"]
        )


def test_people_start_empty(db):
    nessie = MockNessie()
    hydrate_mock_accounts(db, nessie)
    alex = db.execute(
        "SELECT nessie_id FROM accounts WHERE customer_id ="
        " (SELECT nessie_id FROM customers WHERE name = 'Alex Chen')"
    ).fetchone()
    assert nessie.get_balance(alex["nessie_id"]) == 0


def test_hydration_is_a_no_op_for_a_client_without_seed_account(db):
    class Realish:
        pass

    assert hydrate_mock_accounts(db, Realish()) == 0


def test_settled_payouts_are_replayed_into_the_balances(db):
    """A paid expense already moved money, so a restart must not hand it back."""
    department = db.execute(
        "SELECT * FROM departments WHERE department_id = 1"
    ).fetchone()
    db.execute(
        "UPDATE expenses SET nessie_transfer_id = 'deadbeefdeadbeefdeadbeef'"
        " WHERE expense_id = 1"
    )
    db.commit()
    amount = expense_db.get_expense(db, 1)["amount_cents"]

    nessie = MockNessie()
    hydrate_mock_accounts(db, nessie)

    assert (
        nessie.get_balance(department["account_id"])
        == department["monthly_budget_cents"] - amount
    )


def test_a_fresh_mock_never_reissues_a_transfer_id_the_database_holds(db):
    """MockNessie's counter restarts at 1 every process. Against a database seeded by an
    earlier run, that would regenerate an id already stored and trip the UNIQUE constraint."""
    first = MockNessie()
    hydrate_mock_accounts(db, first)
    payer, payee = expense_db.payout_accounts(db, 2)
    issued = first.create_transfer(
        payer_id=payer, payee_id=payee, amount_cents=100, description="x"
    )["id"]
    db.execute(
        "UPDATE expenses SET nessie_transfer_id = ?, status = 'paid' WHERE expense_id = 2",
        (issued,),
    )
    db.commit()

    # A restart: brand new mock, same database
    restarted = MockNessie()
    hydrate_mock_accounts(db, restarted)
    reissued = restarted.create_transfer(
        payer_id=payer, payee_id=payee, amount_cents=100, description="y"
    )["id"]

    assert reissued != issued


def test_payout_after_a_restart_does_not_violate_the_unique_constraint(db):
    payer, payee = expense_db.payout_accounts(db, 2)
    first = MockNessie()
    hydrate_mock_accounts(db, first)
    issued = first.create_transfer(
        payer_id=payer, payee_id=payee, amount_cents=100, description="x"
    )["id"]
    db.execute(
        "UPDATE expenses SET nessie_transfer_id = ?, status = 'paid' WHERE expense_id = 1",
        (issued,),
    )
    db.commit()

    restarted = MockNessie()
    hydrate_mock_accounts(db, restarted)
    db.execute("UPDATE expenses SET status = 'approved' WHERE expense_id = 2")
    db.commit()

    assert pay_expense(db, 2, restarted) == "paid"
