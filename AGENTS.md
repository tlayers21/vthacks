## Project

vthacks: a company spend-control app. Departments get budgets and policies; employees submit
receipt-backed expenses, managers approve them, finance manages budgets/policies/splits, and an
AI assistant answers questions scoped to the user's role. Nessie (Capital One's mock bank API)
moves money; our own database stores everything else. Full spec: `docs/spec.md`.

Current stage: early scaffold. Backend is Flask + SQLModel/pydantic-settings on SQLite
(`db/schema.sql`, `db/seed.sql`, `db/init_db.py`). The full target architecture (FastAPI-style
layered backend, React/Vite frontend, DSPy/LangGraph LLM layer) is described in `docs/spec.md`
but not yet built — check that file before assuming a module exists.

## Build

- Install deps: `uv sync`
- Init the database: `uv run python db/init_db.py`
- Run: `uv run python app.py`
- Format: `uv run ruff format`; lint: `uv run ruff check`

## Skills
- Writing or editing code: read .agents/skills/commenting/SKILL.md