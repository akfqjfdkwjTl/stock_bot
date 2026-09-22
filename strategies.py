"""전략별 조건 검사와 점수 계산을 담당합니다."""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from config import SETTINGS


STRATEGY_LABELS = {
    "short": ["거래대금 급증", "단기 추세", "오닐 추세", "리버모어 고점갱신"],
    "swing": ["다비스 박스", "미너비니 VCP", "거래량 증가", "추세 돌파"],
    "mid": ["CAN SLIM", "정배열", "신고가 근처", "추세추종"],
}


def prepare_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """이동평균과 보조 지표를 미리 계산해 둡니다."""
    data = df.copy()
    data = data.sort_index()

    if "거래대금" in data.columns:
        data["value"] = data["거래대금"]
    else:
        data["value"] = data["종가"] * data["거래량"]
    data["ma5"] = data["종가"].rolling(5).mean()
    data["ma10"] = data["종가"].rolling(10).mean()
    data["ma20"] = data["종가"].rolling(20).mean()
    data["ma60"] = data["종가"].rolling(60).mean()
    data["vol5"] = data["거래량"].rolling(5).mean()
    data["vol20"] = data["거래량"].rolling(20).mean()
    data["value20"] = data["value"].rolling(20).mean()
    data["high20"] = data["고가"].rolling(20).max()
    data["low20"] = data["저가"].rolling(20).min()
    data["high60"] = data["고가"].rolling(60).max()
    data["prev_high20"] = data["고가"].rolling(20).max().shift(1)
    data["prev_high60"] = data["고가"].rolling(60).max().shift(1)
    data["low10"] = data["저가"].rolling(10).min()

    # 변동성 축소 여부를 보기 위해 최근 4주간 일중 변동폭을 계산합니다.
    range_pct = ((data["고가"] - data["저가"]) / data["종가"].replace(0, pd.NA)) * 100
    data["range_pct"] = range_pct
    data["range5"] = data["range_pct"].rolling(5).mean()
    data["range10"] = data["range_pct"].rolling(10).mean()
    data["range20"] = data["range_pct"].rolling(20).mean()

    return data


def attach_relative_strength(df: pd.DataFrame, benchmark_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """전일 종가 기준 1·3·6개월 시장 대비 초과수익률을 붙입니다."""
    data = df.copy()
    for column in ("rs_1m", "rs_3m", "rs_6m"):
        data[column] = 0.0

    if benchmark_df is None or benchmark_df.empty or len(data) < 3:
        return data

    benchmark_close_column = "종가" if "종가" in benchmark_df.columns else "Close"
    if benchmark_close_column not in benchmark_df.columns:
        return data

    aligned = pd.concat(
        [
            pd.to_numeric(data["종가"], errors="coerce").rename("stock"),
            pd.to_numeric(benchmark_df[benchmark_close_column], errors="coerce").rename("market"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    # 오늘 하루 급등이 RS 전체를 왜곡하지 않도록 완성된 전 거래일까지 계산합니다.
    completed = aligned.iloc[:-1]
    if completed.empty:
        return data

    latest_index = data.index[-1]
    for column, sessions in (("rs_1m", 21), ("rs_3m", 63), ("rs_6m", 126)):
        if len(completed) <= sessions:
            continue
        stock_return = (completed["stock"].iloc[-1] / completed["stock"].iloc[-sessions - 1]) - 1
        market_return = (completed["market"].iloc[-1] / completed["market"].iloc[-sessions - 1]) - 1
        data.at[latest_index, column] = (stock_return - market_return) * 100
    return data


def _safe_number(value: Any, digits: int = 2) -> float:
    """NaN이 섞여 있어도 화면 출력용 숫자를 안전하게 만듭니다."""
    if pd.isna(value):
        return 0.0
    return round(float(value), digits)


def _safe_ratio(numerator: Any, denominator: Any) -> float:
    """0 또는 NaN 분모를 피하면서 비율을 계산합니다."""
    if pd.isna(numerator) or pd.isna(denominator) or denominator in (0, 0.0):
        return 0.0
    return float(numerator) / float(denominator)


def _calculate_common_metrics(df: pd.DataFrame) -> Optional[dict[str, Any]]:
    """세 전략이 공통으로 쓰는 최근 수치들을 꺼냅니다."""
    if len(df) < SETTINGS.min_history_rows:
        return None

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    required_values = [
        latest["종가"],
        prev["종가"],
        latest["거래량"],
        latest["고가"],
        latest["저가"],
        latest["ma5"],
        latest["ma20"],
        latest["ma60"],
        latest["vol5"],
        latest["vol20"],
        latest["value20"],
        latest["prev_high20"],
        latest["prev_high60"],
        latest["range5"],
        latest["range10"],
        latest["range20"],
    ]
    if any(pd.isna(value) for value in required_values):
        return None

    if latest["종가"] < SETTINGS.min_price:
        return None

    daily_change_pct = ((latest["종가"] / prev["종가"]) - 1) * 100
    gap_pct = ((latest["시가"] / prev["종가"]) - 1) * 100
    candle_body_pct = ((latest["종가"] / latest["시가"]) - 1) * 100
    trading_value = latest["value"]

    if trading_value < SETTINGS.min_trading_value:
        return None

    if daily_change_pct > SETTINGS.max_daily_change_pct:
        return None

    vol_ratio = _safe_ratio(latest["거래량"], latest["vol20"])
    value_ratio = _safe_ratio(latest["value"], latest["value20"])
    close_to_high_pct = (
        ((latest["고가"] - latest["종가"]) / latest["고가"]) * 100 if latest["고가"] else 0
    )
    high60 = latest["prev_high60"]
    low20 = df["저가"].tail(20).min()
    box_high = latest["prev_high20"]
    box_low = df["저가"].tail(20).min()
    box_range_pct = ((box_high - box_low) / box_low) * 100 if box_low else 0

    # 최근 4주 변동성 평균과 그 이전 4주 평균을 비교해 VCP 힌트를 잡습니다.
    recent_volatility = df["range_pct"].tail(20).mean()
    previous_volatility = df["range_pct"].tail(40).head(20).mean()
    recent_5d_volatility = latest["range5"]
    recent_10d_volatility = latest["range10"]
    recent_20d_volatility = latest["range20"]
    vol5_ratio = _safe_ratio(latest["vol5"], latest["vol20"])

    high52 = df["고가"].tail(252).max()
    high52_ratio = _safe_ratio(latest["종가"], high52)
    high52_distance_pct = (high52_ratio - 1) * 100 if high52_ratio else 0

    pre_pivot_volume = df["거래량"].iloc[-6:-1].mean()
    base_volume = df["거래량"].iloc[-26:-6].mean()
    volume_contraction_ratio = _safe_ratio(pre_pivot_volume, base_volume)
    volume_contraction = 0 < volume_contraction_ratio <= 0.85
    staged_contraction = recent_20d_volatility > recent_10d_volatility > recent_5d_volatility
    pivot_ready = (
        volume_contraction
        and latest["종가"] >= box_high * 0.95
        and vol_ratio >= 1.2
    )

    ma20_slope = latest["ma20"] - df.iloc[-6]["ma20"]
    ma60_slope = latest["ma60"] - df.iloc[-6]["ma60"]

    return {
        "latest": latest,
        "prev": prev,
        "daily_change_pct": daily_change_pct,
        "gap_pct": gap_pct,
        "candle_body_pct": candle_body_pct,
        "trading_value": trading_value,
        "vol_ratio": vol_ratio,
        "value_ratio": value_ratio,
        "close_to_high_pct": close_to_high_pct,
        "high60": high60,
        "low20": low20,
        "box_high": box_high,
        "box_low": box_low,
        "box_range_pct": box_range_pct,
        "recent_volatility": recent_volatility,
        "previous_volatility": previous_volatility,
        "recent_5d_volatility": recent_5d_volatility,
        "recent_10d_volatility": recent_10d_volatility,
        "recent_20d_volatility": recent_20d_volatility,
        "vol5_ratio": vol5_ratio,
        "high52": high52,
        "high52_ratio": high52_ratio,
        "high52_distance_pct": high52_distance_pct,
        "rs_1m": _safe_number(latest.get("rs_1m", 0)),
        "rs_3m": _safe_number(latest.get("rs_3m", 0)),
        "rs_6m": _safe_number(latest.get("rs_6m", 0)),
        "staged_contraction": staged_contraction,
        "volume_contraction_ratio": volume_contraction_ratio,
        "volume_contraction": volume_contraction,
        "pivot_ready": pivot_ready,
        "ma20_slope": ma20_slope,
        "ma60_slope": ma60_slope,
    }


def _passes_downside_risk_filter(metrics: dict[str, Any], min_daily_change_pct: float) -> bool:
    """급락, 큰 갭 하락, 장대음봉 신호를 후보 단계에서 제거합니다."""
    return (
        metrics["daily_change_pct"] >= min_daily_change_pct
        and metrics["gap_pct"] >= SETTINGS.max_gap_down_pct
        and metrics["candle_body_pct"] >= SETTINGS.max_bearish_body_pct
    )


def _score_liquidity(metrics: dict[str, Any]) -> int:
    score = 0
    trading_value = metrics["trading_value"]
    value_ratio = metrics["value_ratio"]

    if trading_value >= 20_000_000_000:
        score += 12
    elif trading_value >= 10_000_000_000:
        score += 10
    elif trading_value >= SETTINGS.min_trading_value:
        score += 8

    if value_ratio >= 3:
        score += 8
    elif value_ratio >= 2:
        score += 6
    elif value_ratio >= 1.3:
        score += 4

    return min(score, 20)


def _score_volume(metrics: dict[str, Any]) -> int:
    vol_ratio = metrics["vol_ratio"]
    if vol_ratio >= 3:
        return 15
    if vol_ratio >= 2:
        return 12
    if vol_ratio >= 1.5:
        return 9
    if vol_ratio >= 1.2:
        return 6
    return 0


def _score_ma_trend(metrics: dict[str, Any], require_mid_trend: bool = False) -> int:
    latest = metrics["latest"]
    score = 0

    if latest["종가"] > latest["ma20"] > latest["ma60"]:
        score += 9
    elif latest["종가"] > latest["ma20"]:
        score += 6

    if metrics["ma20_slope"] > 0:
        score += 3

    if require_mid_trend and metrics["ma60_slope"] > 0:
        score += 3

    return min(score, 15)


def _score_breakout(metrics: dict[str, Any], near_high: bool = False) -> int:
    latest = metrics["latest"]
    score = 0

    if latest["종가"] >= metrics["high60"] * 0.98:
        score += 10 if near_high else 8

    if latest["종가"] > metrics["box_high"] * 0.995:
        score += 5

    high52_ratio = metrics.get("high52_ratio", 0)
    if high52_ratio >= 0.98:
        high52_score = 10
    elif high52_ratio >= 0.95:
        high52_score = 8
    elif high52_ratio >= 0.90:
        high52_score = 5
    else:
        high52_score = 0

    # 60일/박스 돌파와 같은 추세 현상이므로 합산하지 않고 더 강한 값만 사용합니다.
    return min(max(score, high52_score), 15)


def _score_box_breakout(metrics: dict[str, Any]) -> int:
    latest = metrics["latest"]
    if metrics["box_range_pct"] <= 15 and latest["종가"] >= metrics["box_high"] * 0.995:
        return 10
    if metrics["box_range_pct"] <= 20 and latest["종가"] >= metrics["box_high"] * 0.985:
        return 7
    return 0


def _score_vcp(metrics: dict[str, Any]) -> int:
    recent_vol = metrics["recent_volatility"]
    prev_vol = metrics["previous_volatility"]

    if pd.isna(recent_vol) or pd.isna(prev_vol):
        return 0

    score = 0
    if recent_vol < prev_vol * 0.7:
        score = 10
    elif recent_vol < prev_vol * 0.85:
        score = 7

    if metrics.get("staged_contraction"):
        score = max(score, 8)
    if score and metrics.get("volume_contraction"):
        score += 2
    return min(score, 12)


def _score_relative_strength(metrics: dict[str, Any]) -> int:
    """기간별 초과수익이 지속될수록 가점하고 단일 기간 급등은 제한합니다."""
    score = 0
    if metrics.get("rs_1m", 0) >= 2:
        score += 2
    if metrics.get("rs_3m", 0) >= 3:
        score += 3
    if metrics.get("rs_6m", 0) >= 5:
        score += 5
    return score


def _score_risk_reward(
    metrics: dict[str, Any],
    stop_price: float,
    target_price: float,
) -> int:
    """실제 손절가와 목표가를 기준으로 위험 대비 보상을 점수화합니다."""
    latest_close = metrics["latest"]["종가"]
    if stop_price <= 0 or stop_price >= latest_close or target_price <= latest_close:
        return 0

    risk_pct = ((latest_close - stop_price) / latest_close) * 100
    reward_pct = ((target_price - latest_close) / latest_close) * 100

    if risk_pct <= 5 and reward_pct / risk_pct >= 2:
        return 10
    if risk_pct <= 7 and reward_pct / risk_pct >= 1.5:
        return 7
    return 4


def _score_not_overheated(metrics: dict[str, Any]) -> int:
    daily_change_pct = metrics["daily_change_pct"]
    close_to_high_pct = metrics["close_to_high_pct"]

    if daily_change_pct <= 8 and close_to_high_pct <= 2:
        return 5
    if daily_change_pct <= 12 and close_to_high_pct <= 4:
        return 3
    return 0


def _build_candidate(
    strategy: str,
    ticker: str,
    name: str,
    metrics: dict[str, Any],
    stop_price: float,
    target_price: float,
    selected_reasons: list[str],
    score_parts: dict[str, int],
) -> dict[str, Any]:
    total_score = min(sum(score_parts.values()), 100)
    latest = metrics["latest"]

    return {
        "strategy": strategy,
        "name": name,
        "ticker": ticker,
        "current_price": int(latest["종가"]),
        "price_date": str(latest.name.date() if hasattr(latest.name, "date") else latest.name),
        "change_pct": _safe_number(metrics["daily_change_pct"]),
        "trading_value": int(metrics["trading_value"]),
        "total_score": int(total_score),
        "techniques": ", ".join(STRATEGY_LABELS[strategy]),
        "reason": "; ".join(selected_reasons),
        "stop_loss": int(stop_price),
        "target_price": int(target_price),
        "caution": "장 시작 직후 급등 추격, 거래대금 급감, 종가 이탈 여부를 꼭 확인하세요.",
        "score_liquidity": score_parts["liquidity"],
        "score_volume": score_parts["volume"],
        "score_trend": score_parts["trend"],
        "score_breakout": score_parts["breakout"],
        "score_box": score_parts["box"],
        "score_vcp": score_parts["vcp"],
        "score_rs": score_parts["rs"],
        "score_risk": score_parts["risk"],
        "score_overheat": score_parts["overheat"],
        "box_high": int(metrics["box_high"]) if not pd.isna(metrics["box_high"]) else 0,
        "box_low": int(metrics["box_low"]) if not pd.isna(metrics["box_low"]) else 0,
        "box_range_pct": _safe_number(metrics["box_range_pct"]),
        "vcp_score": int(score_parts["vcp"]),
        "recent_5d_volatility": _safe_number(metrics.get("recent_5d_volatility")),
        "recent_10d_volatility": _safe_number(metrics.get("recent_10d_volatility")),
        "recent_20d_volatility": _safe_number(metrics.get("recent_20d_volatility")),
        "vol5_ratio": _safe_number(metrics.get("vol5_ratio")),
        "vol_ratio": _safe_number(metrics.get("vol_ratio")),
        "high52_ratio": _safe_number(metrics.get("high52_ratio"), 4),
        "high52_distance_pct": _safe_number(metrics.get("high52_distance_pct")),
        "rs_1m": _safe_number(metrics.get("rs_1m")),
        "rs_3m": _safe_number(metrics.get("rs_3m")),
        "rs_6m": _safe_number(metrics.get("rs_6m")),
        "staged_contraction": bool(metrics.get("staged_contraction")),
        "volume_contraction_ratio": _safe_number(metrics.get("volume_contraction_ratio")),
        "volume_contraction": bool(metrics.get("volume_contraction")),
        "pivot_ready": bool(metrics.get("pivot_ready")),
    }


def evaluate_short_strategy(ticker: str, name: str, df: pd.DataFrame) -> Optional[dict[str, Any]]:
    """2~3일 단타 후보를 찾습니다."""
    metrics = _calculate_common_metrics(df)
    if metrics is None:
        return None

    latest = metrics["latest"]
    daily_change_pct = metrics["daily_change_pct"]

    if not (0.5 <= daily_change_pct <= 12):
        return None
    if latest["종가"] <= latest["ma5"]:
        return None
    if metrics["close_to_high_pct"] > 4:
        return None
    if metrics["vol_ratio"] < 1.2:
        return None

    stop_price = min(latest["ma5"], metrics["low20"] * 0.99)
    target_price = latest["종가"] * 1.06
    score_parts = {
        "liquidity": _score_liquidity(metrics),
        "volume": _score_volume(metrics),
        "trend": min(_score_ma_trend(metrics), 15),
        "breakout": _score_breakout(metrics),
        "box": 0,
        "vcp": 0,
        "rs": _score_relative_strength(metrics),
        "risk": _score_risk_reward(metrics, stop_price, target_price),
        "overheat": _score_not_overheated(metrics),
    }
    reasons = [
        "거래량이 20일 평균 대비 유의미하게 증가했습니다.",
        "종가가 5일선 위에 있고 당일 고가 대비 밀림이 크지 않습니다.",
        "단기 추세 추종 관점에서 2~3일 관찰 후보입니다.",
    ]

    return _build_candidate(
        "short",
        ticker,
        name,
        metrics,
        stop_price,
        target_price,
        reasons,
        score_parts,
    )


def evaluate_short_fallback(ticker: str, name: str, df: pd.DataFrame) -> Optional[dict[str, Any]]:
    """엄격 조건을 통과하지 못했을 때도 관찰용 단기 후보를 조금 더 넓게 찾습니다."""
    metrics = _calculate_common_metrics(df)
    if metrics is None:
        return None

    latest = metrics["latest"]
    daily_change_pct = metrics["daily_change_pct"]

    if daily_change_pct < 0:
        return None
    if latest["종가"] <= latest["ma5"] * 0.985:
        return None
    if metrics["vol_ratio"] < 1.0 and metrics["value_ratio"] < 1.0:
        return None

    stop_price = min(latest["ma5"] * 0.99, latest["저가"] * 0.99)
    target_price = latest["종가"] * 1.05
    score_parts = {
        "liquidity": _score_liquidity(metrics),
        "volume": max(_score_volume(metrics), 4),
        "trend": _score_ma_trend(metrics),
        "breakout": _score_breakout(metrics),
        "box": 0,
        "vcp": 0,
        "rs": _score_relative_strength(metrics),
        "risk": _score_risk_reward(metrics, stop_price, target_price),
        "overheat": _score_not_overheated(metrics),
    }
    if sum(score_parts.values()) < 35:
        return None

    reasons = [
        "단기 거래대금과 거래량 흐름이 무난한 편입니다.",
        "5일선 부근에서 눌림 이후 재상승 가능성을 보는 관찰 후보입니다.",
        "엄격 조건보다 완화된 보조 기준으로 선별했습니다.",
    ]

    return _build_candidate(
        "short",
        ticker,
        name,
        metrics,
        stop_price,
        target_price,
        reasons,
        score_parts,
    )


def evaluate_swing_strategy(ticker: str, name: str, df: pd.DataFrame) -> Optional[dict[str, Any]]:
    """1~2주 스윙 후보를 찾습니다."""
    metrics = _calculate_common_metrics(df)
    if metrics is None:
        return None

    latest = metrics["latest"]

    if not _passes_downside_risk_filter(metrics, SETTINGS.min_swing_daily_change_pct):
        return None

    box_range_pct = metrics["box_range_pct"]
    if metrics["trading_value"] < 5_000_000_000:
        return None
    if not (5 <= box_range_pct <= 25):
        return None
    if latest["종가"] < metrics["box_high"] * 0.95:
        return None
    if latest["종가"] <= latest["ma20"]:
        return None
    if metrics["ma20_slope"] <= 0:
        return None

    recent_20 = metrics["recent_20d_volatility"]
    recent_10 = metrics["recent_10d_volatility"]
    recent_5 = metrics["recent_5d_volatility"]

    if not (recent_20 > recent_10 > recent_5):
        return None
    if metrics["vol5_ratio"] < 1.05:
        return None
    if metrics["vol_ratio"] < 1.1:
        return None

    box_score = 0
    if 5 <= box_range_pct <= 12:
        box_score = 20
    elif 12 < box_range_pct <= 18:
        box_score = 16
    elif 18 < box_range_pct <= 25:
        box_score = 12
    if box_score == 0:
        return None

    breakout_score = 0
    if latest["종가"] >= metrics["box_high"] * 0.95:
        breakout_score += 10
    if latest["종가"] >= metrics["box_high"] * 0.98:
        breakout_score += 8
    if latest["종가"] >= metrics["box_high"] * 0.995:
        breakout_score += 4
    if latest["종가"] > metrics["box_high"]:
        breakout_score += 3
    breakout_score = min(breakout_score, 25)
    if breakout_score == 0:
        return None

    contraction_20_10 = 1 - _safe_ratio(recent_10, recent_20)
    contraction_10_5 = 1 - _safe_ratio(recent_5, recent_10)
    if contraction_20_10 >= 0.2 and contraction_10_5 >= 0.15:
        vcp_score = 20
    elif contraction_20_10 >= 0.12 and contraction_10_5 >= 0.08:
        vcp_score = 17
    else:
        vcp_score = 14
    if metrics.get("volume_contraction"):
        vcp_score = min(vcp_score + 2, 20)

    if metrics["vol5_ratio"] >= 1.2 and metrics["vol_ratio"] >= 1.4:
        volume_score = 15
    elif metrics["vol5_ratio"] >= 1.1 and metrics["vol_ratio"] >= 1.2:
        volume_score = 12
    else:
        volume_score = 9

    trend_score = 0
    if latest["종가"] > latest["ma20"]:
        trend_score += 8
    if metrics["ma20_slope"] > 0:
        trend_score += 4
    if latest["종가"] > latest["ma60"]:
        trend_score += 3
    trend_score = min(trend_score, 15)

    stop_price = max(metrics["box_low"] * 0.98, latest["ma20"] * 0.98)
    target_price = latest["종가"] * 1.12
    score_parts = {
        "liquidity": 0,
        "volume": volume_score,
        "trend": trend_score,
        "breakout": breakout_score,
        "box": box_score,
        "vcp": vcp_score,
        "rs": _score_relative_strength(metrics),
        "risk": 0,
        "overheat": _score_not_overheated(metrics),
    }
    reasons = [
        f"박스권 형성 여부: 최근 20일 박스폭 {box_range_pct:.2f}%로 스윙 박스 구간에 해당합니다.",
        (
            "박스 상단 근접/돌파 여부: "
            + ("현재 종가가 박스 상단을 돌파했습니다." if latest["종가"] > metrics["box_high"] else "현재 종가가 박스 상단 95% 이상 구간에 근접했습니다.")
        ),
        (
            f"변동성 축소 여부: 20일→10일→5일 변동성이 "
            f"{metrics['recent_20d_volatility']:.2f}% → {metrics['recent_10d_volatility']:.2f}% → {metrics['recent_5d_volatility']:.2f}% 흐름입니다."
        ),
        (
            f"거래량 증가 여부: 최근 5일 평균 거래량은 20일 평균의 {metrics['vol5_ratio']:.2f}배이고, "
            f"돌파일 거래량은 20일 평균의 {metrics['vol_ratio']:.2f}배입니다."
        ),
    ]

    return _build_candidate(
        "swing",
        ticker,
        name,
        metrics,
        stop_price,
        target_price,
        reasons,
        score_parts,
    )


def evaluate_swing_fallback(ticker: str, name: str, df: pd.DataFrame) -> Optional[dict[str, Any]]:
    """억지 스윙 후보를 만들지 않기 위해 보조 후보는 사용하지 않습니다."""
    return None


def evaluate_mid_strategy(ticker: str, name: str, df: pd.DataFrame) -> Optional[dict[str, Any]]:
    """1~3개월 중기 후보를 찾습니다."""
    metrics = _calculate_common_metrics(df)
    if metrics is None:
        return None

    latest = metrics["latest"]

    if not _passes_downside_risk_filter(metrics, SETTINGS.min_mid_daily_change_pct):
        return None

    if metrics["ma20_slope"] <= 0 or metrics["ma60_slope"] <= -0.01:
        return None
    if not (latest["종가"] > latest["ma20"] > latest["ma60"]):
        return None
    if latest["종가"] < metrics["high60"] * 0.92:
        return None
    if metrics["daily_change_pct"] > 8:
        return None
    if metrics["high52_ratio"] < 0.90:
        return None
    relative_strength_values = (
        metrics["rs_1m"],
        metrics["rs_3m"],
        metrics["rs_6m"],
    )
    if metrics["rs_3m"] <= 0 or sum(value > 0 for value in relative_strength_values) < 2:
        return None

    stop_price = latest["ma20"] * 0.97
    target_price = latest["종가"] * 1.18
    score_parts = {
        "liquidity": _score_liquidity(metrics),
        "volume": _score_volume(metrics),
        "trend": _score_ma_trend(metrics, require_mid_trend=True),
        "breakout": _score_breakout(metrics, near_high=True),
        "box": _score_box_breakout(metrics),
        "vcp": _score_vcp(metrics),
        "rs": _score_relative_strength(metrics),
        "risk": _score_risk_reward(metrics, stop_price, target_price),
        "overheat": _score_not_overheated(metrics),
    }
    reasons = [
        "20일선과 60일선이 함께 상승하는 정배열 구조입니다.",
        "60일 신고가 근처에서 강한 추세를 유지하고 있습니다.",
        "과열이 심하지 않은 추세주 관점의 중기 후보입니다.",
    ]

    return _build_candidate(
        "mid",
        ticker,
        name,
        metrics,
        stop_price,
        target_price,
        reasons,
        score_parts,
    )


def evaluate_mid_fallback(ticker: str, name: str, df: pd.DataFrame) -> Optional[dict[str, Any]]:
    """성과 검증 결과에 따라 완화형 중기 후보는 자동추천에서 사용하지 않습니다."""
    return None


def diagnose_strategy_filters(ticker: str, name: str, df: pd.DataFrame) -> dict[str, Any]:
    """점수나 전략 판정은 바꾸지 않고 종목별 필터 통과·탈락 근거를 설명합니다."""
    metrics = _calculate_common_metrics(df)
    if metrics is None:
        return {
            "ticker": ticker,
            "name": name,
            "technical_filter": "FAIL",
            "trend": "UNKNOWN",
            "liquidity": "FAIL",
            "setup_score": 0,
            "entry_score": 0,
            "risk_penalty": 0,
            "risk_filter": "UNKNOWN",
            "failure_reason": "공통 필터 실패: 이력·가격·거래대금·등락률 조건 중 하나를 충족하지 못했습니다.",
            "strategies": {},
        }

    latest = metrics["latest"]
    strategy_checks: dict[str, list[tuple[bool, str]]] = {
        "short_primary": [
            (0.5 <= metrics["daily_change_pct"] <= 12, "당일 등락률이 0.5~12% 범위를 벗어났습니다."),
            (latest["종가"] > latest["ma5"], "종가가 5일선 이하입니다."),
            (metrics["close_to_high_pct"] <= 4, "종가가 당일 고가에서 4% 초과 밀렸습니다."),
            (metrics["vol_ratio"] >= 1.2, "당일 거래량이 20일 평균의 1.2배 미만입니다."),
        ],
        "short_fallback": [
            (metrics["daily_change_pct"] >= 0, "당일 등락률이 음수입니다."),
            (latest["종가"] > latest["ma5"] * 0.985, "종가가 5일선 허용범위 아래입니다."),
            (
                metrics["vol_ratio"] >= 1.0 or metrics["value_ratio"] >= 1.0,
                "거래량과 거래대금이 모두 20일 평균 미만입니다.",
            ),
        ],
        "swing_primary": [
            (
                _passes_downside_risk_filter(metrics, SETTINGS.min_swing_daily_change_pct),
                f"하락위험 필터 실패: 등락 {metrics['daily_change_pct']:.2f}%, 갭 {metrics['gap_pct']:.2f}%, 몸통 {metrics['candle_body_pct']:.2f}%.",
            ),
            (metrics["trading_value"] >= 5_000_000_000, "거래대금이 50억원 미만입니다."),
            (5 <= metrics["box_range_pct"] <= 25, "20일 박스폭이 5~25% 범위를 벗어났습니다."),
            (latest["종가"] >= metrics["box_high"] * 0.95, "종가가 20일 박스 상단의 95% 미만입니다."),
            (latest["종가"] > latest["ma20"], "종가가 20일선 이하입니다."),
            (metrics["ma20_slope"] > 0, "20일선 기울기가 상승이 아닙니다."),
            (
                metrics["recent_20d_volatility"] > metrics["recent_10d_volatility"] > metrics["recent_5d_volatility"],
                "20일→10일→5일 변동성 축소가 성립하지 않습니다.",
            ),
            (metrics["vol5_ratio"] >= 1.05, "5일 평균 거래량이 20일 평균의 1.05배 미만입니다."),
            (metrics["vol_ratio"] >= 1.1, "당일 거래량이 20일 평균의 1.1배 미만입니다."),
        ],
        "mid_primary": [
            (
                _passes_downside_risk_filter(metrics, SETTINGS.min_mid_daily_change_pct),
                f"하락위험 필터 실패: 등락 {metrics['daily_change_pct']:.2f}%, 갭 {metrics['gap_pct']:.2f}%, 몸통 {metrics['candle_body_pct']:.2f}%.",
            ),
            (metrics["ma20_slope"] > 0 and metrics["ma60_slope"] > -0.01, "20일선 또는 60일선 기울기 조건 미달입니다."),
            (latest["종가"] > latest["ma20"] > latest["ma60"], "종가>20일선>60일선 정배열이 아닙니다."),
            (latest["종가"] >= metrics["high60"] * 0.92, "종가가 60일 고점의 92% 미만입니다."),
            (metrics["daily_change_pct"] <= 12, "당일 상승률이 12%를 초과했습니다."),
        ],
        "mid_fallback": [
            (
                _passes_downside_risk_filter(metrics, SETTINGS.min_mid_fallback_daily_change_pct),
                f"하락위험 필터 실패: 등락 {metrics['daily_change_pct']:.2f}%, 갭 {metrics['gap_pct']:.2f}%, 몸통 {metrics['candle_body_pct']:.2f}%.",
            ),
            (metrics["ma20_slope"] >= 0 and metrics["ma60_slope"] > -0.10, "중기 이동평균 기울기 조건 미달입니다."),
            (latest["종가"] > latest["ma20"] * 0.97, "종가가 20일선 허용범위 아래입니다."),
            (latest["종가"] >= metrics["high60"] * 0.85, "종가가 60일 고점의 85% 미만입니다."),
        ],
    }

    evaluators = {
        "short_primary": evaluate_short_strategy,
        "short_fallback": evaluate_short_fallback,
        "swing_primary": evaluate_swing_strategy,
        "mid_primary": evaluate_mid_strategy,
        "mid_fallback": evaluate_mid_fallback,
    }
    strategy_debug: dict[str, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    for key, checks in strategy_checks.items():
        failed = [reason for passed, reason in checks if not passed]
        candidate = evaluators[key](ticker, name, df)
        if candidate:
            candidates.append(candidate)
        strategy_debug[key] = {
            "status": "PASS" if candidate else "FAIL",
            "failure_reason": "" if candidate else (failed[0] if failed else "최소 점수 조건 미달입니다."),
            "failed_checks": failed,
            "score": candidate.get("total_score", 0) if candidate else 0,
        }

    best = max(candidates, key=lambda row: row["total_score"], default={})
    if best:
        setup_score = sum(best.get(field, 0) for field in ("score_breakout", "score_box", "score_vcp"))
        entry_score = sum(best.get(field, 0) for field in ("score_liquidity", "score_volume", "score_trend"))
    else:
        # 탈락 종목도 현재 상태를 비교할 수 있도록 중기 기준의 진단 점수만 계산합니다.
        # 이 값은 실제 추천 점수나 순위에는 사용하지 않습니다.
        setup_score = (
            _score_breakout(metrics, near_high=True)
            + _score_box_breakout(metrics)
            + _score_vcp(metrics)
        )
        entry_score = (
            _score_liquidity(metrics)
            + _score_volume(metrics)
            + _score_ma_trend(metrics, require_mid_trend=True)
        )
    risk_filter_pass = all(
        (
            metrics["gap_pct"] >= SETTINGS.max_gap_down_pct,
            metrics["candle_body_pct"] >= SETTINGS.max_bearish_body_pct,
        )
    )
    first_failure = next(
        (
            detail["failure_reason"]
            for detail in strategy_debug.values()
            if detail["failure_reason"]
        ),
        "",
    )
    return {
        "ticker": ticker,
        "name": name,
        "technical_filter": "PASS" if candidates else "FAIL",
        "trend": "PASS" if latest["종가"] > latest["ma20"] and metrics["ma20_slope"] >= 0 else "FAIL",
        "liquidity": "PASS",
        "setup_score": int(setup_score),
        "entry_score": int(entry_score),
        # 현재 점수식은 위험을 음수 감점하지 않고 필터 탈락으로 처리합니다.
        "risk_penalty": 0,
        "risk_filter": "PASS" if risk_filter_pass else "FAIL",
        "failure_reason": "" if candidates else first_failure,
        "metrics": {
            "change_pct": _safe_number(metrics["daily_change_pct"]),
            "gap_pct": _safe_number(metrics["gap_pct"]),
            "candle_body_pct": _safe_number(metrics["candle_body_pct"]),
            "vol_ratio": _safe_number(metrics["vol_ratio"]),
            "value_ratio": _safe_number(metrics["value_ratio"]),
            "trading_value": int(metrics["trading_value"]),
            "high52_distance_pct": _safe_number(metrics["high52_distance_pct"]),
            "rs_1m": _safe_number(metrics["rs_1m"]),
            "rs_3m": _safe_number(metrics["rs_3m"]),
            "rs_6m": _safe_number(metrics["rs_6m"]),
            "staged_contraction": bool(metrics["staged_contraction"]),
            "volume_contraction": bool(metrics["volume_contraction"]),
            "volume_contraction_ratio": _safe_number(metrics["volume_contraction_ratio"]),
        },
        "strategies": strategy_debug,
    }
