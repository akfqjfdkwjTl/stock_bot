"""Focused tests for the technical-only walk-forward backtester."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from backtester import (
    BacktestConfig,
    _build_summary,
    _measure_selection,
    _technical_only,
)


def _history() -> pd.DataFrame:
    dates = pd.bdate_range("2026-08-03", periods=21)
    rows = []
    for index, _current in enumerate(dates):
        rows.append(
            {
                "시가": 100 if index else 99,
                "고가": 101 + index,
                "저가": 99,
                "종가": 100 + index,
                "거래량": 1000,
                "거래대금": 100000,
            }
        )
    return pd.DataFrame(rows, index=dates)


def _candidate() -> dict:
    return {
        "ticker": "005930",
        "name": "삼성전자",
        "sector_group": "반도체",
        "strategy_type": "mid",
        "grade": "B",
        "recommendation_score": 65,
        "current_price": 100,
        "stop_loss": 95,
        "target_price": 110,
    }


class TechnicalBacktesterTests(unittest.TestCase):
    def test_next_session_open_is_entry_and_horizons_use_forward_sessions(self) -> None:
        history = _history()
        benchmark = pd.DataFrame(
            {"Close": [100 + index * 0.5 for index in range(len(history))]},
            index=history.index,
        )

        row = _measure_selection(
            _candidate(),
            history,
            benchmark,
            history.index[0],
            1,
        )

        self.assertEqual(row["entry_date"], "2026-08-04")
        self.assertEqual(row["entry_price"], 100)
        self.assertEqual(row["d5_return_pct"], 5.0)
        self.assertEqual(row["d10_return_pct"], 10.0)
        self.assertEqual(row["d20_return_pct"], 20.0)
        self.assertEqual(row["first_exit"], "TARGET_FIRST")
        self.assertIsNotNone(row["d5_excess_return_pct"])

    def test_same_day_target_and_stop_does_not_guess_order(self) -> None:
        history = _history()
        history.iloc[1, history.columns.get_loc("고가")] = 112
        history.iloc[1, history.columns.get_loc("저가")] = 88

        row = _measure_selection(
            _candidate(),
            history,
            None,
            history.index[0],
            1,
        )

        self.assertEqual(row["first_exit"], "SAME_DAY")

    def test_news_fields_are_forced_to_zero(self) -> None:
        candidate = {"ticker": "005930", "news_score": 9, "theme": "AI"}
        result = _technical_only(
            candidate,
            {"sector": "반도체", "industry": "반도체 제조업"},
        )

        self.assertEqual(result["news_score"], 0)
        self.assertEqual(result["theme_score"], 0)
        self.assertEqual(result["news_relevance"], "NONE")

    def test_summary_excludes_unfinished_horizons_from_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = BacktestConfig(
                mode="sample",
                start=date(2026, 8, 1),
                end=date(2026, 8, 31),
                max_symbols=10,
                output_dir=Path(directory),
            )
            summary = _build_summary(
                [
                    {"ticker": "005930", "strategy": "mid", "grade": "B", "d5_return_pct": 2.0},
                    {"ticker": "000660", "strategy": "mid", "grade": "관찰", "d5_return_pct": None},
                ],
                cfg,
                signal_days=20,
                errors=[],
            )

        self.assertEqual(summary["signal_count"], 2)
        self.assertEqual(summary["d5"]["sample_count"], 1)
        self.assertEqual(summary["d5"]["win_rate_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
