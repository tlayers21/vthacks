## Project

vthacks: a company spend-control app. Departments get budgets and policies; employees submit
receipt-backed expenses, managers approve them, finance manages budgets/policies/splits, and an
AI assistant answers questions scoped to the user's role. Nessie (Capital One's mock bank API)
moves money; our own database stores everything else. Full spec: `docs/spec.md`.

Current stage: early scaffold. Backend is Flask on SQLite, `src/` is the import root
(`src/db/schema.sql`, `src/db/seed.sql`, `src/db/init_db.py`). The full target architecture (FastAPI-style
layered backend, React/Vite frontend, DSPy/LangGraph LLM layer) is described in `docs/spec.md`
but not yet built — check that file before assuming a module exists.

## Build

- Install deps: `uv sync`
- Init the database (offline, from `src/`): `uv run python db/init_db.py`
- Seed through the Nessie API instead: `uv run python db/seed.py --reset --mode mock|real`
- Run: `uv run python app.py`
- Format: `uv run ruff format`; lint: `uv run ruff check`

## Libraries & docs
- Before writing code against any library, framework, or API (Flask, SQLModel, Alembic, httpx,
  pytest, etc.), fetch current docs via the Context7 MCP server instead of relying on training
  data — APIs change and memory may be stale.
- For Nessie (the mock bank API): use `docs/nessie-reference.md` as the source of truth, not
  Context7 — it isn't indexed there. Nessie mode is controlled by `NESSIE_MODE=real|mock`; only
  `src/nessie/` may call it, via the protocol in `src/nessie/protocol.py` (see `docs/spec.md` §6).

## Skills
- Writing or editing code: read .agents/skills/commenting/SKILL.md