"""Regression tests for news enrichment."""

from __future__ import annotations

import unittest

from news_analyzer import (
    _build_issue_summary,
    _collect_theme_counts,
    enrich_candidate_with_news,
    infer_base_theme,
)


class NewsEnrichmentTests(unittest.TestCase):
    def test_news_score_does_not_change_technical_score(self) -> None:
        candidate = {
            "ticker": "005930",
            "name": "삼성전자",
            "total_score": 64,
        }
        news_info = {
            "theme": "반도체",
            "recent_news_keywords": ["AI", "반도체"],
            "issue_summary": "테스트 뉴스",
            "news_score": 8,
            "news_items": [{"title": "테스트"}],
            "news_error": "",
        }

        enriched = enrich_candidate_with_news(candidate, news_info)

        self.assertEqual(enriched["total_score"], 64)
        self.assertEqual(enriched["news_score"], 8)
        self.assertEqual(enriched["theme"], "반도체")
        self.assertEqual(enriched["recent_news_keywords"], "AI, 반도체")
        self.assertEqual(candidate["total_score"], 64)

    def test_short_english_keyword_does_not_match_inside_word(self) -> None:
        items = [
            {
                "title": "코웨이 제품 review 공개",
                "description": "신제품 사용 후기를 소개합니다.",
            }
        ]

        counts, _repeats = _collect_theme_counts(items, "")

        self.assertNotIn("자동차", counts)

    def test_description_only_theme_requires_repeated_articles(self) -> None:
        items = [
            {
                "title": "HD현대마린솔루션 목표가 상향",
                "description": "서버 투자 전망도 시장에서 언급됐습니다.",
            }
        ]

        counts, _repeats = _collect_theme_counts(items, "")

        self.assertNotIn("데이터센터", counts)

    def test_known_industry_blocks_unrelated_theme(self) -> None:
        items = [
            {
                "title": "코웨이 자동차 관련 단어가 포함된 기사",
                "description": "코웨이 신제품 소식",
            }
        ]

        counts, _repeats = _collect_theme_counts(items, "생활가전")

        self.assertNotIn("자동차", counts)

    def test_stock_name_itself_does_not_create_theme_score(self) -> None:
        items = [
            {
                "title": "KB금융 차기 회장 후보 발표",
                "description": "KB금융이 후보 명단을 공개했습니다.",
            }
        ]

        counts, _repeats = _collect_theme_counts(items, "금융", stock_name="KB금융")

        self.assertNotIn("금융", counts)

    def test_headline_without_credible_theme_uses_factual_summary(self) -> None:
        summary = _build_issue_summary(
            stock_name="코웨이",
            primary_theme="",
            recent_keywords=[],
            repeated_keywords=[],
            headline="코웨이 자회사 신규 매장 입점 - 테스트뉴스",
        )

        self.assertIn("뉴스 테마 점수에는 반영하지 않았습니다", summary)
        self.assertNotIn("자동차", summary)

    def test_krx_description_infers_conservative_base_theme(self) -> None:
        self.assertEqual(infer_base_theme("전동기, 발전기 및 전기 변환장치 제조업", "전력 케이블"), "전력")
        self.assertEqual(infer_base_theme("선박 및 보트 건조업", "선박 구성품"), "조선/기계")


if __name__ == "__main__":
    unittest.main()
