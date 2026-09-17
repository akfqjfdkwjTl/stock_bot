"""Focused tests for tracked-stock forward performance."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from performance_tracker import calculate_tracking_performance


def _observations(count: int = 20) -> list[dict]:
    start = date(2026, 9, 1)
    return [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "close": 100 + index,
            "high": 101 + index,
            "low": 99 + index,
        }
        for index in range(count + 1)
    ]


class TrackingPerformanceTests(unittest.TestCase):
    def test_period_returns_and_excursions_use_sessions_after_reference_date(self) -> None:
        result = calculate_tracking_performance(
            reference_price=100,
            reference_date="2026-09-01",
            observations=_observations(),
        )

        self.assertEqual(result["d5_return_pct"], 5.0)
        self.assertEqual(result["d10_return_pct"], 10.0)
        self.assertEqual(result["d20_return_pct"], 20.0)
        self.assertEqual(result["mfe_pct"], 21.0)
        self.assertEqual(result["mae_pct"], 0.0)
        self.assertEqual(result["observed_sessions"], 20)
        self.assertEqual(result["first_exit"], "NOT_SET")

    def test_target_first_is_detected(self) -> None:
        result = calculate_tracking_performance(
            reference_price=100,
            reference_date="2026-09-01",
            observations=_observations(8),
            target_price=105,
            stop_price=95,
        )

        self.assertEqual(result["target_hit_date"], "2026-09-05")
        self.assertIsNone(result["stop_hit_date"])
        self.assertEqual(result["first_exit"], "TARGET_FIRST")

    def test_stop_first_is_detected(self) -> None:
        observations = [
            {"date": "2026-09-01", "close": 100, "high": 101, "low": 99},
            {"date": "2026-09-02", "close": 96, "high": 100, "low": 94},
            {"date": "2026-09-03", "close": 106, "high": 107, "low": 96},
        ]
        result = calculate_tracking_performance(
            reference_price=100,
            reference_date="2026-09-01",
            observations=observations,
            target_price=105,
            stop_price=95,
        )

        self.assertEqual(result["first_exit"], "STOP_FIRST")

    def test_same_day_touch_does_not_guess_intraday_order(self) -> None:
        observations = [
            {"date": "2026-09-01", "close": 100, "high": 101, "low": 99},
            {"date": "2026-09-02", "close": 100, "high": 106, "low": 94},
        ]
        result = calculate_tracking_performance(
            reference_price=100,
            reference_date="2026-09-01",
            observations=observations,
            target_price=105,
            stop_price=95,
        )

        self.assertEqual(result["first_exit"], "SAME_DAY")
        self.assertEqual(result["target_hit_date"], "2026-09-02")
        self.assertEqual(result["stop_hit_date"], "2026-09-02")

    def test_unfinished_periods_are_none(self) -> None:
        result = calculate_tracking_performance(
            reference_price=100,
            reference_date="2026-09-01",
            observations=_observations(4),
        )

        self.assertIsNone(result["d5_return_pct"])
        self.assertIsNone(result["d10_return_pct"])
        self.assertIsNone(result["d20_return_pct"])


if __name__ == "__main__":
    unittest.main()
