"""Swing 전략 1차 백테스트 실행 스크립트."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from config import SETTINGS
from stock_screener import SAMPLE_STOCKS, _build_sample_ohlcv, _normalize_ohlcv, _select_real_symbols
from strategies import evaluate_swing_strategy, prepare_indicators


@dataclass
class BacktestConfig:
    strategy: str
    mode: str
    start: date
    end: date
    max_symbols: int
    take_profit_pct: float
    stop_loss_pct: float
    hold_days: int


def parse_args() -> BacktestConfig:
    """명령줄 인자를 읽어 백테스트 설정으로 변환한다."""
    parser = argparse.ArgumentParser(description="국내주식 swing 전략 백테스트")
    parser.add_argument("--strategy", default="swing", choices=["swing"], help="현재는 swing 전략만 지원")
    parser.add_argument("--mode", default=SETTINGS.default_mode, choices=["real", "sample"], help="데이터 모드")
    parser.add_argument("--start", required=True, help="백테스트 시작일 (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="백테스트 종료일 (YYYY-MM-DD)")
    parser.add_argument("--max-symbols", type=int, default=SETTINGS.max_symbols, help="조회할 최대 종목 수")
    parser.add_argument(
        "--take-profit",
        type=float,
        default=SETTINGS.backtest_take_profit_pct,
        help="익절 퍼센트",
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        default=SETTINGS.backtest_stop_loss_pct,
        help="손절 퍼센트",
    )
    parser.add_argument(
        "--hold-days",
        type=int,
        default=SETTINGS.backtest_hold_days,
        help="최대 보유 거래일 수",
    )
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    if start > end:
        raise ValueError("시작일이 종료일보다 늦을 수 없습니다.")

    return BacktestConfig(
        strategy=args.strategy,
        mode=args.mode,
        start=start,
        end=end,
        max_symbols=args.max_symbols,
        take_profit_pct=args.take_profit,
        stop_loss_pct=args.stop_loss,
        hold_days=args.hold_days,
    )


def _load_real_symbols(max_symbols: int) -> list[tuple[str, str]]:
    """실데이터 모드에서 조회 대상 종목 목록을 만든다."""
    try:
        import FinanceDataReader as fdr
    except Exception as exc:
        raise RuntimeError(f"FinanceDataReader import 실패: {exc}") from exc

    listing_df = fdr.StockListing("KRX")
    symbols = _select_real_symbols(listing_df).head(max_symbols)
    return [(str(row.Code).zfill(6), str(row.Name)) for row in symbols.itertuples(index=False)]


def _load_real_ohlcv(ticker: str, start: date, end: date) -> pd.DataFrame:
    """실데이터 OHLCV를 정규화한다."""
    try:
        import FinanceDataReader as fdr
    except Exception as exc:
        raise RuntimeError(f"FinanceDataReader import 실패: {exc}") from exc

    # 기준일 이전에도 이동평균이 필요하므로 여유 구간을 더 가져온다.
    fetch_start = start - timedelta(days=SETTINGS.history_calendar_days)
    raw = fdr.DataReader(ticker, fetch_start, end)
    if raw is None or raw.empty:
        raise ValueError("OHLCV 데이터가 비어 있습니다.")
    return _normalize_ohlcv(raw)


def _load_sample_symbols(max_symbols: int) -> list[tuple[str, str]]:
    """샘플 모드에서 사용할 종목 목록."""
    return [(item["ticker"], item["name"]) for item in SAMPLE_STOCKS[:max_symbols]]


def _load_sample_ohlcv(ticker: str) -> pd.DataFrame:
    """샘플 모드 OHLCV 생성."""
    profile = next((item["profile"] for item in SAMPLE_STOCKS if item["ticker"] == ticker), "swing")
    return _build_sample_ohlcv(seed=int(ticker[-3:]), profile=profile)


def _simulate_exit(
    raw_df: pd.DataFrame,
    entry_index: int,
    take_profit_pct: float,
    stop_loss_pct: float,
    hold_days: int,
) -> tuple[int, pd.Timestamp, float, float, str]:
    """익절/손절/기간만료 조건으로 청산 지점을 계산한다.

    같은 날 손절과 익절이 모두 걸리면 보수적으로 손절을 우선 적용한다.
    """
    entry_price = float(raw_df.iloc[entry_index]["시가"])
    stop_price = entry_price * (1 - stop_loss_pct / 100)
    target_price = entry_price * (1 + take_profit_pct / 100)
    last_index = min(entry_index + hold_days - 1, len(raw_df) - 1)

    for idx in range(entry_index, last_index + 1):
        row = raw_df.iloc[idx]
        low_price = float(row["저가"])
        high_price = float(row["고가"])

        if low_price <= stop_price:
            return idx, raw_df.index[idx], stop_price, ((stop_price / entry_price) - 1) * 100, "stop_loss"
        if high_price >= target_price:
            return idx, raw_df.index[idx], target_price, ((target_price / entry_price) - 1) * 100, "take_profit"

    exit_price = float(raw_df.iloc[last_index]["종가"])
    return last_index, raw_df.index[last_index], exit_price, ((exit_price / entry_price) - 1) * 100, "time_exit"


def backtest_symbol(ticker: str, name: str, raw_df: pd.DataFrame, cfg: BacktestConfig) -> list[dict[str, Any]]:
    """단일 종목에 대해 swing 신호를 과거 날짜 기준으로 평가한다."""
    prepared_df = prepare_indicators(raw_df)
    trades: list[dict[str, Any]] = []

    pointer = SETTINGS.min_history_rows - 1
    while pointer < len(prepared_df) - 1:
        trade_date = prepared_df.index[pointer]
        if trade_date.date() < cfg.start:
            pointer += 1
            continue
        if trade_date.date() > cfg.end:
            break

        sliced_df = prepared_df.iloc[: pointer + 1]
        candidate = evaluate_swing_strategy(ticker, name, sliced_df)
        if candidate is None:
            pointer += 1
            continue

        entry_index = pointer + 1
        exit_index, exit_date, exit_price, return_pct, exit_reason = _simulate_exit(
            raw_df=raw_df,
            entry_index=entry_index,
            take_profit_pct=cfg.take_profit_pct,
            stop_loss_pct=cfg.stop_loss_pct,
            hold_days=cfg.hold_days,
        )
        entry_price = float(raw_df.iloc[entry_index]["시가"])
        holding_days = exit_index - entry_index + 1

        trades.append(
            {
                "ticker": ticker,
                "name": name,
                "signal_date": str(trade_date.date()),
                "entry_date": str(raw_df.index[entry_index].date()),
                "exit_date": str(exit_date.date()),
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "return_pct": round(return_pct, 2),
                "holding_days": int(holding_days),
                "exit_reason": exit_reason,
                "signal_score": int(candidate["total_score"]),
                "box_high": candidate.get("box_high", 0),
                "box_low": candidate.get("box_low", 0),
                "box_range_pct": candidate.get("box_range_pct", 0),
                "vcp_score": candidate.get("vcp_score", 0),
                "reason": candidate["reason"],
            }
        )

        # 같은 종목에서 중첩 포지션을 만들지 않기 위해 청산일까지 건너뛴다.
        pointer = exit_index + 1

    return trades


def _build_summary(trades: list[dict[str, Any]], cfg: BacktestConfig, errors: list[dict[str, str]]) -> dict[str, Any]:
    """거래 내역으로 요약 성과를 계산한다."""
    config_payload = asdict(cfg)
    config_payload["start"] = cfg.start.isoformat()
    config_payload["end"] = cfg.end.isoformat()

    if not trades:
        return {
            "config": config_payload,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trade_count": 0,
            "win_rate_pct": 0.0,
            "avg_return_pct": 0.0,
            "cumulative_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "errors": errors,
        }

    trade_df = pd.DataFrame(trades).sort_values(["entry_date", "ticker"]).reset_index(drop=True)
    returns = trade_df["return_pct"].astype(float)
    equity_curve = (1 + returns / 100).cumprod()
    rolling_max = equity_curve.cummax()
    drawdown = ((equity_curve / rolling_max) - 1) * 100

    summary = {
        "config": config_payload,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trade_count": int(len(trade_df)),
        "win_rate_pct": round(float((returns > 0).mean() * 100), 2),
        "avg_return_pct": round(float(returns.mean()), 2),
        "cumulative_return_pct": round(float((equity_curve.iloc[-1] - 1) * 100), 2),
        "max_drawdown_pct": round(float(drawdown.min()), 2),
        "avg_holding_days": round(float(trade_df["holding_days"].mean()), 2),
        "errors": errors,
    }
    return summary


def save_backtest_outputs(trades: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    """CSV와 JSON으로 백테스트 결과를 저장한다."""
    pd.DataFrame(trades).to_csv(
        SETTINGS.backtest_results_csv_path,
        index=False,
        encoding="utf-8-sig",
    )
    with open(SETTINGS.backtest_summary_json_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)


def run_backtest(cfg: BacktestConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """모든 대상 종목을 순회하며 백테스트를 실행한다."""
    if cfg.mode == "real":
        symbols = _load_real_symbols(cfg.max_symbols)
        data_loader = lambda ticker: _load_real_ohlcv(ticker, cfg.start, cfg.end)
    else:
        symbols = _load_sample_symbols(cfg.max_symbols)
        data_loader = _load_sample_ohlcv

    all_trades: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for ticker, name in symbols:
        try:
            raw_df = data_loader(ticker)
            trades = backtest_symbol(ticker, name, raw_df, cfg)
            all_trades.extend(trades)
        except Exception as exc:
            errors.append({"ticker": ticker, "name": name, "error": str(exc)})

    summary = _build_summary(all_trades, cfg, errors)
    return all_trades, summary


def print_summary(summary: dict[str, Any]) -> None:
    """콘솔용 요약 출력."""
    print("[백테스트 요약]")
    print(f"전략: {summary['config']['strategy']}")
    print(f"모드: {summary['config']['mode']}")
    print(f"거래 수: {summary['trade_count']}")
    print(f"승률: {summary['win_rate_pct']}%")
    print(f"평균 수익률: {summary['avg_return_pct']}%")
    print(f"누적 수익률: {summary['cumulative_return_pct']}%")
    print(f"최대 낙폭(MDD): {summary['max_drawdown_pct']}%")
    print(f"평균 보유일: {summary.get('avg_holding_days', 0)}일")
    print(f"CSV 저장: {SETTINGS.backtest_results_csv_path}")
    print(f"JSON 저장: {SETTINGS.backtest_summary_json_path}")
    if summary["errors"]:
        print(f"오류 종목 수: {len(summary['errors'])}")


def main() -> None:
    cfg = parse_args()
    trades, summary = run_backtest(cfg)
    save_backtest_outputs(trades, summary)
    print_summary(summary)


if __name__ == "__main__":
    main()
