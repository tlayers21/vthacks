"""Bounding and whitelisting whatever a reader produced.

Pure, and the only way a model's answer becomes a value this app will act on. DSPy already
coerces its output fields to the declared types; this is the second half, the part types
cannot do -- a total of nine million dollars, a date in the wrong century, a merchant name
a thousand characters long. Anything that does not survive is dropped rather than raised
on, because a receipt nobody could read is an ordinary outcome and a crashed worker is not.

spec 3: "Every LLM output is validated against a schema or whitelist."
"""

import re
from datetime import date

from .protocol import ReceiptReading

MAX_MERCHANT = 100
MAX_LINE_ITEMS = 10
MAX_LINE_ITEM = 120
MAX_NOTE = 300

# A total beyond this is a misread decimal, not a receipt: the largest per-expense cap in
# policy/rules.py is $25,000, and nothing sane prints eight figures
MAX_TOTAL_CENTS = 100_000_000

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def unreadable(note: str | None) -> ReceiptReading:
    return {
        "status": "unreadable",
        "merchant": None,
        "total_cents": None,
        "receipt_date": None,
        "line_items": [],
        "category_consistent": None,
        "note": text(note, MAX_NOTE) or "",
    }


def normalize(
    *,
    readable,
    merchant,
    total_cents,
    receipt_date,
    line_items,
    category_consistent,
    note,
) -> ReceiptReading:
    """Validate one reader's answer. Returns an `unreadable` reading rather than raising."""
    if readable is not True:
        return unreadable(text(note, MAX_NOTE) or "the receipt could not be read")

    total = cents(total_cents)
    if total is None:
        # A reading with no total cannot be compared against anything, which is the only
        # question being asked of it
        return unreadable("no total could be read off the receipt")

    return {
        "status": "read",
        "merchant": text(merchant, MAX_MERCHANT),
        "total_cents": total,
        "receipt_date": iso_date(receipt_date),
        "line_items": line_item_list(line_items),
        "category_consistent": consistency(category_consistent),
        "note": text(note, MAX_NOTE) or "",
    }


def cents(value) -> int | None:
    """Cents only. A float or a "$318.00" is a reader ignoring the schema, not a total."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value <= 0 or value > MAX_TOTAL_CENTS:
        return None
    return value


def text(value, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())[:limit]
    return cleaned or None


def iso_date(value) -> str | None:
    if not isinstance(value, str) or not _ISO_DATE.match(value):
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


def line_item_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    items = [text(item, MAX_LINE_ITEM) for item in value[:MAX_LINE_ITEMS]]
    return [item for item in items if item]


def consistency(value) -> bool | None:
    """'unsure', and anything unexpected, mean the model did not answer the question."""
    if value == "yes":
        return True
    if value == "no":
        return False
    return None
