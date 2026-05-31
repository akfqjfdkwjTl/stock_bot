"""FastAPI dashboard for the stock bot recommendation database."""

from __future__ import annotations

import html
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "stock_bot.db"
KST = ZoneInfo("Asia/Seoul")

app = FastAPI(title="Stock Dashboard")


@dataclass
class Recommendation:
    run_date: str
    market: str
    ticker: str
    name: str
    rank: int
    score: float
    reason: str
    theme: str
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


def _format_volume(value: float) -> str:
    return f"{int(value):,}"


def _empty_price_data() -> dict:
    return {
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
        "current_price": _format_price(latest),
        "change_pct": _format_change(change_pct),
        "change_direction": _change_direction(change_pct),
        "volume": _format_volume(volume) if volume else "N/A",
    }


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


def load_recommendation_dates(limit: int = 7) -> tuple[list[str], str | None]:
    if not DB_PATH.exists():
        return [], f"DB 파일을 찾을 수 없습니다: {DB_PATH}"

    try:
        with sqlite3.connect(DB_PATH) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT run_date
                FROM recommendations
                GROUP BY run_date
                ORDER BY run_date DESC
                LIMIT ?
                """,
                (limit,),
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

            rows = connection.execute(
                """
                SELECT run_date, market, ticker, name, rank, score, reason, theme, created_at
                FROM recommendations
                WHERE run_date = ? AND created_at = ?
                ORDER BY rank ASC, score DESC
                LIMIT ?
                """,
                (selected_date, latest_created_at, limit),
            ).fetchall()
    except sqlite3.Error as exc:
        return [], selected_date, f"DB 조회 실패: {exc}"

    recommendations = [
        Recommendation(
            run_date=str(row["run_date"] or ""),
            market=str(row["market"] or ""),
            ticker=str(row["ticker"] or ""),
            name=str(row["name"] or ""),
            rank=int(row["rank"] or 0),
            score=float(row["score"] or 0),
            reason=str(row["reason"] or ""),
            theme=str(row["theme"] or ""),
            created_at=str(row["created_at"] or ""),
        )
        for row in rows
    ]
    return recommendations, selected_date, None


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


def render_dashboard(selected_date: str | None = None) -> str:
    available_dates, date_error = load_recommendation_dates()
    recommendations, resolved_date, db_error = load_recommendations(selected_date)
    high_conviction = [item for item in recommendations if item.score >= 70]
    watchlist = recommendations[:5]
    latest_run = recommendations[0].created_at if recommendations else get_kst_timestamp()

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
    notices = [error for error in (date_error, db_error) if error]
    db_notice = "".join(f'<div class="db-notice">{esc(error)}</div>' for error in notices)
    date_buttons = render_date_buttons(available_dates, resolved_date)

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
    .date-nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 16px;
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
      .market-card-wide {{ grid-column: span 2; }}
    }}
    @media (max-width: 768px) {{
      .shell {{ width: min(100% - 18px, 1120px); padding: 10px 0 36px; }}
      .hero {{ padding: 18px; }}
      h1 {{ margin-bottom: 8px; font-size: 34px; }}
      .hero-meta {{ gap: 7px; font-size: 12px; }}
      .hero-note {{ margin-top: 10px; font-size: 12px; line-height: 1.5; }}
      .date-nav {{ gap: 6px; margin-top: 12px; }}
      .date-button {{ min-height: 30px; padding: 6px 9px; font-size: 11px; }}
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
      .stock-card, .empty-card {{ padding: 14px; }}
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
      {date_buttons}
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
    </main>
  </div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard(date: str | None = Query(default=None)) -> HTMLResponse:
    return HTMLResponse(render_dashboard(date))
