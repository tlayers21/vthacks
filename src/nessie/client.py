"""Real Nessie client.

Built on stdlib urllib so the project needs no HTTP dependency and `seed.py` runs on a
fresh checkout without anyone re-syncing their venv.

Three things about the live sandbox, each verified by probing it directly, that
docs/nessie-reference.md does not mention:

1. It is a record store, not a bank. Creating a transfer or a deposit persists a
   document and leaves both account balances untouched. Our own database is therefore
   authoritative for balances; Nessie is the audit trail.
2. `TransferCreate` accepts only {transaction_date, status, amount, description} and
   rejects `medium` and `payee_id` outright. There is no destination field, so the payee
   is encoded into `description` and parsed back out by `list_transfers`.
3. `amount` is truncated to a whole number (1.99 is stored as 1), so decimal dollars
   silently lose cents. We send integer cents as the amount and treat that as Nessie's
   unit throughout -- lossless, and self-consistent with the database.

Responses are also not uniform: mutations return either the resource or an
acknowledgement wrapper {code, message, objectCreated: {...}}, so every create unwraps
both shapes, and list endpoints key the id as `id` while single fetches use `_id`.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from config import settings

from .protocol import Account, Customer, Transfer

# Nessie requires a full address on customer creation; this is the placeholder used for
# every seeded customer. It is not meaningful data.
_PLACEHOLDER_ADDRESS = {
    "street_number": "1",
    "street_name": "Main St",
    "city": "Arlington",
    "state": "VA",
    "zip": "22201",
}


class NessieError(RuntimeError):
    """A Nessie request failed. Carries the status code and response body."""

    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"Nessie {status} for {url}: {body}")
        self.status = status
        self.body = body


_PAYEE_TAG = re.compile(r"\s*\[payee:([^\]]+)\]\s*$")


def _amount(value) -> int:
    """Nessie amounts are already integer cents -- see the unit note in the docstring."""
    return int(value or 0)


def _tag_payee(description: str, payee_id: str) -> str:
    """TransferCreate has no destination field, so carry it in the only free-text one."""
    return f"{description} [payee:{payee_id}]".strip()


def _untag_payee(description: str) -> tuple[str, str]:
    match = _PAYEE_TAG.search(description or "")
    if not match:
        return description or "", ""
    return _PAYEE_TAG.sub("", description).strip(), match.group(1)


def _unwrap(payload):
    """Nessie create responses are not uniform -- pull out the resource either way."""
    if isinstance(payload, dict) and "objectCreated" in payload:
        return payload["objectCreated"]
    return payload


class NessieClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 15.0,
    ):
        self.api_key = api_key if api_key is not None else settings.nessie_api_key
        self.base_url = (base_url or settings.nessie_base_url).rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise ValueError(
                "NESSIE_API_KEY is not set. Set it in .env, or use NESSIE_MODE=mock."
            )

    def _request(self, method: str, path: str, body: dict | None = None):
        url = f"{self.base_url}{path}?" + urllib.parse.urlencode({"key": self.api_key})
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as exc:
            raise NessieError(
                exc.code, exc.read().decode(errors="replace"), url
            ) from exc
        except urllib.error.URLError as exc:
            raise NessieError(0, f"connection failed: {exc.reason}", url) from exc

        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Some mutations answer with a bare string rather than JSON.
            return {"message": raw}

    # -- customers ----------------------------------------------------------

    def create_customer(self, first_name: str, last_name: str) -> Customer:
        created = _unwrap(
            self._request(
                "POST",
                "/customers",
                {
                    "first_name": first_name,
                    "last_name": last_name,
                    "address": _PLACEHOLDER_ADDRESS,
                },
            )
        )
        return {
            "id": created["_id"],
            "first_name": created.get("first_name", first_name),
            "last_name": created.get("last_name", last_name),
        }

    # -- accounts -----------------------------------------------------------

    def create_account(
        self,
        customer_id: str,
        nickname: str,
        balance_cents: int = 0,
        account_type: str = "Checking",
    ) -> Account:
        created = _unwrap(
            self._request(
                "POST",
                f"/customers/{customer_id}/accounts",
                {
                    "type": account_type,
                    "nickname": nickname,
                    "rewards": 0,
                    "balance": balance_cents,
                },
            )
        )
        return {
            "id": created["_id"],
            "customer_id": customer_id,
            "nickname": created.get("nickname", nickname),
            "balance_cents": _amount(created.get("balance")),
        }

    def get_balance(self, account_id: str) -> int:
        """Nessie never updates this after creation -- our database owns live balances."""
        account = self._request("GET", f"/accounts/{account_id}")
        return _amount(account.get("balance"))

    # -- money movement -----------------------------------------------------

    def create_transfer(
        self,
        payer_id: str,
        payee_id: str,
        amount_cents: int,
        description: str = "",
    ) -> Transfer:
        created = _unwrap(
            self._request(
                "POST",
                f"/accounts/{payer_id}/transfers",
                {
                    "transaction_date": date.today().isoformat(),
                    "status": "pending",
                    "amount": amount_cents,
                    "description": _tag_payee(description, payee_id),
                },
            )
        )
        return {
            "id": created["_id"],
            # Echoed from the arguments: the record Nessie stores has neither side
            "payer_id": payer_id,
            "payee_id": payee_id,
            "amount_cents": _amount(created.get("amount")) or amount_cents,
            "status": created.get("status", "pending"),
            "description": description,
        }

    def create_purchase(
        self,
        account_id: str,
        merchant_id: str,
        amount_cents: int,
        description: str = "",
    ) -> dict:
        return _unwrap(
            self._request(
                "POST",
                f"/accounts/{account_id}/purchases",
                {
                    "merchant_id": merchant_id,
                    "medium": "balance",
                    "amount": amount_cents,
                    "status": "pending",
                    "description": description,
                },
            )
        )

    # -- housekeeping -------------------------------------------------------

    def list_customers(self) -> list[Customer]:
        rows = self._request("GET", "/customers") or []
        return [
            {
                "id": r.get("_id") or r.get("id", ""),
                "first_name": r.get("first_name", ""),
                "last_name": r.get("last_name", ""),
            }
            for r in rows
        ]

    def list_accounts(self, customer_id: str) -> list[Account]:
        rows = self._request("GET", f"/customers/{customer_id}/accounts") or []
        return [
            {
                "id": r.get("_id") or r.get("id", ""),
                "customer_id": customer_id,
                "nickname": r.get("nickname", ""),
                "balance_cents": _amount(r.get("balance")),
            }
            for r in rows
        ]

    def delete_account(self, account_id: str) -> None:
        self._request("DELETE", f"/accounts/{account_id}")

    def list_transfers(self, account_id: str) -> list[Transfer]:
        rows = self._request("GET", f"/accounts/{account_id}/transfers") or []
        transfers: list[Transfer] = []
        for row in rows:
            description, payee_id = _untag_payee(row.get("description", ""))
            transfers.append(
                {
                    # List rows key the id as `id`; single fetches use `_id`
                    "id": row.get("id") or row.get("_id", ""),
                    "payer_id": account_id,
                    "payee_id": payee_id,
                    "amount_cents": _amount(row.get("amount")),
                    "status": row.get("status", ""),
                    "description": description,
                }
            )
        return transfers
