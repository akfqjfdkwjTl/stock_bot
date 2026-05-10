"""시장 지표 JSON 생성 스크립트."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests


OUTPUT_PATH = Path("market-data.json")

YAHOO_CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
FEAR_GREED_URL = "https://www.finhacker.cz/en/fear-and-greed-index-historical-data-and-chart/"


@dataclass(frozen=True)
class MarketSymbol:
    key: str
    label: str
    symbol: str
    value_format: str
    note: str


MARKET_SYMBOLS = [
    MarketSymbol("fear_index", "공포지수", "CNN Fear & Greed", "number", "미국 증시 투자 심리 지표"),
    MarketSymbol("kospi", "코스피", "^KS11", "index", "국내 대형주 전반 흐름"),
    MarketSymbol("kosdaq", "코스닥", "^KQ11", "index", "성장주와 테마주 흐름"),
    MarketSymbol("nasdaq", "나스닥", "^IXIC", "index", "미국 기술주 선호 흐름"),
    MarketSymbol("sp500", "S&P 500", "^GSPC", "index", "미국 증시 전반 기준 지수"),
    MarketSymbol("usdkrw", "달러/원", "KRW=X", "fx", "원달러 환율 흐름"),
    MarketSymbol("oil", "유가", "CL=F", "commodity_usd", "WTI 기준 에너지 가격"),
    MarketSymbol("copper", "구리 지수", "HG=F", "commodity_usd", "구리 선물 기준 산업 금속 분위기"),
    MarketSymbol("gold", "금", "GC=F", "commodity_usd", "금 선물 기준 안전자산 흐름"),
]


def _make_session() -> requests.Session:
    """로컬 프록시 환경의 영향을 받지 않는 세션."""
    session = requests.Session()
    session.trust_env = False
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/html,application/xhtml+xml,*/*",
            "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
        }
    )
    return session


def _format_value(value: float, value_format: str) -> str:
    if value_format == "fx":
        return f"{value:,.2f}"
    if value_format == "commodity_usd":
        return f"${value:,.2f}"
    if value_format == "number":
        return f"{value:.0f}"
    return f"{value:,.1f}"


def _build_change_text(change_pct: float, symbol_key: str) -> str:
    if symbol_key == "fear_index":
        if change_pct >= 5:
            return "Greed"
        if change_pct <= -5:
            return "Fear"
        return "Neutral"
    sign = "+" if change_pct > 0 else ""
    return f"{sign}{change_pct:.2f}%"


def _fetch_yahoo_pair(session: requests.Session, symbol: str) -> tuple[float, float]:
    params = {
        "range": "1mo",
        "interval": "1d",
        "includeAdjustedClose": "true",
    }
    response = session.get(
        YAHOO_CHART_URL.format(symbol=symbol),
        params=params,
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()

    result = payload.get("chart", {}).get("result") or []
    if not result:
        raise ValueError(f"{symbol} 응답이 비어 있습니다.")

    quote = result[0].get("indicators", {}).get("quote", [{}])[0]
    closes = [float(value) for value in quote.get("close", []) if value is not None]
    if len(closes) < 2:
        raise ValueError(f"{symbol} 최근 종가가 충분하지 않습니다.")

    return closes[-1], closes[-2]


def _fetch_fear_and_greed(session: requests.Session) -> dict:
    """CNN Fear & Greed 현재 점수를 공개 페이지에서 파싱한다."""
    response = session.get(FEAR_GREED_URL, timeout=20)
    response.raise_for_status()
    text = response.text

    updated_match = re.search(
        r"Data updated:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s*[AP]M\s*ET)",
        text,
    )
    current_match = re.search(
        r"The current value of the Fear\s*&\s*Greed Index .*? is .*?<strong>(\d{1,3})</strong>\s*\(([^)]+)\)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not current_match:
        raise ValueError("Fear & Greed 현재 값을 찾지 못했습니다.")

    score = float(current_match.group(1))
    rating = current_match.group(2).strip().title()
    updated_at = updated_match.group(1) if updated_match else ""

    return {
        "value": score,
        "display_value": str(int(score)),
        "change_pct": None,
        "change_text": rating,
        "note_suffix": updated_at,
    }


def build_market_payload() -> dict:
    session = _make_session()
    items: list[dict] = []

    for market in MARKET_SYMBOLS:
        try:
            if market.key == "fear_index":
                fear_payload = _fetch_fear_and_greed(session)
                note = market.note
                if fear_payload["note_suffix"]:
                    note = f"{note} / 기준: {fear_payload['note_suffix']}"

                items.append(
                    {
                        "key": market.key,
                        "label": market.label,
                        "symbol": market.symbol,
                        "value": fear_payload["value"],
                        "display_value": fear_payload["display_value"],
                        "change_pct": fear_payload["change_pct"],
                        "change_text": fear_payload["change_text"],
                        "note": note,
                    }
                )
                continue

            latest, previous = _fetch_yahoo_pair(session, market.symbol)
            change_pct = ((latest / previous) - 1) * 100 if previous else 0.0

            items.append(
                {
                    "key": market.key,
                    "label": market.label,
                    "symbol": market.symbol,
                    "value": latest,
                    "display_value": _format_value(latest, market.value_format),
                    "change_pct": round(change_pct, 2),
                    "change_text": _build_change_text(change_pct, market.key),
                    "note": market.note,
                }
            )
        except Exception as exc:
            items.append(
                {
                    "key": market.key,
                    "label": market.label,
                    "symbol": market.symbol,
                    "value": None,
                    "display_value": "-",
                    "change_pct": None,
                    "change_text": "조회 실패",
                    "note": f"{market.note} / 오류: {exc}",
                }
            )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
    }


def main() -> None:
    payload = build_market_payload()
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"시장 지표 JSON 저장 완료: {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()
