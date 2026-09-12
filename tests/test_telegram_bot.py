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


if __name__ == "__main__":
    unittest.main()
