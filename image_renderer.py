"""Instagram list-style recommendation image rendering."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from config import SETTINGS


CANVAS_SIZE = (1080, 1080)
BACKGROUND = "#0B0B0B"
FOREGROUND = "#FFFFFF"
MUTED = "#B6BDC9"
ACCENT_BLUE = "#3B82F6"
ACCENT_GREEN = "#22C55E"
DIVIDER = "#1E293B"


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load NotoSansKR first, then fall back safely."""
    font_candidates = [r"C:\Windows\Fonts\NotoSansKR-VF.ttf"]
    if bold:
        font_candidates.extend(
            [
                r"C:\Windows\Fonts\malgunbd.ttf",
                r"C:\Windows\Fonts\arialbd.ttf",
            ]
        )
    else:
        font_candidates.extend(
            [
                r"C:\Windows\Fonts\malgun.ttf",
                r"C:\Windows\Fonts\arial.ttf",
            ]
        )

    for font_path in font_candidates:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size=size)
            except Exception:
                continue

    return ImageFont.load_default()


def _trim_chars(text: str, limit: int = 15) -> str:
    """Limit visible text length to keep the layout compact."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _fit_line(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    """Trim text so it fits in one line."""
    text = text.strip()
    if draw.textlength(text, font=font) <= max_width:
        return text

    trimmed = text
    while trimmed and draw.textlength(trimmed + "…", font=font) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + "…") if trimmed else "…"


def _strategy_label(strategy_type: str) -> tuple[str, str]:
    """Return list label and accent color."""
    mapping = {
        "short": ("SHORT", ACCENT_GREEN),
        "swing": ("SWING", ACCENT_BLUE),
        "혼합": ("MIX", ACCENT_BLUE),
    }
    return mapping.get(strategy_type, ("WATCH", ACCENT_GREEN))


def render_recommendation_image(items: list[dict[str, Any]], output_path: str | None = None) -> str:
    """
    Render recommendations into a 1080x1080 Instagram list-style image.
    Each stock uses exactly 3 lines:
    1. Stock name
    2. Theme + strategy
    3. One-line issue summary
    """
    path = output_path or SETTINGS.insta_image_path

    image = Image.new("RGB", CANVAS_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)

    title_font = _load_font(58, bold=True)
    subtitle_font = _load_font(22, bold=False)
    name_font = _load_font(42, bold=True)
    meta_font = _load_font(24, bold=True)
    issue_font = _load_font(24, bold=False)
    footer_font = _load_font(22, bold=False)

    left = 48
    right = CANVAS_SIZE[0] - 48
    top = 36

    draw.text((left, top), "TODAY PICKS", fill=FOREGROUND, font=title_font)
    top += 70
    draw.text(
        (left, top),
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        fill=MUTED,
        font=subtitle_font,
    )
    top += 40

    shown_items = items[:5]
    footer_reserved = 48
    available_height = CANVAS_SIZE[1] - top - footer_reserved
    row_gap = 14
    row_height = int((available_height - row_gap * max(len(shown_items) - 1, 0)) / max(len(shown_items), 1))
    row_height = max(150, row_height)

    for index, item in enumerate(shown_items, start=1):
        row_top = top + (index - 1) * (row_height + row_gap)
        row_bottom = row_top + row_height
        label, accent = _strategy_label(item.get("strategy_type", ""))

        if index > 1:
            draw.line((left, row_top - 8, right, row_top - 8), fill=DIVIDER, width=2)

        name_y = row_top + 8
        meta_y = name_y + 48
        issue_y = meta_y + 38

        stock_name = _fit_line(draw, f"{index}. {_trim_chars(item.get('name', ''), 15)}", name_font, right - left)
        draw.text((left, name_y), stock_name, fill=FOREGROUND, font=name_font)

        score_text = f"{item.get('final_score', item.get('total_score', 0))}점"
        score_width = draw.textlength(score_text, font=meta_font)
        draw.text((right - score_width, name_y + 8), score_text, fill=accent, font=meta_font)

        theme_text = _trim_chars(item.get("theme", "기타") or "기타", 15)
        meta_text = f"{theme_text} · {label}"
        meta_text = _fit_line(draw, meta_text, meta_font, right - left)
        draw.text((left, meta_y), meta_text, fill=accent, font=meta_font)

        issue_summary = item.get("issue_summary", "") or "특이 이슈 없음"
        issue_line = _fit_line(draw, _trim_chars(issue_summary, 30), issue_font, right - left)
        draw.text((left, issue_y), issue_line, fill=MUTED, font=issue_font)

    footer_text = "※ 매수 추천 아님 / 조건 기반 관심종목"
    footer_width = draw.textlength(footer_text, font=footer_font)
    draw.text(
        ((CANVAS_SIZE[0] - footer_width) / 2, CANVAS_SIZE[1] - 38),
        footer_text,
        fill=MUTED,
        font=footer_font,
    )

    image.save(path)
    return path
