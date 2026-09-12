"""Regression tests for news enrichment."""

from __future__ import annotations

import unittest

from news_analyzer import enrich_candidate_with_news


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


if __name__ == "__main__":
    unittest.main()
