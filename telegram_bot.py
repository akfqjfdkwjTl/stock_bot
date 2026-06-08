"""Telegram command bot entrypoint."""

from __future__ import annotations

import atexit
import logging
import os
from pathlib import Path

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from config import SETTINGS
from main import VALID_STRATEGIES, build_performance_message, generate_screening_message
from telegram_sender import split_message


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

LOCK_PATH = Path(__file__).with_suffix(".lock")
DASHBOARD_PUBLIC_URL = "http://168.110.116.149:8000"
DASHBOARD_INTERNAL_URL = "http://127.0.0.1:8000"
DASHBOARD_SCREENSHOT_PATH = Path(__file__).with_name("dashboard.png")


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


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_text_chunks(
        update,
        context,
        "주식 추천 봇입니다. /recommend 입력 시 종목을 보내드립니다. /performance 또는 /perf 입력 시 최근 추천 성과를 조회합니다.",
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

    await send_text_chunks(update, context, "종목을 분석하고 있습니다. 잠시만 기다려 주세요.")

    try:
        result = build_recommendation_text(strategy=strategy)
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


def main() -> None:
    if not SETTINGS.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 환경 변수가 설정되지 않았습니다.")

    _acquire_instance_lock()

    application = ApplicationBuilder().token(SETTINGS.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("recommend", recommend_command))
    application.add_handler(CommandHandler(["performance", "perf"], performance_command))

    print("텔레그램 봇이 실행되었습니다. Ctrl+C 로 종료할 수 있습니다.")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
