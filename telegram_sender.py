"""텔레그램 메시지 전송 기능을 담당합니다."""

from __future__ import annotations

from typing import Optional

import requests

from config import SETTINGS


def split_message(message: str, limit: int = 3500) -> list[str]:
    """텔레그램 길이 제한을 피하기 위해 메시지를 줄 단위로 나눕니다."""
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for line in message.splitlines():
        line_with_break = f"{line}\n"
        if current and current_length + len(line_with_break) > limit:
            chunks.append("".join(current).rstrip())
            current = [line_with_break]
            current_length = len(line_with_break)
        else:
            current.append(line_with_break)
            current_length += len(line_with_break)

    if current:
        chunks.append("".join(current).rstrip())

    return chunks


def send_telegram_message(message: str) -> tuple[bool, Optional[str]]:
    """
    텔레그램으로 메시지를 보냅니다.
    토큰이나 채팅방 ID가 비어 있으면 전송을 건너뜁니다.
    """
    if not SETTINGS.telegram_bot_token or not SETTINGS.telegram_chat_id:
        return False, "텔레그램 환경변수가 비어 있어 전송을 건너뜁니다."

    url = f"https://api.telegram.org/bot{SETTINGS.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": SETTINGS.telegram_chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }

    for chunk in split_message(message):
        payload["text"] = chunk
        try:
            response = requests.post(url, json=payload, timeout=15)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            return False, f"텔레그램 전송 요청 실패: {exc}"

        if not data.get("ok"):
            return False, f"텔레그램 API 오류: {data}"

    return True, None


def send_telegram_photo(photo_path: str, caption: str = "") -> tuple[bool, Optional[str]]:
    """텔레그램으로 이미지를 전송합니다."""
    if not SETTINGS.telegram_bot_token or not SETTINGS.telegram_chat_id:
        return False, "텔레그램 환경변수가 비어 있어 이미지 전송을 건너뜁니다."

    url = f"https://api.telegram.org/bot{SETTINGS.telegram_bot_token}/sendPhoto"

    try:
        with open(photo_path, "rb") as photo_file:
            response = requests.post(
                url,
                data={"chat_id": SETTINGS.telegram_chat_id, "caption": caption},
                files={"photo": photo_file},
                timeout=20,
            )
        response.raise_for_status()
        data = response.json()
    except (OSError, requests.RequestException) as exc:
        return False, f"텔레그램 이미지 전송 실패: {exc}"

    if not data.get("ok"):
        return False, f"텔레그램 API 오류: {data}"

    return True, None
