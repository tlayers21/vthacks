"""Receipt reading. Nothing outside this package makes a model call."""

from config import settings

from .content import content_for
from .mock import MockReceiptReader
from .parse import normalize, unreadable
from .protocol import ReceiptContent, ReceiptReader, ReceiptReading

__all__ = [
    "LLMError",
    "MockReceiptReader",
    "ReceiptContent",
    "ReceiptReader",
    "ReceiptReading",
    "content_for",
    "get_reader",
    "normalize",
    "unreadable",
]


def get_reader(mode: str | None = None) -> ReceiptReader:
    """Return the reader selected by LLM_MODE (or `mode`)."""
    mode = (mode or settings.llm_mode).lower()

    if mode == "real":
        from .receipt import DSPyReceiptReader

        return DSPyReceiptReader()
    if mode == "mock":
        # Stateless, unlike MockNessie, so there is nothing to share between calls
        return MockReceiptReader()
    raise ValueError(f"LLM_MODE must be 'real' or 'mock', got {mode!r}")


def __getattr__(name: str):
    # Keep LLMError importable from the package without importing dspy (a second or two
    # of import time, and an API key) just to name the exception
    if name == "LLMError":
        from .receipt import LLMError

        return LLMError
    raise AttributeError(name)
