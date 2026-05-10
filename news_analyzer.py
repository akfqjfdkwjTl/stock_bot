"""News-based theme and issue analysis for stock candidates."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
import re
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

import requests

from config import SETTINGS


THEME_KEYWORDS: dict[str, list[str]] = {
    "AI": ["ai", "인공지능", "llm", "생성형 ai"],
    "반도체": ["반도체", "hbm", "dram", "낸드", "파운드리", "칩"],
    "전력": ["전력", "변압기", "전선", "송전", "배전", "전력기기"],
    "2차전지": ["2차전지", "배터리", "양극재", "음극재", "전해질"],
    "데이터센터": ["데이터센터", "data center", "서버", "클라우드"],
    "로봇": ["로봇", "휴머노이드", "자동화"],
    "방산": ["방산", "방위산업", "국방", "무기체계"],
    "금융": ["금융", "은행", "보험", "금리", "증권"],
    "자동차": ["자동차", "전기차", "ev", "모빌리티", "차량"],
}

SCORE_THEMES = {"AI", "반도체", "전력", "2차전지", "데이터센터", "로봇", "방산"}

# 종목 고유 산업을 우선 테마로 사용합니다.
STOCK_BASE_THEMES: dict[str, str] = {
    "한화오션": "조선/방산",
    "HD현대": "조선/기계",
    "HD현대중공업": "조선/방산",
    "HD한국조선해양": "조선/기계",
    "현대차": "자동차",
    "기아": "자동차",
    "LG전자": "가전/전장",
    "SK": "지주회사",
    "삼성전자": "반도체",
    "삼성전자우": "반도체",
    "SK하이닉스": "반도체",
    "KB금융": "금융",
    "신한지주": "금융",
    "하나금융지주": "금융",
    "우리금융지주": "금융",
    "POSCO홀딩스": "철강/소재",
    "포스코퓨처엠": "2차전지",
    "삼성SDI": "2차전지",
    "LG화학": "2차전지",
    "에코프로": "2차전지",
    "에코프로비엠": "2차전지",
    "LS ELECTRIC": "전력",
    "HD현대일렉트릭": "전력",
    "삼성전기": "전자부품",
    "NAVER": "인터넷/플랫폼",
    "카카오": "인터넷/플랫폼",
    "셀트리온": "바이오",
    "삼성바이오로직스": "바이오",
}

# 대표 종목은 산업 공통 문장보다 더 직접적인 투자 포인트를 우선 사용합니다.
STOCK_ISSUE_TEMPLATES: dict[str, dict[str, str]] = {
    "LG전자": {
        "base": "전장사업 성장과 AI 가전 확대 기대가 실적 개선 전망으로 이어지는 흐름입니다.",
        "AI": "AI 가전 확대와 스마트 디바이스 고도화 기대가 프리미엄 가전 수요 개선으로 이어지는 흐름입니다.",
        "로봇": "로봇·스마트홈 연계 기대가 생활가전 플랫폼 확장 가능성으로 이어지는 흐름입니다.",
    },
    "SK": {
        "base": "주요 자회사 가치 재평가 기대가 지주회사 할인 축소 전망으로 이어지는 흐름입니다.",
        "반도체": "SK하이닉스 지분가치 부각이 반도체 업황 개선에 따른 간접 수혜 기대로 이어지는 흐름입니다.",
        "AI": "AI 인프라 투자 확대가 그룹 핵심 자회사 가치 재평가 기대를 자극하는 흐름입니다.",
    },
    "삼성전자": {
        "base": "메모리 업황 회복과 첨단 반도체 수요 기대가 실적 개선 전망으로 이어지는 흐름입니다.",
        "AI": "AI 서버 확대로 고부가 메모리 수요 기대가 반도체 실적 개선 전망으로 이어지는 흐름입니다.",
    },
    "삼성전자우": {
        "base": "메모리 업황 회복과 첨단 반도체 수요 기대가 실적 개선 전망으로 이어지는 흐름입니다.",
        "AI": "AI 서버 확대로 고부가 메모리 수요 기대가 반도체 실적 개선 전망으로 이어지는 흐름입니다.",
    },
    "HD현대": {
        "base": "조선·기계 업황 개선과 자회사 가치 부각이 지주사 재평가 기대로 이어지는 흐름입니다.",
        "전력": "전력 인프라 투자 확대가 그룹 기계·전력 계열사 수혜 기대로 연결되는 흐름입니다.",
        "로봇": "로봇·자동화 투자 확대가 그룹 신사업 기대를 자극하는 흐름입니다.",
    },
}

# 기본 산업과 전혀 무관한 뉴스 키워드는 보조 분류에서 제외합니다.
RELATED_NEWS_THEMES: dict[str, set[str]] = {
    "조선/방산": {"방산", "전력", "데이터센터"},
    "조선/기계": {"전력", "방산"},
    "자동차": {"자동차", "2차전지", "로봇", "AI"},
    "가전/전장": {"AI", "로봇", "자동차", "반도체"},
    "지주회사": {"반도체", "AI", "전력", "2차전지", "방산", "금융"},
    "반도체": {"반도체", "AI", "데이터센터", "전력"},
    "금융": {"금융"},
    "철강/소재": {"전력", "2차전지", "방산"},
    "2차전지": {"2차전지", "자동차", "전력"},
    "전력": {"전력", "AI", "데이터센터"},
    "전자부품": {"반도체", "AI", "자동차"},
    "인터넷/플랫폼": {"AI", "데이터센터", "로봇"},
    "바이오": set(),
}

THEME_SUMMARY_TEMPLATES: dict[str, str] = {
    "AI": "AI 서비스 확산과 데이터센터 투자 증가가 이어지며 전력·반도체 수요 확대 기대로 연결되는 흐름입니다.",
    "반도체": "고성능 반도체 수요와 메모리 업황 개선 기대가 실적 회복 전망으로 연결되는 흐름입니다.",
    "전력": "전력 인프라 투자와 송배전 설비 증설 기대가 전력기기 수주 확대 전망으로 이어지는 흐름입니다.",
    "2차전지": "전기차와 에너지저장장치 수요 기대가 배터리 밸류체인 실적 회복 기대로 연결되는 흐름입니다.",
    "데이터센터": "데이터센터 증설 수요가 서버·전력 인프라 투자 확대 기대로 이어지는 흐름입니다.",
    "로봇": "자동화 투자 확대와 휴머노이드 기대가 로봇 부품·장비 수요 증가 전망으로 연결되는 흐름입니다.",
    "방산": "방산 수출 확대와 국방 예산 증가 기대가 수주 성장 전망으로 이어지는 흐름입니다.",
    "금융": "배당 확대와 밸류업 정책 기대가 은행주 재평가와 수익성 개선 기대로 이어지는 흐름입니다.",
    "자동차": "신차 판매 회복과 전동화 투자 기대가 완성차·부품 실적 개선 전망으로 연결되는 흐름입니다.",
}

STOCK_NEWS_ALIASES: dict[str, list[str]] = {
    "LG전자": ["lg전자", "엘지전자"],
    "SK": ["sk㈜", "주식회사 sk", "sk그룹", "sk holdings"],
    "SK하이닉스": ["sk하이닉스", "sk hynix", "하이닉스"],
    "한화오션": ["한화오션", "hanwha ocean"],
    "HD현대": ["hd현대", "hd hyundai"],
    "삼성전자": ["삼성전자", "samsung electronics"],
    "하나금융지주": ["하나금융지주", "하나금융"],
    "신한지주": ["신한지주", "신한금융"],
    "KB금융": ["kb금융", "kb금융지주", "국민은행"],
}


def _normalize_text(text: str) -> str:
    return unescape((text or "").strip()).lower()


def _stock_aliases(stock_name: str) -> list[str]:
    aliases = [stock_name, stock_name.replace(" ", "")]
    aliases.extend(STOCK_NEWS_ALIASES.get(stock_name, []))
    normalized_aliases: list[str] = []
    for alias in aliases:
        value = _normalize_text(alias)
        if value and value not in normalized_aliases:
            normalized_aliases.append(value)
    return normalized_aliases


def _contains_alias(text: str, alias: str) -> bool:
    if not alias:
        return False
    if len(alias) <= 3 and alias.isascii():
        pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return alias in text


def _is_direct_stock_news(stock_name: str, item: dict[str, str]) -> bool:
    body = _normalize_text(f"{item['title']} {item['description']}")
    return any(_contains_alias(body, alias) for alias in _stock_aliases(stock_name))


def _build_rss_url(stock_name: str) -> str:
    query = quote(f'"{stock_name}" when:{SETTINGS.news_lookback_days}d')
    return (
        "https://news.google.com/rss/search"
        f"?q={query}&hl=ko&gl=KR&ceid=KR:ko"
    )


def _parse_items(xml_text: str) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml_text)
    items: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        items.append(
            {
                "title": item.findtext("title", default=""),
                "description": item.findtext("description", default=""),
                "pubDate": item.findtext("pubDate", default=""),
            }
        )
    return items


def _filter_recent_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    cutoff = datetime.now().astimezone() - timedelta(days=SETTINGS.news_lookback_days)
    recent_items: list[dict[str, str]] = []
    for item in items:
        try:
            published = parsedate_to_datetime(item["pubDate"])
            if published.tzinfo is None:
                published = published.astimezone()
        except Exception:
            recent_items.append(item)
            continue

        if published >= cutoff:
            recent_items.append(item)
    return recent_items


def _collect_theme_counts(
    items: list[dict[str, str]],
    base_theme: str,
) -> tuple[Counter, dict[str, int]]:
    theme_counts: Counter[str] = Counter()
    repeated_article_hits: dict[str, int] = defaultdict(int)
    allowed_themes = RELATED_NEWS_THEMES.get(base_theme, set())

    for item in items:
        body = _normalize_text(f"{item['title']} {item['description']}")
        matched_in_article: set[str] = set()
        for theme, aliases in THEME_KEYWORDS.items():
            if allowed_themes and theme not in allowed_themes:
                continue
            for alias in aliases:
                if alias.lower() in body:
                    theme_counts[theme] += 1
                    matched_in_article.add(theme)
                    break
        for theme in matched_in_article:
            repeated_article_hits[theme] += 1

    return theme_counts, repeated_article_hits


def _collect_relevant_news_items(stock_name: str, items: list[dict[str, str]]) -> list[dict[str, str]]:
    """종목명이나 종목 별칭이 직접 언급된 기사만 남깁니다."""
    return [item for item in items if _is_direct_stock_news(stock_name, item)]


def _build_issue_summary(
    stock_name: str,
    primary_theme: str,
    recent_keywords: list[str],
    repeated_keywords: list[str],
    headline: str,
) -> str:
    if not headline and not recent_keywords:
        return "특이 이슈 없음 (기술적 흐름 기반)"

    stock_templates = STOCK_ISSUE_TEMPLATES.get(stock_name, {})
    theme_sentence = (
        stock_templates.get(primary_theme)
        or stock_templates.get("base")
        or THEME_SUMMARY_TEMPLATES.get(
            primary_theme,
            f"{primary_theme} 관련 기대가 실적 또는 수급 개선 전망으로 연결되는 흐름입니다."
            if primary_theme
            else "관련 뉴스 흐름이 실적 또는 수급 기대와 연결되는 모습입니다.",
        )
    )

    if primary_theme and headline:
        short_headline = headline.split(" - ")[0].strip()
        return f"{theme_sentence} 최근 기사에서는 '{short_headline}' 이슈가 함께 부각됐습니다."

    if recent_keywords:
        keyword_text = ", ".join(recent_keywords[:2])
        return f"{theme_sentence} 최근 뉴스에서는 {keyword_text} 관련 기대가 함께 언급됐습니다."

    short_headline = headline.split(" - ")[0].strip()
    return f"최근 뉴스에서는 '{short_headline}' 이슈가 투자심리를 자극하는 모습입니다."


def analyze_stock_news(stock_name: str, ticker: str = "") -> dict[str, Any]:
    """
    Fetch recent news for a stock and convert it into theme/keyword signals.
    News failures never raise; they return a safe default structure.
    """
    default_result = {
        "theme": "",
        "base_theme": STOCK_BASE_THEMES.get(stock_name, ""),
        "recent_news_keywords": [],
        "issue_summary": "특이 이슈 없음 (기술적 흐름 기반)",
        "news_score": 0,
        "repeated_keywords": [],
        "news_error": "",
    }

    try:
        response = requests.get(_build_rss_url(stock_name), timeout=SETTINGS.news_request_timeout)
        response.raise_for_status()
        items = _parse_items(response.text)
        recent_items = _filter_recent_items(items)[: SETTINGS.news_max_items]
        relevant_items = _collect_relevant_news_items(stock_name, recent_items)

        if not recent_items or not relevant_items:
            return {
                **default_result,
                "issue_summary": "특이 이슈 없음 (기술적 흐름 기반)",
            }

        base_theme = STOCK_BASE_THEMES.get(stock_name, "")
        theme_counts, repeated_hits = _collect_theme_counts(relevant_items, base_theme)
        primary_news_theme = theme_counts.most_common(1)[0][0] if theme_counts else ""
        repeated_keywords = sorted(
            [theme for theme, count in repeated_hits.items() if count >= 2],
            key=lambda theme: theme_counts[theme],
            reverse=True,
        )
        recent_keywords = [theme for theme, _count in theme_counts.most_common(4)]
        final_theme = base_theme or primary_news_theme or "기타"

        news_score = 0
        if primary_news_theme:
            news_score += 3
        if recent_keywords:
            news_score += min(4, len(recent_keywords))
        if repeated_keywords:
            news_score += min(2, len(repeated_keywords))
        if primary_news_theme in SCORE_THEMES:
            news_score += 1
        news_score = min(news_score, 10)

        headline = unescape(relevant_items[0]["title"]).strip()
        issue_summary = _build_issue_summary(
            stock_name=stock_name,
            primary_theme=primary_news_theme or final_theme or "기타",
            recent_keywords=recent_keywords,
            repeated_keywords=repeated_keywords,
            headline=headline,
        )

        return {
            "theme": final_theme,
            "base_theme": base_theme,
            "recent_news_keywords": recent_keywords,
            "issue_summary": issue_summary,
            "news_score": news_score,
            "repeated_keywords": repeated_keywords,
            "news_error": "",
        }
    except Exception as exc:
        return {
            **default_result,
            "news_error": str(exc),
        }


def enrich_candidate_with_news(candidate: dict[str, Any], news_info: dict[str, Any]) -> dict[str, Any]:
    """Attach news/theme fields and add the news score to the candidate total."""
    enriched = dict(candidate)
    enriched["theme"] = news_info.get("theme", "") or "기타"
    enriched["recent_news_keywords"] = ", ".join(news_info.get("recent_news_keywords", []))
    enriched["issue_summary"] = news_info.get("issue_summary", "")
    enriched["news_score"] = int(news_info.get("news_score", 0))
    enriched["news_error"] = news_info.get("news_error", "")
    enriched["total_score"] = min(100, int(enriched["total_score"]) + enriched["news_score"])
    return enriched
