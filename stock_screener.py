"""
미국 주식 테마 종목 스크리너
- 거래량 급등, 가격 변동, 뉴스 빈도 기반 종목 선별
- 실적 데이터 포함
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import logging
import finnhub_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 스크리닝 대상 유니버스 (S&P500 + 주요 나스닥 종목) ──
# 실제 운영 시 Finviz 등에서 동적으로 가져올 수도 있음
UNIVERSE = [
    # 빅테크
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "NFLX",
    # 반도체
    "AMD", "INTC", "AVGO", "QCOM", "MU", "MRVL", "ARM", "SMCI", "TSM",
    # AI / 소프트웨어
    "PLTR", "CRM", "SNOW", "AI", "DDOG", "NET", "CRWD", "PANW",
    # 바이오 / 헬스케어
    "LLY", "NVO", "MRNA", "PFE", "JNJ", "UNH", "ABBV",
    # 에너지 / 소재
    "XOM", "CVX", "LNG", "FSLR", "ENPH",
    # 금융
    "JPM", "GS", "V", "MA", "COIN", "SQ",
    # 소비재 / 기타
    "COST", "WMT", "NKE", "DIS", "RIVN", "LCID", "SOFI",
    # 방산 / 산업
    "LMT", "RTX", "BA", "CAT", "GE",
    # 최근 화제 종목 (주기적으로 업데이트)
    "MSTR", "IONQ", "RGTI", "RKLB", "LUNR",
]

SECTOR_MAP = {
    "AAPL": "빅테크", "MSFT": "빅테크", "GOOGL": "빅테크", "AMZN": "빅테크",
    "META": "빅테크", "NVDA": "AI/반도체", "TSLA": "EV/에너지", "NFLX": "미디어",
    "AMD": "AI/반도체", "INTC": "반도체", "AVGO": "AI/반도체", "QCOM": "반도체",
    "MU": "반도체", "MRVL": "반도체", "ARM": "AI/반도체", "SMCI": "AI/반도체", "TSM": "반도체",
    "PLTR": "AI/소프트웨어", "CRM": "클라우드", "SNOW": "클라우드", "AI": "AI",
    "DDOG": "클라우드", "NET": "클라우드", "CRWD": "사이버보안", "PANW": "사이버보안",
    "LLY": "바이오", "NVO": "바이오", "MRNA": "바이오", "PFE": "바이오",
    "JNJ": "헬스케어", "UNH": "헬스케어", "ABBV": "바이오",
    "XOM": "에너지", "CVX": "에너지", "LNG": "에너지",
    "FSLR": "태양광", "ENPH": "태양광",
    "JPM": "금융", "GS": "금융", "V": "핀테크", "MA": "핀테크",
    "COIN": "크립토", "SQ": "핀테크",
    "COST": "소비재", "WMT": "소비재", "NKE": "소비재",
    "DIS": "미디어", "RIVN": "EV", "LCID": "EV", "SOFI": "핀테크",
    "LMT": "방산", "RTX": "방산", "BA": "항공/방산", "CAT": "산업재", "GE": "산업재",
    "MSTR": "크립토/BTC", "IONQ": "양자컴퓨팅", "RGTI": "양자컴퓨팅",
    "RKLB": "우주항공", "LUNR": "우주항공",
}


def fetch_stock_data(symbols: list, period: str = "1mo") -> dict:
    """Finnhub로 주가/거래량 데이터 수집"""
    logger.info(f"Fetching data for {len(symbols)} symbols...")
    days = 30 if "1mo" in period else 90
    return finnhub_data.download_bulk(symbols, days=days)


def analyze_volume_spike(df: pd.DataFrame, window: int = 20) -> dict:
    """거래량 급등 분석"""
    if len(df) < window:
        return {"volume_ratio": 0, "avg_volume": 0, "latest_volume": 0}

    avg_vol = df["Volume"].iloc[-window-1:-1].mean()
    latest_vol = df["Volume"].iloc[-1]
    ratio = latest_vol / avg_vol if avg_vol > 0 else 0

    return {
        "volume_ratio": round(ratio, 2),
        "avg_volume": int(avg_vol),
        "latest_volume": int(latest_vol),
    }


def analyze_price_move(df: pd.DataFrame) -> dict:
    """가격 변동 분석"""
    if len(df) < 2:
        return {"daily_change_pct": 0, "weekly_change_pct": 0, "current_price": 0}

    current = df["Close"].iloc[-1]
    prev = df["Close"].iloc[-2]
    daily_chg = ((current - prev) / prev) * 100

    week_ago = df["Close"].iloc[-6] if len(df) >= 6 else df["Close"].iloc[0]
    weekly_chg = ((current - week_ago) / week_ago) * 100

    return {
        "daily_change_pct": round(float(daily_chg), 2),
        "weekly_change_pct": round(float(weekly_chg), 2),
        "current_price": round(float(current), 2),
    }


def get_fundamentals(symbol: str) -> dict:
    """기본 펀더멘탈 데이터"""
    try:
        info = finnhub_data.get_stock_info(symbol)
        return {
            "market_cap": info.get("marketCap", 0),
            "market_cap_str": _format_market_cap(info.get("marketCap", 0)),
            "pe_ratio": round(info.get("trailingPE", 0) or 0, 1),
            "forward_pe": round(info.get("forwardPE", 0) or 0, 1),
            "eps": info.get("trailingEps", 0),
            "revenue_growth": info.get("revenueGrowth", 0),
            "earnings_date": _get_earnings_date(info),
            "sector": info.get("industry", ""),
            "short_name": info.get("shortName", symbol),
        }
    except Exception as e:
        logger.warning(f"Failed to get fundamentals for {symbol}: {e}")
        return {}


def _format_market_cap(cap: int) -> str:
    if cap >= 1e12:
        return f"${cap/1e12:.1f}T"
    elif cap >= 1e9:
        return f"${cap/1e9:.1f}B"
    elif cap >= 1e6:
        return f"${cap/1e6:.0f}M"
    return f"${cap:,.0f}"


def _get_earnings_date(info: dict) -> str:
    try:
        ts = info.get("earningsTimestamp")
        if ts:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        pass
    return ""


def calculate_score(volume_data: dict, price_data: dict, fundamentals: dict) -> float:
    """종합 점수 계산 (0~100)"""
    score = 0.0

    # 거래량 점수 (최대 35점)
    vr = volume_data.get("volume_ratio", 0)
    if vr >= 3.0:
        score += 35
    elif vr >= 2.0:
        score += 25
    elif vr >= 1.5:
        score += 15

    # 가격 변동 점수 (최대 30점) - 절대값 기준
    daily = abs(price_data.get("daily_change_pct", 0))
    if daily >= 10:
        score += 30
    elif daily >= 5:
        score += 22
    elif daily >= 3:
        score += 15
    elif daily >= 2:
        score += 8

    # 주간 모멘텀 (최대 15점)
    weekly = abs(price_data.get("weekly_change_pct", 0))
    if weekly >= 15:
        score += 15
    elif weekly >= 10:
        score += 10
    elif weekly >= 5:
        score += 5

    # 실적 임박 보너스 (최대 10점)
    earnings_date = fundamentals.get("earnings_date", "")
    if earnings_date:
        try:
            ed = datetime.strptime(earnings_date, "%Y-%m-%d")
            days_to_earnings = (ed - datetime.now()).days
            if 0 <= days_to_earnings <= 7:
                score += 10
            elif 0 <= days_to_earnings <= 14:
                score += 5
        except Exception:
            pass

    # 시가총액 가산점 (대형주 선호, 최대 10점)
    mc = fundamentals.get("market_cap", 0)
    if mc >= 100e9:
        score += 10
    elif mc >= 10e9:
        score += 7
    elif mc >= 1e9:
        score += 4

    return round(score, 1)


def screen_stocks(top_n: int = 5) -> list:
    """
    메인 스크리닝 함수
    Returns: 상위 N개 종목의 분석 결과 리스트
    """
    logger.info("=== Stock Screening Started ===")

    # 1) 가격/거래량 데이터 수집
    stock_data = fetch_stock_data(UNIVERSE)

    candidates = []

    for symbol, df in stock_data.items():
        # 2) 거래량 분석
        vol = analyze_volume_spike(df)
        # 최소 거래량 비율 필터
        if vol["volume_ratio"] < 1.3:
            continue

        # 3) 가격 변동 분석
        price = analyze_price_move(df)
        # 최소 변동 필터
        if abs(price["daily_change_pct"]) < 1.0:
            continue

        # 4) 펀더멘탈
        fund = get_fundamentals(symbol)

        # 5) 점수 계산
        score = calculate_score(vol, price, fund)

        theme = SECTOR_MAP.get(symbol, fund.get("sector", "기타"))

        candidates.append({
            "symbol": symbol,
            "name": fund.get("short_name", symbol),
            "theme": theme,
            "score": score,
            "price": price,
            "volume": vol,
            "fundamentals": fund,
        })

    # 점수 기준 정렬
    candidates.sort(key=lambda x: x["score"], reverse=True)

    top = candidates[:top_n]
    logger.info(f"=== Screening Complete: {len(candidates)} candidates, top {top_n} selected ===")

    return top


def format_report(stocks: list) -> str:
    """텔레그램 전송용 리포트 포맷 (Markdown)"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"📊 *미국 주식 테마 종목 리포트*",
        f"📅 {now} (한국시간)\n",
        "─" * 25,
    ]

    for i, s in enumerate(stocks, 1):
        p = s["price"]
        v = s["volume"]
        f = s["fundamentals"]

        direction = "🔴" if p["daily_change_pct"] < 0 else "🟢"
        change_sign = "+" if p["daily_change_pct"] > 0 else ""

        lines.append(f"\n*{i}. {s['symbol']}* ({s['name']})")
        lines.append(f"   테마: #{s['theme']}")
        lines.append(f"   {direction} ${p['current_price']} ({change_sign}{p['daily_change_pct']}%)")
        lines.append(f"   📈 주간: {change_sign if p['weekly_change_pct']>0 else ''}{p['weekly_change_pct']}%")
        lines.append(f"   🔥 거래량: 평소 대비 {v['volume_ratio']}배")

        if f.get("market_cap_str"):
            lines.append(f"   💰 시총: {f['market_cap_str']}")
        if f.get("pe_ratio") and f["pe_ratio"] > 0:
            lines.append(f"   📊 PER: {f['pe_ratio']} (Fwd: {f.get('forward_pe', '-')})")
        if f.get("earnings_date"):
            lines.append(f"   📅 실적발표: {f['earnings_date']}")

        lines.append(f"   ⭐ 관심도 점수: {s['score']}/100")
        lines.append("")

    lines.append("─" * 25)
    lines.append("_※ 투자 판단의 참고자료이며, 매수/매도 추천이 아닙니다._")

    return "\n".join(lines)


# ── 단독 실행 테스트 ──
if __name__ == "__main__":
    results = screen_stocks(top_n=5)
    report = format_report(results)
    print(report)

    # JSON으로도 저장
    with open("daily_picks.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print("\n✅ Results saved to daily_picks.json")
