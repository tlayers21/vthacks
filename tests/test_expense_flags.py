"""The receipt check: what it flags, and what a flag is allowed to do about it."""

import io

from db import expenses as expense_db
from services import expense_flags
from services.expense_flags import compare

# Alex is in Engineering, whose software auto-approve limit is $1,000
SMALL_SOFTWARE = {"amount_cents": 8_900, "category": "software", "merchant": "Figma"}

RECEIPT_PNG = bytes.fromhex("89504e470d0a1a0a") + bytes(64)


def reading(**overrides) -> dict:
    """A clean reading of the Figma receipt, before a test spoils one field of it."""
    return {
        "status": "read",
        "merchant": "FIGMA INC",
        "total_cents": 8_900,
        "receipt_date": None,
        "line_items": [],
        "category_consistent": None,
        "note": "",
        **overrides,
    }


def claim(**overrides) -> dict:
    return {
        "amount_cents": 8_900,
        "merchant": "Figma",
        "category": "software",
        "submitted_at": "2026-09-19 10:00:00",
        **overrides,
    }


def post(client, receipt=RECEIPT_PNG, name="receipt.png", **overrides):
    fields = {**SMALL_SOFTWARE, **overrides}
    data = {k: str(v) for k, v in fields.items() if v is not None}
    data["receipt"] = (io.BytesIO(receipt), name)
    return client.post("/api/expenses", data=data, content_type="multipart/form-data")


# -- compare() is pure, so it gets tested on its own ------------------------


def test_a_receipt_that_agrees_raises_nothing():
    assert compare(claim(), reading()) == []


def test_a_different_total_is_flagged_with_both_numbers():
    flags = compare(claim(amount_cents=89_000), reading())
    assert [f.flag for f in flags] == ["amount_mismatch"]
    assert "$89.00" in flags[0].message and "$890.00" in flags[0].message


def test_a_rounded_tip_is_within_tolerance():
    """A dollar either way is somebody rounding, not somebody lying."""
    assert compare(claim(amount_cents=9_000), reading()) == []


def test_the_tolerance_does_not_scale_away_on_a_large_claim():
    flags = compare(claim(amount_cents=500_000), reading(total_cents=400_000))
    assert [f.flag for f in flags] == ["amount_mismatch"]


def test_an_abbreviated_merchant_is_not_a_mismatch():
    assert compare(claim(merchant="Figma"), reading(merchant="FIGMA INC")) == []


def test_a_different_merchant_is_flagged():
    flags = compare(claim(merchant="Figma"), reading(merchant="BEST BUY"))
    assert [f.flag for f in flags] == ["merchant_mismatch"]


def test_a_merchant_nobody_entered_is_not_a_mismatch():
    assert compare(claim(merchant=None), reading(merchant="FIGMA INC")) == []


def test_an_old_receipt_is_flagged_but_a_recent_one_is_not():
    assert compare(claim(), reading(receipt_date="2026-09-10")) == []
    flags = compare(claim(), reading(receipt_date="2026-06-01"))
    assert [f.flag for f in flags] == ["stale_receipt"]


def test_the_model_saying_the_category_is_wrong_is_flagged():
    flags = compare(
        claim(), reading(category_consistent=False, note="This is a hotel.")
    )
    assert [f.flag for f in flags] == ["category_mismatch"]
    assert flags[0].message == "This is a hotel."


def test_an_unreadable_receipt_is_reported_rather_than_ignored():
    flags = compare(
        claim(), {**reading(), "status": "unreadable", "note": "too blurry"}
    )
    assert [f.flag for f in flags] == ["unreadable_receipt"]


def test_a_pdf_nobody_could_send_the_model_raises_nothing():
    """'unsupported' is not a finding about the expense, so it must not read as one."""
    assert compare(claim(), {**reading(), "status": "unsupported"}) == []


def test_every_flag_at_once_is_reported_at_once():
    flags = compare(
        claim(amount_cents=50_000, merchant="Figma"),
        reading(merchant="MARRIOTT", receipt_date="2026-01-02"),
    )
    assert {f.flag for f in flags} == {
        "amount_mismatch",
        "merchant_mismatch",
        "stale_receipt",
    }


def test_only_the_contradictions_hold_a_payout():
    assert expense_flags.DIVERTING_FLAGS == {
        "amount_mismatch",
        "merchant_mismatch",
        "category_mismatch",
    }


# -- end to end, through submit --------------------------------------------


def test_a_clean_receipt_lets_the_payout_through(
    client, sign_in, db, reader, funded_nessie
):
    alex = sign_in("alex")
    payee = db.execute(
        "SELECT nessie_id FROM accounts WHERE customer_id = ?", (alex["nessie_id"],)
    ).fetchone()["nessie_id"]
    reader.answer = reading()

    expense_id = post(client).get_json()["expense_id"]

    row = expense_db.get_expense(db, expense_id)
    assert row["receipt_check"] == "clean"
    assert row["status"] == "paid"
    assert expense_db.flags_for(db, [expense_id]) == {}
    assert len(funded_nessie.list_transfers(payee)) == 1


def test_a_contradicted_receipt_holds_the_money_and_queues_the_expense(
    client, sign_in, db, reader, funded_nessie
):
    alex = sign_in("alex")
    payee = db.execute(
        "SELECT nessie_id FROM accounts WHERE customer_id = ?", (alex["nessie_id"],)
    ).fetchone()["nessie_id"]
    # The engine would auto-approve $89 of software and pay it without a person seeing it
    reader.answer = reading(total_cents=8_900)

    body = post(client, amount_cents=89_000).get_json()
    expense_id = body["expense_id"]

    assert body["decision"] == "auto_approved"
    row = expense_db.get_expense(db, expense_id)
    assert row["status"] == "needs_approval"
    assert row["receipt_check"] == "flagged"
    assert row["nessie_transfer_id"] is None
    assert funded_nessie.list_transfers(payee) == []
    assert [f["flag"] for f in expense_db.flags_for(db, [expense_id])[expense_id]] == [
        "amount_mismatch"
    ]


def test_a_held_expense_is_the_manager_s_to_release(client, sign_in, db, reader):
    """The hold routes it to a person; it does not decide anything on that person's behalf."""
    sign_in("alex")
    reader.answer = reading(total_cents=8_900)
    expense_id = post(client, amount_cents=89_000).get_json()["expense_id"]

    sign_in("marcus")  # Engineering's manager
    response = client.post(
        f"/api/expenses/{expense_id}/decision", json={"approve": True}
    )

    assert response.get_json()["status"] == "paid"


def test_a_stale_receipt_is_flagged_without_holding_the_money(
    client, sign_in, db, reader
):
    """A late filing is a filing problem. Holding money over one teaches nothing useful."""
    sign_in("alex")
    reader.answer = reading(receipt_date="2026-01-05")

    expense_id = post(client).get_json()["expense_id"]

    row = expense_db.get_expense(db, expense_id)
    assert row["receipt_check"] == "flagged"
    assert row["status"] == "paid"


def test_an_unreachable_reader_never_costs_anyone_their_expense(
    client, sign_in, db, reader, funded_nessie
):
    """Submitting must not fail because a model was down. The row is already valid."""
    alex = sign_in("alex")
    payee = db.execute(
        "SELECT nessie_id FROM accounts WHERE customer_id = ?", (alex["nessie_id"],)
    ).fetchone()["nessie_id"]
    reader.raises = RuntimeError("endpoint is down")

    response = post(client)

    assert response.status_code == 201
    row = expense_db.get_expense(db, response.get_json()["expense_id"])
    assert row["receipt_check"] == "failed"
    # Held, not paid: nobody read the receipt, which is not the same as it being fine
    assert row["status"] == "needs_approval"
    assert funded_nessie.list_transfers(payee) == []


def test_the_worker_thread_records_a_failure_on_its_own_connection(
    db, reader, funded_nessie
):
    from services.expense_flags import check_expense_async

    # The seeded reading would be served from cache and never reach the reader at all
    db.execute("DELETE FROM receipt_readings")
    db.commit()

    reader.raises = RuntimeError("endpoint is down")
    thread = check_expense_async(9, reader, funded_nessie, conn_factory=lambda: db)
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert expense_db.get_expense(db, 9)["receipt_check"] == "failed"


def test_the_reading_is_cached_by_the_file_rather_than_the_expense(
    client, sign_in, db, reader
):
    """Identical bytes are one file on disk, so they cost one reader call, not two."""
    sign_in("alex")
    reader.answer = reading()

    post(client)
    calls_after_first = reader.calls
    post(client)

    assert calls_after_first == reader.calls


def test_an_expense_with_no_receipt_is_skipped_rather_than_flagged(
    db, reader, funded_nessie
):
    from services.expense_flags import check_expense

    db.execute(
        "UPDATE expenses SET receipt_path = NULL, receipt_hash = NULL WHERE expense_id = 2"
    )
    db.commit()

    assert check_expense(db, 2, reader, funded_nessie) == "skipped"
    assert reader.calls == 0


# -- what the manager and the employee each see -----------------------------


def test_the_manager_sees_the_flag_and_the_reading(client, sign_in):
    sign_in("tomas")  # Sales manager, and expense 9 is the planted mismatch
    page = client.get("/approvals").get_data(as_text=True)

    assert "Receipt check" in page
    assert "Receipt totals $318.00 but $1,318.00 was claimed." in page
    assert "HILTON ATLANTA" in page


def test_the_submitter_is_told_nothing_about_the_check(client, sign_in):
    """Same concealment as the policy verdict: the flag is the department's business."""
    sign_in("omar")  # Sales employee, and expense 9 is his
    page = client.get("/expenses/mine").get_data(as_text=True)

    assert "Receipt check" not in page
    assert "was claimed" not in page


def test_a_trading_name_on_the_receipt_is_not_a_mismatch():
    """ "Meta Ads" on the form against "META PLATFORMS" on the invoice is the same company,
    and flagging it would train managers to ignore the flag that matters."""
    assert compare(claim(merchant="Meta Ads"), reading(merchant="META PLATFORMS")) == []
    assert (
        compare(claim(merchant="LinkedIn Ads"), reading(merchant="LINKEDIN CORP")) == []
    )
    assert compare(claim(merchant="Delta"), reading(merchant="DELTA AIR LINES")) == []


def test_a_shared_filler_word_is_not_a_shared_name():
    flags = compare(claim(merchant="Acme Ads"), reading(merchant="HILTON ADS"))
    assert [f.flag for f in flags] == ["merchant_mismatch"]
