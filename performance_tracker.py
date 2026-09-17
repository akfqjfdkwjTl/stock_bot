"""Pure helpers for evaluating tracked stock performance from daily OHLC data."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable


def _date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")[:10]


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _return_pct(reference_price: float, price: float | None) -> float | None:
    if price is None or reference_price <= 0:
        return None
    return round((price - reference_price) / reference_price * 100, 4)


def calculate_tracking_performance(
    *,
    reference_price: float,
    reference_date: str,
    observations: Iterable[dict[str, Any]],
    target_price: float | None = None,
    stop_price: float | None = None,
) -> dict[str, Any]:
    """Calculate forward-session returns, excursions, and first threshold touch."""
    price = float(reference_price)
    normalized: list[dict[str, Any]] = []
    for observation in observations:
        row_date = _date_text(observation.get("date"))
        close = _optional_float(observation.get("close"))
        high = _optional_float(observation.get("high"))
        low = _optional_float(observation.get("low"))
        if not row_date or close is None:
            continue
        normalized.append(
            {
                "date": row_date,
                "close": close,
                "high": high if high is not None else close,
                "low": low if low is not None else close,
            }
        )

    rows = sorted(normalized, key=lambda row: row["date"])
    latest = rows[-1] if rows else None
    forward_rows = [row for row in rows if row["date"] > reference_date]

    def session_return(session: int) -> float | None:
        if len(forward_rows) < session:
            return None
        return _return_pct(price, forward_rows[session - 1]["close"])

    mfe_pct = None
    mae_pct = None
    if forward_rows:
        mfe_pct = _return_pct(price, max(row["high"] for row in forward_rows))
        mae_pct = _return_pct(price, min(row["low"] for row in forward_rows))

    resolved_target = _optional_float(target_price)
    resolved_stop = _optional_float(stop_price)
    target_hit_date = None
    stop_hit_date = None
    for row in forward_rows:
        if target_hit_date is None and resolved_target and row["high"] >= resolved_target:
            target_hit_date = row["date"]
        if stop_hit_date is None and resolved_stop and row["low"] <= resolved_stop:
            stop_hit_date = row["date"]

    if resolved_target is None and resolved_stop is None:
        first_exit = "NOT_SET"
    elif target_hit_date and stop_hit_date:
        if target_hit_date == stop_hit_date:
            first_exit = "SAME_DAY"
        elif target_hit_date < stop_hit_date:
            first_exit = "TARGET_FIRST"
        else:
            first_exit = "STOP_FIRST"
    elif target_hit_date:
        first_exit = "TARGET_FIRST"
    elif stop_hit_date:
        first_exit = "STOP_FIRST"
    else:
        first_exit = "OPEN"

    return {
        "latest_price": latest["close"] if latest else None,
        "latest_price_date": latest["date"] if latest else "",
        "latest_return_pct": _return_pct(price, latest["close"] if latest else None),
        "d5_return_pct": session_return(5),
        "d10_return_pct": session_return(10),
        "d20_return_pct": session_return(20),
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "target_hit_date": target_hit_date,
        "stop_hit_date": stop_hit_date,
        "first_exit": first_exit,
        "observed_sessions": len(forward_rows),
    }
