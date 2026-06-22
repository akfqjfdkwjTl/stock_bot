"""FastAPI dashboard for the stock bot recommendation database."""

from __future__ import annotations

import html
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from db import init_db, update_recommendation_performance


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "stock_bot.db"
KST = ZoneInfo("Asia/Seoul")

app = FastAPI(title="Stock Dashboard")


@dataclass
class Recommendation:
    id: int
    run_date: str
    market: str
    ticker: str
    name: str
    rank: int
    score: float
    reason: str
    theme: str
    price_at_pick: float | None
    price_date: str
    stored_current_price: float | None
    stored_return_pct: float | None
    performance_updated_at: str
    created_at: str


def get_kst_timestamp() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def _format_market_value(value: float, *, prefix: str = "") -> str:
    return f"{prefix}{value:,.2f}"


def _format_change(change_pct: float) -> str:
    return f"{change_pct:+.2f}%"


def _change_direction(change_pct: float) -> str:
    return "up" if change_pct >= 0 else "down"


def _unavailable_market_item(name: str, note: str) -> dict:
    return {
        "name": name,
        "value": "N/A",
        "change": "N/A",
        "direction": "neutral",
        "note": f"{note} / 데이터 조회 실패",
    }


def _fetch_yfinance_market_data(
    *,
    name: str,
    symbol: str,
    note: str,
    prefix: str = "",
) -> dict:
    try:
        import yfinance as yf

        history = yf.Ticker(symbol).history(period="7d", interval="1d", auto_adjust=False)
        closes = history["Close"].dropna()
        if len(closes) < 2:
            raise ValueError(f"{symbol} close data is insufficient")

        latest = float(closes.iloc[-1])
        previous = float(closes.iloc[-2])
        if previous == 0:
            raise ValueError(f"{symbol} previous close is zero")

        change_pct = (latest - previous) / previous * 100
        return {
            "name": name,
            "value": _format_market_value(latest, prefix=prefix),
            "change": _format_change(change_pct),
            "direction": _change_direction(change_pct),
            "note": note,
        }
    except Exception:
        return _unavailable_market_item(name, note)


def _format_price(value: float) -> str:
    return f"{value:,.0f}원"


def _format_pick_price(value: float | None) -> str:
    if value is None or value <= 0:
        return "N/A"
    return f"{value:,.0f}원"


def _format_return(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2f}%"


def _format_volume(value: float) -> str:
    return f"{int(value):,}"


def _empty_price_data() -> dict:
    return {
        "current_price_value": None,
        "current_price": "N/A",
        "change_pct": "N/A",
        "change_direction": "neutral",
        "volume": "N/A",
    }


def _fetch_yfinance_price(symbol: str) -> dict | None:
    import yfinance as yf

    history = yf.Ticker(symbol).history(period="7d", interval="1d", auto_adjust=False)
    if history.empty:
        return None

    closes = history["Close"].dropna()
    if len(closes) < 2:
        return None

    latest = float(closes.iloc[-1])
    previous = float(closes.iloc[-2])
    if previous == 0:
        return None

    latest_row = history.dropna(subset=["Close"]).iloc[-1]
    volume = float(latest_row["Volume"]) if "Volume" in latest_row else 0
    change_pct = (latest - previous) / previous * 100
    return {
        "current_price_value": latest,
        "current_price": _format_price(latest),
        "change_pct": _format_change(change_pct),
        "change_direction": _change_direction(change_pct),
        "volume": _format_volume(volume) if volume else "N/A",
    }


@lru_cache(maxsize=512)
def get_stock_price_data(ticker: str) -> dict:
    """Fetch Korean stock price data. Try KOSPI first, then KOSDAQ."""
    clean_ticker = "".join(ch for ch in ticker if ch.isdigit()).zfill(6)
    if not clean_ticker:
        return _empty_price_data()

    for suffix in (".KS", ".KQ"):
        try:
            price_data = _fetch_yfinance_price(f"{clean_ticker}{suffix}")
            if price_data:
                return price_data
        except Exception:
            continue

    return _empty_price_data()


def get_fear_greed() -> dict:
    try:
        session = requests.Session()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        page_url = "https://edition.cnn.com/markets/fear-and-greed"
        session.get(page_url, headers={**headers, "Accept": "text/html,application/xhtml+xml"}, timeout=5)
        response = session.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={
                **headers,
                "Accept": "application/json, text/plain, */*",
                "Referer": page_url,
                "Origin": "https://edition.cnn.com",
            },
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
        current = payload.get("fear_and_greed", {})
        score = round(float(current["score"]))
        rating = str(current.get("rating") or "")
        return {
            "name": "Fear & Greed",
            "value": str(score),
            "change": rating.title() if rating else "Live",
            "direction": "up" if score >= 50 else "down",
            "note": "미국 CNN 공포탐욕지수",
        }
    except Exception:
        return _unavailable_market_item("Fear & Greed", "미국 CNN 공포탐욕지수")


def get_market_data() -> list[dict]:
    """Fetch live market data on each page request."""
    return [
        get_fear_greed(),
        _fetch_yfinance_market_data(name="NASDAQ", symbol="^IXIC", note="미국 기술주 대표 지수"),
        _fetch_yfinance_market_data(name="S&P500", symbol="^GSPC", note="미국 대형주 대표 지수"),
        _fetch_yfinance_market_data(name="KOSPI", symbol="^KS11", note="국내 유가증권시장"),
        _fetch_yfinance_market_data(name="KOSDAQ", symbol="^KQ11", note="국내 성장주 시장"),
        _fetch_yfinance_market_data(name="USD/KRW", symbol="KRW=X", note="원달러 환율"),
        _fetch_yfinance_market_data(name="GOLD", symbol="GC=F", note="국제 금 선물", prefix="$"),
        _fetch_yfinance_market_data(name="WTI", symbol="CL=F", note="서부텍사스산 원유", prefix="$"),
    ]


def get_market_indicators() -> list[dict]:
    return get_market_data()


def load_recommendation_dates(limit: int | None = 7) -> tuple[list[str], str | None]:
    if not DB_PATH.exists():
        return [], f"DB 파일을 찾을 수 없습니다: {DB_PATH}"

    try:
        init_db(DB_PATH)
        with sqlite3.connect(DB_PATH) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                (
                    """
                SELECT run_date
                FROM recommendations
                GROUP BY run_date
                ORDER BY run_date DESC
                    """
                    + ("" if limit is None else " LIMIT ?")
                ),
                () if limit is None else (limit,),
            ).fetchall()
    except sqlite3.Error as exc:
        return [], f"DB 날짜 조회 실패: {exc}"

    return [str(row["run_date"]) for row in rows if row["run_date"]], None


def load_recommendations(
    selected_date: str | None = None,
    limit: int = 5,
) -> tuple[list[Recommendation], str | None, str | None]:
    if not DB_PATH.exists():
        return [], None, f"DB 파일을 찾을 수 없습니다: {DB_PATH}"

    try:
        init_db(DB_PATH)
        with sqlite3.connect(DB_PATH) as connection:
            connection.row_factory = sqlite3.Row
            if selected_date is None:
                latest_date = connection.execute(
                    "SELECT MAX(run_date) AS run_date FROM recommendations"
                ).fetchone()
                selected_date = latest_date["run_date"] if latest_date else None

            if not selected_date:
                return [], None, None

            latest = connection.execute(
                """
                SELECT MAX(created_at) AS created_at
                FROM recommendations
                WHERE run_date = ?
                """,
                (selected_date,),
            ).fetchone()
            latest_created_at = latest["created_at"] if latest else None
            if not latest_created_at:
                return [], selected_date, None
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(recommendations)")}
            theme_expr = "COALESCE(sector, theme)" if "sector" in columns else "theme"

            rows = connection.execute(
                f"""
                SELECT id, run_date, market, ticker, name, rank, score, reason,
                       {theme_expr} AS theme,
                       price_at_pick,
                       price_date,
                       current_price,
                       return_pct,
                       performance_updated_at,
                       created_at
                FROM recommendations
                WHERE run_date = ? AND created_at = ?
                ORDER BY rank ASC, score DESC
                LIMIT ?
                """,
                (selected_date, latest_created_at, limit),
            ).fetchall()
    except sqlite3.Error as exc:
        return [], selected_date, f"DB 조회 실패: {exc}"

    recommendations = [_row_to_recommendation(row) for row in rows]
    return recommendations, selected_date, None


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_to_recommendation(row: sqlite3.Row) -> Recommendation:
    return Recommendation(
        id=int(row["id"] or 0),
        run_date=str(row["run_date"] or ""),
        market=str(row["market"] or ""),
        ticker=str(row["ticker"] or ""),
        name=str(row["name"] or ""),
        rank=int(row["rank"] or 0),
        score=float(row["score"] or 0),
        reason=str(row["reason"] or ""),
        theme=str(row["theme"] or ""),
        price_at_pick=_optional_float(row["price_at_pick"]),
        price_date=str(row["price_date"] or ""),
        stored_current_price=_optional_float(row["current_price"]),
        stored_return_pct=_optional_float(row["return_pct"]),
        performance_updated_at=str(row["performance_updated_at"] or ""),
        created_at=str(row["created_at"] or ""),
    )


def load_all_recommendations() -> tuple[list[Recommendation], str | None]:
    if not DB_PATH.exists():
        return [], f"DB 파일을 찾을 수 없습니다: {DB_PATH}"

    try:
        init_db(DB_PATH)
        with sqlite3.connect(DB_PATH) as connection:
            connection.row_factory = sqlite3.Row
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(recommendations)")}
            theme_expr = "COALESCE(sector, theme)" if "sector" in columns else "theme"
            rows = connection.execute(
                f"""
                SELECT id, run_date, market, ticker, name, rank, score, reason,
                       {theme_expr} AS theme,
                       price_at_pick,
                       price_date,
                       current_price,
                       return_pct,
                       performance_updated_at,
                       created_at
                FROM recommendations
                ORDER BY run_date DESC, created_at DESC, rank ASC
                """
            ).fetchall()
    except sqlite3.Error as exc:
        return [], f"DB 전체 성과 조회 실패: {exc}"

    return [_row_to_recommendation(row) for row in rows], None


def calculate_return_pct(price_at_pick: float | None, current_price: float | None) -> float | None:
    if price_at_pick is None or current_price is None or price_at_pick <= 0:
        return None
    return round((current_price - price_at_pick) / price_at_pick * 100, 2)


@lru_cache(maxsize=512)
def infer_price_date(ticker: str, run_date: str, price_at_pick: float | None) -> str:
    if not ticker or not run_date or price_at_pick is None:
        return ""
    try:
        import yfinance as yf

        run_dt = datetime.strptime(run_date, "%Y-%m-%d")
        start = (run_dt - timedelta(days=10)).strftime("%Y-%m-%d")
        end = (run_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        clean_ticker = "".join(ch for ch in ticker if ch.isdigit()).zfill(6)
        history = yf.Ticker(f"{clean_ticker}.KS").history(start=start, end=end, interval="1d", auto_adjust=False)
        closes = history["Close"].dropna()
        if closes.empty:
            return ""
        matched = closes[(closes - float(price_at_pick)).abs() < 0.5]
        if matched.empty:
            return ""
        return matched.index[-1].strftime("%Y-%m-%d")
    except Exception:
        return ""


def get_price_basis_date(item: Recommendation) -> str:
    return item.price_date or infer_price_date(item.ticker, item.run_date, item.price_at_pick)


def build_performance_rows(recommendations: list[Recommendation], *, persist: bool = True) -> list[dict]:
    rows: list[dict] = []
    for item in recommendations:
        price_data = get_stock_price_data(item.ticker)
        current_price = price_data.get("current_price_value")
        return_pct = calculate_return_pct(item.price_at_pick, current_price)
        if persist and return_pct is not None:
            try:
                update_recommendation_performance(
                    item.id,
                    current_price=current_price,
                    return_pct=return_pct,
                    db_path=DB_PATH,
                )
            except Exception:
                pass
        rows.append(
            {
                "item": item,
                "price_data": price_data,
                "price_date": get_price_basis_date(item),
                "return_pct": return_pct,
                "return_direction": "neutral" if return_pct is None else _change_direction(return_pct),
            }
        )
    return rows


def summarize_performance(performance_rows: list[dict]) -> dict:
    valid_rows = [row for row in performance_rows if row["return_pct"] is not None]
    valid_returns = [row["return_pct"] for row in valid_rows]
    winners = [value for value in valid_returns if value > 0]
    losers = [value for value in valid_returns if value <= 0]
    average = round(sum(valid_returns) / len(valid_returns), 2) if valid_returns else None
    win_rate = round(len(winners) / len(valid_returns) * 100, 1) if valid_returns else None
    best_row = max(valid_rows, key=lambda row: row["return_pct"], default=None)
    worst_row = min(valid_rows, key=lambda row: row["return_pct"], default=None)
    return {
        "count": len(performance_rows),
        "valid_count": len(valid_returns),
        "excluded_count": len(performance_rows) - len(valid_returns),
        "average_return": average,
        "win_rate": win_rate,
        "best_return": round(best_row["return_pct"], 2) if best_row else None,
        "worst_return": round(worst_row["return_pct"], 2) if worst_row else None,
        "best_row": best_row,
        "worst_row": worst_row,
        "winners": len(winners),
        "losers": len(losers),
    }


def _parse_run_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


def filter_recommendations_since(
    recommendations: list[Recommendation],
    *,
    days: int,
    reference_date: datetime | None = None,
) -> list[Recommendation]:
    if reference_date is None:
        reference_date = datetime.now(KST).replace(tzinfo=None)
    start_date = reference_date - timedelta(days=days - 1)
    filtered = []
    for item in recommendations:
        run_date = _parse_run_date(item.run_date)
        if run_date and run_date.date() >= start_date.date():
            filtered.append(item)
    return filtered


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_market_card(item: dict, index: int) -> str:
    wide_class = " market-card-wide" if index == 0 else ""
    direction = item.get("direction")
    if direction not in {"up", "down", "neutral"}:
        direction = "neutral"
    return f"""
      <article class="market-card{wide_class}">
        <p class="micro">{esc(item["name"])}</p>
        <div class="market-value-row">
          <strong>{esc(item["value"])}</strong>
          <span class="change {direction}">{esc(item["change"])}</span>
        </div>
        <p class="market-note">{esc(item["note"])}</p>
      </article>
    """


def render_stock_card(item: Recommendation, *, featured: bool = False) -> str:
    featured_class = " featured" if featured else ""
    reason = item.reason or "저장된 선정 이유가 없습니다."
    theme = item.theme or "기타"
    price_data = get_stock_price_data(item.ticker)
    change_direction = price_data["change_direction"]
    return f"""
      <article class="stock-card{featured_class}">
        <div class="card-top">
          <div>
            <h3>{esc(item.name)}</h3>
            <p>{esc(item.ticker)}</p>
            <div class="price-line">
              <span class="price-label">현재가</span>
              <strong>{esc(price_data["current_price"])}</strong>
              <span class="stock-change {esc(change_direction)}">{esc(price_data["change_pct"])}</span>
            </div>
          </div>
          <span class="score">{item.score:.1f}점</span>
        </div>
        <div class="stock-meta">
          <div><span>순위</span><strong>{item.rank}</strong></div>
          <div><span>거래량</span><strong>{esc(price_data["volume"])}</strong></div>
          <div><span>테마</span><strong>{esc(theme)}</strong></div>
        </div>
        <div class="info-block">
          <span>핵심 선정 이유</span>
          <p>{esc(reason)}</p>
        </div>
      </article>
    """


def render_empty_card(message: str) -> str:
    return f"""
      <article class="empty-card">
        <p>{esc(message)}</p>
      </article>
    """


def render_date_buttons(dates: list[str], selected_date: str | None) -> str:
    if not dates:
        return ""

    buttons = []
    for run_date in dates:
        active = " active" if run_date == selected_date else ""
        buttons.append(
            f'<a class="date-button{active}" href="/?date={esc(run_date)}">{esc(run_date)}</a>'
        )

    return f"""
      <nav class="date-nav" aria-label="추천 날짜 선택">
        {''.join(buttons)}
      </nav>
    """


def render_date_controls(
    recent_dates: list[str],
    all_dates: list[str],
    selected_date: str | None,
) -> str:
    if not recent_dates and not all_dates:
        return ""

    buttons = []
    for run_date in recent_dates:
        active = " active" if run_date == selected_date else ""
        buttons.append(
            f'<a class="date-button{active}" href="/?date={esc(run_date)}">{esc(run_date)}</a>'
        )

    date_options = "".join(f'<option value="{esc(run_date)}"></option>' for run_date in all_dates)
    min_date = min(all_dates) if all_dates else ""
    max_date = max(all_dates) if all_dates else ""
    selected_value = selected_date or max_date
    quick_dates = "".join(buttons) or '<span class="date-help">최근 추천 날짜가 없습니다</span>'
    available_dates = ", ".join(all_dates[:12])
    if len(all_dates) > 12:
        available_dates += f" 외 {len(all_dates) - 12}개"
    date_help = f"추천 데이터 보유 날짜 {len(all_dates)}개"
    if available_dates:
        date_help += f": {available_dates}"

    return f"""
      <section class="date-panel" aria-label="추천 날짜 조회">
        <div class="date-panel-block">
          <span class="date-label">최근 날짜</span>
          <nav class="date-nav" aria-label="최근 추천 날짜 빠른 조회">
            {quick_dates}
          </nav>
        </div>
        <form class="date-picker-form" action="/" method="get">
          <label for="history-date">달력</label>
          <div class="date-picker-row">
            <input
              id="history-date"
              name="date"
              type="date"
              value="{esc(selected_value)}"
              min="{esc(min_date)}"
              max="{esc(max_date)}"
              list="recommendation-dates"
              data-available-dates="{esc('|'.join(all_dates))}"
              aria-describedby="date-picker-help"
            >
            <datalist id="recommendation-dates">{date_options}</datalist>
          </div>
          <p id="date-picker-help">{esc(date_help)}</p>
        </form>
      </section>
    """


def render_stat_card(label: str, value: str, direction: str = "neutral", detail: str = "") -> str:
    detail_html = f"<small>{esc(detail)}</small>" if detail else ""
    return f"""
      <div class="perf-stat">
        <span>{esc(label)}</span>
        <strong class="{esc(direction)}">{esc(value)}</strong>
        {detail_html}
      </div>
    """


def _format_win_rate(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.1f}%"


def render_performance_summary_cards(summary: dict, *, scope_label: str) -> str:
    average_direction = "neutral" if summary["average_return"] is None else _change_direction(summary["average_return"])
    best_direction = "neutral" if summary["best_return"] is None else _change_direction(summary["best_return"])
    worst_direction = "neutral" if summary["worst_return"] is None else _change_direction(summary["worst_return"])
    best_detail = _performance_extreme_detail(summary.get("best_row"))
    worst_detail = _performance_extreme_detail(summary.get("worst_row"))
    return f"""
      <div class="performance-summary-title">{esc(scope_label)}</div>
      <div class="performance-summary">
        {render_stat_card("추천 수", str(summary["count"]))}
        {render_stat_card("승률", _format_win_rate(summary["win_rate"]))}
        {render_stat_card("평균 수익률", _format_return(summary["average_return"]), average_direction)}
        {render_stat_card("최고 수익률", _format_return(summary["best_return"]), best_direction, best_detail)}
        {render_stat_card("최저 수익률", _format_return(summary["worst_return"]), worst_direction, worst_detail)}
        {render_stat_card("수익 종목", str(summary["winners"]), "up")}
        {render_stat_card("손실 종목", str(summary["losers"]), "down")}
        {render_stat_card("계산 제외", str(summary["excluded_count"]))}
      </div>
    """


def _performance_extreme_detail(row: dict | None) -> str:
    if not row:
        return ""
    item: Recommendation = row["item"]
    price_data = row["price_data"]
    price_date = row.get("price_date") or "N/A"
    return (
        f"{item.name} / 추천일 {item.run_date} / 가격기준일 {price_date} / "
        f"추천가 {_format_pick_price(item.price_at_pick)} / 현재가 {price_data['current_price']}"
    )


def render_performance_card(row: dict) -> str:
    item: Recommendation = row["item"]
    price_data = row["price_data"]
    price_date = row.get("price_date") or "N/A"
    return_pct = row["return_pct"]
    return_direction = row["return_direction"]
    return f"""
      <article class="performance-card">
        <div>
          <h3>{esc(item.name)}</h3>
          <p>{esc(item.ticker)}</p>
        </div>
        <div class="performance-values">
          <div><span>추천일</span><strong>{esc(item.run_date)}</strong></div>
          <div><span>가격기준일</span><strong>{esc(price_date)}</strong></div>
          <div><span>추천가</span><strong>{esc(_format_pick_price(item.price_at_pick))}</strong></div>
          <div><span>현재가</span><strong>{esc(price_data["current_price"])}</strong></div>
          <div><span>수익률</span><strong class="{esc(return_direction)}">{esc(_format_return(return_pct))}</strong></div>
        </div>
      </article>
    """


def render_performance_section(
    performance_rows: list[dict],
    selected_date: str | None,
    cumulative_rows: list[dict],
) -> str:
    cumulative_summary = summarize_performance(cumulative_rows)
    cumulative_html = render_performance_summary_cards(cumulative_summary, scope_label="누적 성과")
    if not performance_rows:
        cards = render_empty_card("해당 날짜 추천 데이터가 없습니다")
        summary_html = render_performance_summary_cards(summarize_performance([]), scope_label="선택 날짜 성과")
    else:
        summary = summarize_performance(performance_rows)
        summary_html = render_performance_summary_cards(summary, scope_label="선택 날짜 성과")
        cards = "\n".join(render_performance_card(row) for row in performance_rows)

    return f"""
      <section class="section">
        <div class="section-head">
          <div>
            <p class="section-label">PERFORMANCE TRACKING</p>
            <h2>{esc(selected_date or "N/A")} 추천 성과</h2>
          </div>
          <span class="badge green">현재가 기준 수익률</span>
        </div>
        {cumulative_html}
        {summary_html}
        <div class="performance-grid">{cards}</div>
      </section>
    """


def render_dashboard(selected_date: str | None = None) -> str:
    recent_dates, date_error = load_recommendation_dates(7)
    all_dates, all_date_error = load_recommendation_dates(None)
    recommendations, resolved_date, db_error = load_recommendations(selected_date)
    all_recommendations, all_performance_error = load_all_recommendations()
    high_conviction = [item for item in recommendations if item.score >= 70]
    watchlist = recommendations[:5]
    latest_run = recommendations[0].created_at if recommendations else get_kst_timestamp()
    performance_rows = build_performance_rows(watchlist)
    cumulative_rows = build_performance_rows(all_recommendations)

    market_cards = "\n".join(
        render_market_card(item, index)
        for index, item in enumerate(get_market_indicators())
    )
    grade_cards = (
        "\n".join(render_stock_card(item, featured=True) for item in high_conviction)
        if high_conviction
        else render_empty_card("현재 기준 A급 조건을 통과한 종목이 없습니다.")
    )
    watch_cards = (
        "\n".join(render_stock_card(item) for item in watchlist)
        if watchlist
        else render_empty_card("해당 날짜 추천 데이터가 없습니다")
    )
    notices = [error for error in (date_error, all_date_error, db_error, all_performance_error) if error]
    db_notice = "".join(f'<div class="db-notice">{esc(error)}</div>' for error in notices)
    date_controls = render_date_controls(recent_dates, all_dates, resolved_date)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>오늘의 관심종목</title>
  <style>
    :root {{
      --bg: #070a0e;
      --panel: #0d1219;
      --panel-2: #101622;
      --panel-3: #141b2a;
      --line: rgba(255,255,255,.075);
      --line-strong: rgba(255,255,255,.12);
      --text: #f4f7fb;
      --muted: #8e9aad;
      --subtle: #c2cad8;
      --blue: #27b8ee;
      --green: #49e09a;
      --red: #ff7575;
      --shadow: 0 26px 70px rgba(0,0,0,.42);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      background:
        radial-gradient(circle at 92% 0%, rgba(55, 211, 170, .12), transparent 30%),
        linear-gradient(180deg, #080b10 0%, #07090d 100%);
      font-family: "Segoe UI", "Noto Sans KR", Arial, sans-serif;
    }}
    .shell {{
      width: min(1120px, calc(100% - 28px));
      margin: 0 auto;
      padding: 18px 0 60px;
    }}
    .hero {{
      padding: 26px 30px 30px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: linear-gradient(135deg, rgba(17,22,33,.98), rgba(9,12,18,.98));
      box-shadow: var(--shadow);
    }}
    .kicker, .section-label, .stock-card .card-top p, .stock-meta span {{
      margin: 0;
      color: var(--muted);
      font-size: 11px;
      letter-spacing: .09em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 5px 0 10px;
      font-size: clamp(34px, 6vw, 52px);
      line-height: 1;
      letter-spacing: 0;
    }}
    .hero-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      color: var(--subtle);
      font-size: 13px;
    }}
    .hero-note {{
      margin: 13px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.65;
    }}
    .date-panel {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(220px, 300px);
      gap: 14px;
      align-items: end;
      margin-top: 16px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(8,12,18,.45);
    }}
    .date-panel-block {{
      min-width: 0;
    }}
    .date-label,
    .date-picker-form label {{
      display: block;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 900;
      letter-spacing: .08em;
      text-transform: uppercase;
    }}
    .date-nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .date-button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 32px;
      padding: 7px 11px;
      border: 1px solid rgba(39,184,238,.22);
      border-radius: 999px;
      color: #9fdfff;
      background: rgba(39,184,238,.07);
      font-size: 12px;
      font-weight: 800;
      text-decoration: none;
    }}
    .date-button.active {{
      color: #04100b;
      border-color: rgba(73,224,154,.65);
      background: var(--green);
    }}
    .date-picker-form {{
      min-width: 0;
      margin: 0;
    }}
    .date-picker-row {{
      position: relative;
    }}
    .date-picker-row::before {{
      content: "📅";
      position: absolute;
      left: 12px;
      top: 50%;
      transform: translateY(-50%);
      pointer-events: none;
      font-size: 15px;
    }}
    .date-picker-row input {{
      width: 100%;
      min-height: 40px;
      padding: 9px 11px 9px 36px;
      border: 1px solid rgba(39,184,238,.28);
      border-radius: 8px;
      color: var(--text);
      background: rgba(16,22,34,.95);
      font: inherit;
      font-size: 13px;
      font-weight: 800;
      color-scheme: dark;
    }}
    .date-picker-row input:focus {{
      outline: 2px solid rgba(39,184,238,.35);
      outline-offset: 2px;
    }}
    .date-help,
    #date-picker-help {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.45;
    }}
    .content {{
      display: grid;
      gap: 18px;
      margin-top: 18px;
    }}
    .section {{
      padding: 22px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(13,18,25,.96);
      box-shadow: var(--shadow);
    }}
    .section-head {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 18px;
    }}
    h2 {{
      margin: 4px 0 0;
      font-size: clamp(24px, 4vw, 34px);
      line-height: 1.05;
      letter-spacing: 0;
    }}
    .badge {{
      flex: 0 0 auto;
      padding: 7px 10px;
      border: 1px solid rgba(39,184,238,.32);
      border-radius: 999px;
      color: #75d8ff;
      background: rgba(39,184,238,.09);
      font-size: 11px;
      font-weight: 800;
    }}
    .badge.green {{
      color: var(--green);
      border-color: rgba(73,224,154,.32);
      background: rgba(73,224,154,.08);
    }}
    .market-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }}
    .market-card {{
      min-height: 118px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: linear-gradient(180deg, rgba(255,255,255,.035), rgba(255,255,255,.005)), var(--panel-2);
    }}
    .market-card-wide {{ grid-column: span 2; }}
    .market-value-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-top: 13px;
    }}
    .market-value-row strong {{
      min-width: 0;
      font-size: 22px;
      line-height: 1.05;
      white-space: nowrap;
    }}
    .market-card-wide .market-value-row strong {{ font-size: 48px; }}
    .change {{
      padding: 5px 8px;
      border-radius: 999px;
      font-size: 10px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .change.up {{ color: var(--green); background: rgba(73,224,154,.13); }}
    .change.down {{ color: var(--red); background: rgba(255,117,117,.13); }}
    .change.neutral {{ color: var(--muted); background: rgba(142,154,173,.14); }}
    .market-note {{
      margin: 12px 0 0;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.5;
    }}
    .stock-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
    }}
    .stock-card, .empty-card {{
      min-width: 0;
      padding: 16px;
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      background: linear-gradient(180deg, rgba(82,102,150,.13), rgba(12,17,25,.98) 45%), var(--panel-2);
    }}
    .stock-card.featured {{
      border-color: rgba(73,224,154,.25);
      background: linear-gradient(180deg, rgba(73,224,154,.08), rgba(12,17,25,.98) 44%), var(--panel-2);
    }}
    .card-top {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;
    }}
    .stock-card h3 {{
      margin: 0;
      font-size: 18px;
      line-height: 1.15;
      letter-spacing: 0;
      overflow-wrap: anywhere;
    }}
    .price-line {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      margin-top: 9px;
    }}
    .price-line strong {{
      color: var(--text);
      font-size: 13px;
      line-height: 1.2;
      white-space: nowrap;
    }}
    .price-label {{
      color: var(--muted);
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0;
    }}
    .stock-change {{
      padding: 4px 7px;
      border-radius: 999px;
      font-size: 10px;
      font-weight: 900;
      white-space: nowrap;
    }}
    .stock-change.up {{ color: var(--green); background: rgba(73,224,154,.13); }}
    .stock-change.down {{ color: var(--red); background: rgba(255,117,117,.13); }}
    .stock-change.neutral {{ color: var(--muted); background: rgba(142,154,173,.14); }}
    .score {{
      flex: 0 0 auto;
      padding: 5px 8px;
      border-radius: 999px;
      color: #82ddff;
      background: rgba(39,184,238,.18);
      font-size: 10px;
      font-weight: 900;
      white-space: nowrap;
    }}
    .stock-meta {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin: 16px 0;
    }}
    .stock-meta div {{
      min-height: 54px;
      padding: 9px 8px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(8,12,18,.55);
    }}
    .stock-meta strong {{
      display: block;
      margin-top: 7px;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .info-block span {{
      display: block;
      margin-bottom: 7px;
      color: #52d6ff;
      font-size: 11px;
      font-weight: 900;
    }}
    .info-block p, .empty-card p {{
      margin: 0;
      color: #d7deea;
      font-size: 12px;
      line-height: 1.65;
    }}
    .performance-summary {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }}
    .performance-summary-title {{
      margin: 16px 0 9px;
      color: #52d6ff;
      font-size: 12px;
      font-weight: 900;
    }}
    .perf-stat {{
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(8,12,18,.55);
    }}
    .perf-stat span {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
    }}
    .perf-stat strong {{
      display: block;
      margin-top: 8px;
      color: var(--text);
      font-size: 22px;
      line-height: 1.1;
    }}
    .perf-stat small {{
      display: block;
      margin-top: 7px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}
    .perf-stat strong.up,
    .performance-values strong.up {{ color: var(--green); }}
    .perf-stat strong.down,
    .performance-values strong.down {{ color: var(--red); }}
    .perf-stat strong.neutral,
    .performance-values strong.neutral {{ color: var(--muted); }}
    .performance-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
    }}
    .performance-card {{
      min-width: 0;
      padding: 16px;
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      background: linear-gradient(180deg, rgba(73,224,154,.08), rgba(12,17,25,.98) 42%), var(--panel-2);
    }}
    .performance-card h3 {{
      margin: 0;
      font-size: 18px;
      line-height: 1.15;
      overflow-wrap: anywhere;
    }}
    .performance-card p {{
      margin: 5px 0 0;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
    }}
    .performance-values {{
      display: grid;
      gap: 8px;
      margin-top: 14px;
    }}
    .performance-values div {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 9px 8px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(8,12,18,.55);
    }}
    .performance-values span {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .performance-values strong {{
      color: var(--text);
      font-size: 12px;
      text-align: right;
      white-space: nowrap;
    }}
    .empty-card {{
      grid-column: 1 / -1;
      min-height: 84px;
      display: flex;
      align-items: center;
    }}
    .db-notice {{
      margin-bottom: 14px;
      padding: 12px 14px;
      border: 1px solid rgba(255,117,117,.28);
      border-radius: 8px;
      color: #ffd1d1;
      background: rgba(255,117,117,.08);
      font-size: 12px;
    }}
    @media (max-width: 900px) {{
      .market-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .stock-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .performance-summary {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .performance-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .market-card-wide {{ grid-column: span 2; }}
    }}
    @media (max-width: 768px) {{
      .shell {{ width: min(100% - 18px, 1120px); padding: 10px 0 36px; }}
      .hero {{ padding: 18px; }}
      h1 {{ margin-bottom: 8px; font-size: 34px; }}
      .hero-meta {{ gap: 7px; font-size: 12px; }}
      .hero-note {{ margin-top: 10px; font-size: 12px; line-height: 1.5; }}
      .date-panel {{
        grid-template-columns: 1fr;
        gap: 12px;
        margin-top: 12px;
        padding: 12px;
      }}
      .date-nav {{ gap: 6px; }}
      .date-button {{ min-height: 30px; padding: 6px 9px; font-size: 11px; }}
      .date-picker-row input {{ min-height: 38px; font-size: 12px; }}
      #date-picker-help {{ font-size: 10px; }}
      .content {{ gap: 14px; margin-top: 14px; }}
      .section {{ padding: 14px; }}
      .section-head {{ align-items: flex-start; flex-direction: column; gap: 9px; margin-bottom: 12px; }}
      h2 {{ font-size: 25px; }}
      .badge {{ padding: 6px 9px; font-size: 10px; }}
      .market-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }}
      .market-card,
      .market-card-wide {{
        grid-column: span 1;
        min-height: 92px;
        padding: 12px;
      }}
      .market-value-row {{ margin-top: 9px; gap: 6px; }}
      .market-value-row strong,
      .market-card-wide .market-value-row strong {{
        font-size: 22px;
      }}
      .micro {{ font-size: 12px; letter-spacing: 0; }}
      .change {{ padding: 4px 7px; font-size: 9px; }}
      .market-note {{
        margin-top: 9px;
        font-size: 10px;
        line-height: 1.35;
      }}
      .stock-grid {{ grid-template-columns: 1fr; gap: 10px; }}
      .performance-summary {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
      .perf-stat {{ padding: 11px; }}
      .perf-stat strong {{ font-size: 18px; }}
      .performance-grid {{ grid-template-columns: 1fr; gap: 10px; }}
      .stock-card, .empty-card {{ padding: 14px; }}
      .performance-card {{ padding: 14px; }}
      .stock-card h3 {{ font-size: 18px; }}
      .stock-meta {{ margin: 12px 0; }}
      .stock-meta div {{ min-height: 48px; padding: 8px; }}
      .info-block p, .empty-card p {{ font-size: 11px; line-height: 1.55; }}
    }}
    @media (max-width: 560px) {{
      .market-value-row strong,
      .market-card-wide .market-value-row strong {{ font-size: 20px; }}
      .market-note {{ display: none; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <header class="hero">
      <p class="kicker">KOREA STOCK WATCHLIST</p>
      <h1>오늘의 관심종목</h1>
      <div class="hero-meta">
        <span>기준시각: <strong>{esc(get_kst_timestamp())}</strong></span>
        <span>선택 날짜: <strong>{esc(resolved_date or "N/A")}</strong></span>
        <span>최신 저장시각: <strong>{esc(latest_run)}</strong></span>
      </div>
      {date_controls}
      <p class="hero-note">SQLite 추천 데이터와 시장 지표를 한 화면에서 확인하는 서버용 FastAPI 대시보드입니다.</p>
    </header>

    <main class="content">
      {db_notice}
      <section class="section">
        <div class="section-head">
          <div>
            <p class="section-label">MACRO SNAPSHOT</p>
            <h2>시장 지표</h2>
          </div>
          <span class="badge">live market data</span>
        </div>
        <div class="market-grid">{market_cards}</div>
      </section>

      <section class="section">
        <div class="section-head">
          <div>
            <p class="section-label">HIGH CONVICTION</p>
            <h2>A급 추천</h2>
          </div>
          <span class="badge green">강한 조건 통과 종목</span>
        </div>
        <div class="stock-grid">{grade_cards}</div>
      </section>

      <section class="section">
        <div class="section-head">
          <div>
            <p class="section-label">MARKET FLOW</p>
            <h2>관찰 후보</h2>
          </div>
          <span class="badge">최신 추천 5개</span>
        </div>
        <div class="stock-grid">{watch_cards}</div>
      </section>

      {render_performance_section(performance_rows, resolved_date, cumulative_rows)}
    </main>
  </div>
  <script>
  const historyDateInput = document.getElementById("history-date");
  if (historyDateInput) {{
    historyDateInput.addEventListener("change", () => {{
      if (historyDateInput.value) {{
        window.location.href = `/?date=${{encodeURIComponent(historyDateInput.value)}}`;
      }}
    }});
  }}
  </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard(date: str | None = Query(default=None)) -> HTMLResponse:
    return HTMLResponse(render_dashboard(date))
