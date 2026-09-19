"""In-memory receipt reader. No network, no API key, deterministic.

DELIBERATELY DUMBER THAN THE MODEL. It reads the sample SVGs in data/sample_receipts by
pulling the text out of their <text> elements and looking for a line that says TOTAL. It
cannot read an image at all, it never answers the consistency question, and it has no
opinion about anything it was not shown. So passing against this mock proves the flagging
and payout-hold logic works -- it proves nothing about the model.

It exists because the demo has to survive a dead wifi, and because tests that call a paid
endpoint are tests nobody runs.
"""

import re

from .parse import normalize, unreadable
from .protocol import ReceiptContent, ReceiptReading

_TEXT_ELEMENT = re.compile(r"<text[^>]*>(.*?)</text>", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_MONEY = re.compile(r"\$\s*([\d,]+)\.(\d{2})")
_DATE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b"
)
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip


class MockReceiptReader:
    def read(
        self,
        content: ReceiptContent,
        *,
        claimed_category: str = "",
        claimed_description: str = "",
    ) -> ReceiptReading:
        if content["kind"] == "unsupported":
            reading = unreadable(content["value"])
            reading["status"] = "unsupported"
            return reading
        if content["kind"] != "text":
            return unreadable("the mock reader cannot read an image")

        lines = _lines(content["value"])
        total = _total(lines)
        if total is None:
            return unreadable("no total line found in the receipt")

        # Through the same validator the real reader uses, so the two cannot disagree
        # about what a well-formed reading looks like
        return normalize(
            readable=True,
            merchant=lines[0] if lines else None,
            total_cents=total,
            receipt_date=_receipt_date(lines),
            line_items=_line_items(lines),
            # Never guessed: a consistency verdict from a regex would be a lie with a
            # manager's name on it
            category_consistent="unsure",
            note="read offline by the mock reader",
        )


def _lines(svg: str) -> list[str]:
    """The receipt's printed text, in document order, one entry per <text> element."""
    out: list[str] = []
    for match in _TEXT_ELEMENT.finditer(svg):
        text = " ".join(_TAG.sub("", match.group(1)).split())
        if text:
            out.append(text)
    return out


def _total(lines: list[str]) -> int | None:
    """The amount on the last line mentioning a total -- receipts print subtotals first."""
    for line in reversed(lines):
        if "total" not in line.lower() or "subtotal" in line.lower():
            continue
        money = _MONEY.search(line)
        if money:
            return int(money.group(1).replace(",", "")) * 100 + int(money.group(2))

    # The samples put TOTAL and its amount in adjacent elements, so fall back to pairing
    for index, line in enumerate(lines):
        if line.strip().lower() == "total" and index + 1 < len(lines):
            money = _MONEY.search(lines[index + 1])
            if money:
                return int(money.group(1).replace(",", "")) * 100 + int(money.group(2))
    return None


def _line_items(lines: list[str]) -> list[str]:
    """The samples print an item and its amount as two adjacent elements, so pair them."""
    items: list[str] = []
    for index, line in enumerate(lines[:-1]):
        nxt = lines[index + 1]
        if "$" in line or "$" not in nxt or "total" in line.lower():
            continue
        items.append(f"{line} {nxt}")
    return items[:10]


def _receipt_date(lines: list[str]) -> str | None:
    for line in lines:
        match = _DATE.search(line)
        if match:
            month = _MONTHS[match.group(1)[:3].lower()]
            return f"{match.group(3)}-{month:02d}-{int(match.group(2)):02d}"
    return None
