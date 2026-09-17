"""국내주식 조건 기반 관심종목 선별 프로그램의 실행 진입점입니다."""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from config import SETTINGS
from dashboard_capture import capture_dashboard, refresh_market_json, save_dashboard_data
from db import save_recommendations, save_tracked_stock
from stock_screener import debug_symbol, run_screening, save_results_to_csv
from telegram_sender import send_telegram_message, send_telegram_photo


VALID_STRATEGIES = ("short", "swing", "mid")
KST = ZoneInfo("Asia/Seoul")
UNCLASSIFIED_SECTOR = "미분류"
DASHBOARD_URL = "http://168.110.116.149:8000"
DASHBOARD_IMAGE_PATH = "dashboard.png"

SECTOR_GROUPS = {
    "금융": "금융",
    "금융지주": "금융",
    "은행": "금융",
    "반도체": "반도체",
    "AI": "AI/IT",
    "인터넷/플랫폼": "AI/IT",
    "데이터센터": "AI/IT",
    "자동차": "자동차/전장",
    "가전/전장": "자동차/전장",
    "자동차/전장": "자동차/전장",
    "조선/방산": "조선/방산",
    "조선/기계": "조선/방산",
    "전력": "전력",
    "2차전지": "2차전지",
    "지주회사": "지주회사",
    "생활가전": "생활가전",
    "전장": "전장",
    "통신/AI": "통신/AI",
    "항공": "항공/운송",
    "항공운송": "항공/운송",
    "여행": "항공/운송",
    "운송": "항공/운송",
    "항공/운송": "항공/운송",
}

STOCK_MASTER_SECTORS = {
    "086790": {"sector": "금융", "industry": "금융지주"},
    "105560": {"sector": "금융", "industry": "금융지주"},
    "055550": {"sector": "금융", "industry": "금융지주"},
    "000810": {"sector": "금융", "industry": "보험"},
    "032830": {"sector": "금융", "industry": "보험"},
    "006260": {"sector": "전력", "industry": "전력기기"},
    "011070": {"sector": "전장", "industry": "전자부품"},
    "021240": {"sector": "생활가전", "industry": "렌탈/생활가전"},
    "017670": {"sector": "통신/AI", "industry": "통신"},
    "402340": {"sector": "반도체", "industry": "반도체지주"},
    "009150": {"sector": "전자부품", "industry": "전자부품"},
    "034730": {"sector": "지주회사", "industry": "지주회사"},
    "005930": {"sector": "반도체", "industry": "반도체"},
    "005935": {"sector": "반도체", "industry": "반도체"},
    "000660": {"sector": "반도체", "industry": "반도체"},
    "353200": {"sector": "반도체", "industry": "전자부품"},
    "033780": {"sector": "소비재", "industry": "필수소비재"},
    "259960": {"sector": "게임", "industry": "게임"},
    "034020": {"sector": "전력", "industry": "전력/원전"},
    "035420": {"sector": "AI/IT", "industry": "인터넷/플랫폼"},
    "035720": {"sector": "AI/IT", "industry": "인터넷/플랫폼"},
    "005380": {"sector": "자동차", "industry": "완성차"},
    "012330": {"sector": "전장", "industry": "자동차부품"},
    "068270": {"sector": "바이오", "industry": "바이오"},
    "207940": {"sector": "바이오", "industry": "바이오"},
    "003490": {
        "sector": "항공/운송",
        "industry": "항공운송",
        "representative_themes": ["항공", "여행", "운송"],
    },
    "006400": {"sector": "2차전지/배터리", "industry": "일차전지 및 이차전지 제조업"},
    "052690": {"sector": "원전/엔지니어링", "industry": "건축기술, 엔지니어링 및 관련 기술 서비스업"},
    "000150": {"sector": "지주/전자소재", "industry": "회사 본부 및 경영 컨설팅 서비스업"},
    "443060": {"sector": "조선/선박서비스", "industry": "건축기술, 엔지니어링 및 관련 기술 서비스업"},
    "000500": {"sector": "전선/전력인프라", "industry": "절연선 및 케이블 제조업"},
    "009540": {"sector": "조선/조선지주", "industry": "기타 금융업"},
    "329180": {"sector": "조선/선박제조", "industry": "선박 및 보트 건조업"},
    "078930": {"sector": "지주/에너지", "industry": "기타 금융업"},
    "090430": {"sector": "소비재/화장품", "industry": "기타 화학제품 제조업"},
}

STOCK_MASTER_BY_NAME = {
    "하나금융지주": STOCK_MASTER_SECTORS["086790"],
    "KB금융": STOCK_MASTER_SECTORS["105560"],
    "신한지주": STOCK_MASTER_SECTORS["055550"],
    "삼성화재": STOCK_MASTER_SECTORS["000810"],
    "삼성생명": STOCK_MASTER_SECTORS["032830"],
    "LS": STOCK_MASTER_SECTORS["006260"],
    "LG이노텍": STOCK_MASTER_SECTORS["011070"],
    "코웨이": STOCK_MASTER_SECTORS["021240"],
    "SK텔레콤": STOCK_MASTER_SECTORS["017670"],
    "SK스퀘어": STOCK_MASTER_SECTORS["402340"],
    "삼성전기": STOCK_MASTER_SECTORS["009150"],
    "SK": STOCK_MASTER_SECTORS["034730"],
    "두산에너빌리티": STOCK_MASTER_SECTORS["034020"],
    "NAVER": STOCK_MASTER_SECTORS["035420"],
    "카카오": STOCK_MASTER_SECTORS["035720"],
    "현대차": STOCK_MASTER_SECTORS["005380"],
    "현대모비스": STOCK_MASTER_SECTORS["012330"],
    "셀트리온": STOCK_MASTER_SECTORS["068270"],
    "삼성바이오로직스": STOCK_MASTER_SECTORS["207940"],
    "대한항공": STOCK_MASTER_SECTORS["003490"],
    "HD현대마린솔루션": STOCK_MASTER_SECTORS["443060"],
    "가온전선": STOCK_MASTER_SECTORS["000500"],
    "삼성SDI": STOCK_MASTER_SECTORS["006400"],
    "한전기술": STOCK_MASTER_SECTORS["052690"],
    "두산": STOCK_MASTER_SECTORS["000150"],
    "HD한국조선해양": STOCK_MASTER_SECTORS["009540"],
    "HD현대중공업": STOCK_MASTER_SECTORS["329180"],
    "GS": STOCK_MASTER_SECTORS["078930"],
    "아모레퍼시픽": STOCK_MASTER_SECTORS["090430"],
}


SCORE_DETAIL_FIELDS = (
    "score_liquidity",
    "score_volume",
    "score_trend",
    "score_breakout",
    "score_box",
    "score_vcp",
    "score_rs",
    "score_risk",
    "score_overheat",
)


def _format_currency(value: int) -> str:
    """숫자를 원화 형식으로 보여줍니다."""
    return f"{value:,}원"


def _format_kst_now() -> str:
    """메시지와 대시보드에 사용할 한국시간 기준시각입니다."""
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def _format_news_relevance(value: object) -> str:
    """뉴스 분석 내부 상태를 사용자에게 이해하기 쉬운 문구로 바꿉니다."""
    labels = {
        "DIRECT": "종목 직접 관련",
        "MATCH": "종목 관련",
        "SECTOR": "업종 관련",
        "WEAK": "관련성 낮음",
        "MISMATCH": "비관련 기사 제외",
        "NONE": "관련 뉴스 없음",
    }
    return labels.get(str(value or "NONE"), "관련 뉴스 없음")


def _build_title(mode: str) -> str:
    """메시지 상단 제목을 만듭니다."""
    if mode == "real":
        return "[국내주식 조건 기반 관심종목][실데이터 모드]"
    return "[국내주식 조건 기반 관심종목][샘플 모드]"


def _append_dashboard_link(lines: list[str]) -> None:
    """텔레그램과 콘솔 메시지 하단에 웹 대시보드 링크를 붙입니다."""
    lines.append("")
    lines.append("🌐 대시보드")
    lines.append(DASHBOARD_URL)


def _normalize_sector(theme: str) -> str:
    """비슷한 테마를 하나의 섹터 그룹으로 정규화합니다."""
    normalized = (theme or "기타").strip()
    return SECTOR_GROUPS.get(normalized, normalized or "기타")


def _normalize_listing_sector(sector: str, industry: str) -> str:
    """KRX 원업종을 투자자가 읽기 쉬운 섹터로 정규화합니다."""
    text = f"{sector} {industry}".strip().lower()
    mappings = (
        (("이차전지", "2차전지", "축전지", "배터리"), "2차전지/배터리"),
        (("원자력", "원전"), "원전/엔지니어링"),
        (("전선", "케이블", "송전", "배전"), "전선/전력인프라"),
        (("은행", "금융", "보험", "증권"), "금융"),
        (("반도체",), "반도체"),
        (("변압기", "발전기", "전력"), "전력기기/인프라"),
        (("자동차",), "자동차/전장"),
        (("선박", "조선"), "조선/선박서비스"),
        (("항공", "운송"), "항공/운송"),
        (("의약", "바이오"), "바이오"),
        (("소프트웨어", "정보서비스", "인터넷", "통신"), "AI/IT"),
        (("가정용 기기", "생활가전", "생활용품"), "생활가전"),
        (("화장품",), "소비재/화장품"),
        (("오디오물", "음반", "연예", "방송", "영상"), "엔터/미디어"),
        (("엔지니어링", "건축기술"), "산업재/엔지니어링"),
    )
    for keywords, group in mappings:
        if any(keyword in text for keyword in keywords):
            return group
    return UNCLASSIFIED_SECTOR


def _resolve_master_classification(
    ticker: str,
    name: str,
    fallback_theme: str,
    listing_sector: str = "",
    listing_industry: str = "",
) -> tuple[str, str, list[str]]:
    """투자용 sector와 공식 industry_raw를 분리해 반환합니다."""
    master = STOCK_MASTER_SECTORS.get(ticker) or STOCK_MASTER_BY_NAME.get(name)
    if master:
        themes = master.get("representative_themes") or [master["sector"]]
        industry_raw = (listing_sector or listing_industry or master["industry"]).strip()
        return master["sector"], industry_raw, list(themes)

    if listing_sector or listing_industry:
        sector_group = _normalize_listing_sector(listing_sector, listing_industry)
        market_departments = ("기업부", "소속부없음")
        use_industry = listing_industry and any(
            marker in listing_sector for marker in market_departments
        )
        industry_group = (listing_industry if use_industry else listing_sector or listing_industry).strip()
        return sector_group, industry_group, [sector_group]

    news_theme = (fallback_theme or "").strip()
    representative_themes = [news_theme] if news_theme and news_theme != "기타" else []
    return UNCLASSIFIED_SECTOR, UNCLASSIFIED_SECTOR, representative_themes


def _log_theme_resolution(
    *,
    ticker: str,
    name: str,
    fallback_theme: str,
    sector_group: str,
    industry_group: str,
    representative_themes: list[str],
) -> None:
    themes = ", ".join(representative_themes) if representative_themes else sector_group
    print(
        "[theme-resolution] "
        f"{ticker} {name} | news_theme={fallback_theme or 'N/A'} "
        f"-> sector={sector_group}, industry={industry_group}, representative_themes={themes}"
    )


def _format_change_pct(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "N/A"
    sign = "+" if numeric > 0 else ""
    return f"{sign}{numeric:.2f}%"


def _filter_strategy_results(
    strategy_results: dict[str, list[dict]],
    strategy: Optional[str] = None,
) -> dict[str, list[dict]]:
    """특정 전략만 보고 싶을 때 결과를 고릅니다."""
    if strategy is None:
        return strategy_results
    return {strategy: strategy_results.get(strategy, [])}


def _get_vcp_core_candidates(items: list[dict]) -> list[dict]:
    """진짜 VCP 조건을 만족하는 swing 핵심 후보입니다."""
    candidates = [
        item
        for item in items
        if item.get("recent_20d_volatility", 0) > item.get("recent_10d_volatility", 0) > item.get("recent_5d_volatility", 0)
        and item.get("vol5_ratio", 0) >= 1.05
    ]
    candidates.sort(key=lambda row: row["total_score"], reverse=True)
    return candidates[:3]


def _get_semi_vcp_candidates(items: list[dict]) -> list[dict]:
    """변동성 축소가 일부 보이는 준 VCP 후보입니다."""
    candidates = [
        item
        for item in items
        if (
            item.get("recent_20d_volatility", 0) > item.get("recent_10d_volatility", 0)
            or item.get("recent_10d_volatility", 0) > item.get("recent_5d_volatility", 0)
        )
        and item.get("vol5_ratio", 0) >= 1.0
    ]
    candidates.sort(key=lambda row: row["total_score"], reverse=True)
    return candidates[:3]


def _get_breakout_candidates(items: list[dict]) -> list[dict]:
    """박스 상단 돌파와 거래량 증가가 보이는 후보입니다."""
    candidates = [
        item
        for item in items
        if item.get("current_price", 0) >= item.get("box_high", 0)
        and item.get("vol_ratio", 0) >= 1.3
    ]
    candidates.sort(key=lambda row: row["total_score"], reverse=True)
    return candidates[:3]


def _get_vcp_theme_candidates(items: list[dict]) -> list[dict]:
    """VCP 조건과 뉴스/테마 점수를 함께 만족하는 후보입니다."""
    core_candidates = _get_vcp_core_candidates(items)
    themed = [item for item in core_candidates if item.get("news_score", 0) > 0 and item.get("theme")]
    themed.sort(key=lambda row: row["total_score"], reverse=True)
    return themed[:3]


def _summarize_recommendation_reason(candidate: dict) -> str:
    """최종 추천의 핵심 이유를 1~2문장으로 요약합니다."""
    parts: list[str] = []
    if candidate.get("swing_score", 0) > 0:
        parts.append(f"박스 {candidate.get('box_range_pct', 0)}% 구간과 VCP 흐름을 확인했습니다.")
    if candidate.get("short_score", 0) > 0 and candidate.get("strategy_type") in ("short", "혼합"):
        parts.append(f"단기 거래량이 20일 평균 대비 {candidate.get('vol_ratio', 0)}배 수준입니다.")
    if candidate.get("mid_score", 0) > 0 and candidate.get("strategy_type") == "mid":
        parts.append("중기 추세·유동성 조건을 통과했습니다.")
    if candidate.get("news_score", 0) > 0 and candidate.get("theme") and candidate.get("theme") != "기타":
        parts.append(f"{candidate['theme']} 테마 뉴스 흐름이 반영됐습니다.")
    return " ".join(parts[:2]) or "기술적 조건과 뉴스 흐름을 함께 고려했습니다."


def _copy_score_fields(entry: dict, item: dict) -> None:
    for field in SCORE_DETAIL_FIELDS:
        entry[field] = item.get(field, entry.get(field, 0))
    for field in (
        "high52_ratio",
        "high52_distance_pct",
        "rs_1m",
        "rs_3m",
        "rs_6m",
        "staged_contraction",
        "volume_contraction_ratio",
        "volume_contraction",
        "pivot_ready",
    ):
        entry[field] = item.get(field, entry.get(field, 0))


def _copy_strategy_trade_levels(entry: dict, item: dict, strategy: str) -> None:
    """Keep each strategy's exit levels separate while candidates are merged."""
    entry[f"{strategy}_stop_loss"] = item.get("stop_loss")
    entry[f"{strategy}_target_price"] = item.get("target_price")


def _score_detail_from_entry(entry: dict) -> dict:
    technical_score = (
        entry.get("score_breakout", 0)
        + entry.get("score_box", 0)
        + entry.get("score_vcp", 0)
        + entry.get("score_rs", 0)
        + entry.get("score_risk", 0)
        + entry.get("score_overheat", 0)
    )
    return {
        "뉴스 점수": int(entry.get("news_score", 0)),
        "거래량 점수": int(entry.get("score_volume", 0)),
        "추세 점수": int(entry.get("score_trend", 0)),
        "기술적 점수": int(technical_score),
        "총점": float(entry.get("recommendation_score", entry.get("final_score", 0))),
    }


def _passes_vcp_gate(candidate: dict) -> bool:
    """A급 인정용 강한 VCP 조건을 체크합니다."""
    return (
        candidate.get("swing_score", 0) > 0
        and candidate.get("recent_20d_volatility", 0) > candidate.get("recent_10d_volatility", 0) > candidate.get("recent_5d_volatility", 0)
        and candidate.get("vol5_ratio", 0) >= 1.05
        and candidate.get("vol_ratio", 0) >= 1.1
        and candidate.get("current_price", 0) >= candidate.get("box_high", 0) * 0.95
    )


def _append_unique_sector(
    items: list[dict],
    selected: list[dict],
    used_sectors: set[str],
    limit: int,
) -> None:
    """섹터 중복 없이 상위 종목만 담습니다."""
    for row in items:
        if len(selected) >= limit:
            break
        sector = row["sector_group"]
        if sector in used_sectors:
            continue
        selected.append(row)
        used_sectors.add(sector)


def _append_unique_ticker(items: list[dict], selected: list[dict], limit: int) -> None:
    """섹터 제한 없이 점수 상위 종목을 중복 없이 채웁니다."""
    selected_tickers = {row["ticker"] for row in selected}
    for row in items:
        if len(selected) >= limit:
            break
        if row["ticker"] in selected_tickers:
            continue
        selected.append(row)
        selected_tickers.add(row["ticker"])


def _calculate_final_score(entry: dict) -> float:
    """최종 추천용 점수를 계산합니다."""
    theme_score = min(100, int(entry["news_score"]) * 10)
    score = entry["swing_score"] * 0.4 + entry["short_score"] * 0.3 + theme_score * 0.3
    return round(score, 1)


def _calculate_observation_score(entry: dict) -> float:
    """시장 흐름 관찰용 점수를 조금 더 넓게 계산합니다."""
    theme_score = min(100, int(entry["news_score"]) * 10)
    trend_mix = max(entry["short_score"], entry["swing_score"], entry.get("mid_score", 0))
    score = max(
        _calculate_final_score(entry),
        entry.get("mid_score", 0) * 0.75 + theme_score * 0.25,
        trend_mix * 0.7 + theme_score * 0.3,
    )
    return round(score, 1)


def _grade_for_score(score: float) -> str:
    if score >= SETTINGS.grade_a_threshold:
        return "A"
    if score >= SETTINGS.grade_b_threshold:
        return "B"
    return "관찰"


def _change_warning(change_pct: object) -> str:
    try:
        numeric_change = float(change_pct)
    except (TypeError, ValueError):
        return ""
    if numeric_change >= 7:
        return "주의: 당일 급등 후 추격매수 위험"
    if numeric_change <= -5:
        return "주의: 단기 낙폭 확대"
    return ""


def _can_add_candidate(
    candidate: dict,
    selected: list[dict],
    sector_counts: dict[str, int],
    industry_counts: dict[str, int],
) -> bool:
    if candidate["ticker"] in {row["ticker"] for row in selected}:
        return False
    sector_limit = max(1, SETTINGS.max_per_sector)
    sector_group = candidate["sector_group"]
    if (
        sector_group != UNCLASSIFIED_SECTOR
        and sector_counts.get(sector_group, 0) >= sector_limit
    ):
        return False
    return True


def _select_diversified_candidates(candidates: list[dict], limit: int) -> list[dict]:
    """점수순을 유지하되 동일 섹터/산업군 쏠림을 제한합니다."""
    eligible = list(candidates)
    eligible.sort(key=lambda row: row["recommendation_score"], reverse=True)

    selected: list[dict] = []
    sector_counts: dict[str, int] = defaultdict(int)
    industry_counts: dict[str, int] = defaultdict(int)

    for candidate in eligible:
        if len(selected) >= limit:
            break
        if not _can_add_candidate(candidate, selected, sector_counts, industry_counts):
            continue
        selected.append(candidate)
        sector_counts[candidate["sector_group"]] += 1
        industry_counts[candidate["industry_group"]] += 1

    available_sectors = {
        row["sector_group"]
        for row in eligible
        if row["sector_group"] != UNCLASSIFIED_SECTOR
    }
    target_sector_count = min(3, len(available_sectors), limit)
    selected_sectors = {
        row["sector_group"]
        for row in selected
        if row["sector_group"] != UNCLASSIFIED_SECTOR
    }
    if len(selected_sectors) < target_sector_count:
        selected_tickers = {row["ticker"] for row in selected}
        for candidate in eligible:
            if len(selected_sectors) >= target_sector_count:
                break
            if candidate["sector_group"] == UNCLASSIFIED_SECTOR:
                continue
            if candidate["ticker"] in selected_tickers or candidate["sector_group"] in selected_sectors:
                continue
            replace_index = next(
                (
                    index
                    for index, row in sorted(
                        enumerate(selected),
                        key=lambda pair: pair[1]["recommendation_score"],
                    )
                    if (
                        row["sector_group"] == UNCLASSIFIED_SECTOR
                        or sector_counts[row["sector_group"]] > 1
                    )
                ),
                None,
            )
            if replace_index is None:
                continue
            removed = selected[replace_index]
            sector_counts[removed["sector_group"]] -= 1
            industry_counts[removed["industry_group"]] -= 1
            selected[replace_index] = candidate
            sector_counts[candidate["sector_group"]] += 1
            industry_counts[candidate["industry_group"]] += 1
            selected_tickers = {row["ticker"] for row in selected}
            selected_sectors = {
                row["sector_group"]
                for row in selected
                if row["sector_group"] != UNCLASSIFIED_SECTOR
            }

    selected.sort(key=lambda row: row["recommendation_score"], reverse=True)
    return selected[:limit]


def _build_final_recommendations(strategy_results: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """조건 → 필터 → 출력 순서로 A급/관찰 후보를 구성합니다."""
    merged_by_ticker: dict[str, dict] = {}

    for item in strategy_results.get("short", []):
        entry = merged_by_ticker.setdefault(
            item["ticker"],
            {
                "ticker": item["ticker"],
                "name": item["name"],
                "current_price": item["current_price"],
                "price_date": item.get("price_date", ""),
                "change_pct": item.get("change_pct"),
                "trading_value": item["trading_value"],
                "theme": item.get("theme", "기타"),
                "recent_news_keywords": item.get("recent_news_keywords", ""),
                "issue_summary": item.get("issue_summary", ""),
                "news_score": item.get("news_score", 0),
                "news_relevance": item.get("news_relevance", "NONE"),
                "news_items": item.get("news_items", []),
                "listing_sector": item.get("listing_sector", ""),
                "listing_industry": item.get("listing_industry", ""),
                "short_score": 0,
                "swing_score": 0,
                "mid_score": 0,
                "vol_ratio": item.get("vol_ratio", 0),
                "vol5_ratio": item.get("vol5_ratio", 0),
                "box_high": item.get("box_high", 0),
                "box_range_pct": item.get("box_range_pct", 0),
                "recent_5d_volatility": item.get("recent_5d_volatility", 0),
                "recent_10d_volatility": item.get("recent_10d_volatility", 0),
                "recent_20d_volatility": item.get("recent_20d_volatility", 0),
            },
        )
        if item["total_score"] > entry["short_score"]:
            entry["short_score"] = item["total_score"]
            entry["current_price"] = item["current_price"]
            entry["price_date"] = item.get("price_date", entry.get("price_date", ""))
            entry["change_pct"] = item.get("change_pct", entry.get("change_pct"))
            entry["trading_value"] = max(entry["trading_value"], item["trading_value"])
            entry["vol_ratio"] = item.get("vol_ratio", entry["vol_ratio"])
            entry["vol5_ratio"] = item.get("vol5_ratio", entry["vol5_ratio"])
            entry["theme"] = item.get("theme", entry["theme"])
            entry["recent_news_keywords"] = item.get("recent_news_keywords", entry["recent_news_keywords"])
            entry["issue_summary"] = item.get("issue_summary", entry["issue_summary"])
            entry["news_score"] = max(entry["news_score"], item.get("news_score", 0))
            entry["news_relevance"] = item.get("news_relevance", entry.get("news_relevance", "NONE"))
            entry["news_items"] = item.get("news_items", entry.get("news_items", []))
            entry["listing_sector"] = item.get("listing_sector", entry.get("listing_sector", ""))
            entry["listing_industry"] = item.get("listing_industry", entry.get("listing_industry", ""))
            _copy_score_fields(entry, item)
            _copy_strategy_trade_levels(entry, item, "short")

    for item in strategy_results.get("swing", []):
        entry = merged_by_ticker.setdefault(
            item["ticker"],
            {
                "ticker": item["ticker"],
                "name": item["name"],
                "current_price": item["current_price"],
                "price_date": item.get("price_date", ""),
                "change_pct": item.get("change_pct"),
                "trading_value": item["trading_value"],
                "theme": item.get("theme", "기타"),
                "recent_news_keywords": item.get("recent_news_keywords", ""),
                "issue_summary": item.get("issue_summary", ""),
                "news_score": item.get("news_score", 0),
                "news_relevance": item.get("news_relevance", "NONE"),
                "news_items": item.get("news_items", []),
                "listing_sector": item.get("listing_sector", ""),
                "listing_industry": item.get("listing_industry", ""),
                "short_score": 0,
                "swing_score": 0,
                "mid_score": 0,
                "vol_ratio": item.get("vol_ratio", 0),
                "vol5_ratio": item.get("vol5_ratio", 0),
                "box_high": item.get("box_high", 0),
                "box_range_pct": item.get("box_range_pct", 0),
                "recent_5d_volatility": item.get("recent_5d_volatility", 0),
                "recent_10d_volatility": item.get("recent_10d_volatility", 0),
                "recent_20d_volatility": item.get("recent_20d_volatility", 0),
            },
        )
        if item["total_score"] > entry["swing_score"]:
            entry["swing_score"] = item["total_score"]
            entry["current_price"] = item["current_price"]
            entry["price_date"] = item.get("price_date", entry.get("price_date", ""))
            entry["change_pct"] = item.get("change_pct", entry.get("change_pct"))
            entry["trading_value"] = max(entry["trading_value"], item["trading_value"])
            entry["vol_ratio"] = item.get("vol_ratio", entry["vol_ratio"])
            entry["vol5_ratio"] = item.get("vol5_ratio", entry["vol5_ratio"])
            entry["box_high"] = item.get("box_high", entry["box_high"])
            entry["box_range_pct"] = item.get("box_range_pct", entry["box_range_pct"])
            entry["recent_5d_volatility"] = item.get("recent_5d_volatility", entry["recent_5d_volatility"])
            entry["recent_10d_volatility"] = item.get("recent_10d_volatility", entry["recent_10d_volatility"])
            entry["recent_20d_volatility"] = item.get("recent_20d_volatility", entry["recent_20d_volatility"])
            entry["theme"] = item.get("theme", entry["theme"])
            entry["recent_news_keywords"] = item.get("recent_news_keywords", entry["recent_news_keywords"])
            entry["issue_summary"] = item.get("issue_summary", entry["issue_summary"])
            entry["news_score"] = max(entry["news_score"], item.get("news_score", 0))
            entry["news_relevance"] = item.get("news_relevance", entry.get("news_relevance", "NONE"))
            entry["news_items"] = item.get("news_items", entry.get("news_items", []))
            entry["listing_sector"] = item.get("listing_sector", entry.get("listing_sector", ""))
            entry["listing_industry"] = item.get("listing_industry", entry.get("listing_industry", ""))
            _copy_score_fields(entry, item)
            _copy_strategy_trade_levels(entry, item, "swing")

    for item in strategy_results.get("mid", []):
        entry = merged_by_ticker.setdefault(
            item["ticker"],
            {
                "ticker": item["ticker"],
                "name": item["name"],
                "current_price": item["current_price"],
                "price_date": item.get("price_date", ""),
                "change_pct": item.get("change_pct"),
                "trading_value": item["trading_value"],
                "theme": item.get("theme", "기타"),
                "recent_news_keywords": item.get("recent_news_keywords", ""),
                "issue_summary": item.get("issue_summary", ""),
                "news_score": item.get("news_score", 0),
                "news_relevance": item.get("news_relevance", "NONE"),
                "news_items": item.get("news_items", []),
                "listing_sector": item.get("listing_sector", ""),
                "listing_industry": item.get("listing_industry", ""),
                "short_score": 0,
                "swing_score": 0,
                "mid_score": 0,
                "vol_ratio": item.get("vol_ratio", 0),
                "vol5_ratio": item.get("vol5_ratio", 0),
                "box_high": item.get("box_high", 0),
                "box_range_pct": item.get("box_range_pct", 0),
                "recent_5d_volatility": item.get("recent_5d_volatility", 0),
                "recent_10d_volatility": item.get("recent_10d_volatility", 0),
                "recent_20d_volatility": item.get("recent_20d_volatility", 0),
            },
        )
        if item["total_score"] > entry["mid_score"]:
            entry["mid_score"] = item["total_score"]
            entry["current_price"] = item["current_price"]
            entry["price_date"] = item.get("price_date", entry.get("price_date", ""))
            entry["change_pct"] = item.get("change_pct", entry.get("change_pct"))
            entry["trading_value"] = max(entry["trading_value"], item["trading_value"])
            entry["theme"] = item.get("theme", entry["theme"])
            entry["recent_news_keywords"] = item.get("recent_news_keywords", entry["recent_news_keywords"])
            entry["issue_summary"] = item.get("issue_summary", entry["issue_summary"])
            entry["news_score"] = max(entry["news_score"], item.get("news_score", 0))
            entry["news_relevance"] = item.get("news_relevance", entry.get("news_relevance", "NONE"))
            entry["news_items"] = item.get("news_items", entry.get("news_items", []))
            entry["listing_sector"] = item.get("listing_sector", entry.get("listing_sector", ""))
            entry["listing_industry"] = item.get("listing_industry", entry.get("listing_industry", ""))
            _copy_score_fields(entry, item)
            _copy_strategy_trade_levels(entry, item, "mid")

    all_candidates: list[dict] = []
    for entry in merged_by_ticker.values():
        if entry["trading_value"] < SETTINGS.min_trading_value:
            continue
        final_score = _calculate_final_score(entry)
        observation_score = _calculate_observation_score(entry)

        if entry["short_score"] >= 60 and entry["swing_score"] >= 60:
            strategy_type = "혼합"
        elif entry["mid_score"] >= max(entry["short_score"], entry["swing_score"]):
            strategy_type = "mid"
        elif entry["swing_score"] >= entry["short_score"]:
            strategy_type = "swing"
        else:
            strategy_type = "short"

        enriched = dict(entry)
        enriched["final_score"] = round(final_score, 1)
        enriched["observation_score"] = round(observation_score, 1)
        enriched["recommendation_score"] = round(observation_score, 1)
        enriched["grade"] = _grade_for_score(enriched["recommendation_score"])
        enriched["strategy_type"] = strategy_type
        level_strategy = strategy_type
        if strategy_type == "혼합":
            level_strategy = "swing" if entry["swing_score"] >= entry["short_score"] else "short"
        enriched["stop_loss"] = entry.get(f"{level_strategy}_stop_loss")
        enriched["target_price"] = entry.get(f"{level_strategy}_target_price")
        fallback_theme = enriched.get("theme", "기타")
        sector_group, industry_group, representative_themes = _resolve_master_classification(
            enriched["ticker"],
            enriched["name"],
            fallback_theme,
            enriched.get("listing_sector", ""),
            enriched.get("listing_industry", ""),
        )
        enriched["sector_group"] = sector_group
        enriched["industry_group"] = industry_group
        enriched["industry_raw"] = industry_group
        enriched["representative_themes"] = representative_themes
        enriched["news_theme"] = fallback_theme
        _log_theme_resolution(
            ticker=enriched["ticker"],
            name=enriched["name"],
            fallback_theme=fallback_theme,
            sector_group=sector_group,
            industry_group=industry_group,
            representative_themes=representative_themes,
        )
        enriched["change_warning"] = _change_warning(enriched.get("change_pct"))
        enriched["summary_reason"] = _summarize_recommendation_reason(enriched)
        enriched["score_detail"] = _score_detail_from_entry(enriched)
        all_candidates.append(enriched)

    selectable_candidates = [
        row
        for row in all_candidates
        if row["recommendation_score"] >= SETTINGS.watch_min_score
    ]
    selected = _select_diversified_candidates(selectable_candidates, SETTINGS.final_recommendation_limit)
    ranked_candidates = sorted(
        all_candidates,
        key=lambda row: row["recommendation_score"],
        reverse=True,
    )
    selected_a = [row for row in selected if row["grade"] == "A"]
    selected_b = [row for row in selected if row["grade"] == "B"]
    selected_observation = [row for row in selected if row["grade"] == "관찰"]

    return {
        "grade_a": selected_a,
        "grade_b": selected_b,
        "watch": selected_observation,
        "selected": selected,
        "all_candidates": ranked_candidates,
    }


def build_symbol_debug_message(ticker_or_name: str) -> str:
    """자동추천 범위와 무관하게 지정 종목을 쉬운 표현으로 분석합니다."""
    query = str(ticker_or_name or "").strip()
    if not query:
        return "사용법: /search 종목코드 또는 종목명\n예시: /search 000500"

    symbol_info = debug_symbol(query)
    if not symbol_info.get("found", True):
        return "\n".join(
            [
                f"[종목 분석] {query}",
                "종목 확인: 찾지 못함",
                symbol_info.get("failure_reason", "종목명 또는 종목코드를 확인해 주세요."),
            ]
        )

    diagnostic = symbol_info["diagnostic"]
    news = symbol_info["news"]
    direct_strategy_results: dict[str, list[dict]] = {"short": [], "swing": [], "mid": []}
    for item in symbol_info.get("candidates", []):
        strategy_name = item.get("strategy")
        if strategy_name in direct_strategy_results:
            direct_strategy_results[strategy_name].append(item)
    final_groups = _build_final_recommendations(direct_strategy_results)
    ticker = diagnostic["ticker"]
    candidate = next(
        (item for item in final_groups["all_candidates"] if item["ticker"] == ticker),
        None,
    )
    sector, industry_raw, _themes = _resolve_master_classification(
        ticker,
        diagnostic["name"],
        news.get("theme", ""),
        symbol_info.get("listing_sector", ""),
        symbol_info.get("listing_industry", ""),
    )
    reference_price = symbol_info.get("current_price")
    if reference_price:
        save_tracked_stock(
            source="search",
            ticker=ticker,
            name=diagnostic["name"],
            reference_price=reference_price,
            price_date=symbol_info.get("price_date", ""),
            score=candidate.get("recommendation_score", 0) if candidate else 0,
            strategy=candidate.get("strategy_type", "") if candidate else "",
            sector=sector,
            stop_price=candidate.get("stop_loss") if candidate else None,
            target_price=candidate.get("target_price") if candidate else None,
        )

    universe_included = bool(symbol_info.get("universe_included"))
    universe_status = "포함" if universe_included else "미포함"
    universe_note = (
        "자동추천 실행 시 점수 경쟁 대상입니다."
        if universe_included
        else "자동추천 범위 밖이지만, 요청한 종목은 아래에서 별도로 끝까지 분석했습니다."
    )
    metrics = diagnostic.get("metrics", {})
    candidate_score = candidate.get("recommendation_score", 0) if candidate else 0
    grade = (
        candidate.get("grade")
        if candidate and candidate_score >= SETTINGS.watch_min_score
        else "추천 기준 미달"
    )
    score_text = f"{candidate.get('recommendation_score', 0):.1f}점" if candidate else "산출 안 됨"
    volume_contraction = "예" if metrics.get("volume_contraction") else "아니오"
    staged_contraction = "예" if metrics.get("staged_contraction") else "아니오"

    lines = [
        f"[종목 분석] {diagnostic['name']} / {ticker}",
        f"기준가격: {_format_currency(int(symbol_info.get('current_price', 0)))} ({symbol_info.get('price_date', '-')})",
        "",
        "[자동추천 대상 여부]",
        f"자동추천 분석 대상: {universe_status}",
        f"선정 범위: {symbol_info.get('universe_description', '설정된 자동추천 대상 종목')}",
        f"안내: {universe_note}",
        "",
        "[종합 판단]",
        f"판정: {grade}",
        f"종합점수: {score_text}",
        f"적합 전략: {candidate.get('strategy_type', '-') if candidate else '-'}",
        f"기술적 기본조건: {'통과' if diagnostic.get('technical_filter') == 'PASS' else '미충족'}",
        f"추세 상태: {'양호' if diagnostic.get('trend') == 'PASS' else '확인 필요'}",
        f"거래대금 조건: {'충족' if diagnostic.get('liquidity') == 'PASS' else '부족'}",
        f"급락 위험 신호: {'이상 없음' if diagnostic.get('risk_filter') == 'PASS' else '주의'}",
        "",
        "[주가 흐름]",
        f"당일 등락률: {metrics.get('change_pct', 0):+.2f}%",
        f"52주 최고가와의 거리: {metrics.get('high52_distance_pct', 0):+.2f}%",
        (
            "시장 대비 주가 흐름: "
            f"1개월 {metrics.get('rs_1m', 0):+.2f}%p / "
            f"3개월 {metrics.get('rs_3m', 0):+.2f}%p / "
            f"6개월 {metrics.get('rs_6m', 0):+.2f}%p"
        ),
        f"당일 거래량: 20일 평균의 {metrics.get('vol_ratio', 0):.2f}배",
        f"거래량 감소 여부: {volume_contraction} ({metrics.get('volume_contraction_ratio', 0):.2f}배)",
        f"가격 변동폭 단계적 축소: {staged_contraction}",
        "",
        "[업종·뉴스]",
        f"업종: {sector}",
        f"세부 업종: {industry_raw or '확인되지 않음'}",
        f"주요 테마: {news.get('theme') or '없음'}",
        f"뉴스 관련성: {_format_news_relevance(news.get('news_relevance'))}",
        f"뉴스 점수: {news.get('news_score', 0)}점",
    ]
    if news.get("issue_summary"):
        lines.append(f"최근 이슈: {news['issue_summary']}")

    lines.extend(["", "[전략별 판단]"])
    strategy_labels = {
        "short": ("단기", ("short_primary", "short_fallback")),
        "swing": ("스윙", ("swing_primary",)),
        "mid": ("중기", ("mid_primary", "mid_fallback")),
    }
    for strategy_key, (label, diagnostic_keys) in strategy_labels.items():
        strategy_candidate = next(
            (item for item in symbol_info.get("candidates", []) if item.get("strategy") == strategy_key),
            None,
        )
        if strategy_candidate:
            lines.append(f"- {label}: 통과 ({strategy_candidate.get('total_score', 0)}점)")
            continue
        details = [diagnostic.get("strategies", {}).get(key, {}) for key in diagnostic_keys]
        reason = next(
            (detail.get("failure_reason") for detail in details if detail.get("failure_reason")),
            "조건 미충족",
        )
        lines.append(f"- {label}: 미충족 — {reason}")

    lines.extend(["", "[최종 의견]"])
    if candidate:
        lines.append(candidate.get("summary_reason") or "기술 조건과 뉴스 흐름을 함께 확인했습니다.")
        if candidate.get("change_warning"):
            lines.append(candidate["change_warning"])
    else:
        lines.append(
            diagnostic.get("failure_reason")
            or "현재는 추천 전략의 기본조건을 충족하지 못해 관찰이 필요합니다."
        )
    return "\n".join(lines)


def _build_strategy_recommendations(strategy_results: dict[str, list[dict]], strategy: str) -> list[dict]:
    """전략 전용 요청에서 사용할 최대 5개 결과입니다."""
    items = strategy_results.get(strategy, [])[: SETTINGS.top_n_per_strategy]
    recommendations: list[dict] = []
    for item in items:
        recommendations.append(
            {
                "ticker": item["ticker"],
                "name": item["name"],
                "current_price": item["current_price"],
                "theme": item.get("theme", "기타"),
                "issue_summary": item.get("issue_summary", "특이 이슈 없음 (기술적 흐름 기반)"),
                "final_score": item["total_score"],
            }
        )
    return recommendations


def _append_ranked_recommendations(
    lines: list[str],
    title: str,
    items: list[dict],
    empty_message: Optional[str] = None,
    start_index: int = 1,
    score_key: str = "final_score",
) -> int:
    """최종 추천/관찰 섹션을 출력합니다."""
    lines.append(title)
    if not items:
        if empty_message:
            lines.append(empty_message)
            lines.append("")
        return start_index

    current_index = start_index
    for item in items:
        score_value = item.get(score_key, item.get("final_score", 0))
        lines.append(
            f"{current_index}. {item['name']} / {score_value}점 / "
            f"{item['sector_group']} / {item['strategy_type']}"
        )
        lines.append(f"현재가: {_format_currency(int(item.get('current_price') or 0))}")
        lines.append(f"등락률: {_format_change_pct(item.get('change_pct'))}")
        lines.append(f"뉴스 연관성: {item.get('news_relevance', 'NONE')}")
        if item.get("change_warning"):
            lines.append(item["change_warning"])
        lines.append(
            f"이슈 요약: {item.get('issue_summary', '특이 이슈 없음 (기술적 흐름 기반)') or '특이 이슈 없음 (기술적 흐름 기반)'}"
        )
        lines.append(f"핵심 선정 이유: {item['summary_reason']}")
        current_index += 1
    lines.append("")
    return current_index


def _append_group(lines: list[str], title: str, items: list[dict], kind: str) -> None:
    """swing 전용 그룹 섹션을 추가합니다."""
    lines.append(title)
    if not items:
        lines.append("조건 미충족")
        lines.append("")
        return

    for idx, item in enumerate(items, start=1):
        if kind == "core":
            lines.append(
                f"{idx}. {item['name']} / {item['ticker']} / 총점 {item['total_score']}점 / "
                f"변동성 {item['recent_20d_volatility']}% > {item['recent_10d_volatility']}% > {item['recent_5d_volatility']}% / "
                f"5일거래량 {item['vol5_ratio']}배"
            )
        elif kind == "semi":
            lines.append(
                f"{idx}. {item['name']} / {item['ticker']} / 총점 {item['total_score']}점 / "
                f"변동성 20일 {item['recent_20d_volatility']}% / 10일 {item['recent_10d_volatility']}% / 5일 {item['recent_5d_volatility']}% / "
                f"5일거래량 {item['vol5_ratio']}배"
            )
        else:
            lines.append(
                f"{idx}. {item['name']} / {item['ticker']} / 총점 {item['total_score']}점 / "
                f"박스상단 {item['box_high']:,}원 / 현재가 {item['current_price']:,}원 / "
                f"당일거래량 {item['vol_ratio']}배"
            )
    lines.append("")


def build_message(
    mode: str,
    strategy_results: dict[str, list[dict]],
    strategy: Optional[str] = None,
    error_count: int = 0,
) -> str:
    """텔레그램 전송용 문자 메시지를 만듭니다."""
    lines: list[str] = []
    lines.append(_build_title(mode))
    lines.append(f"기준시각: {_format_kst_now()}")
    if strategy:
        lines.append(f"요청 전략: {strategy}")
    lines.append("")

    filtered_results = _filter_strategy_results(strategy_results, strategy)
    target_strategies = (strategy,) if strategy else VALID_STRATEGIES

    if strategy is None:
        final_groups = _build_final_recommendations(strategy_results)
        lines.append("최종 추천 결과")
        lines.append("")
        next_index = 1
        if final_groups["grade_a"]:
            next_index = _append_ranked_recommendations(
                lines,
                "A급 추천",
                final_groups["grade_a"],
                None,
                next_index,
                "recommendation_score",
            )
        else:
            lines.append("A급 추천")
            lines.append("현재 기준 A급 없음")
            lines.append("")
            if final_groups["grade_b"]:
                next_index = _append_ranked_recommendations(
                    lines,
                    "B급 추천",
                    final_groups["grade_b"],
                    None,
                    next_index,
                    "recommendation_score",
                )
        if final_groups["grade_a"] and final_groups["grade_b"]:
            next_index = _append_ranked_recommendations(
                lines,
                "B급 추천",
                final_groups["grade_b"],
                None,
                next_index,
                "recommendation_score",
            )
        _append_ranked_recommendations(
            lines,
            "관찰 후보",
            final_groups["watch"],
            "관찰 후보 없음",
            next_index,
            "recommendation_score",
        )
        _append_dashboard_link(lines)
        return "\n".join(lines)

    if strategy == "swing":
        swing_items = filtered_results.get("swing", [])
        _append_group(lines, "VCP + 테마 TOP3", _get_vcp_theme_candidates(swing_items), "semi")
        _append_group(lines, "VCP 핵심 TOP", _get_vcp_core_candidates(swing_items), "core")
        _append_group(lines, "준 VCP 후보", _get_semi_vcp_candidates(swing_items), "semi")
        _append_group(lines, "돌파형 후보", _get_breakout_candidates(swing_items), "breakout")

    for strategy_name in target_strategies:
        lines.append(f"전략: {strategy_name}")
        items = filtered_results.get(strategy_name, [])[: SETTINGS.top_n_per_strategy]

        if not items:
            if strategy_name == "swing":
                lines.append("조건 미충족")
            else:
                lines.append("후보 종목이 없습니다.")
            lines.append("")
            continue

        for idx, item in enumerate(items, start=1):
            lines.append(f"{idx}. {item['name']} / {item['ticker']}")
            lines.append(f"현재가: {_format_currency(item['current_price'])}")
            lines.append(f"등락률: {item['change_pct']}%")
            lines.append(f"거래대금: {_format_currency(item['trading_value'])}")
            lines.append(f"총점: {item['total_score']}점")
            lines.append(f"52주 고점거리: {item.get('high52_distance_pct', 0):.2f}%")
            lines.append(
                "RS: "
                f"1개월 {item.get('rs_1m', 0):+.2f}%p / "
                f"3개월 {item.get('rs_3m', 0):+.2f}%p / "
                f"6개월 {item.get('rs_6m', 0):+.2f}%p "
                f"({item.get('score_rs', 0)}점)"
            )
            lines.append(
                f"VCP: {item.get('score_vcp', 0)}점 / "
                f"단계적 축소 {'예' if item.get('staged_contraction') else '아니오'}"
            )
            lines.append(
                f"거래량수축: {'예' if item.get('volume_contraction') else '아니오'} "
                f"({item.get('volume_contraction_ratio', 0):.2f}배)"
            )
            lines.append(f"주요 테마: {item.get('theme', '기타') or '기타'}")
            lines.append(f"최근 뉴스 키워드: {item.get('recent_news_keywords', '없음') or '없음'}")
            lines.append(f"이슈 요약: {item.get('issue_summary', '최근 이슈 없음') or '최근 이슈 없음'}")
            lines.append(f"적용 기법: {item['techniques']}")
            lines.append(f"선정 사유: {item['reason']}")
            lines.append(f"손절 기준 예시: {_format_currency(item['stop_loss'])}")
            lines.append(f"1차 목표가 예시: {_format_currency(item['target_price'])}")
            lines.append(f"주의할 점: {item['caution']}")
            lines.append("")

    if error_count:
        lines.append(f"분석 중 오류 종목 수: {error_count}")
        lines.append("")

    _append_dashboard_link(lines)
    return "\n".join(lines)


def generate_screening_message(
    mode: str = "real",
    strategy: Optional[str] = None,
) -> tuple[str, list[dict]]:
    """
    스크리닝을 실행하고 최종 메시지를 만듭니다.
    텔레그램 명령형 봇과 기존 main.py가 함께 재사용하는 함수입니다.
    """
    message, errors, _display_items = generate_screening_payload(mode=mode, strategy=strategy)
    return message, errors


def generate_screening_payload(
    mode: str = "real",
    strategy: Optional[str] = None,
) -> tuple[str, list[dict], list[dict]]:
    """텍스트 메시지와 보조 출력용 추천 리스트를 함께 만듭니다."""
    if strategy is not None and strategy not in VALID_STRATEGIES:
        raise ValueError(f"지원하지 않는 전략입니다: {strategy}")

    strategy_results, flat_results, errors = run_screening(mode=mode, strategy_filter=strategy)
    save_results_to_csv(flat_results)
    message = build_message(
        mode=mode,
        strategy_results=strategy_results,
        strategy=strategy,
        error_count=len(errors),
    )

    if strategy:
        display_items = _build_strategy_recommendations(strategy_results, strategy)
    else:
        final_groups = _build_final_recommendations(strategy_results)
        try:
            save_recommendations(
                final_groups["grade_a"],
                final_groups["grade_b"] + final_groups["watch"],
                market="KR",
            )
        except Exception as exc:
            print(f"추천 결과 DB 저장 실패: {exc}")

        generated_at = _format_kst_now()
        save_dashboard_data(
            mode=mode,
            generated_at=generated_at,
            grade_a_items=final_groups["grade_a"],
            watch_items=final_groups["grade_b"] + final_groups["watch"],
        )
        try:
            refresh_market_json()
        except Exception as exc:
            print(f"시장 지표 JSON 생성 실패: {exc}")
        display_items = final_groups["selected"]

    return message, errors, display_items


def build_performance_message(selected_date: Optional[str] = None) -> str:
    """Return the latest recommendation performance summary without sending Telegram messages."""
    from app import (
        _format_pick_price,
        _format_return,
        _format_win_rate,
        build_performance_rows,
        filter_recommendations_since,
        load_all_recommendations,
        load_recommendations,
        summarize_performance,
    )

    recommendations, resolved_date, db_error = load_recommendations(selected_date)
    all_recommendations, all_error = load_all_recommendations()
    performance_rows = build_performance_rows(recommendations[: SETTINGS.final_recommendation_limit])
    cumulative_rows = build_performance_rows(all_recommendations)
    recent_7_rows = build_performance_rows(filter_recommendations_since(all_recommendations, days=7))
    recent_30_rows = build_performance_rows(filter_recommendations_since(all_recommendations, days=30))

    lines = [
        "[추천 성과 추적]",
        f"기준시각: {_format_kst_now()}",
        f"조회일자: {resolved_date or 'N/A'}",
        "",
    ]

    errors = [error for error in (db_error, all_error) if error]
    if errors:
        lines.append(f"DB 조회 오류: {' / '.join(errors)}")
        return "\n".join(lines)

    def append_summary(title: str, rows: list[dict]) -> None:
        summary = summarize_performance(rows)
        best_detail = _performance_detail(summary.get("best_row"))
        worst_detail = _performance_detail(summary.get("worst_row"))
        lines.extend(
            [
                title,
                f"추천수: {summary['count']}",
                f"승률: {_format_win_rate(summary['win_rate'])}",
                f"평균수익률: {_format_return(summary['average_return'])}",
                f"최고수익률: {_format_return(summary['best_return'])}{best_detail}",
                f"최저수익률: {_format_return(summary['worst_return'])}{worst_detail}",
                f"수익 종목: {summary['winners']}",
                f"손실 종목: {summary['losers']}",
                f"계산 제외: {summary['excluded_count']}",
                "",
            ]
        )

    append_summary("누적 성과", cumulative_rows)
    append_summary("최근 7일 성과", recent_7_rows)
    append_summary("최근 30일 성과", recent_30_rows)

    if not performance_rows:
        lines.append("선택 날짜 추천 성과 데이터가 없습니다.")
        return "\n".join(lines)

    append_summary("선택 날짜 성과", performance_rows)
    lines.append("종목별 성과")

    for index, row in enumerate(performance_rows, start=1):
        item = row["item"]
        price_data = row["price_data"]
        lines.extend(
            [
                f"{index}. {item.name}",
                f"추천일: {item.run_date}",
                f"가격기준일: {row.get('price_date') or 'N/A'}",
                f"추천가: {_format_pick_price(item.price_at_pick)}",
                f"현재가: {price_data['current_price']}",
                f"수익률: {_format_return(row['return_pct'])}",
                "",
            ]
        )

    return "\n".join(lines).rstrip()


def _performance_detail(row: dict | None) -> str:
    if not row:
        return ""
    item = row["item"]
    price_data = row["price_data"]
    price_date = row.get("price_date") or "N/A"
    from app import _format_pick_price

    return (
        f" ({item.name}, 추천일 {item.run_date}, 가격기준일 {price_date}, "
        f"추천가 {_format_pick_price(item.price_at_pick)}, 현재가 {price_data['current_price']})"
    )


def main(mode: str = "real", strategy: Optional[str] = None) -> None:
    """전체 실행 흐름을 담당합니다."""
    try:
        message, _errors, _display_items = generate_screening_payload(mode=mode, strategy=strategy)
    except Exception as exc:
        print(f"실데이터 조회 실패 원인: {exc}")
        failure_message = (
            f"{_build_title(mode)}\n"
            f"프로그램 실행 중 오류가 발생했습니다: {exc}"
        )
        print(failure_message)
        return

    print(message)

    sent, send_error = send_telegram_message(message)
    if send_error:
        print(f"텔레그램 메시지 전송 실패: {send_error}")
    elif sent:
        print("텔레그램 메시지 전송 완료")

    if strategy is None:
        try:
            dashboard_path = capture_dashboard(DASHBOARD_IMAGE_PATH)
            if not Path(dashboard_path).exists():
                print(f"대시보드 이미지 파일이 없습니다: {dashboard_path}")
                return

            photo_sent, photo_error = send_telegram_photo(str(dashboard_path), caption="대시보드 캡처")
            if photo_error:
                print(f"대시보드 이미지 전송 실패: {photo_error}")
            elif photo_sent:
                print("대시보드 이미지 전송 완료")
        except Exception as exc:
            print(f"대시보드 이미지 캡처/전송 실패: {exc}")


if __name__ == "__main__":
    if os.getenv("PM2_HOME") or os.getenv("pm_id") is not None:
        raise SystemExit(
            "main.py is a one-shot console script and must not be run by PM2. "
            "Run telegram_bot.py with PM2 instead."
        )
    main(mode=SETTINGS.default_mode)
