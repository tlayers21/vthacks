"""Real Nessie client.

Endpoints, the `key` query parameter, and the customer/account payload shapes follow
docs/nessie-reference.md. Built on stdlib urllib so the project needs no HTTP dependency
and `seed.py` runs on a fresh checkout without anyone re-syncing their venv.

Two conversions happen here and nowhere else:
  - money: our code speaks integer cents, Nessie speaks decimal dollars
  - responses: Nessie mutations sometimes return the resource, sometimes an
    acknowledgement wrapper {code, message, objectCreated: {...}} (see the reference's
    "Notes on Responses"), so every create unwraps both shapes
"""

import json
import urllib.error
import urllib.parse
import urllib.request

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


def _cents(dollars: float | int | None) -> int:
    return round((dollars or 0) * 100)


def _dollars(cents: int) -> float:
    return round(cents / 100, 2)


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
            raise NessieError(exc.code, exc.read().decode(errors="replace"), url) from exc
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
                    "balance": _dollars(balance_cents),
                },
            )
        )
        return {
            "id": created["_id"],
            "customer_id": customer_id,
            "nickname": created.get("nickname", nickname),
            "balance_cents": _cents(created.get("balance")),
        }

    def get_balance(self, account_id: str) -> int:
        account = self._request("GET", f"/accounts/{account_id}")
        return _cents(account.get("balance"))

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
                    "medium": "balance",
                    "payee_id": payee_id,
                    "amount": _dollars(amount_cents),
                    "status": "pending",
                    "description": description,
                },
            )
        )
        return {
            "id": created["_id"],
            "payer_id": payer_id,
            "payee_id": payee_id,
            "amount_cents": _cents(created.get("amount")) or amount_cents,
            "status": created.get("status", "pending"),
            "description": created.get("description", description),
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
                    "amount": _dollars(amount_cents),
                    "status": "pending",
                    "description": description,
                },
            )
        )

    def list_transfers(self, account_id: str) -> list[Transfer]:
        rows = self._request("GET", f"/accounts/{account_id}/transfers") or []
        return [
            {
                "id": r["_id"],
                "payer_id": r.get("payer_id", ""),
                "payee_id": r.get("payee_id", ""),
                "amount_cents": _cents(r.get("amount")),
                "status": r.get("status", ""),
                "description": r.get("description", ""),
            }
            for r in rows
        ]
