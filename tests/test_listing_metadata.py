"""Tests for KRX listing metadata handling."""

from __future__ import annotations

import unittest

import pandas as pd

import stock_screener
from stock_screener import (
    _attach_listing_metadata,
    _load_listing_metadata,
    _select_real_symbols,
)


class ListingMetadataTests(unittest.TestCase):
    def test_price_listing_is_enriched_with_krx_description(self) -> None:
        listing = pd.DataFrame(
            [
                {"Code": "443060", "Name": "HD현대마린솔루션", "Market": "KOSPI", "Marcap": 2},
                {"Code": "000500", "Name": "가온전선", "Market": "KOSPI", "Marcap": 1},
            ]
        )
        description = pd.DataFrame(
            [
                {"Code": "443060", "Sector": "선박 및 보트 건조업", "Industry": "선박 애프터마켓"},
                {"Code": "000500", "Sector": "절연선 및 케이블 제조업", "Industry": "전력 케이블"},
            ]
        )

        symbols = _select_real_symbols(listing)
        enriched = _attach_listing_metadata(symbols, description)

        self.assertEqual(enriched.loc[0, "Sector"], "선박 및 보트 건조업")
        self.assertEqual(enriched.loc[1, "Industry"], "전력 케이블")

    def test_description_listing_is_cached_for_process_lifetime(self) -> None:
        class FakeFinanceDataReader:
            calls = 0

            @classmethod
            def StockListing(cls, listing_type: str) -> pd.DataFrame:
                self.assertEqual(listing_type, "KRX-DESC")
                cls.calls += 1
                return pd.DataFrame([{"Code": "005930", "Industry": "반도체"}])

        original_cache = stock_screener._LISTING_METADATA_CACHE
        stock_screener._LISTING_METADATA_CACHE = None
        try:
            first = _load_listing_metadata(FakeFinanceDataReader)
            first.loc[0, "Industry"] = "변경값"
            second = _load_listing_metadata(FakeFinanceDataReader)

            self.assertEqual(FakeFinanceDataReader.calls, 1)
            self.assertEqual(second.loc[0, "Industry"], "반도체")
        finally:
            stock_screener._LISTING_METADATA_CACHE = original_cache


if __name__ == "__main__":
    unittest.main()
