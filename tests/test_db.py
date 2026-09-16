"""Regression tests for recommendation persistence."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from db import load_tracked_stocks, save_recommendations, save_tracked_stock


class RecommendationPersistenceTests(unittest.TestCase):
    @staticmethod
    def _item(score: float, price: float = 100000) -> dict:
        return {
            "ticker": "005930",
            "name": "삼성전자",
            "recommendation_score": score,
            "summary_reason": "테스트 추천",
            "theme": "반도체",
            "sector_group": "반도체",
            "industry_group": "반도체",
            "representative_themes": ["반도체"],
            "current_price": price,
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

    def test_recommendation_price_is_frozen_on_first_daily_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "stock_bot.db"

            save_recommendations([self._item(70, 100000)], [], db_path=db_path)
            save_recommendations([self._item(82, 105000)], [], db_path=db_path)
            tracked = load_tracked_stocks(db_path=db_path)

        self.assertEqual(len(tracked), 1)
        self.assertEqual(tracked[0]["source"], "recommendation")
        self.assertEqual(tracked[0]["reference_price"], 100000.0)
        self.assertEqual(tracked[0]["score"], 70.0)

    def test_recommendation_and_search_are_separate_daily_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "stock_bot.db"

            save_recommendations([self._item(70)], [], db_path=db_path)
            inserted = save_tracked_stock(
                source="search",
                ticker="005930",
                name="삼성전자",
                reference_price=101000,
                price_date="2026-09-12",
                score=65,
                sector="반도체",
                db_path=db_path,
            )
            tracked = load_tracked_stocks(db_path=db_path)

        self.assertTrue(inserted)
        self.assertEqual({row["source"] for row in tracked}, {"recommendation", "search"})

    def test_duplicate_search_does_not_overwrite_reference_price(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "stock_bot.db"
            arguments = {
                "source": "search",
                "ticker": "000660",
                "name": "SK하이닉스",
                "price_date": "2026-09-16",
                "track_date": "2026-09-16",
                "db_path": db_path,
            }

            first = save_tracked_stock(reference_price=350000, **arguments)
            second = save_tracked_stock(reference_price=360000, **arguments)
            tracked = load_tracked_stocks(db_path=db_path)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(tracked[0]["reference_price"], 350000.0)


if __name__ == "__main__":
    unittest.main()
