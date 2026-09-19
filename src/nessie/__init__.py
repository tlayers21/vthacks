"""Nessie integration. Nothing outside this package talks to Nessie over HTTP."""

from config import settings

from .mock import InsufficientFunds, MockNessie
from .protocol import Account, Customer, Nessie, Transfer

__all__ = [
    "Account",
    "Customer",
    "InsufficientFunds",
    "MockNessie",
    "Nessie",
    "NessieError",
    "Transfer",
    "get_nessie",
]

# Shared across calls so mock state (balances, transfers) survives within a process.
_mock_singleton: MockNessie | None = None


def get_nessie(mode: str | None = None) -> Nessie:
    """Return the Nessie implementation selected by NESSIE_MODE (or `mode`)."""
    global _mock_singleton
    mode = (mode or settings.nessie_mode).lower()

    if mode == "real":
        from .client import NessieClient

        return NessieClient()
    if mode == "mock":
        if _mock_singleton is None:
            _mock_singleton = MockNessie()
        return _mock_singleton
    raise ValueError(f"NESSIE_MODE must be 'real' or 'mock', got {mode!r}")


def __getattr__(name: str):
    # Keep NessieError importable from the package without importing the HTTP client
    # (and therefore requiring an API key) at package-import time.
    if name == "NessieError":
        from .client import NessieError

        return NessieError
    raise AttributeError(name)
