# Nessie Banking API

Verified API reference for the Nessie banking simulation API.

- **Documentation:** https://prod.nessieisreal.com/docs
- **API base URL:** `https://prod-api.nessieisreal.com`
- **Authentication:** API key passed as the `key` query parameter

> The live documentation site currently renders as a JavaScript application, so its OpenAPI document could not be directly extracted here. `/openapi.json` returns 403 even with a valid key. The endpoint reference below was cross-checked against the official Nessie SDK repositories and a current typed Nessie SDK that tracks the API's OpenAPI contracts. Exact live schemas should still be checked in the interactive docs when available.

## ⚠ Live behaviour that contradicts this document

Probed directly against the sandbox on 2026-09-19. **Where this section and the rest of this
file disagree, this section is right** — the tables below describe the documented Nessie API,
not the instance we actually talk to. See `docs/spec.md` §6.

1. **Balances never change.** Creating a transfer, deposit, or withdrawal persists a record
   and leaves both accounts' `balance` untouched. It is a record store, not a bank.
2. **`TransferCreate` is `{transaction_date, status, amount, description}` — all required.**
   It **rejects** `medium` and `payee_id` with `extra fields not permitted`. There is no
   destination field of any kind, so a transfer cannot express "A pays B" on its own.
   `DepositCreate` does require `medium`; `PurchaseCreate` requires `{merchant_id, medium,
   amount}`. The three are not interchangeable.
3. **`amount` truncates to a whole number.** `1.23` and `1.99` both store as `1`; `0.5`
   stores as `0`. Treat the unit as integer cents and never send a decimal.
4. **Ids are UUIDs**, not 24-character hex ObjectIds.
5. **List endpoints key the id as `id`; single-resource fetches use `_id`.** Reading `_id`
   off a list row raises `KeyError`.
6. **`DELETE /customers/{id}` does not exist** — 403 `Missing Authentication Token`, and the
   customer survives. `DELETE /accounts/{id}` and `DELETE /transfers/{id}` do work (200).
7. **`POST /customers` accepts an empty body.** Every field, address included, is optional.
8. **`GET /merchants` is empty**, so there is no valid `merchant_id` for purchases.

The key's dataset is **shared and global** — every run's records persist and are visible to
anyone using the same key.

---

## Authentication

Every API request uses the `key` query parameter:

```http
GET https://prod-api.nessieisreal.com/customers?key=YOUR_API_KEY
```

The API server and authentication convention are also documented by the current SDK reference. The official Nessie Python SDK likewise instructs users to provide `NESSIE_API_KEY`. 

---

# Endpoints

## Customers

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/customers` | List customers |
| `GET` | `/customers/{customerId}` | Get a customer |
| `GET` | `/accounts/{accountId}/customer` | Get the customer that owns an account |
| `POST` | `/customers` | Create a customer |
| `PUT` | `/customers/{customerId}` | Update a customer |

### Create customer

Typical documented fields:

```json
{
  "first_name": "Jane",
  "last_name": "Doe",
  "address": {
    "street_number": "1",
    "street_name": "Main St",
    "city": "Arlington",
    "state": "VA",
    "zip": "22201"
  }
}
```

---

## Accounts

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/accounts` | List accounts |
| `GET` | `/accounts/{accountId}` | Get an account |
| `GET` | `/customers/{customerId}/accounts` | List accounts belonging to a customer |
| `GET` | `/accounts/{accountId}/customer` | Get the customer that owns an account |
| `POST` | `/customers/{customerId}/accounts` | Create an account for a customer |
| `PUT` | `/accounts/{accountId}` | Update an account |
| `DELETE` | `/accounts/{accountId}` | Delete an account |

### Account filtering

The documented SDK supports filtering the account collection by `type`:

```http
GET /accounts?type=Checking&key=YOUR_API_KEY
```

The official Nessie JavaScript SDK documents these account types:

- `Credit Card`
- `Savings`
- `Checking`

### Typical account fields

```json
{
  "type": "Checking",
  "nickname": "My Checking",
  "rewards": 0,
  "balance": 1000,
  "customer_id": "CUSTOMER_ID"
}
```

---

## Bills

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/accounts/{accountId}/bills` | List bills for an account |
| `GET` | `/customers/{customerId}/bills` | List bills for a customer |
| `GET` | `/bills/{billId}` | Get a bill |
| `POST` | `/accounts/{accountId}/bills` | Create a bill for an account |
| `PUT` | `/bills/{billId}` | Update a bill |
| `DELETE` | `/bills/{billId}` | Delete a bill |

### Typical bill fields

The official Nessie JavaScript SDK documents fields including:

```json
{
  "status": "",
  "payee": "",
  "nickname": "",
  "payment_date": "",
  "recurring_date": 0,
  "payment_amount": 0
}
```

---

## Deposits

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/deposits` | List deposits |
| `GET` | `/accounts/{accountId}/deposits` | List deposits for an account |
| `GET` | `/deposits/{depositId}` | Get a deposit |
| `POST` | `/accounts/{accountId}/deposits` | Create a deposit for an account |
| `PUT` | `/deposits/{depositId}` | Update a deposit |
| `DELETE` | `/deposits/{depositId}` | Delete a deposit |

> `GET /deposits` is present in the current typed API reference. The older official JavaScript SDK documented the account-scoped, single-resource, create, update, and delete operations but did not expose a top-level list method.

### Typical deposit fields

```json
{
  "medium": "balance",
  "transaction_date": "string",
  "status": "pending",
  "amount": 0,
  "description": "string"
}
```

---

## Loans

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/accounts/{accountId}/loans` | List loans for an account |
| `GET` | `/loans/{loanId}` | Get a loan |
| `POST` | `/accounts/{accountId}/loans` | Create a loan for an account |
| `PUT` | `/loans/{loanId}` | Update a loan |
| `DELETE` | `/loans/{loanId}` | Delete a loan |

---

## Merchants

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/merchants` | List merchants |
| `GET` | `/merchants/{merchantId}` | Get a merchant |
| `POST` | `/merchants` | Create a merchant |
| `PUT` | `/merchants/{merchantId}` | Update a merchant |

---

## ATMs

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/atms` | List ATMs |
| `GET` | `/atms/{atmId}` | Get an ATM |

ATM resources are read-only in the documented SDK/API surface.

---

## Branches

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/branches` | List branches |
| `GET` | `/branches/{branchId}` | Get a branch |

Branch resources are read-only in the documented SDK/API surface.

---

## Withdrawals

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/withdrawals/{withdrawalId}` | Get a withdrawal |
| `GET` | `/accounts/{accountId}/withdrawals` | List withdrawals for an account |
| `POST` | `/accounts/{accountId}/withdrawals` | Create a withdrawal |
| `PUT` | `/withdrawals/{withdrawalId}` | Update a withdrawal |
| `DELETE` | `/withdrawals/{withdrawalId}` | Delete a withdrawal |

---

## Transfers

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/transfers/{transferId}` | Get a transfer |
| `GET` | `/accounts/{accountId}/transfers` | List transfers for an account |
| `POST` | `/accounts/{accountId}/transfers` | Create a transfer |
| `PUT` | `/transfers/{transferId}` | Update a transfer |
| `DELETE` | `/transfers/{transferId}` | Delete a transfer |

---

## Purchases

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/purchases/{purchaseId}` | Get a purchase |
| `GET` | `/accounts/{accountId}/purchases` | List purchases for an account |
| `GET` | `/merchants/{merchantId}/purchases` | List purchases for a merchant |
| `GET` | `/merchants/{merchantId}/accounts/{accountId}/purchases` | List purchases for a merchant and account |
| `POST` | `/accounts/{accountId}/purchases` | Create a purchase |
| `PUT` | `/purchases/{purchaseId}` | Update a purchase |
| `DELETE` | `/purchases/{purchaseId}` | Delete a purchase |

---

# Resource Relationships

```text
Customer
└── Accounts
    ├── Bills
    ├── Deposits
    ├── Loans
    ├── Purchases ── Merchant
    ├── Transfers
    └── Withdrawals
```

There are also independent read-only location resources:

```text
ATMs
Branches
```

---

# Common ID Parameters

The API uses resource IDs in path parameters:

```text
customerId
accountId
billId
depositId
loanId
merchantId
atmId
branchId
withdrawalId
transferId
purchaseId
```

---

# API Request Pattern

All authenticated requests use the API base URL plus an endpoint and the `key` query parameter:

```text
https://prod-api.nessieisreal.com/{endpoint}?key=YOUR_API_KEY
```

For JSON write requests, send the request body with:

```http
Content-Type: application/json
```

---

# Notes on Responses

The API returns JSON resource objects or arrays for read operations.

Create/update/delete responses are not uniform across every Nessie endpoint. Current SDK implementations account for both structured acknowledgement objects and plain-string/empty responses, so client code should not assume every mutation returns the full resource object.

---

# Sources

### Live documentation

https://prod.nessieisreal.com/docs

### Official Nessie GitHub organization

https://github.com/nessieisreal

### Official JavaScript SDK

https://github.com/nessieisreal/nessie-javascript-sdk

The official JavaScript SDK directly implements the customer, account, bill, deposit, loan, merchant, ATM, branch, purchase, transfer, and withdrawal resource paths. 

### Official Python SDK

https://github.com/nessieisreal/nessie-python-sdk

The official Python SDK documents the Customer → Account → Bill/Deposit/Loan/Purchase/Transfer/Withdrawal relationship structure and the same API key setup convention.

### Current typed API reference used for cross-checking

https://www.npmjs.com/package/nessie-node-sdk

This independent SDK states that its checked-in schemas track Nessie's OpenAPI contracts and currently lists the resource operations used in this document.

---

# Verification Status

The endpoint structure in this file was cross-checked against:

- the live Nessie documentation URL (the page itself is currently JS-only to this retrieval environment),
- the official `nessieisreal` JavaScript and Python SDK repositories, and
- a current typed Nessie SDK that references a checked-in OpenAPI specification.

The older version of this document contained several non-documentation sections (security advice, project structure, tutorial code, generic HTTP error guidance, duplicate endpoint summaries, and an unverified enterprise section). Those have been removed.