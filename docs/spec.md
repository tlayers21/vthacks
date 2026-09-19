# vthacks: technical spec

A company transaction-management app. Departments get budgets. Employees submit receipt-backed expenses, managers approve or reject them, and finance manages department budgets and requests. An AI assistant answers questions scoped to the user's role.

**Nessie (Capital One's mock bank API) records the money movement; our own database owns
balances and everything else.** The original intent was for Nessie to hold balances, but the
sandbox never updates them — see section 6, which documents the verified behaviour.

Not included: inter-company invoices, real authentication (a role switcher is used), native mobile, split payments.

## 1. Roles

| Role | Sees | Can do | 
|---|---|---|
| Employee | Own expenses, own department's budget totals | Submit expenses, upload receipts |
| Manager | All expenses in their department | Approve or reject, request budget |
| Finance | Everything | Decide budget requests |

Permissions are enforced in the backend only. User ID, role, and department come from the session, never from the request body or chat text.

## 2. Stack

- **Backend:** Python 3.12, Flask
- **LLM:** DSPy (tagging, receipt reading, consistency check); LangChain + LangGraph (assistant); LangSmith (tracing); pgvector or Chroma (text retrieval)
- **SQL safety:** sqlglot
- **Frontend:** React, Vite, TypeScript, Tailwind, shadcn/ui, TanStack Query and Table, Recharts, react-hook-form + zod, Framer Motion, sonner, cmdk. TypeScript client generated from the OpenAPI schema (openapi-typescript).
- **Tooling:** ruff, pyright, pytest, vitest, Playwright, GitHub Actions

Library APIs change quickly, so Claude Code pulls current docs through Context7 instead of relying on memory (section 13). The Nessie sandbox may change too.

## 3. Architecture

```
React → Flask routes → services → models (Postgres)
                             ├→ integrations/nessie (real | mock) → Nessie
                             └→ llm/ → LLM API
```

Rules:
- Permissions live in code, not in prompts.
- Only `integrations/nessie/` calls Nessie.
- Only `db/` and `llm/assistant/sql_guard.py` execute SQL.
- Every LLM output is validated against a schema or whitelist. LLMs suggest and flag; code decides.
- Receipt text and user notes are untrusted input.

## 4. Directory structure

```
vthacks/
├── README.md
├── CLAUDE.md
├── .mcp.json
├── .env.example
├── .gitignore
├── Makefile
├── docker-compose.yml
├── .github/workflows/ci.yml
├── .claude/
│   ├── settings.json
│   ├── agents/
│   ├── skills/
│   ├── commands/
│   └── hooks/
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/                 config.py, session.py
│   │   ├── db/                   session.py, seed.py
│   │   ├── models/               user, department, expense, budget_request,
│   │   │                         transfer, notification, audit_log
│   │   ├── schemas/              request and response models per resource
│   │   ├── api/
│   │   │   ├── deps.py           current user, role checks
│   │   │   └── routes/           auth, expenses, receipts, budgets,
│   │   │                         assistant, transfers, audit, notifications, admin
│   │   ├── services/             expense_flags, reimbursement,
│   │   │                         budget_requests, categorization,
│   │   │                         permissions, notifications, audit
│   │   ├── integrations/
│   │   │   └── nessie/           client.py, mock.py, protocol.py
│   │   └── llm/
│   │       ├── modules/          tagger, receipt, consistency, optimize (DSPy)
│   │       └── assistant/        graph, tools, sql_guard, scope, prompts (LangGraph)
│   ├── scripts/                  seed.py
│   └── tests/                    unit/, integration/, evals/
├── frontend/
│   ├── package.json, vite.config.ts, tailwind.config.ts, tsconfig.json, index.html
│   ├── src/
│   │   ├── main.tsx, App.tsx, router.tsx
│   │   ├── api/                  generated client
│   │   ├── pages/                Login.tsx, employee/, manager/, finance/
│   │   ├── components/           ui/ (shadcn), layout/, expenses/, budgets/,
│   │   │                         transfers/, assistant/, common/
│   │   ├── hooks/
│   │   ├── context/              auth
│   │   ├── lib/                  format, sse, utils
│   │   └── types/
│   └── e2e/                      Playwright tests
└── data/
    └── sample_receipts/
```

## 5. Data model

- **users:** id, name, role, department_id, nessie_customer_id, nessie_account_id
- **departments:** id, name, monthly_budget, nessie_account_id
- **expenses:** id, user_id, department_id, amount, merchant, description, expense_date, category, category_source (user|llm), llm_category, llm_confidence, flags (json), status, policy_decision, receipt_path, receipt_hash, receipt_data (json), approver_id, decision_comment, decided_at, nessie_transfer_id
- **expense_violations:** id, expense_id, rule, severity, message
- **budget_requests:** id, department_id, requested_by, category, amount, justification, status, decided_by, decision_comment, nessie_transfer_id
- **transfers:** id, kind (allocation|reimbursement), from_account, to_account, amount, nessie_id, ref_type, ref_id, status
- **notifications:** id, user_id, message, link, read
- **audit_log:** id, actor_id, action, entity, entity_id, details (json), ts

Expense statuses: `needs_approval`, `approved`, `rejected`, `paid`, `payout_failed`. Categories
are a fixed enum: travel, food, client meals, software, equipment, marketing, training, office
supplies, shipping, other.

`status` and `policy_decision` are separate on purpose. `status` is the lifecycle a manager can
still move; `policy_decision` records what the engine said at submission and never changes.
Without both you cannot tell a policy block from a manager rejection.

## 6. Nessie integration

**Nessie does not move money. Our database is authoritative for balances; Nessie is the
audit trail.** This contradicts the one-liner at the top of this document, and it is the
single most important thing to know before writing code against it. The sandbox at
`https://prod-api.nessieisreal.com` was probed directly on 2026-09-19; the findings below
are verified behaviour, not documentation.

- Accounts: one corporate, one per department, one per employee. IDs are stored on our rows.
- `protocol.py` defines the interface: `create_customer`, `create_account`, `get_balance`, `create_transfer`, `create_purchase` (seeding only), `list_transfers`, plus `list_customers`, `list_accounts`, `delete_account` for seed housekeeping. `client.py` is the real implementation, `mock.py` is in-memory. `NESSIE_MODE=real|mock` switches them.
- Every Nessie transfer also writes a `transfers` row. The UI reads our database, not Nessie.
- Payouts are idempotent: one transfer per expense, Nessie's ID saved before the status becomes `paid`. A failure sets `payout_failed` and allows a retry.

### 6.1 Verified sandbox behaviour

| Finding | Consequence |
|---|---|
| Creating a transfer or deposit leaves **both balances unchanged** | Never read a balance back to decide anything. `get_balance` returns the balance set at account creation, nothing more |
| `TransferCreate` accepts only `{transaction_date, status, amount, description}` and **rejects `medium` and `payee_id`** | There is no destination field. `client.py` encodes the payee as a `[payee:<id>]` suffix on `description` and parses it back out in `list_transfers` |
| `amount` is **truncated to a whole number** (`1.99` stores as `1`) | Decimal dollars lose cents. We send integer cents and treat that as Nessie's unit everywhere. No dollar conversion exists in the client |
| List endpoints key the id as `id`; single fetches use `_id` | `client.py` accepts either |
| Ids are **UUIDs**, not 24-char ObjectIds | Harmless — every id column is `TEXT` |
| `POST /customers` accepts `{}`; all fields optional | The address we send is placeholder data |
| `GET /merchants` is empty | `create_purchase` has no valid `merchant_id` available. Nothing calls it yet |

### 6.2 The sandbox is shared and append-only

The API key's data is global and persists across runs. `DELETE /accounts/{id}` and
`DELETE /transfers/{id}` work, but **`DELETE /customers/{id}` does not exist** — it returns
403 `Missing Authentication Token` and the customer survives. Seeding therefore used to
strand 18 more customers on every run; we found 130, seven copies of each name.

`seed.py --reset` now calls `reclaim_sandbox()` first: it matches customers by
`(first_name, last_name)` against the seed org, deletes every account they own, and reuses
the first matching customer instead of creating another. Accounts carry all the state that
matters — balance, nickname, transfers — so recycling them is sufficient.

Measured: a re-seed went from 130 accounts to 21, and a second run held at 21 rather than
climbing to 148. Customer count cannot be reduced and stays flat.

## 7. Backend logic

### 7.1 Policy engine (`policy/`)

Decides what happens to an expense the moment it is submitted: pay it out, route it to a
manager, or refuse it. Pure — no SQL, no Flask, no Nessie — so the same call backs both
`POST /api/expenses` and the live preview the submit form runs while you type.

Rules are a typed constant in `policy/rules.py`, resolved most-specific-first:
`(department, category)` → `(org, category)` → a catch-all fallback, so lookup is total.

```python
def evaluate_expense(expense, budget, rules=None) -> PolicyResult
```

Every rule runs; none short-circuit. The submitter sees every reason at once.

| Rule | Fires when | Severity |
|---|---|---|
| `per_expense_cap` | amount over the category's per-expense limit | `block` |
| `department_budget` | committed + amount over the month's budget | `warn` |
| `approval_threshold` | amount over the category's auto-approve limit | `warn` |

The decision is the worst severity present: any `block` → `blocked`; else any `warn` →
`needs_approval`; else `auto_approved`. Violations are persisted to `expense_violations` and
shown to the approver.

**Assumptions.** None of these are derivable from the code, and several differ from how a
policy engine is usually built:

1. Rules live in a Python module, so finance cannot change a limit without a deploy.
   `RuleSource` in `policy/rules.py` is the seam where a database-backed source drops in.
2. Going over budget **escalates to `needs_approval`, never blocks**. Section 11 plants
   Marketing at 112% as an accepted overrun, so blocking would contradict the seed.
3. Committed spend counts every status except `rejected` — wider than "approved and paid",
   because a pending approval is exposure and `payout_failed` money is still owed.
4. All comparisons are strictly greater-than: an expense exactly at a limit passes.
5. Blocked expenses are still persisted, and `POST /api/expenses` returns 201 for them. The row
   exists and the caller needs the violations; a 4xx would imply nothing happened.
6. `auto_approved` pays out immediately rather than queueing.
7. Violations are a table, not a JSON column — the approval queue filters on `rule`, and the
   vocabularies stay CHECK-declared beside every other enum in `schema.sql`.
8. Receipts are not part of policy. The engine never looks at one; the receipt rules in 7.2
   stay separate and unbuilt.
9. Seeded expenses omit `submitted_at` so it defaults to `CURRENT_TIMESTAMP`. The budget check
   only counts the current month, so a hardcoded date would break the over-budget demo on the
   1st of every month.
10. The budget check reads committed spend and then writes, so two concurrent submissions can
    both squeak under. Acceptable for a single-user demo; `BEGIN IMMEDIATE` in
    `db/connect.py::transaction` is the fix if it stops being one.
11. `MockNessie` derives ids from a counter that restarts each process, so a mock started
    against an already-seeded database would re-mint a transfer id the database holds. Startup
    reserves the existing ids; the `UNIQUE` constraint on `nessie_transfer_id` is the backstop.
12. The front end is server-rendered Jinja, not the React/Vite stack in sections 2 and 10 — see
    section 10.

### 7.2 Flags (`services/expense_flags.py`) — not built

Informational only, shown to the approver; they don't block submission except where noted.
- Receipt total differs from the entered amount
- Receipt older than 30 days
- Consistency check failed (category or note contradicts receipt items)
- Employee's category differs from the LLM suggestion
- Duplicate (same receipt hash, or same merchant, amount, and date)
- Missing receipt on an expense over $25 (blocks submission)

### 7.3 Reimbursement flow (`services/expenses.py`)

1. Employee drops in a receipt. `POST /receipts/parse` extracts merchant, total, date, and items and pre-fills the form. *(Not built.)*
2. `POST /expenses/suggest-category` pre-fills the category. The employee confirms or changes it. Choosing "other" requires a note. *(Not built.)*
3. As the form is filled, `POST /api/policies/preview` shows the decision and any violations before submit.
4. `POST /api/expenses` runs the policy engine and persists the expense with its violations.
5. Result: auto-approved (paid immediately), sent to the manager, or blocked with its reasons. A blocked expense is still recorded.
6. Manager approves or rejects. Approval triggers a department-to-employee Nessie transfer, then status `paid`.
7. `POST /api/expenses/{id}/retry-payout` retries a `payout_failed` expense. It shares one code path with both approval routes, so the idempotency guard in section 6 covers all three.

### 7.4 Budget requests (`services/budget_requests.py`)

A manager submits category, amount, and justification. Finance sees it next to the department's current spend. Approving triggers a corporate-to-department transfer and raises `monthly_budget`. Denying requires a reason.

## 8. LLM layer

### 8.1 Structured tasks (DSPy, `llm/modules/`)

```python
class TagExpense(dspy.Signature):
    """Categorize a company expense."""

    merchant: str = dspy.InputField()
    description: str = dspy.InputField()
    amount: float = dspy.InputField()
    department: str = dspy.InputField()
    category: Cat = dspy.OutputField()  # Literal of the category enum
    confidence: float = dspy.OutputField(desc="0 to 1")
```

- **Tagger:** merchant cache, then keyword rules, then the DSPy module. Confidence under 0.7 shows the user the top choices. Invalid output falls back to `other` and is flagged.
- **Receipt reader:** image in; merchant, total, date, and line items out. Results cached by file hash.
- **Consistency check:** employee category, note, and receipt items in; `consistent` and `reason` out.
- **Learning:** user-corrected tags become training examples. `optimize.py` compiles the tagger with `BootstrapFewShot` and reports accuracy before and after on a held-out set.

### 8.2 Assistant (LangGraph, `llm/assistant/`)

Graph:
1. **route:** classify the question as numbers, text, or action.
2. **SQL path:** generate SQL, validate, run scoped and read-only. Retry once on error.
3. **Text path:** retrieve budget-request justifications, filtered by department.
4. **Action path:** propose the action and pause for explicit user confirmation before any money moves.
5. **answer:** respond only from returned rows or retrieved text. Stream tokens and attach the SQL, row count, and sources.

**SQL guard (`sql_guard.py`):** parse with sqlglot. Allow one SELECT only, no LLM-written `WITH`, only whitelisted view names, forced `LIMIT 200`, read-only database role, statement timeout.

**Scoping (`scope.py`):** the LLM only sees `scoped_expenses` and `scoped_budget_requests`. Before running, the query is wrapped in CTEs that define those names by role: employee gets own rows, manager gets their department, finance gets all. Base tables are not whitelisted.

Empty results produce "no matching data," never invented numbers.

## 9. API

Every route checks role and department server-side.

Built so far — JSON lives under `/api` so it cannot collide with a rendered page at the same
name (`GET /policies` is a page; `GET /api/policies` is the rule set):

```
POST /auth/switch                 GET  /auth/me           GET  /auth/users
POST /api/expenses                GET  /api/expenses?scope=mine|dept|all
GET  /api/expenses/{id}           POST /api/expenses/{id}/decision
POST /api/expenses/{id}/retry-payout
GET  /api/policies                POST /api/policies/preview
GET  /api/policies/budgets
```

Planned:

```
GET  /budgets/summary
POST /receipts/parse
POST /expenses/suggest-category
POST /budget-requests             GET  /budget-requests
POST /budget-requests/{id}/decision
POST /assistant/ask (SSE)         POST /assistant/confirm
GET  /transfers                   GET  /audit
GET  /notifications               POST /notifications/read
POST /admin/seed                  POST /admin/reset
```

The OpenAPI schema is the contract. The frontend client is generated from it.

## 10. Frontend

**Built today: server-rendered Jinja, not React.** There is no `package.json` or node toolchain
in this repo, so a SPA would mean a build pipeline, a dev proxy, and a generated client before a
single policy decision reached the screen. Templates in `src/templates/`, styling in
`src/static/style.css` on top of simple.css, dark mode from `prefers-color-scheme`. The React
stack in section 2 remains the target; nothing below depends on staying with Jinja.

**Shell:** top bar with a "Viewing as" switcher, nav per role.

**Employee**
- New expense: form with a **live policy preview** — the decision badge and its violations
  update as you type, before you submit
- My expenses: status and policy badges, violations, retry on a failed payout

**Manager**
- Approval queue: each expense with the violations that routed it there, approve and reject

**Finance**
- Overview: budget vs. committed spend per department, over-budget highlighted
- Policies: the resolved rule set per department, read-only because rules are code

Still to build: receipt dropzone, budget-request screens, transfers and audit log, the
assistant panel, and the money-flow animation.

**Assistant panel:** streaming answers, SQL and sources disclosed under each answer, confirmation card for actions, suggested question chips.

**State:** TanStack Query for server data, auth context for the session, fetch streaming for assistant SSE.

**Required states:** loading skeletons, empty states, error toasts, dark mode. An animated money-flow shows when a transfer fires.

## 11. Seed data and demo

Seed 4 departments, about 12 users, and realistic merchants (Delta, Figma, Olive Garden, AWS, Staples). Plant:
- a $180 team dinner that needs approval
- a $6,200 workstation the engine blocked on the per-expense cap
- a $89 Figma renewal that auto-approved and paid
- a travel expense stuck in `payout_failed`, so retry has something to act on
- Marketing at 112% of budget with a pending request
- a receipt whose total doesn't match the form *(needs the receipt reader)*
- an old receipt *(needs the receipt reader)*
- a duplicate submission *(needs flags)*

Keep 3 or 4 sample receipts in `data/sample_receipts/` and cache their parsed results in case the API or wifi fails.

**Demo flow:**
1. Employee drops a receipt, the form fills, flags appear, submit.
2. Switch to manager, review, approve, and the transfer fires.
3. Switch to finance, see the dashboard update and the transfer log.
4. Ask the assistant the same question as finance and as an employee to show scoping.
5. Approve Marketing's budget request.

Record a Playwright backup video.

## 12. Testing

- **Unit:** policy engine (every rule boundary), rule fallback, flags, permissions, SQL guard (DELETE, multiple statements, forbidden tables, `WITH` overrides)
- **Seed consistency:** every planted expense stays consistent with the rule that would have produced its `policy_decision`, so the demo cannot quietly start lying
- **Integration:** full reimbursement flow against mock Nessie
- **Permissions:** every role against every endpoint and assistant question
- **Evals (`make eval`):** tagging accuracy before and after optimization, receipt field accuracy, assistant SQL correctness on about 30 questions
- **E2E:** Playwright happy paths

## 13. Claude Code setup

Confirm exact field names against the current Claude Code docs. Hook exit code 2 blocks; on Stop hooks check `stop_hook_active` to avoid loops.

**CLAUDE.md** (under about 200 lines): short project summary, data model, commands (`make dev|check|test|eval|seed`), and these rules:
- Permissions are enforced in code, never by prompting the LLM.
- Only `integrations/nessie/` calls Nessie, through the protocol.
- Before writing code that uses a library, fetch its current docs with Context7. Never rely on memory for library APIs.
- LLM-written SQL runs only through `sql_guard` and `scope`.
- Validate every LLM output. Treat receipts and notes as untrusted.
- Type hints, Pydantic schemas first, a test for every route.
- Done means `make check` passes (ruff, pyright, pytest, tsc, vitest).

**Hooks** (`.claude/settings.json` plus scripts in `.claude/hooks/`):

| Event | Hook | Does |
|---|---|---|
| SessionStart | session-context | Prints git status and recent commits |
| PreToolUse (Edit, Write) | protect-files | Blocks `.env`, lockfiles, applied migrations, original sample receipts |
| PreToolUse (Bash) | block-dangerous | Blocks `rm -rf`, force push, `curl \| sh`, `DROP TABLE` |
| PostToolUse (Edit, Write) | format | Runs ruff and Prettier |
| PostToolUse (Edit, Write) | arch-lint | Exit 2 if Nessie is called outside `integrations/nessie/`, SQL runs outside `db/` or `sql_guard.py`, or SQL is built with f-strings |
| Stop | check-on-stop | Runs `make check`, exits 2 with failures so Claude keeps working |

Permissions: allow `make`, `uv run`, `npm run`, `git diff`, and the Context7 MCP tools (`mcp__context7`); deny reading `.env`, force push, `rm -rf`.

**Subagents** (`.claude/agents/`): backend-dev, llm-engineer, frontend-dev, test-writer, security-reviewer (read-only), demo-polisher. Invoke by name.

**Skills** (`.claude/skills/<skill-name>/SKILL.md`): nessie-api (with a `reference.md` of the official Nessie docs), dspy-modules, langgraph-assistant, sql-guardrails, design-system, seed-data. Skills hold project-specific patterns only and tell Claude to fetch current library docs via Context7 first.

**Commands** (`.claude/commands/`): `/new-endpoint`, `/add-dspy-module`, `/seed`, `/check`, `/eval`, `/demo-check`, `/review`.

**MCP** (`.mcp.json`, servers only): Context7, GitHub, Playwright, read-only Postgres.

**Library docs (Context7)**

Context7 is an MCP server from Upstash that fetches current, version-specific documentation and code examples for libraries and injects them into the model's context. It replaces stale training-data knowledge of APIs.

Setup (requires Node 18+):

```json
{
  "mcpServers": {
    "context7": { "command": "npx", "args": ["-y", "@upstash/context7-mcp@latest"] }
  }
}
```

Or run `claude mcp add context7 -- npx -y @upstash/context7-mcp@latest`. A free API key from context7.com/dashboard raises rate limits. Keep it in `.env`, not in the repo.

How it's used:
- **CLAUDE.md lists every library to look up:**
  - Backend: FastAPI, Pydantic, SQLModel, Alembic, sqlglot, httpx, DSPy, LangChain, LangGraph, LangSmith, pytest, uv
  - Frontend: React, Vite, TypeScript, Tailwind, shadcn/ui, TanStack Query, TanStack Table, Recharts, react-hook-form, zod, Framer Motion, sonner, cmdk, openapi-typescript, Playwright, vitest
  - LLM provider: Anthropic API and SDK
  - Tooling: Claude Code (hooks, settings, subagents), if indexed
- **Lookup flow:** resolve the library ID, fetch docs for the specific topic, and match the versions pinned in `pyproject.toml` and `package.json`. Once resolved, paste the IDs (format `/org/project`) into CLAUDE.md so later sessions skip the lookup.
- **Subagents:** backend-dev, llm-engineer, frontend-dev, and test-writer are allowed the Context7 tools. security-reviewer stays read-only.
- **Nessie:** check whether it's indexed. If not, save the official Nessie API docs to `.claude/skills/nessie-api/reference.md` and treat that file as the source of truth. Do the same for any other library Context7 doesn't have.
- **Fallback:** if a lookup fails, fetch the official docs page directly. Don't guess an API.

**Workflow:** plan mode first. Define Pydantic schemas, then the OpenAPI spec, then generate the TS client. Run backend, LLM, and frontend work as separate sessions in git worktrees. `/clear` between tasks.

## 14. Build order

1. Scaffolding, Claude Code setup, models, mock Nessie, seed script
2. Expense API, permissions
3. Reimbursement flow end to end, then switch to real Nessie
4. Employee and manager screens
5. DSPy tagging and receipt reading with flags
6. Finance screens, budget requests
7. Assistant: SQL path, then text path, then confirmed actions
8. Audit log, notifications
9. Evals, polish, demo recording