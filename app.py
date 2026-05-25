"""FastAPI dashboard for the stock bot recommendation database."""

from __future__ import annotations

import html
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI
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


def get_mock_market_indicators() -> list[dict]:
    """Fallback market data used when live providers fail."""
    return [
        {"name": "Fear & Greed", "value": "63", "change": "Greed", "direction": "up", "note": "미국 CNN 공포탐욕지수"},
        {"name": "NASDAQ", "value": "17,516.10", "change": "+0.72%", "direction": "up", "note": "미국 기술주 대표 지수"},
        {"name": "S&P500", "value": "5,911.11", "change": "-0.18%", "direction": "down", "note": "미국 대형주 대표 지수"},
        {"name": "KOSPI", "value": "2,625.10", "change": "+0.41%", "direction": "up", "note": "국내 유가증권시장"},
        {"name": "KOSDAQ", "value": "740.85", "change": "-1.26%", "direction": "down", "note": "국내 성장주 시장"},
        {"name": "USD/KRW", "value": "1,501.11", "change": "+0.30%", "direction": "up", "note": "원달러 환율"},
        {"name": "GOLD", "value": "$3,358.40", "change": "-0.49%", "direction": "down", "note": "국제 금 선물"},
        {"name": "WTI", "value": "$62.33", "change": "-0.95%", "direction": "down", "note": "서부텍사스산 원유"},
    ]


MOCK_MARKET_BY_NAME = {item["name"]: item for item in get_mock_market_indicators()}


def _format_market_value(value: float, *, prefix: str = "") -> str:
    return f"{prefix}{value:,.2f}"


def _format_change(change_pct: float) -> str:
    return f"{change_pct:+.2f}%"


def _change_direction(change_pct: float) -> str:
    return "up" if change_pct >= 0 else "down"


def _fallback_market_item(name: str, note: str | None = None) -> dict:
    fallback = dict(MOCK_MARKET_BY_NAME[name])
    if note:
        fallback["note"] = note
    return fallback


def _fetch_yfinance_indicator(
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
        return _fallback_market_item(name, f"{note} / fallback")


def _fetch_fear_greed_index() -> dict:
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
        return _fallback_market_item("Fear & Greed", "미국 CNN 공포탐욕지수 / fallback")


def get_market_indicators() -> list[dict]:
    """Fetch live market data on each page request, with per-card fallback."""
    return [
        _fetch_fear_greed_index(),
        _fetch_yfinance_indicator(name="NASDAQ", symbol="^IXIC", note="미국 기술주 대표 지수"),
        _fetch_yfinance_indicator(name="S&P500", symbol="^GSPC", note="미국 대형주 대표 지수"),
        _fetch_yfinance_indicator(name="KOSPI", symbol="^KS11", note="국내 유가증권시장"),
        _fetch_yfinance_indicator(name="KOSDAQ", symbol="^KQ11", note="국내 성장주 시장"),
        _fetch_yfinance_indicator(name="USD/KRW", symbol="KRW=X", note="원달러 환율"),
        _fetch_yfinance_indicator(name="GOLD", symbol="GC=F", note="국제 금 선물", prefix="$"),
        _fetch_yfinance_indicator(name="WTI", symbol="CL=F", note="서부텍사스산 원유", prefix="$"),
    ]


def load_latest_recommendations(limit: int = 5) -> tuple[list[Recommendation], str | None]:
    if not DB_PATH.exists():
        return [], f"DB 파일을 찾을 수 없습니다: {DB_PATH}"

    try:
        with sqlite3.connect(DB_PATH) as connection:
            connection.row_factory = sqlite3.Row
            latest = connection.execute(
                "SELECT MAX(created_at) AS created_at FROM recommendations"
            ).fetchone()
            latest_created_at = latest["created_at"] if latest else None
            if not latest_created_at:
                return [], None

            rows = connection.execute(
                """
                SELECT run_date, market, ticker, name, rank, score, reason, theme, created_at
                FROM recommendations
                WHERE created_at = ?
                ORDER BY rank ASC, score DESC
                LIMIT ?
                """,
                (latest_created_at, limit),
            ).fetchall()
    except sqlite3.Error as exc:
        return [], f"DB 조회 실패: {exc}"

    return [
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
    ], None


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_market_card(item: dict, index: int) -> str:
    wide_class = " market-card-wide" if index == 0 else ""
    direction = "up" if item.get("direction") == "up" else "down"
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
    return f"""
      <article class="stock-card{featured_class}">
        <div class="card-top">
          <div>
            <h3>{esc(item.name)}</h3>
            <p>{esc(item.ticker)}</p>
          </div>
          <span class="score">{item.score:.1f}점</span>
        </div>
        <div class="stock-meta">
          <div><span>순위</span><strong>{item.rank}</strong></div>
          <div><span>시장</span><strong>{esc(item.market)}</strong></div>
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


def render_dashboard() -> str:
    recommendations, db_error = load_latest_recommendations()
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
        else render_empty_card("표시할 최신 추천 데이터가 없습니다.")
    )
    db_notice = f'<div class="db-notice">{esc(db_error)}</div>' if db_error else ""

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
      .market-grid, .stock-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .market-card-wide {{ grid-column: span 2; }}
    }}
    @media (max-width: 560px) {{
      .shell {{ width: min(100% - 18px, 930px); padding-top: 9px; }}
      .hero, .section {{ padding: 18px; }}
      .section-head {{ align-items: flex-start; flex-direction: column; }}
      .market-grid, .stock-grid {{ grid-template-columns: 1fr; }}
      .market-card-wide {{ grid-column: span 1; }}
      .market-card-wide .market-value-row strong {{ font-size: 38px; }}
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
        <span>최신 저장시각: <strong>{esc(latest_run)}</strong></span>
      </div>
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
          <span class="badge">live data / fallback</span>
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
def dashboard() -> HTMLResponse:
    return HTMLResponse(render_dashboard())
