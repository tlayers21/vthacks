"""The interface every Nessie implementation satisfies.

Only the `nessie` package may make HTTP calls to Nessie. Everything else in the app
depends on this protocol, which is what lets the whole thing run offline against the
mock when the wifi or the sandbox misbehaves during a demo.

Money crosses this boundary as INTEGER CENTS, matching how the database stores it.
Nessie itself speaks decimal dollars; the conversion happens inside the client.
"""

from typing import Protocol, TypedDict


class Customer(TypedDict):
    id: str
    first_name: str
    last_name: str


class Account(TypedDict):
    id: str
    customer_id: str
    nickname: str
    balance_cents: int


class Transfer(TypedDict):
    id: str
    payer_id: str
    payee_id: str
    amount_cents: int
    status: str
    description: str


class Nessie(Protocol):
    def create_customer(self, first_name: str, last_name: str) -> Customer:
        """Create a customer. Returns the created record including its Nessie id."""
        ...

    def create_account(
        self,
        customer_id: str,
        nickname: str,
        balance_cents: int = 0,
        account_type: str = "Checking",
    ) -> Account:
        """Create an account owned by `customer_id`."""
        ...

    def get_balance(self, account_id: str) -> int:
        """Current balance of an account, in cents."""
        ...

    def create_transfer(
        self,
        payer_id: str,
        payee_id: str,
        amount_cents: int,
        description: str = "",
    ) -> Transfer:
        """Move money between two accounts. Returns the transfer, including its id.

        Callers must persist the returned id before marking anything paid -- that
        ordering is what makes a payout retryable instead of duplicable.
        """
        ...

    def create_purchase(
        self,
        account_id: str,
        merchant_id: str,
        amount_cents: int,
        description: str = "",
    ) -> dict:
        """Record a purchase against an account. Used for seeding history only."""
        ...

    def list_transfers(self, account_id: str) -> list[Transfer]:
        """All transfers involving an account."""
        ...

    def list_customers(self) -> list[Customer]:
        """Every customer the API key can see."""
        ...

    def list_accounts(self, customer_id: str) -> list[Account]:
        """Accounts owned by one customer."""
        ...

    def delete_account(self, account_id: str) -> None:
        """Delete an account. Used by seeding to reclaim a previous run's accounts.

        There is no matching delete for customers -- the live API has no such route --
        so re-seeding reuses customers by name instead of creating duplicates.
        """
        ...
