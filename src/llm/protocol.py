"""The interface every receipt reader satisfies.

Only the `llm` package may make a model call. Everything else depends on this protocol,
which is what lets the whole thing run offline against the mock when the wifi or the
endpoint misbehaves during a demo -- the same arrangement `nessie/protocol.py` makes.

Money crosses this boundary as INTEGER CENTS, matching how the database stores it.
A receipt prints decimal dollars; the conversion happens inside the reader.

Nothing that comes back through here has been trusted yet. A reading is what a model
claims a receipt says; `services/expense_flags.py` is what decides it means anything.
"""

from typing import Literal, Protocol, TypedDict

# 'text' carries the receipt's own source (SVG), 'image' a data: URI, 'unsupported' means
# there is nothing we can hand a model -- a PDF, or a raster too large to inline.
ContentKind = Literal["text", "image", "unsupported"]

ReadingStatus = Literal["read", "unreadable", "unsupported", "failed"]


class ReceiptContent(TypedDict):
    kind: ContentKind
    # The SVG source for 'text', a data: URI for 'image', the reason for 'unsupported'
    value: str


class ReceiptReading(TypedDict):
    status: ReadingStatus
    merchant: str | None
    total_cents: int | None
    # ISO 8601 date, or None when the receipt does not print one we could parse
    receipt_date: str | None
    line_items: list[str]
    # None when the reader was not asked, False when the receipt contradicts the category
    category_consistent: bool | None
    note: str


class ReceiptReader(Protocol):
    def read(
        self,
        content: ReceiptContent,
        *,
        claimed_category: str = "",
        claimed_description: str = "",
    ) -> ReceiptReading:
        """Extract what the receipt says. Never raises for a bad receipt, only for a bad call.

        `claimed_category` and `claimed_description` are passed so the reader can answer
        the consistency question in the same pass. They are context, not an instruction:
        a reader that cannot tell must return None rather than agreeing.
        """
        ...
