"""Tests for the web view of persisted technical backtest results."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class BacktestPageTests(unittest.TestCase):
    def test_load_backtest_report_reads_json_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary_path = root / "summary.json"
            rows_path = root / "rows.csv"
            summary_path.write_text(
                json.dumps({"signal_count": 1, "config": {"start": "2026-08-18", "end": "2026-09-18"}}),
                encoding="utf-8",
            )
            rows_path.write_text(
                "signal_date,rank,ticker,name\n2026-09-17,1,005930,삼성전자\n",
                encoding="utf-8-sig",
            )

            summary, rows, error = app.load_backtest_report(summary_path, rows_path)

        self.assertIsNone(error)
        self.assertEqual(summary["signal_count"], 1)
        self.assertEqual(rows[0]["ticker"], "005930")

    def test_missing_report_has_clear_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary, rows, error = app.load_backtest_report(
                root / "missing.json",
                root / "missing.csv",
            )

        self.assertEqual(summary, {})
        self.assertEqual(rows, [])
        self.assertIn("아직 생성된 백테스트 결과", error)

    def test_backtest_route_renders_summary_and_detail(self) -> None:
        summary = {
            "generated_at": "2026-09-18 17:10:00",
            "config": {"start": "2026-08-19", "end": "2026-09-18", "max_symbols": 300},
            "signal_days": 22,
            "signal_count": 1,
            "unique_tickers": 1,
            "average_picks_per_day": 0.05,
            "d5": {"sample_count": 1, "win_rate_pct": 100, "average_pct": 3.2, "median_pct": 3.2},
            "d10": {},
            "d20": {},
            "d20_excess": {},
            "mfe": {},
            "mae": {},
            "by_strategy": {},
            "by_grade": {},
        }
        rows = [{
            "signal_date": "2026-09-10",
            "entry_date": "2026-09-11",
            "ticker": "005930",
            "name": "삼성전자",
            "sector": "반도체",
            "grade": "B",
            "strategy": "mid",
            "score": "65",
            "entry_price": "100000",
            "d5_return_pct": "3.2",
            "first_exit": "OPEN",
        }]

        with patch("app.load_backtest_report", return_value=(summary, rows, None)):
            response = app.backtest()

        self.assertEqual(response.status_code, 200)
        body = response.body.decode("utf-8")
        self.assertIn("1개월 기술적 백테스트", body)
        self.assertIn("삼성전자", body)
        self.assertIn("D+5 평균 수익률", body)


if __name__ == "__main__":
    unittest.main()
