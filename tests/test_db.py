"""Regression tests for recommendation persistence."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from db import save_recommendations


class RecommendationPersistenceTests(unittest.TestCase):
    @staticmethod
    def _item(score: float) -> dict:
        return {
            "ticker": "005930",
            "name": "삼성전자",
            "recommendation_score": score,
            "summary_reason": "테스트 추천",
            "theme": "반도체",
            "sector_group": "반도체",
            "industry_group": "반도체",
            "representative_themes": ["반도체"],
            "current_price": 100000,
            "price_date": "2026-09-12",
            "news_items": [],
            "score_detail": {"총점": score},
        }

    def test_same_day_market_results_are_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "stock_bot.db"

            save_recommendations([self._item(70)], [], db_path=db_path)
            save_recommendations([self._item(82)], [], db_path=db_path)

            with sqlite3.connect(db_path) as connection:
                rows = connection.execute(
                    "SELECT ticker, score FROM recommendations"
                ).fetchall()

        self.assertEqual(rows, [("005930", 82.0)])


if __name__ == "__main__":
    unittest.main()
