"""SQLite database helpers for stock bot results."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "stock_bot.db"
KST = ZoneInfo("Asia/Seoul")


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date TEXT NOT NULL,
        market TEXT NOT NULL,
        ticker TEXT NOT NULL,
        name TEXT NOT NULL,
        rank INTEGER NOT NULL,
        score REAL NOT NULL,
        reason TEXT,
        theme TEXT,
        sector TEXT,
        price_at_pick REAL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        ticker TEXT NOT NULL,
        name TEXT NOT NULL,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume INTEGER,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS news_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        ticker TEXT NOT NULL,
        name TEXT NOT NULL,
        keyword TEXT,
        title TEXT,
        source TEXT,
        url TEXT,
        score REAL,
        created_at TEXT NOT NULL
    )
    """,
)


def _kst_now() -> datetime:
    return datetime.now(KST)


def _connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


def init_db(db_path: Path | str = DB_PATH) -> Path:
    """Create the SQLite database and required tables if they do not exist."""
    path = Path(db_path)
    with _connect(path) as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        _ensure_column(connection, "recommendations", "sector", "TEXT")
        _ensure_column(connection, "recommendations", "price_at_pick", "REAL")
        connection.commit()
    return path


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def _recommendation_reason(item: dict) -> str:
    reason = item.get("summary_reason") or item.get("issue_summary", "")
    warning = item.get("change_warning", "")
    if warning and warning not in reason:
        return f"{reason} {warning}".strip()
    return reason


def _price_at_pick(item: dict) -> float | None:
    price = item.get("price_at_pick", item.get("current_price"))
    if price in (None, ""):
        return None
    try:
        return float(price)
    except (TypeError, ValueError):
        return None


def save_recommendations(
    grade_a_items: list[dict],
    watch_items: list[dict],
    *,
    market: str = "KR",
    db_path: Path | str = DB_PATH,
) -> int:
    """Persist final recommendation rows. Returns the number of inserted rows."""
    init_db(db_path)
    now = _kst_now()
    run_date = now.strftime("%Y-%m-%d")
    created_at = now.strftime("%Y-%m-%d %H:%M:%S KST")

    rows: list[tuple] = []
    rank = 1
    for item in grade_a_items:
        rows.append(
            (
                run_date,
                market,
                item["ticker"],
                item["name"],
                rank,
                float(item.get("recommendation_score", item.get("final_score", 0))),
                _recommendation_reason(item),
                item.get("theme", ""),
                item.get("sector_group", item.get("theme", "")),
                _price_at_pick(item),
                created_at,
            )
        )
        rank += 1

    for item in watch_items:
        rows.append(
            (
                run_date,
                market,
                item["ticker"],
                item["name"],
                rank,
                float(item.get("recommendation_score", item.get("observation_score", item.get("final_score", 0)))),
                _recommendation_reason(item),
                item.get("theme", ""),
                item.get("sector_group", item.get("theme", "")),
                _price_at_pick(item),
                created_at,
            )
        )
        rank += 1

    if not rows:
        return 0

    with _connect(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO recommendations (
                run_date, market, ticker, name, rank, score, reason, theme, sector, price_at_pick, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()

    return len(rows)
