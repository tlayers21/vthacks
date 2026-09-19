"""In-memory Nessie. No network, no API key, deterministic ids.

This is what tests run against, and what the demo falls back to if the sandbox is
unreachable. Ids are sha1-derived from a per-kind counter so the same sequence of calls
always produces the same ids -- tests can assert on them.

DELIBERATELY STRICTER THAN THE LIVE SANDBOX. This mock actually moves money between
accounts, rejects overdrafts, and rejects non-positive amounts. The real API does none
of that -- it stores transaction records and never touches a balance (see the notes in
client.py). So passing here is necessary but not sufficient: code that relies on Nessie
balances changing will work against the mock and silently do nothing against `real`.
Treat our own database as the source of truth for balances and this stays a useful
stand-in rather than a misleading one.
"""

import hashlib
import itertools
from collections.abc import Iterable

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
        self._reserved: set[str] = set()

    def _next_id(self, kind: str) -> str:
        counter = self._counters.setdefault(kind, itertools.count(1))
        while True:
            candidate = hashlib.sha1(f"{kind}:{next(counter)}".encode()).hexdigest()[
                :24
            ]
            if candidate not in self._reserved:
                return candidate

    def reserve_ids(self, ids: Iterable[str]) -> None:
        """Refuse to re-issue ids that something else already handed out.

        The counter restarts at 1 in every process, so a mock started fresh against a database
        seeded by an earlier run would otherwise mint a transfer id that database already
        stores -- and the UNIQUE constraint on expenses.nessie_transfer_id would reject it.
        """
        self._reserved.update(i for i in ids if i)

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

    def seed_account(
        self, account_id: str, customer_id: str, nickname: str, balance_cents: int
    ) -> Account:
        """Register an account that already exists in our database, keeping its id.

        Deliberately not on the Nessie protocol -- the real client cannot choose its own ids.
        This exists because db/seed.py registers accounts with a mock in its own process and
        then exits, so the Flask process starts with a mock that has never heard of them and
        the first payout would KeyError.
        """
        account: Account = {
            "id": account_id,
            "customer_id": customer_id,
            "nickname": nickname,
            "balance_cents": balance_cents,
        }
        self._accounts[account_id] = account
        return account

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

    # -- housekeeping -------------------------------------------------------

    def list_customers(self) -> list[Customer]:
        return list(self._customers.values())

    def list_accounts(self, customer_id: str) -> list[Account]:
        return [a for a in self._accounts.values() if a["customer_id"] == customer_id]

    def delete_account(self, account_id: str) -> None:
        self._accounts.pop(account_id, None)
