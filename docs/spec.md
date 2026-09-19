# vthacks: technical spec

A company spend-control app. Departments get budgets and per-category policies. Employees submit receipt-backed expenses, managers approve them, and finance manages budgets, policies, and split payments. An AI assistant answers questions scoped to the user's role.

**Nessie (Capital One's mock bank API) moves the money. Our own database stores everything else.**

Not included: inter-company invoices, real authentication (a role switcher is used), native mobile.

## 1. Roles

| Role | Sees | Can do | 
|---|---|---|
| Employee | Own expenses, own department's budget totals | Submit expenses, upload receipts |
| Manager | All expenses in their department | Approve or reject, request budget |
| Finance | Everything | Set policies, decide budget requests, run splits |

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
│   │   ├── models/               user, department, policy, expense, budget_request,
│   │   │                         split_rule, transfer, merchant_category,
│   │   │                         notification, audit_log
│   │   ├── schemas/              request and response models per resource
│   │   ├── api/
│   │   │   ├── deps.py           current user, role checks
│   │   │   └── routes/           auth, expenses, receipts, budgets, policies, splits,
│   │   │                         assistant, transfers, audit, notifications, admin
│   │   ├── services/             policy_engine, expense_flags, reimbursement,
│   │   │                         budget_requests, splits, categorization,
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
│   │   │                         policies/, splits/, transfers/, assistant/, common/
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
- **policies:** id, department_id, role (optional), category, per_expense_limit, monthly_limit, approval_threshold
- **expenses:** id, user_id, department_id, amount, merchant, description, expense_date, category, category_source (user|llm), llm_category, llm_confidence, flags (json), status, policy_reason, receipt_path, receipt_hash, receipt_data (json), approver_id, decision_comment, decided_at, nessie_transfer_id
- **budget_requests:** id, department_id, requested_by, category, amount, justification, status, decided_by, decision_comment, nessie_transfer_id
- **split_rules:** id, name, shares (json: department_id and pct, sums to 100)
- **transfers:** id, kind (allocation|reimbursement|split), from_account, to_account, amount, nessie_id, ref_type, ref_id, status
- **merchant_categories:** merchant, category, source (rule|user|llm)
- **notifications:** id, user_id, message, link, read
- **audit_log:** id, actor_id, action, entity, entity_id, details (json), ts

Expense statuses: `needs_approval`, `approved`, `rejected`, `paid`, `payout_failed`.
Categories (fixed enum): travel, food, client meals, software, equipment, marketing, training, office supplies, shipping, other.

## 6. Nessie integration

- Accounts: one corporate, one per department, one per employee. IDs are stored on our rows.
- `protocol.py` defines the interface: `create_customer`, `create_account`, `get_balance`, `create_transfer`, `create_purchase` (seeding only), `list_transfers`. `client.py` is the real implementation, `mock.py` is in-memory. `NESSIE_MODE=real|mock` switches them.
- Every Nessie transfer also writes a `transfers` row. The UI reads our database, not Nessie.
- Payouts are idempotent: one transfer per expense, Nessie's ID saved before the status becomes `paid`. A failure sets `payout_failed` and allows a retry.

## 7. Backend logic

### 7.1 Policy engine (`services/policy_engine.py`)

```python
def check_expense(e, policy, month_spent):
    if e.amount > policy.per_expense_limit:
        return "rejected", "Over per-expense limit"
    if month_spent + e.amount > policy.monthly_limit:
        return "rejected", "Exceeds monthly limit"
    if e.amount > policy.approval_threshold:
        return "needs_approval", "Manager approval required"
    return "approved", "Within policy"
```

Policy lookup: department + role + category, falling back to department + category. Monthly spend counts `approved` and `paid` expenses.

### 7.2 Flags (`services/expense_flags.py`)

Shown to the approver; they don't block submission except where noted.
- Receipt total differs from the entered amount
- Receipt older than 30 days
- Consistency check failed (category or note contradicts receipt items)
- Employee's category differs from the LLM suggestion
- Duplicate (same receipt hash, or same merchant, amount, and date)
- Missing receipt on an expense over $25 (blocks submission)

### 7.3 Reimbursement flow (`services/reimbursement.py`)

1. Employee drops in a receipt. `POST /receipts/parse` extracts merchant, total, date, and items and pre-fills the form.
2. `POST /expenses/suggest-category` pre-fills the category. The employee confirms or changes it. Choosing "other" requires a note.
3. `POST /expenses` computes flags, runs the policy engine, and writes the audit log.
4. Result: auto-approved (paid immediately), sent to the manager, or rejected with a reason.
5. Manager approves or rejects with an optional comment. Approval triggers a department-to-employee Nessie transfer, then status `paid`.
6. The submitter and approver are notified at each step.

### 7.4 Budget requests (`services/budget_requests.py`)

A manager submits category, amount, and justification. Finance sees it next to the department's current spend. Approving triggers a corporate-to-department transfer and raises `monthly_budget`. Denying requires a reason.

### 7.5 Splits (`services/splits.py`)

`POST /splits/execute` takes a total, a vendor account, and a split rule. It checks shares sum to 100, then sends one transfer per department to the vendor and logs each. Any rounding remainder goes to the largest share.

## 8. LLM layer

### 8.1 Structured tasks (DSPy, `llm/modules/`)

```python
class TagExpense(dspy.Signature):
    """Categorize a company expense."""
    merchant: str = dspy.InputField()
    description: str = dspy.InputField()
    amount: float = dspy.InputField()
    department: str = dspy.InputField()
    category: Cat = dspy.OutputField()   # Literal of the category enum
    confidence: float = dspy.OutputField(desc="0 to 1")
```

- **Tagger:** merchant cache, then keyword rules, then the DSPy module. Confidence under 0.7 shows the user the top choices. Invalid output falls back to `other` and is flagged.
- **Receipt reader:** image in; merchant, total, date, and line items out. Results cached by file hash.
- **Consistency check:** employee category, note, and receipt items in; `consistent` and `reason` out.
- **Learning:** user-corrected tags update `merchant_categories` and become training examples. `optimize.py` compiles the tagger with `BootstrapFewShot` and reports accuracy before and after on a held-out set.

### 8.2 Assistant (LangGraph, `llm/assistant/`)

Graph:
1. **route:** classify the question as numbers, text, or action.
2. **SQL path:** generate SQL, validate, run scoped and read-only. Retry once on error.
3. **Text path:** retrieve justifications and policies, filtered by department.
4. **Action path:** propose the action and pause for explicit user confirmation before any money moves.
5. **answer:** respond only from returned rows or retrieved text. Stream tokens and attach the SQL, row count, and sources.

**SQL guard (`sql_guard.py`):** parse with sqlglot. Allow one SELECT only, no LLM-written `WITH`, only whitelisted view names, forced `LIMIT 200`, read-only database role, statement timeout.

**Scoping (`scope.py`):** the LLM only sees `scoped_expenses` and `scoped_budget_requests`. Before running, the query is wrapped in CTEs that define those names by role: employee gets own rows, manager gets their department, finance gets all. Base tables are not whitelisted.

Empty results produce "no matching data," never invented numbers.

## 9. API

Every route checks role and department server-side.

```
POST /auth/switch                 GET  /me
GET  /budgets/summary
POST /receipts/parse
POST /expenses/suggest-category
POST /expenses                    GET  /expenses?scope=mine|dept|all
POST /expenses/{id}/decision      POST /expenses/{id}/retry-payout
POST /budget-requests             GET  /budget-requests
POST /budget-requests/{id}/decision
GET  /policies                    PUT  /policies/{id}
GET  /split-rules                 POST /split-rules
POST /splits/execute
POST /assistant/ask (SSE)         POST /assistant/confirm
GET  /transfers                   GET  /audit
GET  /notifications               POST /notifications/read
POST /admin/seed                  POST /admin/reset
```

The OpenAPI schema is the contract. The frontend client is generated from it.

## 10. Frontend

**Shell:** sidebar per role, top bar with a "Viewing as" user switcher and notification bell, Cmd+K opens the assistant.

**Employee**
- Dashboard: budget bars by category
- New expense: receipt dropzone, pre-filled form, live flags, policy preview
- My expenses: list with status and manager comments

**Manager**
- Approval queue: receipt preview, note, flags, approve and reject with comment
- Team spend: budget vs. spent by category, department expense table
- New budget request: category, amount, justification

**Finance**
- Overview: totals, department comparison, over-budget highlight
- Department detail
- Budget requests: justification, Deny and Approve-and-transfer
- Policies: editable table
- Splits: rule builder and preview
- Transfers and audit log

**Assistant panel:** streaming answers, SQL and sources disclosed under each answer, confirmation card for actions, suggested question chips.

**State:** TanStack Query for server data, auth context for the session, fetch streaming for assistant SSE.

**Required states:** loading skeletons, empty states, error toasts, dark mode. An animated money-flow shows when a transfer fires.

## 11. Seed data and demo

Seed 4 departments, about 12 users, realistic merchants (Delta, Figma, Olive Garden, AWS, Staples), and policies per category. Plant:
- a $180 team dinner that needs approval
- a receipt whose total doesn't match the form
- an old receipt
- Marketing at 112% of budget with a pending request
- a duplicate submission

Keep 3 or 4 sample receipts in `data/sample_receipts/` and cache their parsed results in case the API or wifi fails.

**Demo flow:**
1. Employee drops a receipt, the form fills, flags appear, submit.
2. Switch to manager, review, approve, and the transfer fires.
3. Switch to finance, see the dashboard update and the transfer log.
4. Ask the assistant the same question as finance and as an employee to show scoping.
5. Approve Marketing's budget request.
6. Run a split.

Record a Playwright backup video.

## 12. Testing

- **Unit:** policy engine, flags, split math, permissions, SQL guard (DELETE, multiple statements, forbidden tables, `WITH` overrides)
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

**Skills** (`.claude/skills/<skill-name>/SKILL.md`): nessie-api (with a `reference.md` of the official Nessie docs), policy-engine, dspy-modules, langgraph-assistant, sql-guardrails, design-system, seed-data. Skills hold project-specific patterns only and tell Claude to fetch current library docs via Context7 first.

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
2. Policy engine, expense API, permissions
3. Reimbursement flow end to end, then switch to real Nessie
4. Employee and manager screens
5. DSPy tagging and receipt reading with flags
6. Finance screens, budget requests, policy editor
7. Assistant: SQL path, then text path, then confirmed actions
8. Splits, audit log, notifications
9. Evals, polish, demo recording