import sqlite3
from pathlib import Path

DB_PATH = Path("app.db")
SQL_DIR = Path(__file__).parent

def init_db(path=DB_PATH):
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
