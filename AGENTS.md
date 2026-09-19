## Project

**Nessence** (repo `vthacks`): a company spend-control app, named after Nessie — Capital One's
mock bank API, which records every money movement. Our own database owns balances and everything
else; the sandbox never updates a balance (see `docs/spec.md` §6). Full spec: `docs/spec.md`.

**Each role has exactly one job, and nobody does two of them.** This is the spine of the app,
enforced in `src/services/permissions.py` and guarded again per page in `src/api/routes/ui.py`:

- **Employee** — submits expenses, and only that. Nothing is ever refused by the machine: a
  hard per-category cap routes to the manager wearing its violation rather than rejecting
  (`DECISION_TO_STATUS` in `src/policy/engine.py`). The submit form and "My expenses" never
  state the engine's verdict — an employee told their expense auto-approves is an employee told
  exactly which amount to type. `POST /api/expenses` still returns `decision` and `violations`;
  hiding happens at the view layer, deliberately, so the API stays honest for tests and callers.
- **Manager** — approves or rejects their department's expenses, and asks finance for funding.
  Cannot submit. A rejection requires a reason. An approval that would take the department past
  its budget is refused with **409** and a shortfall; the manager's only way forward is funding.
- **Finance** — decides funding requests and watches `/transactions`. Cannot submit, cannot
  decide an expense.

Current stage: Flask on SQLite, `src/` is the import root (`src/db/schema.sql`,
`src/db/seed.sql`, `src/db/init_db.py`). The full target architecture (FastAPI-style layered
backend, React/Vite frontend, DSPy/LangGraph LLM layer) is described in `docs/spec.md` but not
yet built — check that file before assuming a module exists.

Built so far: the **policy engine** (`src/policy/`, spec §7.1), the expense path around it, and
the **funding flow** (spec §7.4) — `src/db/`, `src/services/`, JSON routes under `/api` in
`src/api/routes/`, and server-rendered Jinja pages. Funding requests carry no `category`, unlike
the spec's sketch: a manager asks for department money, not per-category money. Splits are still
out of scope. Rules are code, not rows: `src/policy/rules.py` holds them, so changing a limit is
a deploy. The engine is a pure function — keep SQL, Flask, and Nessie out of `src/policy/`.

Money moves in exactly two shapes, and `src/db/ledger.py` is the only place they are read
together: corporate → department (an approved funding request) and department → employee (a paid
expense). Both use the same idempotency shape — write the Nessie transfer id and commit it
*before* flipping status, never hold a SQLite write lock across a network call.

Money is always INTEGER cents with a `_cents` suffix, never DECIMAL/REAL.

The seeded org is deliberately small — 1 finance, 3 managers, 1 employee each — because it is
demoed live. `src/db/seed.sql` ids are `sha1(name)[:24]` for a customer and
`sha1('account:' + owner name)[:24]` for an account; regenerate rather than hand-editing them.
Department ids 1 and 2 are load-bearing: `src/policy/rules.py` keys its overrides on them.

## Brand

Colours are CSS custom properties in the `@theme` block of `src/templates/base.html` and are
re-stepped once for dark mode, so components never carry a `dark:` variant — change a token, not
a component. Navy `#08254C`, blue `#0C77D5`, teal `#35C9A3`, taken from the logo. Teal is
`--color-accent` and means one thing only: money arriving from the corporation. The status
green/amber/red are a separate scale and are never reused as brand or series colours.
`--color-on-brand` exists because white clears 4.5:1 on the light-mode blue but not on the
dark-mode one.

Images live in `src/static/brand/` — see its README for sizes and the regeneration script.
Every one is optional; `inject_brand` in `src/api/routes/ui.py` reports what is on disk and the
templates fall back to an inline SVG mark, so nothing 404s with an empty folder. `nessence.png`
at the repo root is the master artwork the derivatives are cut from.

## Build

- Install deps: `uv sync`
- Init the database (offline, from `src/`): `uv run python db/init_db.py`
- Seed through the Nessie API instead: `uv run python db/seed.py --reset --mode mock|real`
  (`--reset` also reclaims the shared sandbox: deletes accounts a previous run left and
  reuses its customers, since customers cannot be deleted)
- Run: `uv run python app.py`
- Format: `uv run ruff format`; lint: `uv run ruff check`

## Libraries & docs
- Before writing code against any library, framework, or API (Flask, SQLModel, Alembic, httpx,
  pytest, etc.), fetch current docs via the Context7 MCP server instead of relying on training
  data — APIs change and memory may be stale.
- For Nessie (the mock bank API): use `docs/nessie-reference.md` as the source of truth, not
  Context7 — it isn't indexed there. Read that file's "Live behaviour that contradicts this
  document" section first; the live sandbox differs from the documented API in ways that
  will silently corrupt money values (amounts truncate to integers, transfers have no payee). Nessie mode is controlled by `NESSIE_MODE=real|mock`; only
  `src/nessie/` may call it, via the protocol in `src/nessie/protocol.py` (see `docs/spec.md` §6).

## Skills
- Writing or editing code: read .agents/skills/commenting/SKILL.md