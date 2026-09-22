"""Regression tests for strategy score calculations."""

from __future__ import annotations

import unittest

import pandas as pd

from stock_screener import _build_sample_ohlcv, _market_regime_is_favorable
from strategies import (
    _calculate_common_metrics,
    _passes_downside_risk_filter,
    _score_breakout,
    _score_relative_strength,
    _score_risk_reward,
    _score_vcp,
    attach_relative_strength,
    diagnose_strategy_filters,
    prepare_indicators,
)


class TechnicalStrengthScoreTests(unittest.TestCase):
    def test_invalid_zero_open_price_is_rejected(self) -> None:
        prepared = prepare_indicators(_build_sample_ohlcv(seed=500, profile="mid"))
        prepared.loc[prepared.index[-1], "시가"] = 0

        self.assertIsNone(_calculate_common_metrics(prepared))

    def test_market_regime_requires_rising_20_and_60_day_trend(self) -> None:
        dates = pd.bdate_range("2026-01-01", periods=80)
        rising = pd.DataFrame({"Close": range(100, 180)}, index=dates)
        falling = pd.DataFrame({"Close": range(180, 100, -1)}, index=dates)

        self.assertTrue(_market_regime_is_favorable(rising))
        self.assertFalse(_market_regime_is_favorable(falling))

    def test_52week_high_proximity_reuses_breakout_bucket(self) -> None:
        metrics = {
            "latest": pd.Series({"종가": 96.0}),
            "high60": 120.0,
            "box_high": 120.0,
            "high52_ratio": 0.96,
        }

        self.assertEqual(_score_breakout(metrics), 8)

    def test_relative_strength_ignores_latest_day_spike(self) -> None:
        dates = pd.bdate_range("2026-01-01", periods=150)
        market_close = pd.Series(range(100, 250), index=dates, dtype=float)
        stock_close = market_close.copy()
        stock_close.iloc[-1] *= 2
        stock = pd.DataFrame({"종가": stock_close}, index=dates)
        market = pd.DataFrame({"Close": market_close}, index=dates)

        result = attach_relative_strength(stock, market).iloc[-1]

        self.assertAlmostEqual(result["rs_1m"], 0.0)
        self.assertAlmostEqual(result["rs_3m"], 0.0)
        self.assertAlmostEqual(result["rs_6m"], 0.0)

    def test_persistent_relative_strength_receives_all_period_points(self) -> None:
        metrics = {"rs_1m": 2.0, "rs_3m": 3.0, "rs_6m": 5.0}

        self.assertEqual(_score_relative_strength(metrics), 10)

    def test_near_zero_relative_strength_does_not_receive_points(self) -> None:
        metrics = {"rs_1m": 0.01, "rs_3m": 0.01, "rs_6m": 0.01}

        self.assertEqual(_score_relative_strength(metrics), 0)

    def test_vcp_adds_volume_contraction_inside_existing_bucket(self) -> None:
        metrics = {
            "recent_volatility": 1.0,
            "previous_volatility": 2.0,
            "staged_contraction": True,
            "volume_contraction": True,
        }

        self.assertEqual(_score_vcp(metrics), 12)


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

    def test_symbol_diagnostic_exposes_required_fields(self) -> None:
        prepared = prepare_indicators(_build_sample_ohlcv(seed=500, profile="mid"))

        result = diagnose_strategy_filters("000500", "가온전선", prepared)

        for field in (
            "technical_filter",
            "trend",
            "liquidity",
            "setup_score",
            "entry_score",
            "risk_penalty",
            "risk_filter",
            "failure_reason",
            "strategies",
        ):
            self.assertIn(field, result)


if __name__ == "__main__":
    unittest.main()
