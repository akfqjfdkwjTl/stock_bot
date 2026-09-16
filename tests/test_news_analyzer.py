"""Regression tests for news enrichment."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from news_analyzer import (
    _build_issue_summary,
    _collect_theme_counts,
    _collect_relevant_news_items,
    _classify_news_relevance,
    _validate_news_entity,
    analyze_stock_news,
    enrich_candidate_with_news,
    infer_base_theme,
)


class NewsEnrichmentTests(unittest.TestCase):
    def test_sports_team_article_is_entity_mismatch(self) -> None:
        article = {
            "title": "'5위 넘볼 생각 마' 두산, 다시 3G 차 리드! NC 9-2 제압",
            "description": "두산 선수들이 경기에서 승리했습니다.",
        }

        matched, reason = _validate_news_entity("두산", "000150", article)

        self.assertFalse(matched)
        self.assertEqual(reason, "MISMATCH_SPORTS")

    def test_doosan_corporate_article_is_entity_match(self) -> None:
        article = {
            "title": "두산, 전자소재 사업 투자 확대",
            "description": "두산 주가와 계열사 실적 전망이 부각됐습니다.",
        }

        matched, reason = _validate_news_entity("두산", "000150", article)

        self.assertTrue(matched)
        self.assertEqual(reason, "MATCH_CORPORATE_CONTEXT")

    def test_ambiguous_doosan_photo_caption_is_sports_mismatch(self) -> None:
        article = {
            "title": "[사진] 토마, 두산 반드시 잡는다",
            "description": "현장 포토뉴스",
        }

        matched, reason = _validate_news_entity("두산", "000150", article)

        self.assertFalse(matched)
        self.assertEqual(reason, "MISMATCH_SPORTS")

    def test_gs_volleyball_article_is_entity_mismatch(self) -> None:
        article = {
            "title": "GS칼텍스, V리그 여자배구 3세트 승리",
            "description": "감독과 선수들이 블로킹으로 경기를 제압했습니다.",
        }

        matched, reason = _validate_news_entity("GS", "078930", article)

        self.assertFalse(matched)
        self.assertEqual(reason, "MISMATCH_SPORTS")

    def test_samsung_sdi_battery_article_is_direct(self) -> None:
        article = {
            "title": "삼성SDI 전고체 배터리 상용화 속도",
            "description": "차세대 배터리 기술 경쟁이 확대되고 있습니다.",
        }

        relevance = _classify_news_relevance("삼성SDI", "006400", article, "2차전지")

        self.assertEqual(relevance, "DIRECT")

    def test_sm_gambling_spam_is_entity_mismatch(self) -> None:
        article = {
            "title": "게임 안팎의 설명이 일치하는지 확인할 에스엠 토토 먹튀",
            "description": "전기차 배터리 추천과 무관한 사설 토토 사이트 광고입니다.",
        }

        matched, reason = _validate_news_entity("에스엠", "041510", article)
        relevance = _classify_news_relevance(
            "에스엠", "041510", article, "엔터/미디어"
        )

        self.assertFalse(matched)
        self.assertEqual(reason, "MISMATCH_GAMBLING")
        self.assertEqual(relevance, "MISMATCH")

    def test_sm_entertainment_article_is_direct(self) -> None:
        article = {
            "title": "에스엠, 신인 아티스트 앨범 공개",
            "description": "SM엔터테인먼트가 신규 음반과 콘서트 계획을 발표했습니다.",
        }

        relevance = _classify_news_relevance(
            "에스엠", "041510", article, "엔터/미디어"
        )

        self.assertEqual(relevance, "DIRECT")

    def test_sm_vexel_article_is_not_sm_news(self) -> None:
        article = {
            "title": "에스엠벡셀, 자진상폐 수순 밟나",
            "description": "SM그룹 지분이 89%를 돌파하고 두 달째 장내매수를 이어갔습니다.",
        }

        matched, reason = _validate_news_entity("에스엠", "041510", article)
        relevance = _classify_news_relevance(
            "에스엠", "041510", article, "엔터/미디어"
        )

        self.assertFalse(matched)
        self.assertEqual(reason, "NO_ENTITY_MENTION")
        self.assertEqual(relevance, "MISMATCH")

    def test_exact_korean_company_name_with_particle_is_allowed(self) -> None:
        article = {
            "title": "에스엠은 신인 아티스트 앨범을 공개했다",
            "description": "엔터테인먼트 사업과 콘서트 계획도 발표했습니다.",
        }

        relevance = _classify_news_relevance(
            "에스엠", "041510", article, "엔터/미디어"
        )

        self.assertEqual(relevance, "DIRECT")

    def test_similar_listed_company_suffix_is_not_partial_match(self) -> None:
        article = {
            "title": "삼성전자우 배당 확대 기대",
            "description": "우선주 투자 수요가 증가했습니다.",
        }

        matched, reason = _validate_news_entity("삼성전자", "005930", article)

        self.assertFalse(matched)
        self.assertEqual(reason, "NO_ENTITY_MENTION")

    def test_indirect_industry_article_is_sector_or_weak(self) -> None:
        article = {
            "title": "배터리 업종 투자 확대",
            "description": "삼성SDI 관련 공급망 기대가 언급됐습니다.",
        }

        relevance = _classify_news_relevance("삼성SDI", "006400", article, "2차전지")

        self.assertEqual(relevance, "SECTOR")

    def test_mismatched_articles_are_removed_before_theme_extraction(self) -> None:
        articles = [
            {
                "title": "두산 NC 9-2 제압",
                "description": "야구 경기에서 투수와 타자가 활약했습니다.",
            }
        ]

        relevant, mismatched = _collect_relevant_news_items("두산", articles, ticker="000150")

        self.assertEqual(relevant, [])
        self.assertEqual(len(mismatched), 1)

    def test_all_mismatched_news_returns_zero_scores(self) -> None:
        class FakeResponse:
            text = """<rss><channel><item><title>두산 NC 9-2 제압</title><description>야구 경기 선수 승리</description><pubDate>Sat, 12 Sep 2026 10:00:00 +0900</pubDate></item></channel></rss>"""

            @staticmethod
            def raise_for_status() -> None:
                return None

        with (
            patch("news_analyzer.requests.get", return_value=FakeResponse()),
            patch("news_analyzer.SETTINGS.news_lookback_days", 100),
        ):
            result = analyze_stock_news("두산", ticker="000150")

        self.assertEqual(result["news_relevance"], "MISMATCH")
        self.assertEqual(result["news_score"], 0)
        self.assertEqual(result["theme_score"], 0)

    def test_sm_gambling_news_does_not_create_battery_theme_or_score(self) -> None:
        class FakeResponse:
            text = """<rss><channel><item><title>게임 안팎의 설명이 일치하는지 확인할 에스엠 토토 먹튀</title><description>전기차 배터리 추천과 무관한 사설 토토 사이트 광고</description><pubDate>Sat, 12 Sep 2026 10:00:00 +0900</pubDate></item></channel></rss>"""

            @staticmethod
            def raise_for_status() -> None:
                return None

        with (
            patch("news_analyzer.requests.get", return_value=FakeResponse()),
            patch("news_analyzer.SETTINGS.news_lookback_days", 100),
        ):
            result = analyze_stock_news(
                "에스엠",
                ticker="041510",
                sector="우량기업부",
                industry="오디오물 출판 및 원판 녹음업",
            )

        self.assertEqual(result["theme"], "엔터/미디어")
        self.assertEqual(result["news_relevance"], "MISMATCH")
        self.assertEqual(result["news_score"], 0)
        self.assertNotIn("2차전지", result["recent_news_keywords"])

    def test_sm_vexel_rss_item_is_excluded_from_sm_news(self) -> None:
        class FakeResponse:
            text = """<rss><channel><item><title>에스엠벡셀, 자진상폐 수순 밟나…SM그룹 지분 89% 돌파</title><description>두 달째 장내매수를 이어갔습니다.</description><pubDate>Sat, 12 Sep 2026 10:00:00 +0900</pubDate></item></channel></rss>"""

            @staticmethod
            def raise_for_status() -> None:
                return None

        with (
            patch("news_analyzer.requests.get", return_value=FakeResponse()),
            patch("news_analyzer.SETTINGS.news_lookback_days", 100),
        ):
            result = analyze_stock_news(
                "에스엠",
                ticker="041510",
                sector="우량기업부",
                industry="오디오물 출판 및 원판 녹음업",
            )

        self.assertEqual(result["theme"], "엔터/미디어")
        self.assertEqual(result["news_relevance"], "NONE")
        self.assertEqual(result["news_score"], 0)
        self.assertEqual(result["news_items"], [])
        self.assertNotIn("에스엠벡셀", result["issue_summary"])

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
        self.assertEqual(infer_base_theme("우량기업부", "오디오물 출판 및 원판 녹음업"), "엔터/미디어")


if __name__ == "__main__":
    unittest.main()
