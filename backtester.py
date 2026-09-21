"""현재 기술적 추천 로직을 과거 날짜별로 재실행하는 워크포워드 백테스트."""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from config import SETTINGS
from main import _build_final_recommendations
from performance_tracker import calculate_tracking_performance
from stock_screener import (
    SAMPLE_STOCKS,
    _attach_listing_metadata,
    _build_sample_ohlcv,
    _evaluate_dataframe,
    _load_listing_metadata,
    _normalize_ohlcv,
    _select_real_symbols,
)


HORIZONS = (5, 10, 20)
DEFAULT_OUTPUT_DIR = Path("data") / "backtests"


@dataclass
class BacktestConfig:
    mode: str
    start: date
    end: date
    max_symbols: int
    output_dir: Path = DEFAULT_OUTPUT_DIR


def parse_args() -> BacktestConfig:
    parser = argparse.ArgumentParser(description="현재 기술적 추천 로직 워크포워드 백테스트")
    parser.add_argument("--mode", default="real", choices=["real", "sample"])
    parser.add_argument("--start", help="신호 시작일 (YYYY-MM-DD)")
    parser.add_argument("--end", help="신호 종료일 (YYYY-MM-DD), 기본값 오늘")
    parser.add_argument("--days", type=int, default=183, help="시작일 미지정 시 달력 기준 조회 일수 (기본 183일, 약 6개월)")
    parser.add_argument("--max-symbols", type=int, default=SETTINGS.max_symbols)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else date.today()
    start = (
        datetime.strptime(args.start, "%Y-%m-%d").date()
        if args.start
        else end - timedelta(days=max(1, args.days))
    )
    if start > end:
        raise ValueError("시작일이 종료일보다 늦을 수 없습니다.")
    return BacktestConfig(
        mode=args.mode,
        start=start,
        end=end,
        max_symbols=max(1, args.max_symbols),
        output_dir=Path(args.output_dir),
    )


def _technical_only(candidate: dict[str, Any], symbol: dict[str, str]) -> dict[str, Any]:
    """뉴스를 완전히 제외하고 상장 분류만 후보에 붙입니다."""
    return {
        **candidate,
        "theme": "기타",
        "recent_news_keywords": "",
        "issue_summary": "기술적 분석 전용 백테스트",
        "news_score": 0,
        "theme_score": 0,
        "news_relevance": "NONE",
        "news_items": [],
        "listing_sector": symbol.get("sector", ""),
        "listing_industry": symbol.get("industry", ""),
        "industry_raw": symbol.get("sector", "") or symbol.get("industry", ""),
    }


def _real_symbols(max_symbols: int) -> list[dict[str, str]]:
    import FinanceDataReader as fdr

    listing = fdr.StockListing("KRX")
    symbols = _select_real_symbols(listing).head(max_symbols)
    try:
        symbols = _attach_listing_metadata(symbols, _load_listing_metadata(fdr))
    except Exception as exc:
        print(f"[backtest] KRX 업종 메타데이터 없이 진행: {exc}")

    return [
        {
            "ticker": str(row.Code).zfill(6),
            "name": str(row.Name),
            "market": str(getattr(row, "Market", "KOSPI") or "KOSPI"),
            "sector": str(getattr(row, "Sector", "") or "").strip(),
            "industry": str(getattr(row, "Industry", "") or "").strip(),
        }
        for row in symbols.itertuples(index=False)
    ]


def _sample_symbols(max_symbols: int) -> list[dict[str, str]]:
    return [
        {
            "ticker": item["ticker"],
            "name": item["name"],
            "market": "KOSPI",
            "sector": "",
            "industry": "",
        }
        for item in SAMPLE_STOCKS[:max_symbols]
    ]


def _load_market_data(
    cfg: BacktestConfig,
    symbols: list[dict[str, str]],
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame | None], list[dict[str, str]]]:
    """이동평균용 과거 구간과 현재까지의 사후 성과 구간을 한 번만 조회합니다."""
    histories: dict[str, pd.DataFrame] = {}
    errors: list[dict[str, str]] = []

    if cfg.mode == "sample":
        for symbol in symbols:
            profile = next(
                (item["profile"] for item in SAMPLE_STOCKS if item["ticker"] == symbol["ticker"]),
                "swing",
            )
            histories[symbol["ticker"]] = _build_sample_ohlcv(
                seed=int(symbol["ticker"][-3:]),
                profile=profile,
            )
        return histories, {"KOSPI": None, "KOSDAQ": None}, errors

    import FinanceDataReader as fdr

    fetch_start = cfg.start - timedelta(days=SETTINGS.history_calendar_days)
    outcome_end = min(date.today(), cfg.end + timedelta(days=45))
    benchmarks: dict[str, pd.DataFrame | None] = {"KOSPI": None, "KOSDAQ": None}
    for market, ticker in (("KOSPI", "KS11"), ("KOSDAQ", "KQ11")):
        try:
            benchmarks[market] = fdr.DataReader(ticker, fetch_start, outcome_end)
        except Exception as exc:
            errors.append({"ticker": ticker, "name": market, "error": f"기준지수 조회 실패: {exc}"})

    for index, symbol in enumerate(symbols, start=1):
        ticker = symbol["ticker"]
        try:
            raw = fdr.DataReader(ticker, fetch_start, outcome_end)
            if raw is None or raw.empty:
                raise ValueError("OHLCV 데이터가 비어 있습니다.")
            histories[ticker] = _normalize_ohlcv(raw)
        except Exception as exc:
            errors.append({"ticker": ticker, "name": symbol["name"], "error": str(exc)})
        if index % 50 == 0 or index == len(symbols):
            print(f"[backtest] 시세 조회 {index}/{len(symbols)}")
    return histories, benchmarks, errors


def _signal_dates(histories: dict[str, pd.DataFrame], cfg: BacktestConfig) -> list[pd.Timestamp]:
    dates: set[pd.Timestamp] = set()
    for history in histories.values():
        for index in history.loc[str(cfg.start) : str(cfg.end)].index:
            dates.add(pd.Timestamp(index).normalize())
    return sorted(dates)


def _market_key(symbol: dict[str, str]) -> str:
    return "KOSDAQ" if symbol.get("market", "").startswith("KOSDAQ") else "KOSPI"


def _build_daily_selection(
    signal_date: pd.Timestamp,
    symbols: list[dict[str, str]],
    histories: dict[str, pd.DataFrame],
    benchmarks: dict[str, pd.DataFrame | None],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    strategy_results: dict[str, list[dict[str, Any]]] = {"short": [], "swing": [], "mid": []}
    errors: list[dict[str, str]] = []

    for symbol in symbols:
        history = histories.get(symbol["ticker"])
        if history is None or history.empty:
            continue
        sliced = history.loc[:signal_date]
        if sliced.empty or pd.Timestamp(sliced.index[-1]).normalize() != signal_date:
            continue

        benchmark = benchmarks.get(_market_key(symbol))
        benchmark_slice = benchmark.loc[:signal_date] if benchmark is not None else None
        results = _evaluate_dataframe(
            symbol["ticker"],
            symbol["name"],
            sliced,
            benchmark_df=benchmark_slice,
        )
        for candidate in results:
            if candidate.get("strategy") == "error":
                errors.append(
                    {
                        "ticker": symbol["ticker"],
                        "name": symbol["name"],
                        "error": candidate.get("error", "전략 평가 실패"),
                    }
                )
                continue
            strategy_results[candidate["strategy"]].append(_technical_only(candidate, symbol))

    # 운영 코드의 상세 분류 로그만 숨기고 점수·등급·분산선정 로직은 그대로 사용합니다.
    with redirect_stdout(io.StringIO()):
        final_groups = _build_final_recommendations(strategy_results)
    return final_groups["selected"], errors


def _return_pct(reference: float, value: float) -> float:
    return round((value / reference - 1) * 100, 4)


def _benchmark_returns(
    benchmark: pd.DataFrame | None,
    entry_date: pd.Timestamp,
) -> dict[str, float | None]:
    result = {f"benchmark_d{h}_return_pct": None for h in HORIZONS}
    if benchmark is None or benchmark.empty:
        return result
    close_column = "종가" if "종가" in benchmark.columns else "Close"
    if close_column not in benchmark.columns:
        return result

    future = benchmark.loc[benchmark.index >= entry_date]
    if future.empty:
        return result
    entry_close = float(future.iloc[0][close_column])
    for horizon in HORIZONS:
        if len(future) >= horizon:
            result[f"benchmark_d{horizon}_return_pct"] = _return_pct(
                entry_close,
                float(future.iloc[horizon - 1][close_column]),
            )
    return result


def _measure_selection(
    candidate: dict[str, Any],
    raw_df: pd.DataFrame,
    benchmark: pd.DataFrame | None,
    signal_date: pd.Timestamp,
    rank: int,
) -> dict[str, Any] | None:
    positions = raw_df.index.get_indexer([signal_date])
    if len(positions) != 1 or positions[0] < 0 or positions[0] + 1 >= len(raw_df):
        return None
    entry_index = int(positions[0]) + 1
    entry_row = raw_df.iloc[entry_index]
    entry_date = pd.Timestamp(raw_df.index[entry_index])
    entry_price = float(entry_row["시가"])
    forward = raw_df.iloc[entry_index : entry_index + max(HORIZONS)]
    observations = [
        {
            "date": pd.Timestamp(index).date().isoformat(),
            "high": float(row["고가"]),
            "low": float(row["저가"]),
            "close": float(row["종가"]),
        }
        for index, row in forward.iterrows()
    ]
    performance = calculate_tracking_performance(
        reference_price=entry_price,
        reference_date=pd.Timestamp(signal_date).date().isoformat(),
        observations=observations,
        target_price=candidate.get("target_price"),
        stop_price=candidate.get("stop_loss"),
    )
    benchmark_metrics = _benchmark_returns(benchmark, entry_date)
    excess_metrics: dict[str, float | None] = {}
    for horizon in HORIZONS:
        stock_return = performance.get(f"d{horizon}_return_pct")
        market_return = benchmark_metrics.get(f"benchmark_d{horizon}_return_pct")
        excess_metrics[f"d{horizon}_excess_return_pct"] = (
            round(float(stock_return) - float(market_return), 4)
            if stock_return is not None and market_return is not None
            else None
        )

    return {
        "signal_date": pd.Timestamp(signal_date).date().isoformat(),
        "entry_date": entry_date.date().isoformat(),
        "rank": rank,
        "ticker": candidate["ticker"],
        "name": candidate["name"],
        "sector": candidate.get("sector_group", "미분류"),
        "strategy": candidate.get("strategy_type", ""),
        "grade": candidate.get("grade", ""),
        "score": candidate.get("recommendation_score", 0),
        "signal_close": candidate.get("current_price"),
        "entry_price": round(entry_price, 2),
        "stop_price": candidate.get("stop_loss"),
        "target_price": candidate.get("target_price"),
        **performance,
        **benchmark_metrics,
        **excess_metrics,
    }


def _metric_summary(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    if not values:
        return {"sample_count": 0, "win_rate_pct": None, "average_pct": None, "median_pct": None}
    return {
        "sample_count": len(values),
        "win_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 2),
        "average_pct": round(sum(values) / len(values), 2),
        "median_pct": round(median(values), 2),
    }


def _group_summary(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key) or "미분류"), []).append(row)
    return {
        name: {
            "signal_count": len(items),
            "d5": _metric_summary(items, "d5_return_pct"),
            "d10": _metric_summary(items, "d10_return_pct"),
            "d20": _metric_summary(items, "d20_return_pct"),
        }
        for name, items in sorted(grouped.items())
    }


def _build_summary(
    rows: list[dict[str, Any]],
    cfg: BacktestConfig,
    signal_days: int,
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    config = asdict(cfg)
    config["start"] = cfg.start.isoformat()
    config["end"] = cfg.end.isoformat()
    config["output_dir"] = str(cfg.output_dir)
    return {
        "method": "technical_only_walk_forward",
        "news_score": 0,
        "entry_rule": "신호 다음 거래일 시가",
        "universe_note": "현재 KRX 상장목록의 시가총액·거래대금 기준 유니버스",
        "config": config,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "signal_days": signal_days,
        "signal_count": len(rows),
        "unique_tickers": len({row["ticker"] for row in rows}),
        "average_picks_per_day": round(len(rows) / signal_days, 2) if signal_days else 0,
        "d5": _metric_summary(rows, "d5_return_pct"),
        "d10": _metric_summary(rows, "d10_return_pct"),
        "d20": _metric_summary(rows, "d20_return_pct"),
        "d5_excess": _metric_summary(rows, "d5_excess_return_pct"),
        "d10_excess": _metric_summary(rows, "d10_excess_return_pct"),
        "d20_excess": _metric_summary(rows, "d20_excess_return_pct"),
        "mfe": _metric_summary(rows, "mfe_pct"),
        "mae": _metric_summary(rows, "mae_pct"),
        "target_first_count": sum(row.get("first_exit") == "TARGET_FIRST" for row in rows),
        "stop_first_count": sum(row.get("first_exit") == "STOP_FIRST" for row in rows),
        "same_day_count": sum(row.get("first_exit") == "SAME_DAY" for row in rows),
        "open_count": sum(row.get("first_exit") == "OPEN" for row in rows),
        "by_strategy": _group_summary(rows, "strategy"),
        "by_grade": _group_summary(rows, "grade"),
        "error_count": len(errors),
        "errors": errors,
    }


def run_backtest(cfg: BacktestConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    symbols = _real_symbols(cfg.max_symbols) if cfg.mode == "real" else _sample_symbols(cfg.max_symbols)
    histories, benchmarks, errors = _load_market_data(cfg, symbols)
    dates = _signal_dates(histories, cfg)
    rows: list[dict[str, Any]] = []
    symbol_by_ticker = {symbol["ticker"]: symbol for symbol in symbols}

    for index, signal_date in enumerate(dates, start=1):
        selected, daily_errors = _build_daily_selection(
            signal_date,
            symbols,
            histories,
            benchmarks,
        )
        errors.extend(daily_errors)
        for rank, candidate in enumerate(selected, start=1):
            symbol = symbol_by_ticker[candidate["ticker"]]
            measured = _measure_selection(
                candidate,
                histories[candidate["ticker"]],
                benchmarks.get(_market_key(symbol)),
                signal_date,
                rank,
            )
            if measured:
                rows.append(measured)
        print(
            f"[backtest] 신호일 {index}/{len(dates)} "
            f"{signal_date.date()} · 선정 {len(selected)}개"
        )

    summary = _build_summary(rows, cfg, len(dates), errors)
    return rows, summary


def save_backtest_outputs(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "technical_backtest_latest.csv"
    json_path = output_dir / "technical_backtest_latest.json"
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return csv_path, json_path


def _format_metric(metric: dict[str, Any]) -> str:
    if not metric.get("sample_count"):
        return "표본 없음"
    return (
        f"표본 {metric['sample_count']}건 / 승률 {metric['win_rate_pct']}% / "
        f"평균 {metric['average_pct']:+.2f}% / 중앙값 {metric['median_pct']:+.2f}%"
    )


def print_summary(summary: dict[str, Any], csv_path: Path, json_path: Path) -> None:
    print("[기술적 로직 워크포워드 백테스트]")
    print(f"신호 기간: {summary['config']['start']} ~ {summary['config']['end']}")
    print(f"뉴스 점수: {summary['news_score']}점 고정")
    print(f"신호일: {summary['signal_days']}일 / 추천 기록: {summary['signal_count']}건")
    for horizon in HORIZONS:
        print(f"D+{horizon}: {_format_metric(summary[f'd{horizon}'])}")
        print(f"D+{horizon} 시장초과: {_format_metric(summary[f'd{horizon}_excess'])}")
    print(f"MFE: {_format_metric(summary['mfe'])}")
    print(f"MAE: {_format_metric(summary['mae'])}")
    print("[전략별]")
    for strategy, metrics in summary["by_strategy"].items():
        print(
            f"{strategy}: 신호 {metrics['signal_count']}건 / "
            f"D+5 {_format_metric(metrics['d5'])} / "
            f"D+10 {_format_metric(metrics['d10'])} / "
            f"D+20 {_format_metric(metrics['d20'])}"
        )
    print(
        "목표/손절 선도달: "
        f"목표 {summary['target_first_count']} / 손절 {summary['stop_first_count']} / "
        f"동일일 {summary['same_day_count']} / 미도달 {summary['open_count']}"
    )
    print(f"오류: {summary['error_count']}건")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")


def main() -> None:
    cfg = parse_args()
    rows, summary = run_backtest(cfg)
    csv_path, json_path = save_backtest_outputs(rows, summary, cfg.output_dir)
    print_summary(summary, csv_path, json_path)


if __name__ == "__main__":
    main()
