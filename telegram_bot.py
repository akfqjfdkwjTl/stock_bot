"""텔레그램 명령형 봇 실행 파일입니다."""

from __future__ import annotations

import logging

from telegram import InputFile, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from config import SETTINGS
from dashboard_capture import capture_dashboard
from main import VALID_STRATEGIES, generate_screening_payload
from telegram_sender import split_message


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "주식 추천 봇입니다. /recommend 입력 시 종목을 보내드립니다."
    )


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
        message, _errors, _display_items = generate_screening_payload(
            mode=SETTINGS.default_mode,
            strategy=strategy,
        )
    except Exception as exc:
        logging.exception("스크리닝 실행 실패")
        await update.message.reply_text(f"분석 중 오류가 발생했습니다: {exc}")
        return

    for chunk in split_message(message):
        await update.message.reply_text(chunk)

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

    application = ApplicationBuilder().token(SETTINGS.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("recommend", recommend_command))

    print("텔레그램 봇이 실행되었습니다. Ctrl+C 로 종료할 수 있습니다.")
    application.run_polling()


if __name__ == "__main__":
    main()
