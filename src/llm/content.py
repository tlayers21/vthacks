"""Turning a stored receipt file into something a model can be shown.

Three shapes, and which one a receipt gets is decided by its mime type alone, never by
its extension -- `services/receipts.py` already checked those agree.

SVG goes as text rather than as an image. Every seeded receipt is an SVG whose source
carries the printed words verbatim, so reading it as text is both exact and far cheaper
than rendering it; and it means the demo does not depend on the model's vision holding up.
"""

import base64
from pathlib import Path

from config import settings

from .protocol import ReceiptContent

RASTER_MIMES = {"image/png", "image/jpeg", "image/webp"}


def content_for(path: Path, mime: str) -> ReceiptContent:
    data = path.read_bytes()

    if mime == "image/svg+xml":
        return {"kind": "text", "value": data.decode("utf-8", errors="replace")}

    if mime in RASTER_MIMES:
        if len(data) > settings.llm_max_image_bytes:
            limit_mb = settings.llm_max_image_bytes // (1024 * 1024)
            return {
                "kind": "unsupported",
                "value": f"image is over {limit_mb}MB",
            }
        encoded = base64.b64encode(data).decode("ascii")
        return {"kind": "image", "value": f"data:{mime};base64,{encoded}"}

    # PDFs land here. The endpoint takes images, not documents, and rendering one would
    # cost a dependency the rest of this project does without
    return {"kind": "unsupported", "value": f"cannot read {mime}"}
