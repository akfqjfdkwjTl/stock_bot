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
_install_import_stub(
    "db",
    save_recommendations=lambda *args, **kwargs: 0,
    save_tracked_stock=lambda *args, **kwargs: False,
)
_install_import_stub(
    "stock_screener",
    debug_symbol=lambda *args, **kwargs: {},
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
    _build_final_recommendations,
    _can_add_candidate,
    _grade_for_score,
    _normalize_listing_sector,
    _resolve_master_classification,
    build_symbol_debug_message,
)


class RecommendationSettingsTests(unittest.TestCase):
    def test_watch_candidates_below_configured_minimum_are_not_selected(self) -> None:
        strategy_results = {
            "short": [],
            "swing": [],
            "mid": [
                {
                    "ticker": "105560",
                    "name": "KB금융",
                    "current_price": 1000,
                    "change_pct": 0,
                    "trading_value": SETTINGS.min_trading_value,
                    "total_score": 54,
                    "theme": "기타",
                    "news_score": 0,
                },
                {
                    "ticker": "005930",
                    "name": "삼성전자",
                    "current_price": 1000,
                    "change_pct": 0,
                    "trading_value": SETTINGS.min_trading_value,
                    "total_score": 52,
                    "theme": "기타",
                    "news_score": 0,
                },
            ],
        }

        with patch.object(SETTINGS, "watch_min_score", 40):
            result = _build_final_recommendations(strategy_results)

        self.assertEqual([item["ticker"] for item in result["selected"]], ["105560"])
        self.assertEqual(result["selected"][0]["recommendation_score"], 40.5)

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

        self.assertEqual(sector, "전선/전력인프라")
        self.assertEqual(industry, "절연선 및 케이블 제조업")
        self.assertEqual(themes, ["전선/전력인프라"])

    def test_investment_sector_is_separate_from_raw_industry(self) -> None:
        sector, industry_raw, _themes = _resolve_master_classification(
            "006400",
            "삼성SDI",
            "자동차",
            "일차전지 및 이차전지 제조업",
            "배터리 셀",
        )

        self.assertEqual(sector, "2차전지/배터리")
        self.assertEqual(industry_raw, "일차전지 및 이차전지 제조업")

    def test_generic_engineering_does_not_override_verified_nuclear_sector(self) -> None:
        sector, industry_raw, _themes = _resolve_master_classification(
            "052690",
            "한전기술",
            "기타",
            "건축기술, 엔지니어링 및 관련 기술 서비스업",
            "원전 설계",
        )

        self.assertEqual(sector, "원전/엔지니어링")
        self.assertIn("엔지니어링", industry_raw)

    def test_unknown_raw_industry_is_not_exposed_as_sector(self) -> None:
        self.assertEqual(
            _normalize_listing_sector("그외 기타 개인 서비스업", "렌탈"),
            UNCLASSIFIED_SECTOR,
        )

    def test_symbol_debug_message_contains_filter_and_ranking_fields(self) -> None:
        symbol_info = {
            "universe_included": True,
            "listing_sector": "절연선 및 케이블 제조업",
            "listing_industry": "전력 케이블",
            "diagnostic": {
                "ticker": "000500",
                "name": "가온전선",
                "technical_filter": "FAIL",
                "trend": "PASS",
                "liquidity": "PASS",
                "setup_score": 7,
                "entry_score": 27,
                "risk_penalty": 0,
                "risk_filter": "FAIL",
                "failure_reason": "갭 하락 필터 실패",
                "strategies": {},
            },
            "news": {"theme": "전력", "news_relevance": "MATCH", "news_score": 5},
        }
        final_groups = {"all_candidates": [], "selected": []}

        with (
            patch("main.run_screening", return_value=({}, [], [])),
            patch("main.debug_symbol", return_value=symbol_info),
            patch("main._build_final_recommendations", return_value=final_groups),
        ):
            message = build_symbol_debug_message("000500")

        self.assertIn("universe 포함 여부: PASS", message)
        self.assertIn("technical filter: FAIL", message)
        self.assertIn("sector: 전선/전력인프라", message)
        self.assertIn("news relevance: MATCH", message)
        self.assertIn("final score: 0", message)
        self.assertIn("최종 TOP5 ranking: 미포함", message)


if __name__ == "__main__":
    unittest.main()
