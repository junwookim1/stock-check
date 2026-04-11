"""
Claude API를 활용한 종목 분석 자연어 요약 생성
- 수집된 데이터를 읽기 쉬운 한국어 리포트로 변환
- 왜 주목받는지 근거 포함
"""

import os
import json
import anthropic
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def generate_ai_summary(stocks: List[dict], news_data: Dict[str, dict]) -> str:
    """
    Claude API로 종목 분석 요약 생성

    Args:
        stocks: stock_screener의 screen_stocks() 결과
        news_data: {symbol: get_news_summary() 결과} 딕셔너리
    Returns:
        텔레그램 전송용 마크다운 리포트
    """
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set, using template report")
        return _fallback_report(stocks, news_data)

    # Claude에게 보낼 데이터 정리
    stock_info = []
    for s in stocks:
        sym = s["symbol"]
        news = news_data.get(sym, {})
        stock_info.append({
            "symbol": sym,
            "name": s.get("name", sym),
            "theme": s.get("theme", ""),
            "price": s["price"],
            "volume": s["volume"],
            "fundamentals": {
                k: v for k, v in s.get("fundamentals", {}).items()
                if k in ["market_cap_str", "pe_ratio", "forward_pe", "eps",
                         "revenue_growth", "earnings_date"]
            },
            "score": s["score"],
            "news_count": news.get("news_count", 0),
            "headlines": news.get("headlines", [])[:3],
            "detected_themes": news.get("themes", []),
        })

    prompt = f"""당신은 미국 주식 시장 전문 애널리스트입니다.
아래 데이터를 바탕으로 오늘의 테마 종목 리포트를 작성해주세요.

## 요구사항
1. 각 종목별로 **왜 오늘 주목받는지** 근거를 명확히 설명
2. 거래량, 가격 변동, 뉴스 헤드라인을 근거로 활용
3. 관련 테마/섹터 동향을 짧게 언급
4. 한국 투자자 관점에서 작성 (한국어)
5. 텔레그램 메시지 형식 (마크다운)
6. 각 종목 설명은 3~4줄로 간결하게
7. 마지막에 "오늘의 시장 한줄평" 추가
8. 투자 권유가 아닌 정보 제공 목적임을 명시

## 종목 데이터
{json.dumps(stock_info, ensure_ascii=False, indent=2)}

## 출력 형식
📊 *오늘의 미국 주식 테마 종목* (날짜)

1. **SYMBOL (이름)** — #테마
   가격/변동/거래량 요약
   주목 이유 설명 (뉴스 기반)
   펀더멘탈 한줄

(반복)

💡 오늘의 시장 한줄평: ...

⚠️ 면책조항
"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.content[0].text

    except Exception as e:
        logger.error(f"Claude API call failed: {e}")
        return _fallback_report(stocks, news_data)


def _fallback_report(stocks: List[dict], news_data: Dict[str, dict]) -> str:
    """API 키 없을 때 템플릿 기반 리포트 (advanced_screener.to_json() 형식 기준)"""
    from datetime import datetime

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    GRADE_EMOJI = {"S": "🏆", "A": "🔥", "B": "✅", "C": "📌", "D": "⬜"}
    lines = [
        "📊 *오늘의 미국 주식 테마 종목*",
        f"📅 {now} KST\n",
    ]

    for i, s in enumerate(stocks, 1):
        sym = s["symbol"]
        price = s.get("price", 0)
        chg = s.get("change_pct", 0)
        score = s.get("total_score", 0)
        grade = s.get("grade", "C")
        fund = s.get("fundamental", {})
        earn = s.get("earnings", {})
        vol = s.get("volume", {})
        news = news_data.get(sym, {})

        sign = "+" if chg > 0 else ""
        icon = "🟢" if chg > 0 else "🔴"
        ge = GRADE_EMOJI.get(grade, "")

        lines.append(f"{'─' * 28}")
        lines.append(f"*{i}. {ge} {sym}* ({s.get('name', sym)})")
        lines.append(f"   {icon} ${price:.2f} ({sign}{chg}%) | 점수 {score} ({grade})")

        rvol = vol.get("rvol", 1.0)
        if rvol >= 1.5:
            lines.append(f"   📊 거래량 {rvol}배")

        # 뉴스 헤드라인
        headlines = news.get("headlines", [])
        if headlines:
            lines.append(f"   📰 {headlines[0]}")

        # 펀더멘탈
        parts = []
        if fund.get("market_cap_str"):
            parts.append(f"시총 {fund['market_cap_str']}")
        if fund.get("pe_ratio") and fund["pe_ratio"] > 0:
            parts.append(f"PER {fund['pe_ratio']}")
        if earn.get("earnings_date"):
            parts.append(f"실적 {earn['earnings_date']}")
        if parts:
            lines.append(f"   💼 {' | '.join(parts)}")

        signals = s.get("signals", [])
        if signals:
            lines.append(f"   🔑 {' · '.join(signals[:3])}")

        lines.append("")

    lines.append("─" * 28)
    lines.append("")
    lines.append("_⚠️ 본 리포트는 정보 제공 목적이며,_")
    lines.append("_투자 판단의 최종 책임은 본인에게 있습니다._")

    return "\n".join(lines)


# ── 테스트 ──
if __name__ == "__main__":
    # 더미 데이터로 테스트
    test_stocks = [
        {
            "symbol": "NVDA",
            "name": "NVIDIA Corporation",
            "theme": "AI/반도체",
            "score": 85,
            "price": {"current_price": 135.5, "daily_change_pct": 7.2, "weekly_change_pct": 12.3},
            "volume": {"volume_ratio": 3.1, "avg_volume": 50000000, "latest_volume": 155000000},
            "fundamentals": {"market_cap_str": "$3.3T", "pe_ratio": 65.2, "forward_pe": 35.1,
                             "earnings_date": "2026-04-20"},
        },
    ]
    test_news = {
        "NVDA": {
            "news_count": 8,
            "headlines": ["NVIDIA unveils next-gen AI chip", "Data center demand surges"],
            "themes": ["AI", "반도체"],
        },
    }

    report = generate_ai_summary(test_stocks, test_news)
    print(report)
