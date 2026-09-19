"""Application settings, read from the environment and .env.

Deliberately stdlib-only: `python db/init_db.py` and `python db/seed.py` are the first
things a teammate runs on a fresh checkout, and they should not fail on a missing
package or a half-built virtualenv. Pydantic still earns its place later, for request
and response schemas at the route boundary -- it just isn't needed to read five strings.
"""

import os
from pathlib import Path

SRC_DIR = Path(__file__).parent
# .env and the database live at the repo root, one level above src/
REPO_ROOT = SRC_DIR.parent
ENV_FILE = REPO_ROOT / ".env"


def _load_env_file(path: Path) -> None:
    """Populate os.environ from a .env file. Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


_load_env_file(ENV_FILE)


class Settings:
    # Where the SQLite file lives.
    db_path = Path(os.environ.get("DB_PATH", REPO_ROOT / "app.db"))

    # "mock" keeps everything in memory and offline; "real" talks to the Nessie sandbox.
    nessie_mode = os.environ.get("NESSIE_MODE", "mock")
    nessie_api_key = os.environ.get("NESSIE_API_KEY", "")
    nessie_base_url = os.environ.get(
        "NESSIE_BASE_URL", "https://prod-api.nessieisreal.com"
    )

    # Signs the session cookie used by the role switcher.
    secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")


settings = Settings()
