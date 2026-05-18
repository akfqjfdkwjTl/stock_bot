"""텔레그램 명령형 봇 실행 파일입니다."""

from __future__ import annotations

import atexit
import logging
import os
from pathlib import Path

from telegram import InputFile, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from config import SETTINGS
from dashboard_capture import capture_dashboard
from main import VALID_STRATEGIES, generate_screening_message
from telegram_sender import split_message


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

LOCK_PATH = Path(__file__).with_suffix(".lock")


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


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "주식 추천 봇입니다. /recommend 입력 시 종목을 보내드립니다."
    )


def build_recommendation_text(strategy: str | None = None) -> str:
    message, _errors = generate_screening_message(
        mode=SETTINGS.default_mode,
        strategy=strategy,
    )
    return message


async def send_recommendation_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    if update.effective_chat is None:
        return

    chunks = split_message(text.strip() or "추천 결과가 비어 있습니다.")
    for chunk in chunks:
        if update.message is not None:
            await update.message.reply_text(chunk)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=chunk)


async def recommend_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    strategy = None
    if context.args:
        requested = context.args[0].strip().lower()
        if requested not in VALID_STRATEGIES:
            await update.message.reply_text(
                "사용 가능한 전략은 short, swing, mid 입니다.\n예시: /recommend short"
            )
            return
        strategy = requested

    await update.message.reply_text("종목을 분석하고 있습니다. 잠시만 기다려 주세요.")

    try:
        result = build_recommendation_text(strategy=strategy)
    except Exception as exc:
        logging.exception("스크리닝 실행 실패")
        await update.message.reply_text(f"분석 중 오류가 발생했습니다: {exc}")
        return

    await send_recommendation_text(update, context, result)

    if strategy is None:
        try:
            capture_path = capture_dashboard()
            with open(capture_path, "rb") as image_file:
                await update.message.reply_photo(
                    photo=InputFile(image_file),
                    caption="추천 대시보드 캡처",
                )
        except Exception as exc:
            logging.exception("대시보드 캡처 실패")
            await update.message.reply_text(f"대시보드 캡처 실패: {exc}")


def main() -> None:
    if not SETTINGS.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 환경 변수가 설정되지 않았습니다.")

    _acquire_instance_lock()

    application = ApplicationBuilder().token(SETTINGS.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("recommend", recommend_command))

    print("텔레그램 봇이 실행되었습니다. Ctrl+C 로 종료할 수 있습니다.")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
