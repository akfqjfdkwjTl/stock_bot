"""프로젝트 설정값과 실행 모드를 관리합니다."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass
class Settings:
    """프로그램 전역 설정입니다."""

    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    results_csv_path: str = "results.csv"
    backtest_results_csv_path: str = "backtest_results.csv"
    backtest_summary_json_path: str = "backtest_summary.json"
    insta_image_path: str = "insta_post.png"
    market_json_path: str = "market-data.json"
    dashboard_json_path: str = "dashboard-data.json"
    dashboard_capture_path: str = "dashboard_capture.png"
    enable_image_output: bool = os.getenv("ENABLE_IMAGE_OUTPUT", "false").strip().lower() == "true"
    enable_dashboard_capture: bool = os.getenv("ENABLE_DASHBOARD_CAPTURE", "false").strip().lower() == "true"
    top_n_per_strategy: int = 5
    default_mode: str = os.getenv("SCREEN_MODE", "real").strip().lower() or "real"
    max_per_sector: int = int(os.getenv("MAX_PER_SECTOR", "1"))
    final_recommendation_limit: int = int(os.getenv("FINAL_RECOMMENDATION_LIMIT", "5"))

    # 실데이터 조회 범위를 제한해서 실행 시간을 줄입니다.
    max_symbols: int = int(os.getenv("MAX_SYMBOLS", "100"))
    history_calendar_days: int = int(os.getenv("HISTORY_CALENDAR_DAYS", "140"))
    news_lookback_days: int = int(os.getenv("NEWS_LOOKBACK_DAYS", "3"))
    news_max_items: int = int(os.getenv("NEWS_MAX_ITEMS", "8"))
    news_request_timeout: int = int(os.getenv("NEWS_REQUEST_TIMEOUT", "6"))
    grade_a_threshold: float = float(os.getenv("GRADE_A_THRESHOLD", "60"))
    grade_b_threshold: float = float(os.getenv("GRADE_B_THRESHOLD", os.getenv("WATCH_THRESHOLD", "45")))
    backtest_take_profit_pct: float = float(os.getenv("BACKTEST_TAKE_PROFIT_PCT", "10"))
    backtest_stop_loss_pct: float = float(os.getenv("BACKTEST_STOP_LOSS_PCT", "5"))
    backtest_hold_days: int = int(os.getenv("BACKTEST_HOLD_DAYS", "10"))

    # 공통 제외 조건
    min_price: int = 1000
    min_trading_value: int = 3_000_000_000
    max_daily_change_pct: float = 15.0

    # 60일 이동평균과 기울기를 계산하려면 여유 있는 일봉이 필요합니다.
    min_history_rows: int = 66


SETTINGS = Settings()
