"""Tests for non-blocking Telegram recommendation handling."""

from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


telegram_module = types.ModuleType("telegram")
telegram_module.Update = object
telegram_ext_module = types.ModuleType("telegram.ext")
telegram_ext_module.ApplicationBuilder = object
telegram_ext_module.CommandHandler = object
telegram_ext_module.ContextTypes = SimpleNamespace(DEFAULT_TYPE=object)
sys.modules.setdefault("telegram", telegram_module)
sys.modules.setdefault("telegram.ext", telegram_ext_module)

if "telegram_sender" in sys.modules and not hasattr(sys.modules["telegram_sender"], "split_message"):
    sys.modules["telegram_sender"].split_message = lambda text, limit=3500: [text]

import telegram_bot


class TelegramRecommendationTests(unittest.IsolatedAsyncioTestCase):
    async def test_screening_runs_in_worker_thread(self) -> None:
        update = SimpleNamespace(effective_chat=SimpleNamespace(id=1234))
        context = SimpleNamespace(args=["short"], bot=SimpleNamespace())

        with (
            patch.object(telegram_bot, "send_text_chunks", new_callable=AsyncMock) as send,
            patch.object(
                telegram_bot.asyncio,
                "to_thread",
                new_callable=AsyncMock,
                return_value="추천 결과",
            ) as to_thread,
        ):
            await telegram_bot.recommend_command(update, context)

        to_thread.assert_awaited_once_with(
            telegram_bot.build_recommendation_text,
            strategy="short",
        )
        self.assertEqual(send.await_count, 2)
        self.assertEqual(send.await_args_list[-1].args[2], "추천 결과")

    async def test_search_accepts_stock_name(self) -> None:
        update = SimpleNamespace(effective_chat=SimpleNamespace(id=1234))
        context = SimpleNamespace(args=["SK하이닉스"], bot=SimpleNamespace())

        with (
            patch.object(telegram_bot, "send_text_chunks", new_callable=AsyncMock) as send,
            patch.object(
                telegram_bot.asyncio,
                "to_thread",
                new_callable=AsyncMock,
                return_value="종목 진단 결과",
            ) as to_thread,
        ):
            await telegram_bot.search_command(update, context)

        to_thread.assert_awaited_once_with(
            telegram_bot.build_symbol_debug_message,
            "SK하이닉스",
        )
        self.assertEqual(send.await_count, 2)
        self.assertEqual(send.await_args_list[-1].args[2], "종목 진단 결과")

    async def test_search_without_name_shows_new_usage(self) -> None:
        update = SimpleNamespace(effective_chat=SimpleNamespace(id=1234))
        context = SimpleNamespace(args=[], bot=SimpleNamespace())

        with patch.object(telegram_bot, "send_text_chunks", new_callable=AsyncMock) as send:
            await telegram_bot.search_command(update, context)

        self.assertIn("/search 종목명", send.await_args.args[2])


if __name__ == "__main__":
    unittest.main()
