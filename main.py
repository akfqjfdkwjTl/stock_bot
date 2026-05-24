"""국내주식 조건 기반 관심종목 선별 프로그램의 실행 진입점입니다."""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from config import SETTINGS
from dashboard_capture import capture_dashboard, refresh_market_json, save_dashboard_data
from db import save_recommendations
from stock_screener import run_screening, save_results_to_csv


VALID_STRATEGIES = ("short", "swing", "mid")
KST = ZoneInfo("Asia/Seoul")

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
}


def _format_currency(value: int) -> str:
    """숫자를 원화 형식으로 보여줍니다."""
    return f"{value:,}원"


def _format_kst_now() -> str:
    """메시지와 대시보드에 사용할 한국시간 기준시각입니다."""
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def _build_title(mode: str) -> str:
    """메시지 상단 제목을 만듭니다."""
    if mode == "real":
        return "[국내주식 조건 기반 관심종목][실데이터 모드]"
    return "[국내주식 조건 기반 관심종목][샘플 모드]"


def _normalize_sector(theme: str) -> str:
    """비슷한 테마를 하나의 섹터 그룹으로 정규화합니다."""
    normalized = (theme or "기타").strip()
    return SECTOR_GROUPS.get(normalized, normalized or "기타")


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
    if candidate.get("theme") and candidate.get("theme") != "기타":
        parts.append(f"{candidate['theme']} 테마 뉴스 흐름이 반영됐습니다.")
    return " ".join(parts[:2]) or "기술적 조건과 뉴스 흐름을 함께 고려했습니다."


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
                "trading_value": item["trading_value"],
                "theme": item.get("theme", "기타"),
                "recent_news_keywords": item.get("recent_news_keywords", ""),
                "issue_summary": item.get("issue_summary", ""),
                "news_score": item.get("news_score", 0),
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
            entry["trading_value"] = max(entry["trading_value"], item["trading_value"])
            entry["vol_ratio"] = item.get("vol_ratio", entry["vol_ratio"])
            entry["vol5_ratio"] = item.get("vol5_ratio", entry["vol5_ratio"])
            entry["theme"] = item.get("theme", entry["theme"])
            entry["recent_news_keywords"] = item.get("recent_news_keywords", entry["recent_news_keywords"])
            entry["issue_summary"] = item.get("issue_summary", entry["issue_summary"])
            entry["news_score"] = max(entry["news_score"], item.get("news_score", 0))

    for item in strategy_results.get("swing", []):
        entry = merged_by_ticker.setdefault(
            item["ticker"],
            {
                "ticker": item["ticker"],
                "name": item["name"],
                "current_price": item["current_price"],
                "trading_value": item["trading_value"],
                "theme": item.get("theme", "기타"),
                "recent_news_keywords": item.get("recent_news_keywords", ""),
                "issue_summary": item.get("issue_summary", ""),
                "news_score": item.get("news_score", 0),
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

    for item in strategy_results.get("mid", []):
        entry = merged_by_ticker.setdefault(
            item["ticker"],
            {
                "ticker": item["ticker"],
                "name": item["name"],
                "current_price": item["current_price"],
                "trading_value": item["trading_value"],
                "theme": item.get("theme", "기타"),
                "recent_news_keywords": item.get("recent_news_keywords", ""),
                "issue_summary": item.get("issue_summary", ""),
                "news_score": item.get("news_score", 0),
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
            entry["trading_value"] = max(entry["trading_value"], item["trading_value"])
            entry["theme"] = item.get("theme", entry["theme"])
            entry["recent_news_keywords"] = item.get("recent_news_keywords", entry["recent_news_keywords"])
            entry["issue_summary"] = item.get("issue_summary", entry["issue_summary"])
            entry["news_score"] = max(entry["news_score"], item.get("news_score", 0))

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
        enriched["strategy_type"] = strategy_type
        enriched["sector_group"] = _normalize_sector(enriched.get("theme", "기타"))
        enriched["summary_reason"] = _summarize_recommendation_reason(enriched)
        all_candidates.append(enriched)

    all_candidates.sort(key=lambda row: row["observation_score"], reverse=True)

    a_candidates = [
        row for row in all_candidates
        if row["final_score"] >= SETTINGS.grade_a_threshold and _passes_vcp_gate(row)
    ]
    selected_a: list[dict] = []
    used_sectors: set[str] = set()

    _append_unique_sector(a_candidates, selected_a, used_sectors, SETTINGS.final_recommendation_limit)
    selected_a_tickers = {row["ticker"] for row in selected_a}
    selected_observation: list[dict] = []
    _append_unique_ticker(
        [row for row in all_candidates if row["ticker"] not in selected_a_tickers],
        selected_observation,
        SETTINGS.final_recommendation_limit,
    )

    return {
        "grade_a": selected_a,
        "grade_b": selected_observation,
    }


def _build_strategy_recommendations(strategy_results: dict[str, list[dict]], strategy: str) -> list[dict]:
    """전략 전용 요청에서 사용할 최대 5개 결과입니다."""
    items = strategy_results.get(strategy, [])[:5]
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
        next_index = _append_ranked_recommendations(
            lines,
            "A급 추천",
            final_groups["grade_a"],
            "현재 기준 A급 없음",
            1,
            "final_score",
        )
        _append_ranked_recommendations(
            lines,
            "관찰 후보",
            final_groups["grade_b"],
            None,
            next_index,
            "observation_score",
        )
        return "\n".join(lines)

    if strategy == "swing":
        swing_items = filtered_results.get("swing", [])
        _append_group(lines, "VCP + 테마 TOP3", _get_vcp_theme_candidates(swing_items), "semi")
        _append_group(lines, "VCP 핵심 TOP", _get_vcp_core_candidates(swing_items), "core")
        _append_group(lines, "준 VCP 후보", _get_semi_vcp_candidates(swing_items), "semi")
        _append_group(lines, "돌파형 후보", _get_breakout_candidates(swing_items), "breakout")

    for strategy_name in target_strategies:
        lines.append(f"전략: {strategy_name}")
        items = filtered_results.get(strategy_name, [])

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
                final_groups["grade_b"],
                market="KR",
            )
        except Exception as exc:
            print(f"추천 결과 DB 저장 실패: {exc}")

        generated_at = _format_kst_now()
        save_dashboard_data(
            mode=mode,
            generated_at=generated_at,
            grade_a_items=final_groups["grade_a"],
            watch_items=final_groups["grade_b"],
        )
        try:
            refresh_market_json()
        except Exception as exc:
            print(f"시장 지표 JSON 생성 실패: {exc}")
        display_items = final_groups["grade_a"] + final_groups["grade_b"]

    return message, errors, display_items


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

    if strategy is None and SETTINGS.enable_dashboard_capture:
        try:
            capture_dashboard()
        except Exception as exc:
            print(f"대시보드 캡처 실패: {exc}")


if __name__ == "__main__":
    if os.getenv("PM2_HOME") or os.getenv("pm_id") is not None:
        raise SystemExit(
            "main.py is a one-shot console script and must not be run by PM2. "
            "Run telegram_bot.py with PM2 instead."
        )
    main(mode=SETTINGS.default_mode)
