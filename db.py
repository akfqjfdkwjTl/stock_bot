"""SQLite database helpers for stock bot results."""

from __future__ import annotations

import json
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
        price_date TEXT,
        news_items_json TEXT,
        score_detail_json TEXT,
        current_price REAL,
        return_pct REAL,
        performance_updated_at TEXT,
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
        _ensure_column(connection, "recommendations", "price_date", "TEXT")
        _ensure_column(connection, "recommendations", "news_items_json", "TEXT")
        _ensure_column(connection, "recommendations", "score_detail_json", "TEXT")
        _ensure_column(connection, "recommendations", "current_price", "REAL")
        _ensure_column(connection, "recommendations", "return_pct", "REAL")
        _ensure_column(connection, "recommendations", "performance_updated_at", "TEXT")
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


def _json_dump(value: object) -> str:
    try:
        return json.dumps(value or [], ensure_ascii=False)
    except TypeError:
        return "[]"


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
                item.get("price_date", ""),
                _json_dump(item.get("news_items", [])),
                _json_dump(item.get("score_detail", {})),
                _price_at_pick(item),
                None,
                None,
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
                item.get("price_date", ""),
                _json_dump(item.get("news_items", [])),
                _json_dump(item.get("score_detail", {})),
                _price_at_pick(item),
                None,
                None,
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
                run_date, market, ticker, name, rank, score, reason, theme, sector,
                price_at_pick, price_date, news_items_json, score_detail_json,
                current_price, return_pct, performance_updated_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()

    return len(rows)


def update_recommendation_performance(
    recommendation_id: int,
    *,
    current_price: float | None,
    return_pct: float | None,
    db_path: Path | str = DB_PATH,
) -> None:
    """Store the latest calculated performance metrics for one recommendation row."""
    if current_price is None or return_pct is None:
        return

    init_db(db_path)
    updated_at = _kst_now().strftime("%Y-%m-%d %H:%M:%S KST")
    with _connect(db_path) as connection:
        connection.execute(
            """
            UPDATE recommendations
            SET current_price = ?, return_pct = ?, performance_updated_at = ?
            WHERE id = ?
            """,
            (float(current_price), float(return_pct), updated_at, int(recommendation_id)),
        )
        connection.commit()
