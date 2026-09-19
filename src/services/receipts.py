"""Validating and storing uploaded receipts.

The stored filename is always derived from the sha256 of the bytes, never from what the
client called the file -- that is what makes path traversal impossible rather than merely
unlikely. The original name is kept alongside it for display only.

Content type is checked twice, against the extension and against the leading magic bytes,
because the extension is entirely attacker-controlled.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from config import settings


class RejectedReceipt(Exception):
    """The upload is not something we are willing to store."""


# extension -> (mime, magic byte prefixes). SVG is absent on purpose: it can carry script,
# and nothing stops a browser executing it if it is ever served as a document.
ALLOWED: dict[str, tuple[str, tuple[bytes, ...]]] = {
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "webp": ("image/webp", (b"RIFF",)),
    "pdf": ("application/pdf", (b"%PDF-",)),
}


@dataclass(frozen=True, slots=True)
class StoredReceipt:
    path: str
    filename: str
    mime: str
    hash: str


def _extension(filename: str) -> str:
    return Path(filename or "").suffix.lstrip(".").lower()


def validate(filename: str, data: bytes) -> str:
    """Return the canonical extension, or raise RejectedReceipt."""
    if not data:
        raise RejectedReceipt("that file is empty")
    if len(data) > settings.max_receipt_bytes:
        limit_mb = settings.max_receipt_bytes // (1024 * 1024)
        raise RejectedReceipt(f"receipts must be under {limit_mb}MB")

    extension = _extension(filename)
    if extension not in ALLOWED:
        allowed = ", ".join(sorted(ALLOWED))
        raise RejectedReceipt(f"receipts must be one of: {allowed}")

    _, magic = ALLOWED[extension]
    if not any(data.startswith(prefix) for prefix in magic):
        raise RejectedReceipt(f"that file is not really a {extension}")
    return extension


def store(filename: str, data: bytes) -> StoredReceipt:
    """Validate and write to the receipts directory. Identical bytes reuse one file."""
    extension = validate(filename, data)
    mime, _ = ALLOWED[extension]
    digest = hashlib.sha256(data).hexdigest()

    stored_name = f"{digest}.{extension}"
    settings.receipts_dir.mkdir(parents=True, exist_ok=True)
    destination = settings.receipts_dir / stored_name
    if not destination.exists():
        destination.write_bytes(data)

    return StoredReceipt(
        path=stored_name, filename=Path(filename).name, mime=mime, hash=digest
    )


def install_samples() -> int:
    """Copy data/sample_receipts into the receipts directory under their hashed names.

    Seeded expenses reference those names, so the samples are indistinguishable from real
    uploads once installed. Called by init_db and seed rather than left to the reader,
    because a seeded receipt_path with no file behind it renders as a broken image.
    """
    source = settings.sample_receipts_dir
    if not source.is_dir():
        return 0

    settings.receipts_dir.mkdir(parents=True, exist_ok=True)
    installed = 0
    for sample in sorted(source.iterdir()):
        if not sample.is_file():
            continue
        data = sample.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        destination = settings.receipts_dir / f"{digest}{sample.suffix.lower()}"
        if not destination.exists():
            destination.write_bytes(data)
        installed += 1
    return installed


def resolve(stored_path: str) -> Path:
    """Absolute path of a stored receipt, refusing anything outside the receipts directory.

    Belt and braces: `stored_path` comes from our own database rather than a request, but a
    single bad write upstream should not become an arbitrary file read.
    """
    root = settings.receipts_dir.resolve()
    candidate = (root / stored_path).resolve()
    if not candidate.is_relative_to(root):
        raise RejectedReceipt("receipt path escapes the receipts directory")
    return candidate
