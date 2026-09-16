"""실데이터 또는 샘플 데이터로 국내주식 후보를 선별합니다."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from config import SETTINGS
from news_analyzer import analyze_stock_news, enrich_candidate_with_news
from strategies import (
    attach_relative_strength,
    evaluate_mid_fallback,
    evaluate_mid_strategy,
    evaluate_short_fallback,
    evaluate_short_strategy,
    evaluate_swing_fallback,
    evaluate_swing_strategy,
    diagnose_strategy_filters,
    prepare_indicators,
)

VALID_STRATEGIES = ("short", "swing", "mid")
_LISTING_METADATA_CACHE: pd.DataFrame | None = None


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
    benchmark_df: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """일봉 데이터 하나를 세 전략으로 평가합니다."""
    results: list[dict[str, Any]] = []
    df = prepare_indicators(raw_df)
    df = attach_relative_strength(df, benchmark_df)
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


def _normalize_listing_symbols(listing_df: pd.DataFrame) -> pd.DataFrame:
    """KRX 목록을 KOSPI·KOSDAQ 보통 종목 조회에 필요한 형태로 정리합니다."""
    data = listing_df.copy()
    if "Market" in data.columns:
        market_names = data["Market"].fillna("").astype(str).str.strip()
        data = data[market_names.str.startswith(("KOSPI", "KOSDAQ"))]

    code_column = None
    for candidate in ("Symbol", "Code"):
        if candidate in data.columns:
            code_column = candidate
            break

    if code_column is None or "Name" not in data.columns:
        raise ValueError("StockListing 결과에 Code/Symbol 또는 Name 컬럼이 없습니다.")

    data = data.drop_duplicates(subset=[code_column])
    selected_columns = [code_column, "Name"]
    selected_columns.extend(
        column
        for column in ("Market", "Sector", "Industry", "Marcap", "Amount")
        if column in data.columns
    )
    data = data[selected_columns].copy()
    data = data.rename(columns={code_column: "Code"})
    if "Market" not in data.columns:
        data["Market"] = "KOSPI"
    data["Market"] = data["Market"].fillna("KOSPI").astype(str).str.strip()
    for column in ("Sector", "Industry"):
        if column not in data.columns:
            data[column] = ""
        data[column] = data[column].fillna("").astype(str).str.strip()
    data["Code"] = data["Code"].astype(str).str.zfill(6)
    return data.reset_index(drop=True)


def _select_real_symbols(listing_df: pd.DataFrame) -> pd.DataFrame:
    """시가총액 중심 후보에 거래대금 상위 종목을 보완해 자동추천 대상을 고릅니다."""
    data = _normalize_listing_symbols(listing_df)
    limit = max(1, SETTINGS.max_symbols)

    if "Marcap" not in data.columns:
        return data.head(limit).reset_index(drop=True)

    data["Marcap"] = pd.to_numeric(data["Marcap"], errors="coerce").fillna(0)
    market_cap_limit = max(1, (limit * 2) // 3)
    market_cap_symbols = data.sort_values("Marcap", ascending=False).head(market_cap_limit)

    if "Amount" not in data.columns or market_cap_limit >= limit:
        selected = data.sort_values("Marcap", ascending=False).head(limit)
        return selected.reset_index(drop=True)

    data["Amount"] = pd.to_numeric(data["Amount"], errors="coerce").fillna(0)
    active_symbols = data[~data["Code"].isin(market_cap_symbols["Code"])].sort_values(
        ["Amount", "Marcap"], ascending=False
    )
    selected = pd.concat(
        [market_cap_symbols, active_symbols.head(limit - market_cap_limit)],
        ignore_index=True,
    )
    return selected.reset_index(drop=True)


def _attach_listing_metadata(symbols: pd.DataFrame, description_df: pd.DataFrame) -> pd.DataFrame:
    """가격 중심 KRX 목록에 KRX-DESC 업종과 주요제품 정보를 결합합니다."""
    description = description_df.copy()
    code_column = next(
        (column for column in ("Symbol", "Code") if column in description.columns),
        None,
    )
    if code_column is None:
        raise ValueError("KRX-DESC 결과에 Code/Symbol 컬럼이 없습니다.")
    for column in ("Sector", "Industry"):
        if column not in description.columns:
            description[column] = ""
    description = description[[code_column, "Sector", "Industry"]].rename(
        columns={code_column: "Code"}
    )
    description["Code"] = description["Code"].astype(str).str.zfill(6)
    description = description.drop_duplicates(subset=["Code"])
    base = symbols.drop(columns=["Sector", "Industry"], errors="ignore")
    merged = base.merge(description, on="Code", how="left")
    for column in ("Sector", "Industry"):
        merged[column] = merged[column].fillna("").astype(str).str.strip()
    return merged


def _load_listing_metadata(fdr: Any) -> pd.DataFrame:
    """느린 KRX-DESC 조회는 프로세스 수명 동안 한 번만 수행합니다."""
    global _LISTING_METADATA_CACHE
    if _LISTING_METADATA_CACHE is None:
        _LISTING_METADATA_CACHE = fdr.StockListing("KRX-DESC")
    return _LISTING_METADATA_CACHE.copy()


def _fallback_real_symbols() -> pd.DataFrame:
    """KRX listing endpoint 장애 시 사용하는 보수적인 대형주 후보군입니다."""
    data = pd.DataFrame(FALLBACK_REAL_STOCKS).head(SETTINGS.max_symbols)
    data["Market"] = "KOSPI"
    data["Sector"] = ""
    data["Industry"] = ""
    return data


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
            "score_rs": row["score_rs"],
            "score_risk": row["score_risk"],
            "score_overheat": row["score_overheat"],
            "box_high": row.get("box_high", 0),
            "box_low": row.get("box_low", 0),
            "box_range_pct": row.get("box_range_pct", 0),
            "vcp_score": row.get("vcp_score", 0),
            "high52_ratio": row.get("high52_ratio", 0),
            "high52_distance_pct": row.get("high52_distance_pct", 0),
            "rs_1m": row.get("rs_1m", 0),
            "rs_3m": row.get("rs_3m", 0),
            "rs_6m": row.get("rs_6m", 0),
            "volume_contraction_ratio": row.get("volume_contraction_ratio", 0),
            "volume_contraction": row.get("volume_contraction", False),
            "pivot_ready": row.get("pivot_ready", False),
            "theme": row.get("theme", ""),
            "recent_news_keywords": row.get("recent_news_keywords", ""),
            "issue_summary": row.get("issue_summary", ""),
            "news_score": row.get("news_score", 0),
            "news_relevance": row.get("news_relevance", "NONE"),
            "listing_sector": row.get("listing_sector", ""),
            "listing_industry": row.get("listing_industry", ""),
            "industry_raw": row.get("industry_raw", row.get("listing_sector", "") or row.get("listing_industry", "")),
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
        try:
            description_df = _load_listing_metadata(fdr)
            target_symbols = _attach_listing_metadata(target_symbols, description_df)
        except Exception as exc:
            print(f"KRX 업종 메타데이터 조회 실패, 기본 분류 사용: {exc}")
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
    benchmarks: dict[str, pd.DataFrame | None] = {"KOSPI": None, "KOSDAQ": None}
    for market, symbol in (("KOSPI", "KS11"), ("KOSDAQ", "KQ11")):
        try:
            benchmarks[market] = fdr.DataReader(symbol, start_date, end_date)
        except Exception as exc:
            print(f"{market} RS 기준지수 조회 실패, RS 점수 제외: {exc}")

    for row in target_symbols.itertuples(index=False):
        ticker = str(row.Code).zfill(6)
        name = str(row.Name)
        listing_sector = str(getattr(row, "Sector", "") or "").strip()
        listing_industry = str(getattr(row, "Industry", "") or "").strip()
        market = str(getattr(row, "Market", "KOSPI") or "KOSPI").strip()

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

        ticker_results = _evaluate_dataframe(
            ticker,
            name,
            normalized,
            strategy_filter=strategy_filter,
            benchmark_df=benchmarks.get("KOSDAQ" if market.startswith("KOSDAQ") else "KOSPI"),
        )
        for item in ticker_results:
            if item.get("strategy") != "error":
                item["listing_sector"] = listing_sector
                item["listing_industry"] = listing_industry
                item["industry_raw"] = listing_sector or listing_industry

        if any(item.get("strategy") != "error" for item in ticker_results):
            news_info = analyze_stock_news(
                name,
                ticker=ticker,
                sector=listing_sector,
                industry=listing_industry,
            )
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


def debug_symbol(ticker_or_name: str) -> dict[str, Any]:
    """자동추천 대상 여부와 무관하게 특정 종목을 끝까지 진단합니다."""
    import FinanceDataReader as fdr

    query = str(ticker_or_name or "").strip()
    listing_df = fdr.StockListing("KRX")
    all_symbols = _normalize_listing_symbols(listing_df)
    target_symbols = _select_real_symbols(listing_df)

    code_query = query.zfill(6) if query.isdigit() else ""
    mask = all_symbols["Code"].eq(code_query) if code_query else all_symbols["Name"].eq(query)
    matched = all_symbols[mask]
    if matched.empty:
        return {
            "query": query,
            "found": False,
            "universe_included": False,
            "failure_reason": "KOSPI·KOSDAQ 상장 종목에서 찾지 못했습니다. 종목명 또는 6자리 코드를 확인해 주세요.",
        }

    try:
        matched = _attach_listing_metadata(matched, _load_listing_metadata(fdr))
    except Exception:
        pass

    row = matched.iloc[0]
    ticker = str(row["Code"]).zfill(6)
    name = str(row["Name"])
    listing_sector = str(row.get("Sector", "") or "").strip()
    listing_industry = str(row.get("Industry", "") or "").strip()
    end_date = datetime.today().date()
    start_date = end_date - timedelta(days=SETTINGS.history_calendar_days)
    fetched = fdr.DataReader(ticker, start_date, end_date)
    normalized = _normalize_ohlcv(fetched)
    market = str(row.get("Market", "KOSPI") or "KOSPI").strip()
    benchmark_symbol = "KQ11" if market.startswith("KOSDAQ") else "KS11"
    try:
        benchmark = fdr.DataReader(benchmark_symbol, start_date, end_date)
    except Exception:
        benchmark = None
    prepared = attach_relative_strength(prepare_indicators(normalized), benchmark)
    diagnostic = diagnose_strategy_filters(ticker, name, prepared)
    news_info = analyze_stock_news(
        name,
        ticker=ticker,
        sector=listing_sector,
        industry=listing_industry,
    )
    direct_candidates: list[dict[str, Any]] = []
    for candidate in _evaluate_dataframe(
        ticker,
        name,
        normalized,
        benchmark_df=benchmark,
    ):
        if candidate.get("strategy") == "error":
            continue
        candidate["listing_sector"] = listing_sector
        candidate["listing_industry"] = listing_industry
        candidate["industry_raw"] = listing_sector or listing_industry
        direct_candidates.append(enrich_candidate_with_news(candidate, news_info))

    universe_included = ticker in set(target_symbols["Code"].astype(str).str.zfill(6))
    return {
        "query": query,
        "found": True,
        "universe_included": universe_included,
        "universe_description": (
            f"시가총액 중심 {max(1, (SETTINGS.max_symbols * 2) // 3)}개와 "
            f"거래대금 상위 보완 종목을 합친 최대 {SETTINGS.max_symbols}개"
        ),
        "current_price": float(prepared.iloc[-1]["종가"]),
        "price_date": pd.Timestamp(prepared.index[-1]).date().isoformat(),
        "listing_sector": listing_sector,
        "listing_industry": listing_industry,
        "diagnostic": diagnostic,
        "news": news_info,
        "candidates": direct_candidates,
    }


def save_results_to_csv(rows: list[dict[str, Any]]) -> None:
    """최종 후보 결과를 CSV로 저장합니다."""
    pd.DataFrame(rows).to_csv(SETTINGS.results_csv_path, index=False, encoding="utf-8-sig")
