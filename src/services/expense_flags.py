"""Comparing a receipt against the claim made about it (spec 7.2).

A flag is not a violation. A violation is the policy engine's verdict, reproducible from
the row at any time, and it lives in `expense_violations`. A flag is what a model noticed
about a file, it cannot be recomputed without asking again, and it lives in
`expense_flags`. Keeping them apart is what stops anything an LLM said from ever becoming
policy: `compare` below is pure and mechanical, and the model's only influence on it is the
numbers it read off the paper.

The model never decides anything. It reports a total, a merchant and a date; the rules for
what those mean are here, in code a person can read.
"""

import json
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime

from db import expenses as expense_db
from db.connect import connect, transaction
from services import receipts as receipt_service

log = logging.getLogger(__name__)

# Absorbs a tip rounded on the paper but not in the form, and nothing more. Anything wider
# and the $890-for-an-$89-receipt case stops being the only thing this catches.
TOLERANCE_CENTS = 100
TOLERANCE_FRACTION = 0.01

STALE_AFTER_DAYS = 30

# The three that mean the claim and the receipt disagree about the same fact, and so hold a
# payout until a person has looked. A stale or unreadable receipt is a filing problem, not a
# contradiction, and punishing a bad photo would teach people not to attach one.
DIVERTING_FLAGS = frozenset(
    {"amount_mismatch", "merchant_mismatch", "category_mismatch"}
)


@dataclass(frozen=True, slots=True)
class Flag:
    flag: str
    message: str


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def compare(expense, reading) -> list[Flag]:
    """What this receipt contradicts about this expense. Pure -- no SQL, no network."""
    if reading["status"] == "unsupported":
        return []
    if reading["status"] != "read":
        return [
            Flag(
                "unreadable_receipt",
                reading.get("note")
                or "The receipt could not be read, so nothing was checked against it.",
            )
        ]

    flags: list[Flag] = []
    claimed = expense["amount_cents"]
    total = reading["total_cents"]

    if total is not None and _differs(total, claimed):
        flags.append(
            Flag(
                "amount_mismatch",
                f"Receipt totals {_money(total)} but {_money(claimed)} was claimed.",
            )
        )

    if _merchant_differs(expense["merchant"], reading["merchant"]):
        flags.append(
            Flag(
                "merchant_mismatch",
                f"Receipt is from {reading['merchant']} "
                f"but {expense['merchant']} was entered.",
            )
        )

    if reading["category_consistent"] is False:
        flags.append(
            Flag(
                "category_mismatch",
                reading.get("note")
                or f"The receipt does not look like {expense['category']}.",
            )
        )

    stale = _stale_days(reading["receipt_date"], expense["submitted_at"])
    if stale is not None:
        flags.append(
            Flag(
                "stale_receipt",
                f"Receipt is dated {reading['receipt_date']}, {stale} days "
                f"before it was submitted.",
            )
        )

    return flags


def _differs(total_cents: int, claimed_cents: int) -> bool:
    allowed = max(TOLERANCE_CENTS, int(claimed_cents * TOLERANCE_FRACTION))
    return abs(total_cents - claimed_cents) > allowed


def _merchant_differs(claimed: str | None, read: str | None) -> bool:
    """Only flagged when the two names have nothing in common at all.

    A receipt header is "FIGMA INC" where the form says "Figma", and "META PLATFORMS"
    where it says "Meta Ads". Substring alone gets the first and not the second, so a
    shared word counts too -- a manager who gets told off for abbreviating stops reading
    flags, and a flag nobody reads protects nobody. Four letters because "ads", "inc" and
    "llc" are shared by companies with nothing else in common.
    """
    if not claimed or not read:
        return False
    a, b = claimed.casefold().strip(), read.casefold().strip()
    if a in b or b in a:
        return False
    return not (_words(a) & _words(b))


def _words(name: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", name) if len(word) >= 4}


def _stale_days(receipt_date: str | None, submitted_at) -> int | None:
    printed = _as_date(receipt_date)
    submitted = _as_date(submitted_at)
    # Not knowing when either happened is not evidence that one was late
    if printed is None or submitted is None:
        return None
    gap = (submitted - printed).days
    return gap if gap > STALE_AFTER_DAYS else None


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def check_expense(
    conn: sqlite3.Connection, expense_id: int, reader=None, nessie=None
) -> str:
    """Read the expense's receipt, record what it says, then release or hold the payout.

    Returns the `receipt_check` state it settled on. Safe to call more than once: the
    reading is cached by file hash and the flags are replaced rather than appended, so a
    re-check restates the finding instead of doubling it.
    """
    expense = expense_db.get_expense(conn, expense_id)
    if expense is None:
        raise KeyError(f"no such expense: {expense_id}")
    if not expense["receipt_hash"]:
        return _settle(conn, expense, [], "skipped", nessie)

    if reader is None:
        from llm import get_reader

        reader = get_reader()

    reading, model = _reading_for(conn, expense, reader)
    flags = compare(expense, reading)
    state = "flagged" if flags else "clean"

    # One transaction, and the network call is already behind us
    with transaction(conn):
        expense_db.save_reading(conn, expense["receipt_hash"], reading, model)
        expense_db.replace_flags(conn, expense_id, flags)
        expense_db.set_receipt_check(conn, expense_id, state)

    return _settle(conn, expense, flags, state, nessie)


def _reading_for(conn: sqlite3.Connection, expense, reader) -> tuple[dict, str]:
    """The cached reading for these bytes, or a fresh one. Never inside a transaction."""
    cached = expense_db.get_reading(conn, expense["receipt_hash"])
    if cached is not None and cached["status"] == "read":
        return (
            {
                "status": cached["status"],
                "merchant": cached["merchant"],
                "total_cents": cached["total_cents"],
                "receipt_date": cached["receipt_date"],
                "line_items": json.loads(cached["line_items"] or "[]"),
                # Not cached: it is an answer about one claim, not about the file
                "category_consistent": None,
                "note": "",
            },
            cached["model"],
        )

    from config import settings
    from llm import content_for

    path = receipt_service.resolve(expense["receipt_path"])
    content = content_for(path, expense["receipt_mime"] or "")
    reading = reader.read(
        content,
        claimed_category=expense["category"] or "",
        claimed_description=expense["description"] or "",
    )
    return dict(reading), getattr(reader, "model", settings.llm_model)


def _settle(conn: sqlite3.Connection, expense, flags, state: str, nessie) -> str:
    """Release the payout the submit path deliberately did not make, or leave it held.

    Only `auto_approved` expenses are waiting on this. Everything else is already in a
    manager's queue, where the flag will be sitting next to it.
    """
    if expense["policy_decision"] != "auto_approved":
        return state
    if expense["status"] != "approved":
        return state

    diverting = [flag.flag for flag in flags if flag.flag in DIVERTING_FLAGS]
    if diverting:
        # The engine would have paid this without a person seeing it, and the receipt says
        # the claim is wrong. Route it to the manager rather than to the bank.
        with transaction(conn):
            expense_db.set_status(conn, expense["expense_id"], "needs_approval")
        log.info("held payout for expense %s: %s", expense["expense_id"], diverting)
        return state

    from services.expenses import pay_expense

    pay_expense(conn, expense["expense_id"], nessie)
    return state


def check_expense_safely(
    conn: sqlite3.Connection, expense_id: int, reader=None, nessie=None
) -> str:
    """`check_expense`, but a reader that is down never costs anyone their expense.

    Submitting is not allowed to fail because a model was unreachable -- the row is already
    written and the claim is already valid. What a failure does cost is the fast path: an
    expense the engine would have paid unseen is routed to its manager instead, because
    "nobody could read the receipt" is not the same as "the receipt was fine".
    """
    try:
        return check_expense(conn, expense_id, reader, nessie)
    except Exception as exc:  # noqa: BLE001
        log.warning("receipt check failed for expense %s: %s", expense_id, exc)
        try:
            _record_failure(conn, expense_id)
        except Exception:
            log.exception("could not record the failed check for %s", expense_id)
        return "failed"


def _record_failure(conn: sqlite3.Connection, expense_id: int) -> None:
    expense = expense_db.get_expense(conn, expense_id)
    with transaction(conn):
        expense_db.set_receipt_check(conn, expense_id, "failed")
        if (
            expense is not None
            and expense["policy_decision"] == "auto_approved"
            and expense["status"] == "approved"
        ):
            expense_db.set_status(conn, expense_id, "needs_approval")


def check_expense_async(
    expense_id: int, reader=None, nessie=None, conn_factory=connect
) -> threading.Thread:
    """Run the check off the request thread, on a connection of its own.

    The request's connection is closed at app-context teardown, so the worker opens one.
    `conn_factory` is the seam tests use; nothing else passes it.
    """

    # Only a connection this worker opened is a connection it may close -- a test hands in
    # one it still needs afterwards, exactly as app.config["KEEP_CONN"] does per request
    owns_conn = conn_factory is connect

    def run() -> None:
        conn = conn_factory()
        try:
            check_expense_safely(conn, expense_id, reader, nessie)
        finally:
            if owns_conn:
                conn.close()

    thread = threading.Thread(
        target=run, name=f"receipt-check-{expense_id}", daemon=True
    )
    thread.start()
    return thread


__all__ = [
    "DIVERTING_FLAGS",
    "Flag",
    "check_expense",
    "check_expense_async",
    "check_expense_safely",
    "compare",
]
