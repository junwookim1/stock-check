"""
멀티팩터 주식 스크리너
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
팩터:
  1. 모멘텀   (1W/1M/3M 수익률)          30%
  2. 기술적   (RSI, MACD, 이동평균)       25%
  3. 거래량   (RVOL, 52주 고가, 돌파)     20%
  4. 실적     (성장률, 실적발표일)         15%
  5. 펀더멘탈 (PER, 시총, 애널리스트)     10%
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
import pytz
import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")

# ── 스크리닝 유니버스 ──────────────────────────────────
UNIVERSE = [
    "NVDA", "AMD", "TSLA", "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "PLTR", "SMCI", "ARM", "AVGO", "COIN", "MSTR", "IONQ", "RGTI",
    "RKLB", "SOFI", "RIVN", "LLY", "NVO", "MRNA", "CRWD", "PANW",
    "NET", "CRM", "SNOW", "DDOG", "QCOM", "MU", "MRVL", "INTC",
    "V", "MA", "JPM", "GS", "XOM", "CVX", "LMT", "RTX", "BA",
    "COST", "WMT", "NFLX", "DIS", "ABBV", "UNH", "TSM", "FSLR", "ENPH",
]

SECTOR_MAP = {
    "AI": ["NVDA", "AMD", "AVGO", "ARM", "SMCI", "PLTR", "CRM", "SNOW"],
    "반도체": ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "MU", "MRVL", "ARM", "SMCI", "TSM"],
    "빅테크": ["AAPL", "MSFT", "GOOGL", "AMZN", "META"],
    "EV": ["TSLA", "RIVN"],
    "바이오": ["LLY", "NVO", "MRNA", "ABBV"],
    "헬스케어": ["LLY", "NVO", "UNH", "ABBV"],
    "에너지": ["XOM", "CVX", "FSLR", "ENPH"],
    "방산": ["LMT", "RTX", "BA"],
    "사이버보안": ["CRWD", "PANW", "NET"],
    "클라우드": ["CRM", "SNOW", "DDOG", "NET"],
    "크립토": ["COIN", "MSTR"],
    "핀테크": ["V", "MA", "SOFI", "COIN"],
    "금융": ["JPM", "GS", "V", "MA"],
    "양자": ["IONQ", "RGTI"],
}


# ── 결과 데이터클래스 ──────────────────────────────────
@dataclass
class StockResult:
    symbol: str
    name: str
    price: float
    change_pct: float
    total_score: float
    grade: str
    momentum: dict = field(default_factory=dict)
    technical: dict = field(default_factory=dict)
    volume: dict = field(default_factory=dict)
    earnings: dict = field(default_factory=dict)
    fundamental: dict = field(default_factory=dict)
    signals: list = field(default_factory=list)


# ── 유틸 ──────────────────────────────────────────────
def _bar(score: float, width: int = 10) -> str:
    """점수(0~100)를 █░ 바로 변환"""
    filled = max(0, min(width, round(score / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def assign_grade(total: float) -> str:
    if total >= 80:
        return "S"
    if total >= 65:
        return "A"
    if total >= 50:
        return "B"
    if total >= 35:
        return "C"
    return "D"


def compute_total_score(m: dict, t: dict, v: dict, e: dict, f: dict) -> float:
    """팩터 가중 합산 → 0~100"""
    return round(
        m["score"] * 0.30
        + t["score"] * 0.25
        + v["score"] * 0.20
        + e["score"] * 0.15
        + f["score"] * 0.10,
        1,
    )


# ── 팩터 스코어 함수 ──────────────────────────────────
def score_momentum(data: pd.DataFrame) -> dict:
    """1W/1M/3M 모멘텀 → 0~100"""
    close = data["Close"].dropna()

    def _ret(n: int) -> float:
        if len(close) > n:
            return round(float((close.iloc[-1] / close.iloc[-n] - 1) * 100), 2)
        return 0.0

    ret_1w = _ret(5)
    ret_1m = _ret(21)
    ret_3m = _ret(63)

    score = 50.0
    score += max(-15, min(15, ret_1w * 3))
    score += max(-20, min(20, ret_1m * 1.5))
    score += max(-15, min(15, ret_3m * 0.5))

    return {
        "score": round(max(0, min(100, score))),
        "ret_1w": ret_1w,
        "ret_1m": ret_1m,
        "ret_3m": ret_3m,
    }


def score_technical(data: pd.DataFrame) -> dict:
    """RSI / MACD / 이동평균 → 0~100"""
    close = data["Close"].dropna()
    signals = []
    score = 50.0

    # RSI(14)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = float(100 - 100 / (1 + gain.iloc[-1] / (loss.iloc[-1] + 1e-9)))

    if rsi > 70:
        score -= 10
        signals.append("RSI 과매수")
    elif rsi > 55:
        score += 10
        signals.append("RSI 강세")
    elif rsi < 30:
        score -= 15
        signals.append("RSI 과매도")
    elif rsi < 45:
        score -= 5

    # MACD(12,26,9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    sig = macd.ewm(span=9, adjust=False).mean()
    histogram = float(macd.iloc[-1] - sig.iloc[-1])
    prev_hist = float(macd.iloc[-2] - sig.iloc[-2]) if len(macd) >= 2 else 0
    macd_cross = prev_hist < 0 < histogram

    if macd_cross:
        score += 15
        signals.append("MACD 골든크로스")
    elif histogram > 0:
        score += 8
    else:
        score -= 8

    # 이동평균
    p = float(close.iloc[-1])
    for period, bonus in [(20, 8), (50, 7), (200, 5)]:
        if len(close) >= period:
            ma = float(close.rolling(period).mean().iloc[-1])
            if p > ma:
                score += bonus
                if period == 20:
                    signals.append("20MA 위")
                elif period == 200:
                    signals.append("200MA 위")
            else:
                score -= bonus // 2

    return {
        "score": round(max(0, min(100, score))),
        "rsi": round(rsi, 1),
        "macd_cross": macd_cross,
        "macd_histogram": round(histogram, 4),
        "signals": signals,
    }


def score_volume_breakout(data: pd.DataFrame) -> dict:
    """RVOL / 52주 신고가 / 20일 돌파 → 0~100"""
    close = data["Close"].dropna()
    volume = data["Volume"].dropna()
    signals = []
    score = 40.0

    if len(volume) < 21:
        return {"score": 40, "rvol": 1.0, "at_52w_high": False, "breakout_20d": False, "signals": []}

    avg_vol = float(volume.iloc[-21:-1].mean())
    rvol = round(float(volume.iloc[-1]) / (avg_vol + 1), 2) if avg_vol > 0 else 1.0

    if rvol >= 3.0:
        score += 30
        signals.append(f"거래량 폭발 {rvol}x")
    elif rvol >= 2.0:
        score += 20
        signals.append(f"거래량 급증 {rvol}x")
    elif rvol >= 1.5:
        score += 10
        signals.append(f"거래량 증가 {rvol}x")
    elif rvol < 0.7:
        score -= 10

    price = float(close.iloc[-1])
    high_52w = float(close.tail(252).max()) if len(close) >= 252 else float(close.max())
    at_52w_high = price >= high_52w * 0.98
    if at_52w_high:
        score += 20
        signals.append("52주 신고가 근접")

    high_20d = float(close.tail(21).iloc[:-1].max()) if len(close) > 21 else float(close.max())
    breakout_20d = price > high_20d
    if breakout_20d:
        score += 15
        signals.append("20일 고점 돌파")

    return {
        "score": round(max(0, min(100, score))),
        "rvol": rvol,
        "at_52w_high": at_52w_high,
        "breakout_20d": breakout_20d,
        "signals": signals,
    }


def score_earnings(symbol: str, data: pd.DataFrame) -> dict:
    """실적 성장률 / 발표일 → 0~100"""
    signals = []
    score = 50.0
    earnings_date = None
    revenue_growth = None

    try:
        info = yf.Ticker(symbol).info

        ts = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
        if ts:
            ed = datetime.fromtimestamp(ts)
            days_left = (ed - datetime.now()).days
            if 0 <= days_left <= 14:
                score += 10
                signals.append(f"실적 D-{days_left}")
            earnings_date = ed.strftime("%m/%d")

        rev_q = info.get("revenueGrowth")
        if rev_q is not None:
            revenue_growth = round(rev_q * 100, 1)
            if revenue_growth > 20:
                score += 20
                signals.append(f"매출 +{revenue_growth}%")
            elif revenue_growth > 10:
                score += 10
                signals.append(f"매출 +{revenue_growth}%")
            elif revenue_growth < 0:
                score -= 10

        trailing_eps = info.get("trailingEps") or 0
        forward_eps = info.get("forwardEps") or 0
        if trailing_eps > 0 and forward_eps > trailing_eps:
            score += 10
            signals.append("EPS 상향 추정")

    except Exception as ex:
        logger.debug(f"score_earnings {symbol}: {ex}")

    return {
        "score": round(max(0, min(100, score))),
        "earnings_date": earnings_date,
        "revenue_growth": revenue_growth,
        "signals": signals,
    }


def score_fundamental(symbol: str) -> dict:
    """PER / 시총 / 애널리스트 → 0~100"""
    signals = []
    score = 50.0
    short_name = symbol
    market_cap_str = None
    pe_ratio = None

    try:
        info = yf.Ticker(symbol).info
        short_name = info.get("shortName", symbol)

        mc = info.get("marketCap") or 0
        if mc >= 1e12:
            market_cap_str = f"{mc/1e12:.1f}T"
            score += 10
        elif mc >= 1e11:
            market_cap_str = f"{mc/1e9:.0f}B"
            score += 5
        elif mc >= 1e9:
            market_cap_str = f"{mc/1e9:.1f}B"
        elif mc > 0:
            market_cap_str = f"{mc/1e6:.0f}M"
            score -= 5

        pe = info.get("trailingPE") or info.get("forwardPE")
        if pe and pe > 0:
            pe_ratio = round(pe, 1)
            if pe < 15:
                score += 15
                signals.append(f"PER 저평가({pe_ratio})")
            elif pe < 30:
                score += 5
            elif pe > 100:
                score -= 10
                signals.append(f"PER 고평가({pe_ratio})")

        rating = info.get("recommendationKey", "")
        if rating in ("strong_buy", "buy"):
            score += 15
            signals.append("애널리스트 매수")
        elif rating in ("sell", "strong_sell"):
            score -= 15
            signals.append("애널리스트 매도")

        profit_margin = info.get("profitMargins") or 0
        if profit_margin > 0.20:
            score += 10
            signals.append(f"순이익률 {profit_margin*100:.0f}%")
        elif profit_margin < 0:
            score -= 10

    except Exception as ex:
        logger.debug(f"score_fundamental {symbol}: {ex}")

    return {
        "score": round(max(0, min(100, score))),
        "short_name": short_name,
        "market_cap_str": market_cap_str,
        "pe_ratio": pe_ratio,
        "signals": signals,
    }


# ── 스크리너 메인 ──────────────────────────────────────
def screen_stocks_advanced(
    universe: Optional[List] = None,
    top_n: int = 5,
) -> List["StockResult"]:
    """유니버스 전체 스크리닝 → 상위 top_n 반환"""
    symbols = universe or UNIVERSE
    results = []

    try:
        raw = yf.download(symbols, period="3mo", group_by="ticker", progress=False, threads=True)
    except Exception as ex:
        logger.error(f"Bulk download failed: {ex}")
        return []

    for sym in symbols:
        try:
            df = raw[sym].dropna() if len(symbols) > 1 else raw.dropna()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            if len(df) < 15:
                continue

            m = score_momentum(df)
            t = score_technical(df)
            v = score_volume_breakout(df)
            e = score_earnings(sym, df)
            f = score_fundamental(sym)
            total = compute_total_score(m, t, v, e, f)
            grade = assign_grade(total)

            price = float(df["Close"].iloc[-1])
            chg = round((price / float(df["Close"].iloc[-2]) - 1) * 100, 2)
            all_signals = (
                t.get("signals", []) + v.get("signals", []) +
                e.get("signals", []) + f.get("signals", [])
            )

            results.append(StockResult(
                symbol=sym,
                name=f.get("short_name", sym),
                price=price,
                change_pct=chg,
                total_score=total,
                grade=grade,
                momentum=m,
                technical=t,
                volume=v,
                earnings=e,
                fundamental=f,
                signals=all_signals[:6],
            ))

        except Exception as ex:
            logger.debug(f"Screen {sym}: {ex}")

    results.sort(key=lambda x: x.total_score, reverse=True)
    return results[:top_n]


def format_advanced_report(stocks: List["StockResult"]) -> str:
    """텔레그램용 멀티팩터 리포트"""
    if not stocks:
        return "📊 오늘은 특별히 주목할 종목이 없습니다."

    now = datetime.now(KST).strftime("%m/%d %H:%M")
    GRADE_EMOJI = {"S": "🏆", "A": "🔥", "B": "✅", "C": "📌", "D": "⬜"}
    lines = [f"📊 *오늘의 추천 종목* ({now} KST)\n"]

    for i, s in enumerate(stocks, 1):
        icon = "🟢" if s.change_pct > 0 else "🔴"
        sign = "+" if s.change_pct > 0 else ""
        ge = GRADE_EMOJI.get(s.grade, "")
        m, t, v = s.momentum, s.technical, s.volume

        lines.append(f"{i}. {ge} *{s.symbol}* ({s.name})")
        lines.append(f"   {icon} ${s.price:.2f} ({sign}{s.change_pct}%) | 점수 *{s.total_score}* ({s.grade})")
        lines.append(f"   모멘텀 {m['score']} | 기술 {t['score']} | 거래량 {v['score']}")
        lines.append(f"   1M {'+' if m['ret_1m']>0 else ''}{m['ret_1m']}% | RSI {t['rsi']:.0f} | RVOL {v['rvol']}x")
        if s.signals:
            lines.append(f"   🔑 {' · '.join(s.signals[:3])}")
        lines.append("")

    lines.append("_⚠️ 정보 제공 목적이며 투자 권유가 아닙니다_")
    return "\n".join(lines)


def to_json(stocks: List["StockResult"]) -> List[dict]:
    """StockResult 리스트 → JSON 직렬화 (AI 요약용)"""
    return [
        {
            "symbol": s.symbol,
            "name": s.name,
            "price": s.price,
            "change_pct": s.change_pct,
            "total_score": s.total_score,
            "grade": s.grade,
            "momentum": s.momentum,
            "technical": s.technical,
            "volume": s.volume,
            "earnings": s.earnings,
            "fundamental": s.fundamental,
            "signals": s.signals,
        }
        for s in stocks
    ]
