"""Regression tests for strategy score calculations."""

from __future__ import annotations

import unittest

import pandas as pd

from strategies import _passes_downside_risk_filter, _score_risk_reward


class RiskRewardScoreTests(unittest.TestCase):
    @staticmethod
    def _metrics(close: float = 100.0) -> dict:
        return {"latest": pd.Series({"종가": close})}

    def test_short_target_uses_actual_six_percent_reward(self) -> None:
        score = _score_risk_reward(
            self._metrics(),
            stop_price=96.0,
            target_price=106.0,
        )

        self.assertEqual(score, 7)

    def test_fallback_short_target_does_not_receive_twelve_percent_score(self) -> None:
        score = _score_risk_reward(
            self._metrics(),
            stop_price=96.0,
            target_price=105.0,
        )

        self.assertEqual(score, 4)

    def test_twelve_percent_target_keeps_high_reward_score(self) -> None:
        score = _score_risk_reward(
            self._metrics(),
            stop_price=95.5,
            target_price=112.0,
        )

        self.assertEqual(score, 10)

    def test_non_profitable_target_is_rejected(self) -> None:
        score = _score_risk_reward(
            self._metrics(),
            stop_price=95.0,
            target_price=100.0,
        )

        self.assertEqual(score, 0)


class DownsideRiskFilterTests(unittest.TestCase):
    def test_rejects_large_daily_drop(self) -> None:
        metrics = {
            "daily_change_pct": -4.5,
            "gap_pct": -1.0,
            "candle_body_pct": -2.0,
        }

        self.assertFalse(_passes_downside_risk_filter(metrics, -4.0))

    def test_rejects_large_gap_down(self) -> None:
        metrics = {
            "daily_change_pct": -2.0,
            "gap_pct": -3.5,
            "candle_body_pct": 1.0,
        }

        self.assertFalse(_passes_downside_risk_filter(metrics, -4.0))

    def test_accepts_orderly_pullback(self) -> None:
        metrics = {
            "daily_change_pct": -1.5,
            "gap_pct": -0.5,
            "candle_body_pct": -1.0,
        }

        self.assertTrue(_passes_downside_risk_filter(metrics, -3.0))


if __name__ == "__main__":
    unittest.main()
