"""Initialize the stock bot SQLite database."""

from __future__ import annotations

from db import init_db


if __name__ == "__main__":
    db_path = init_db()
    print(f"DB initialized: {db_path}")
