import sqlite3
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402

# Anchored to the repo root, not the working directory -- otherwise running this from
# another folder silently creates a second app.db that nothing else reads.
DB_PATH = settings.db_path
SQL_DIR = Path(__file__).parent


def init_db(path=DB_PATH):
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    try:
        for name in ("schema.sql", "seed.sql"):
            f = SQL_DIR / name
            if f.exists():
                conn.executescript(f.read_text())
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Created {DB_PATH}")
