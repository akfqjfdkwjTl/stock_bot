"""Telegram command bot entrypoint."""

from __future__ import annotations

import atexit
import asyncio
import logging
import os
from contextlib import suppress
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from config import SETTINGS
from main import (
    VALID_STRATEGIES,
    build_performance_message,
    build_symbol_debug_message,
    generate_screening_message,
)
from telegram_sender import split_message


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# HTTP client request URLs contain the Telegram bot token. Keep routine
# request logging disabled so credentials never reach PM2 or repository logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

LOCK_PATH = Path(__file__).with_suffix(".lock")
DASHBOARD_PUBLIC_URL = "http://168.110.116.149:8000"
DASHBOARD_INTERNAL_URL = "http://127.0.0.1:8000"
DASHBOARD_SCREENSHOT_PATH = Path(__file__).with_name("dashboard.png")
SCREENING_LOCK = asyncio.Lock()
KST = ZoneInfo("Asia/Seoul")
DAILY_RECOMMENDATION_TASK_KEY = "daily_recommendation_task"


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _acquire_instance_lock() -> None:
    if LOCK_PATH.exists():
        try:
            existing_pid = int(LOCK_PATH.read_text(encoding="utf-8").strip())
        except ValueError:
            existing_pid = 0
        if existing_pid and _process_exists(existing_pid):
            raise RuntimeError(f"telegram_bot.py is already running with PID {existing_pid}.")
        LOCK_PATH.unlink(missing_ok=True)

    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
        lock_file.write(str(os.getpid()))
    atexit.register(lambda: LOCK_PATH.unlink(missing_ok=True))


def build_recommendation_text(strategy: str | None = None) -> str:
    """Return the recommendation message. This function must not send Telegram messages."""
    message, _errors = generate_screening_message(
        mode=SETTINGS.default_mode,
        strategy=strategy,
    )
    return message


async def capture_web_dashboard(output_path: Path = DASHBOARD_SCREENSHOT_PATH) -> Path:
    """Capture the FastAPI dashboard with Playwright."""
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 430, "height": 1200})
        try:
            await page.goto(DASHBOARD_INTERNAL_URL, wait_until="networkidle", timeout=60000)
            await page.screenshot(path=str(output_path), full_page=True)
        finally:
            await browser.close()

    return output_path


async def send_dashboard_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        logging.error("Dashboard screenshot send skipped: update.effective_chat is missing.")
        return

    try:
        from telegram import InputFile

        capture_path = await capture_web_dashboard()
        with open(capture_path, "rb") as image_file:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=InputFile(image_file, filename="dashboard.png"),
                caption="대시보드 캡처",
            )
    except Exception:
        logging.exception("Dashboard screenshot capture/send failed")


async def send_text_chunks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    limit: int = 3500,
) -> None:
    if update.effective_chat is None:
        logging.error("Telegram send skipped: update.effective_chat is missing.")
        return

    chat_id = update.effective_chat.id
    chunks = split_message(text.strip() or "추천 결과가 비어 있습니다.", limit=limit)
    logging.info("Sending Telegram message: chat_id=%s, chunks=%s", chat_id, len(chunks))

    for index, chunk in enumerate(chunks, start=1):
        await context.bot.send_message(chat_id=chat_id, text=chunk)
        logging.info("Sent Telegram chunk: chat_id=%s, chunk=%s/%s", chat_id, index, len(chunks))


async def send_bot_text_chunks(bot: object, chat_id: str, text: str, *, limit: int = 3500) -> None:
    """Send text without a Telegram Update, for scheduled recommendations."""
    chunks = split_message(text.strip() or "추천 결과가 비어 있습니다.", limit=limit)
    for index, chunk in enumerate(chunks, start=1):
        await bot.send_message(chat_id=chat_id, text=chunk)
        logging.info(
            "Sent scheduled Telegram chunk: chat_id=%s, chunk=%s/%s",
            chat_id,
            index,
            len(chunks),
        )


def seconds_until_daily_recommendation(now: datetime | None = None) -> float:
    """Return seconds until the next configured 08:50 KST run."""
    current = now.astimezone(KST) if now is not None else datetime.now(KST)
    scheduled_time = time(
        hour=SETTINGS.auto_recommend_hour,
        minute=SETTINGS.auto_recommend_minute,
        tzinfo=KST,
    )
    next_run = datetime.combine(current.date(), scheduled_time)
    if next_run <= current:
        next_run += timedelta(days=1)
    return (next_run - current).total_seconds()


async def send_scheduled_recommendation(application: object) -> None:
    """Run the same analysis as /recommend and send its result plus dashboard link."""
    chat_id = SETTINGS.telegram_chat_id
    if not chat_id:
        logging.error("Scheduled recommendation skipped: TELEGRAM_CHAT_ID is empty.")
        return

    async with SCREENING_LOCK:
        result = await asyncio.to_thread(build_recommendation_text)

    await send_bot_text_chunks(application.bot, chat_id, result)
    await application.bot.send_message(
        chat_id=chat_id,
        text=f"추천 결과 확인: {DASHBOARD_PUBLIC_URL}",
    )


async def daily_recommendation_loop(application: object) -> None:
    """Keep the daily KST schedule alive inside the PM2-managed bot process."""
    while True:
        delay = seconds_until_daily_recommendation()
        next_run = datetime.now(KST) + timedelta(seconds=delay)
        logging.info("Next automatic /recommend: %s", next_run.strftime("%Y-%m-%d %H:%M:%S KST"))
        await asyncio.sleep(delay)
        try:
            await send_scheduled_recommendation(application)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Automatic /recommend failed")


async def start_daily_recommendation(application: object) -> None:
    if not SETTINGS.auto_recommend_enabled:
        logging.info("Automatic /recommend is disabled.")
        return
    if not SETTINGS.telegram_chat_id:
        logging.error("Automatic /recommend is enabled but TELEGRAM_CHAT_ID is empty.")
        return
    application.bot_data[DAILY_RECOMMENDATION_TASK_KEY] = asyncio.create_task(
        daily_recommendation_loop(application),
        name=DAILY_RECOMMENDATION_TASK_KEY,
    )


async def stop_daily_recommendation(application: object) -> None:
    task = application.bot_data.pop(DAILY_RECOMMENDATION_TASK_KEY, None)
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_text_chunks(
        update,
        context,
        "주식 추천 봇입니다. /recommend 입력 시 자동추천 종목을 보내드립니다. "
        "/search 종목명 입력 시 자동추천 범위와 무관하게 해당 종목을 분석하고, "
        "/performance 또는 /perf 입력 시 최근 추천 성과를 조회합니다.",
    )


async def recommend_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    strategy = None
    if context.args:
        requested = context.args[0].strip().lower()
        if requested not in VALID_STRATEGIES:
            await send_text_chunks(
                update,
                context,
                "사용 가능한 전략은 short, swing, mid 입니다.\n예시: /recommend short",
            )
            return
        strategy = requested

    if SCREENING_LOCK.locked():
        await send_text_chunks(update, context, "현재 다른 종목 분석이 진행 중입니다. 완료 후 다시 요청해 주세요.")
        return

    await send_text_chunks(update, context, "종목을 분석하고 있습니다. 잠시만 기다려 주세요.")

    async with SCREENING_LOCK:
        try:
            result = await asyncio.to_thread(
                build_recommendation_text,
                strategy=strategy,
            )
        except Exception as exc:
            logging.exception("Screening failed")
            await send_text_chunks(update, context, f"분석 중 오류가 발생했습니다: {exc}")
            return

        await send_text_chunks(update, context, result)

        if strategy is None:
            await send_dashboard_screenshot(update, context)


async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    selected_date = context.args[0].strip() if context.args else None
    try:
        result = build_performance_message(selected_date)
    except Exception as exc:
        logging.exception("Performance lookup failed")
        await send_text_chunks(update, context, f"성과 조회 중 오류가 발생했습니다: {exc}")
        return

    await send_text_chunks(update, context, result)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await send_text_chunks(update, context, "사용법: /search 종목명 또는 종목코드\n예시: /search SK하이닉스")
        return
    if SCREENING_LOCK.locked():
        await send_text_chunks(update, context, "현재 다른 종목 분석이 진행 중입니다. 완료 후 다시 요청해 주세요.")
        return

    await send_text_chunks(update, context, f"{query} 종목을 분석하고 있습니다. 잠시만 기다려 주세요.")
    async with SCREENING_LOCK:
        try:
            result = await asyncio.to_thread(build_symbol_debug_message, query)
        except Exception as exc:
            logging.exception("Symbol debug failed")
            await send_text_chunks(update, context, f"종목 진단 중 오류가 발생했습니다: {exc}")
            return
        await send_text_chunks(update, context, result)


# 기존 사용자를 위해 /debug도 같은 검색 기능의 별칭으로 유지합니다.
debug_command = search_command


def main() -> None:
    if not SETTINGS.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 환경 변수가 설정되지 않았습니다.")

    _acquire_instance_lock()

    application = (
        ApplicationBuilder()
        .token(SETTINGS.telegram_bot_token)
        .post_init(start_daily_recommendation)
        .post_shutdown(stop_daily_recommendation)
        .build()
    )
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("recommend", recommend_command))
    application.add_handler(CommandHandler(["performance", "perf"], performance_command))
    application.add_handler(CommandHandler(["search", "debug"], search_command))

    print("텔레그램 봇이 실행되었습니다. Ctrl+C 로 종료할 수 있습니다.")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
