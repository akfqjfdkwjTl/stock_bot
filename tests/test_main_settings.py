"""Tests for settings-driven recommendation behavior."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch


def _install_import_stub(module_name: str, **attributes: object) -> None:
    module = types.ModuleType(module_name)
    for name, value in attributes.items():
        setattr(module, name, value)
    sys.modules.setdefault(module_name, module)


_install_import_stub(
    "dashboard_capture",
    capture_dashboard=lambda *args, **kwargs: None,
    refresh_market_json=lambda *args, **kwargs: None,
    save_dashboard_data=lambda *args, **kwargs: None,
)
_install_import_stub("db", save_recommendations=lambda *args, **kwargs: 0)
_install_import_stub(
    "stock_screener",
    run_screening=lambda *args, **kwargs: ({}, [], []),
    save_results_to_csv=lambda *args, **kwargs: None,
)
_install_import_stub(
    "telegram_sender",
    send_telegram_message=lambda *args, **kwargs: (False, None),
    send_telegram_photo=lambda *args, **kwargs: (False, None),
)

from config import SETTINGS
from main import (
    UNCLASSIFIED_SECTOR,
    _build_strategy_recommendations,
    _can_add_candidate,
    _grade_for_score,
    _resolve_master_classification,
)


class RecommendationSettingsTests(unittest.TestCase):
    def test_grade_thresholds_come_from_settings(self) -> None:
        with (
            patch.object(SETTINGS, "grade_a_threshold", 75),
            patch.object(SETTINGS, "grade_b_threshold", 55),
        ):
            self.assertEqual(_grade_for_score(75), "A")
            self.assertEqual(_grade_for_score(74.9), "B")
            self.assertEqual(_grade_for_score(54.9), "관찰")

    def test_sector_limit_comes_from_settings(self) -> None:
        candidate = {
            "ticker": "000002",
            "sector_group": "반도체",
            "industry_group": "반도체",
        }
        selected = [{"ticker": "000001"}]
        sector_counts = {"반도체": 1}
        industry_counts = {"반도체": 1}

        with patch.object(SETTINGS, "max_per_sector", 1):
            self.assertFalse(
                _can_add_candidate(
                    candidate,
                    selected,
                    sector_counts,
                    industry_counts,
                )
            )

        with patch.object(SETTINGS, "max_per_sector", 2):
            self.assertTrue(
                _can_add_candidate(
                    candidate,
                    selected,
                    sector_counts,
                    industry_counts,
                )
            )

    def test_strategy_result_count_comes_from_settings(self) -> None:
        items = [
            {
                "ticker": f"{index:06d}",
                "name": f"종목{index}",
                "current_price": 1000,
                "theme": "테스트",
                "issue_summary": "테스트",
                "total_score": 50,
            }
            for index in range(4)
        ]

        with patch.object(SETTINGS, "top_n_per_strategy", 2):
            result = _build_strategy_recommendations({"short": items}, "short")

        self.assertEqual(len(result), 2)


    def test_unknown_stock_news_theme_is_not_used_as_sector(self) -> None:
        sector, industry, themes = _resolve_master_classification(
            "028300",
            "HLB",
            "자동차",
        )

        self.assertEqual(sector, UNCLASSIFIED_SECTOR)
        self.assertEqual(industry, UNCLASSIFIED_SECTOR)
        self.assertEqual(themes, ["자동차"])

    def test_registered_stock_keeps_verified_sector(self) -> None:
        sector, industry, themes = _resolve_master_classification(
            "005930",
            "삼성전자",
            "자동차",
        )

        self.assertEqual(sector, "반도체")
        self.assertEqual(industry, "반도체")
        self.assertEqual(themes, ["반도체"])

    def test_unclassified_stocks_are_not_blocked_by_sector_cap(self) -> None:
        candidate = {
            "ticker": "000002",
            "sector_group": UNCLASSIFIED_SECTOR,
            "industry_group": UNCLASSIFIED_SECTOR,
        }

        with patch.object(SETTINGS, "max_per_sector", 1):
            self.assertTrue(
                _can_add_candidate(
                    candidate,
                    [{"ticker": "000001"}],
                    {UNCLASSIFIED_SECTOR: 1},
                    {UNCLASSIFIED_SECTOR: 1},
                )
            )

    def test_unknown_stock_uses_krx_listing_classification(self) -> None:
        sector, industry, themes = _resolve_master_classification(
            "999999",
            "테스트전선",
            "데이터센터",
            "절연선 및 케이블 제조업",
            "전력 케이블",
        )

        self.assertEqual(sector, "전력")
        self.assertEqual(industry, "전력 케이블")
        self.assertEqual(themes, ["전력"])


if __name__ == "__main__":
    unittest.main()
