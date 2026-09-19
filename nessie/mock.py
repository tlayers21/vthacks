"""In-memory Nessie. No network, no API key, deterministic ids.

This is what tests run against, and what the demo falls back to if the sandbox is
unreachable. Ids are sha1-derived from a per-kind counter so the same sequence of calls
always produces the same ids -- tests can assert on them.
"""

import hashlib
import itertools

from .protocol import Account, Customer, Transfer


class InsufficientFunds(Exception):
    """Raised when a transfer would overdraw the payer."""


class MockNessie:
    def __init__(self) -> None:
        self._customers: dict[str, Customer] = {}
        self._accounts: dict[str, Account] = {}
        self._transfers: dict[str, Transfer] = {}
        self._purchases: dict[str, dict] = {}
        self._counters: dict[str, itertools.count] = {}

    def _next_id(self, kind: str) -> str:
        counter = self._counters.setdefault(kind, itertools.count(1))
        return hashlib.sha1(f"{kind}:{next(counter)}".encode()).hexdigest()[:24]

    # -- customers ----------------------------------------------------------

    def create_customer(self, first_name: str, last_name: str) -> Customer:
        customer: Customer = {
            "id": self._next_id("customer"),
            "first_name": first_name,
            "last_name": last_name,
        }
        self._customers[customer["id"]] = customer
        return customer

    # -- accounts -----------------------------------------------------------

    def create_account(
        self,
        customer_id: str,
        nickname: str,
        balance_cents: int = 0,
        account_type: str = "Checking",
    ) -> Account:
        if customer_id not in self._customers:
            raise KeyError(f"no such customer: {customer_id}")
        account: Account = {
            "id": self._next_id("account"),
            "customer_id": customer_id,
            "nickname": nickname,
            "balance_cents": balance_cents,
        }
        self._accounts[account["id"]] = account
        return account

    def get_balance(self, account_id: str) -> int:
        return self._accounts[account_id]["balance_cents"]

    # -- money movement -----------------------------------------------------

    def create_transfer(
        self,
        payer_id: str,
        payee_id: str,
        amount_cents: int,
        description: str = "",
    ) -> Transfer:
        if amount_cents <= 0:
            raise ValueError("transfer amount must be positive")
        payer = self._accounts[payer_id]
        payee = self._accounts[payee_id]
        if payer["balance_cents"] < amount_cents:
            raise InsufficientFunds(
                f"{payer_id} has {payer['balance_cents']}c, needs {amount_cents}c"
            )

        payer["balance_cents"] -= amount_cents
        payee["balance_cents"] += amount_cents

        transfer: Transfer = {
            "id": self._next_id("transfer"),
            "payer_id": payer_id,
            "payee_id": payee_id,
            "amount_cents": amount_cents,
            "status": "completed",
            "description": description,
        }
        self._transfers[transfer["id"]] = transfer
        return transfer

    def create_purchase(
        self,
        account_id: str,
        merchant_id: str,
        amount_cents: int,
        description: str = "",
    ) -> dict:
        account = self._accounts[account_id]
        account["balance_cents"] -= amount_cents
        purchase = {
            "id": self._next_id("purchase"),
            "account_id": account_id,
            "merchant_id": merchant_id,
            "amount_cents": amount_cents,
            "description": description,
        }
        self._purchases[purchase["id"]] = purchase
        return purchase

    def list_transfers(self, account_id: str) -> list[Transfer]:
        return [
            t
            for t in self._transfers.values()
            if account_id in (t["payer_id"], t["payee_id"])
        ]
