"""실데이터 또는 샘플 데이터로 국내주식 후보를 선별합니다."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from config import SETTINGS
from news_analyzer import analyze_stock_news, enrich_candidate_with_news
from strategies import (
    evaluate_mid_fallback,
    evaluate_mid_strategy,
    evaluate_short_fallback,
    evaluate_short_strategy,
    evaluate_swing_fallback,
    evaluate_swing_strategy,
    prepare_indicators,
)

VALID_STRATEGIES = ("short", "swing", "mid")


SAMPLE_STOCKS: list[dict[str, str]] = [
    {"ticker": "005930", "name": "삼성전자", "profile": "mid"},
    {"ticker": "000660", "name": "SK하이닉스", "profile": "mid"},
    {"ticker": "035420", "name": "NAVER", "profile": "swing"},
    {"ticker": "035720", "name": "카카오", "profile": "swing"},
    {"ticker": "005380", "name": "현대차", "profile": "mid"},
    {"ticker": "012330", "name": "현대모비스", "profile": "mid"},
    {"ticker": "068270", "name": "셀트리온", "profile": "swing"},
    {"ticker": "105560", "name": "KB금융", "profile": "mid"},
    {"ticker": "207940", "name": "삼성바이오로직스", "profile": "mid"},
    {"ticker": "034020", "name": "두산에너빌리티", "profile": "short"},
]

FALLBACK_REAL_STOCKS: list[dict[str, str]] = [
    {"Code": "005930", "Name": "삼성전자"},
    {"Code": "000660", "Name": "SK하이닉스"},
    {"Code": "009150", "Name": "삼성전기"},
    {"Code": "011070", "Name": "LG이노텍"},
    {"Code": "017670", "Name": "SK텔레콤"},
    {"Code": "034730", "Name": "SK"},
    {"Code": "402340", "Name": "SK스퀘어"},
    {"Code": "006260", "Name": "LS"},
    {"Code": "105560", "Name": "KB금융"},
    {"Code": "055550", "Name": "신한지주"},
    {"Code": "086790", "Name": "하나금융지주"},
    {"Code": "000810", "Name": "삼성화재"},
    {"Code": "032830", "Name": "삼성생명"},
    {"Code": "021240", "Name": "코웨이"},
    {"Code": "033780", "Name": "KT&G"},
    {"Code": "259960", "Name": "크래프톤"},
    {"Code": "353200", "Name": "대덕전자"},
    {"Code": "034020", "Name": "두산에너빌리티"},
    {"Code": "035420", "Name": "NAVER"},
    {"Code": "035720", "Name": "카카오"},
    {"Code": "005380", "Name": "현대차"},
    {"Code": "012330", "Name": "현대모비스"},
    {"Code": "068270", "Name": "셀트리온"},
    {"Code": "207940", "Name": "삼성바이오로직스"},
]


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """FinanceDataReader 일봉을 전략 입력 형식으로 바꿉니다."""
    data = df.copy()
    rename_map = {
        "Open": "시가",
        "High": "고가",
        "Low": "저가",
        "Close": "종가",
        "Volume": "거래량",
    }
    data = data.rename(columns=rename_map)

    if "거래량" not in data.columns:
        raise ValueError("거래량 컬럼이 없습니다.")

    if "거래대금" in data.columns:
        pass
    elif "Value" in data.columns:
        data["거래대금"] = data["Value"]
    elif "Amount" in data.columns:
        data["거래대금"] = data["Amount"]
    else:
        # FDR에는 거래대금이 없을 수 있으므로 종가*거래량으로 근사합니다.
        data["거래대금"] = data["종가"] * data["거래량"]

    required = ["시가", "고가", "저가", "종가", "거래량", "거래대금"]
    data = data[required].dropna().copy()
    data["거래량"] = pd.to_numeric(data["거래량"], errors="coerce")
    data["거래대금"] = pd.to_numeric(data["거래대금"], errors="coerce")
    data["시가"] = pd.to_numeric(data["시가"], errors="coerce")
    data["고가"] = pd.to_numeric(data["고가"], errors="coerce")
    data["저가"] = pd.to_numeric(data["저가"], errors="coerce")
    data["종가"] = pd.to_numeric(data["종가"], errors="coerce")
    data = data.dropna()
    return data


def _build_sample_ohlcv(seed: int, profile: str) -> pd.DataFrame:
    """샘플 모드용 일봉 데이터를 생성합니다."""
    dates = pd.bdate_range(end=datetime.today().date(), periods=SETTINGS.min_history_rows + 25)
    rows: list[dict[str, int]] = []
    base_price = 12000 + (seed % 9) * 2500
    base_volume = 180_000 + (seed % 7) * 40_000

    close = float(base_price)
    for idx, current_date in enumerate(dates):
        drift = 0.003
        volume_factor = 1.0
        intraday_range = 0.02

        if profile == "short" and idx >= len(dates) - 3:
            drift = 0.03
            volume_factor = 2.4
            intraday_range = 0.018
        elif profile == "swing" and idx >= len(dates) - 5:
            drift = 0.015
            volume_factor = 1.8
            intraday_range = 0.017
        elif profile == "mid":
            drift = 0.0045
            volume_factor = 1.1

        close = round(close * (1 + drift), 0)
        open_price = round(close * (1 - intraday_range * 0.35), 0)
        high = round(close * (1 + intraday_range), 0)
        low = round(close * (1 - intraday_range * 0.9), 0)
        volume = round(base_volume * volume_factor + idx * 1500 + seed * 900, 0)

        rows.append(
            {
                "날짜": current_date,
                "시가": max(int(open_price), 1000),
                "고가": max(int(high), 1000),
                "저가": max(int(low), 1000),
                "종가": max(int(close), 1000),
                "거래량": max(int(volume), 10000),
                "거래대금": max(int(close * volume), 1_000_000),
            }
        )

    return pd.DataFrame(rows).set_index("날짜")


def _evaluate_dataframe(
    ticker: str,
    name: str,
    raw_df: pd.DataFrame,
    strategy_filter: str | None = None,
) -> list[dict[str, Any]]:
    """일봉 데이터 하나를 세 전략으로 평가합니다."""
    results: list[dict[str, Any]] = []
    df = prepare_indicators(raw_df)
    evaluator_map = {
        "short": (evaluate_short_strategy, evaluate_short_fallback),
        "swing": (evaluate_swing_strategy, evaluate_swing_fallback),
        "mid": (evaluate_mid_strategy, evaluate_mid_fallback),
    }
    evaluator_pairs = (
        (evaluate_short_strategy, evaluate_short_fallback),
        (evaluate_swing_strategy, evaluate_swing_fallback),
        (evaluate_mid_strategy, evaluate_mid_fallback),
    )
    if strategy_filter:
        evaluator_pairs = (evaluator_map[strategy_filter],)

    for primary_evaluator, fallback_evaluator in evaluator_pairs:
        try:
            candidate = primary_evaluator(ticker, name, df)
            if candidate is None:
                candidate = fallback_evaluator(ticker, name, df)
            if candidate:
                results.append(candidate)
        except Exception as exc:
            results.append(
                {
                    "strategy": "error",
                    "name": name,
                    "ticker": ticker,
                    "error": f"{primary_evaluator.__name__}: {exc}",
                }
            )

    return results


def _select_real_symbols(listing_df: pd.DataFrame) -> pd.DataFrame:
    """KRX 상장 종목 중 실데이터 조회 대상을 줄입니다."""
    data = listing_df.copy()
    if "Market" in data.columns:
        data = data[data["Market"].isin(["KOSPI", "KOSDAQ"])]

    code_column = None
    for candidate in ("Symbol", "Code"):
        if candidate in data.columns:
            code_column = candidate
            break

    if code_column is None or "Name" not in data.columns:
        raise ValueError("StockListing 결과에 Code/Symbol 또는 Name 컬럼이 없습니다.")

    if "Marcap" in data.columns:
        data["Marcap"] = pd.to_numeric(data["Marcap"], errors="coerce").fillna(0)
        data = data.sort_values("Marcap", ascending=False)

    data = data.drop_duplicates(subset=[code_column]).head(SETTINGS.max_symbols)
    data = data[[code_column, "Name"]].copy()
    data.columns = ["Code", "Name"]
    return data.reset_index(drop=True)


def _fallback_real_symbols() -> pd.DataFrame:
    """KRX listing endpoint 장애 시 사용하는 보수적인 대형주 후보군입니다."""
    return pd.DataFrame(FALLBACK_REAL_STOCKS).head(SETTINGS.max_symbols)


def _append_flat_row(flat_results: list[dict[str, Any]], strategy_name: str, row: dict[str, Any]) -> None:
    """CSV 저장용 행을 추가합니다."""
    flat_results.append(
        {
            "strategy": strategy_name,
            "name": row["name"],
            "ticker": row["ticker"],
            "current_price": row["current_price"],
            "change_pct": row["change_pct"],
            "trading_value": row["trading_value"],
            "total_score": row["total_score"],
            "techniques": row["techniques"],
            "reason": row["reason"],
            "stop_loss": row["stop_loss"],
            "target_price": row["target_price"],
            "caution": row["caution"],
            "score_liquidity": row["score_liquidity"],
            "score_volume": row["score_volume"],
            "score_trend": row["score_trend"],
            "score_breakout": row["score_breakout"],
            "score_box": row["score_box"],
            "score_vcp": row["score_vcp"],
            "score_risk": row["score_risk"],
            "score_overheat": row["score_overheat"],
            "box_high": row.get("box_high", 0),
            "box_low": row.get("box_low", 0),
            "box_range_pct": row.get("box_range_pct", 0),
            "vcp_score": row.get("vcp_score", 0),
            "theme": row.get("theme", ""),
            "recent_news_keywords": row.get("recent_news_keywords", ""),
            "issue_summary": row.get("issue_summary", ""),
            "news_score": row.get("news_score", 0),
        }
    )


def _run_real_screening(
    strategy_filter: str | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    """FinanceDataReader 실데이터로 종목을 선별합니다."""
    try:
        import FinanceDataReader as fdr
    except Exception as exc:
        raise RuntimeError(f"FinanceDataReader import 실패: {exc}") from exc

    try:
        listing_df = fdr.StockListing("KRX")
        target_symbols = _select_real_symbols(listing_df)
    except Exception as exc:
        print(f"KRX 종목 목록 조회 실패, fallback 후보군 사용: {exc}")
        target_symbols = _fallback_real_symbols()
    if target_symbols.empty:
        raise RuntimeError("KRX 종목 목록이 비어 있습니다.")

    end_date = datetime.today().date()
    start_date = end_date - timedelta(days=SETTINGS.history_calendar_days)

    strategy_results: dict[str, list[dict[str, Any]]] = {
        "short": [],
        "swing": [],
        "mid": [],
    }
    errors: list[dict[str, Any]] = []

    for row in target_symbols.itertuples(index=False):
        ticker = str(row.Code).zfill(6)
        name = str(row.Name)

        try:
            fetched = fdr.DataReader(ticker, start_date, end_date)
        except Exception as exc:
            errors.append(
                {
                    "strategy": "error",
                    "name": name,
                    "ticker": ticker,
                    "error": f"DataReader 실패: {exc}",
                }
            )
            continue

        if fetched is None or fetched.empty:
            errors.append(
                {
                    "strategy": "error",
                    "name": name,
                    "ticker": ticker,
                    "error": "DataReader 결과가 비어 있습니다.",
                }
            )
            continue

        try:
            normalized = _normalize_ohlcv(fetched)
        except Exception as exc:
            errors.append(
                {
                    "strategy": "error",
                    "name": name,
                    "ticker": ticker,
                    "error": f"OHLCV 정규화 실패: {exc}",
                }
            )
            continue

        ticker_results = _evaluate_dataframe(ticker, name, normalized, strategy_filter=strategy_filter)
        if any(item.get("strategy") != "error" for item in ticker_results):
            news_info = analyze_stock_news(name, ticker=ticker)
        else:
            news_info = None

        for item in ticker_results:
            if item.get("strategy") == "error":
                errors.append(item)
                continue
            if news_info is not None:
                if news_info.get("news_error"):
                    errors.append(
                        {
                            "strategy": "error",
                            "name": name,
                            "ticker": ticker,
                            "error": f"뉴스 조회 실패: {news_info['news_error']}",
                        }
                    )
                item = enrich_candidate_with_news(item, news_info)
            strategy_results[item["strategy"]].append(item)

    flat_results: list[dict[str, Any]] = []
    for strategy_name, items in strategy_results.items():
        items.sort(key=lambda row: row["total_score"], reverse=True)
        for row in items:
            _append_flat_row(flat_results, strategy_name, row)

    return strategy_results, flat_results, errors


def _run_sample_screening(
    strategy_filter: str | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    """샘플 모드입니다."""
    strategy_results: dict[str, list[dict[str, Any]]] = {
        "short": [],
        "swing": [],
        "mid": [],
    }
    errors: list[dict[str, Any]] = []

    for stock_info in SAMPLE_STOCKS:
        raw_df = _build_sample_ohlcv(seed=int(stock_info["ticker"][-3:]), profile=stock_info["profile"])
        ticker_results = _evaluate_dataframe(
            stock_info["ticker"],
            stock_info["name"],
            raw_df,
            strategy_filter=strategy_filter,
        )
        for item in ticker_results:
            if item.get("strategy") == "error":
                errors.append(item)
                continue
            item = enrich_candidate_with_news(
                item,
                {
                    "theme": "기타",
                    "recent_news_keywords": [],
                    "issue_summary": "샘플 모드에서는 실시간 뉴스 분석을 사용하지 않습니다.",
                    "news_score": 0,
                    "news_error": "",
                },
            )
            strategy_results[item["strategy"]].append(item)

    flat_results: list[dict[str, Any]] = []
    for strategy_name, items in strategy_results.items():
        items.sort(key=lambda row: row["total_score"], reverse=True)
        for row in items:
            _append_flat_row(flat_results, strategy_name, row)

    return strategy_results, flat_results, errors


def run_screening(
    mode: str = "real",
    strategy_filter: str | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    """실데이터 또는 샘플 데이터로 스크리닝합니다."""
    selected_mode = (mode or SETTINGS.default_mode).lower()
    if strategy_filter is not None and strategy_filter not in VALID_STRATEGIES:
        raise ValueError(f"지원하지 않는 전략입니다: {strategy_filter}")
    if selected_mode == "sample":
        return _run_sample_screening(strategy_filter=strategy_filter)
    if selected_mode == "real":
        return _run_real_screening(strategy_filter=strategy_filter)
    raise ValueError(f"지원하지 않는 mode 입니다: {mode}")


def save_results_to_csv(rows: list[dict[str, Any]]) -> None:
    """최종 후보 결과를 CSV로 저장합니다."""
    pd.DataFrame(rows).to_csv(SETTINGS.results_csv_path, index=False, encoding="utf-8-sig")
