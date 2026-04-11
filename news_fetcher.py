"""
뉴스 수집 및 테마 감지 모듈
- Finviz 뉴스 스크래핑
- NewsAPI 연동 (선택)
- 테마 키워드 매칭
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import logging
import os
import re
from typing import List

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# 테마 키워드 사전 — 뉴스 헤드라인에서 테마를 자동 분류
THEME_KEYWORDS = {
    "AI": ["artificial intelligence", "AI ", "generative ai", "chatgpt", "llm",
           "machine learning", "nvidia", "gpu", "data center"],
    "반도체": ["semiconductor", "chip", "foundry", "tsmc", "fab", "wafer",
              "memory", "hbm", "dram", "nand"],
    "양자컴퓨팅": ["quantum", "qubit", "quantum computing"],
    "우주항공": ["space", "rocket", "satellite", "lunar", "mars", "launch"],
    "EV/배터리": ["electric vehicle", "ev ", "battery", "lithium", "charging",
                 "tesla", "rivian"],
    "바이오/헬스": ["fda", "drug", "trial", "pharma", "biotech", "obesity",
                   "glp-1", "vaccine", "approval"],
    "크립토": ["bitcoin", "crypto", "blockchain", "ethereum", "btc"],
    "에너지": ["oil", "natural gas", "solar", "wind", "energy", "opec"],
    "사이버보안": ["cybersecurity", "breach", "hack", "ransomware", "security"],
    "방산": ["defense", "military", "weapon", "pentagon", "nato"],
    "금리/매크로": ["fed", "interest rate", "inflation", "cpi", "fomc", "powell",
                   "treasury", "yield"],
}


def fetch_finviz_news(symbol: str) -> List[dict]:
    """Finviz에서 종목별 최신 뉴스 헤드라인 수집"""
    url = f"https://finviz.com/quote.ashx?t={symbol}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        news_table = soup.find("table", {"id": "news-table"})
        if not news_table:
            return []

        news_items = []
        current_date = ""

        for row in news_table.find_all("tr")[:10]:  # 최근 10개
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            date_cell = cells[0].text.strip()
            # 날짜가 포함된 경우 업데이트
            if len(date_cell) > 8:
                current_date = date_cell.split()[0]
                time_str = date_cell.split()[1] if len(date_cell.split()) > 1 else ""
            else:
                time_str = date_cell

            link = cells[1].find("a")
            if link:
                news_items.append({
                    "date": current_date,
                    "time": time_str,
                    "headline": link.text.strip(),
                    "url": link.get("href", ""),
                    "source": cells[1].find("span").text.strip() if cells[1].find("span") else "",
                })

        return news_items

    except Exception as e:
        logger.warning(f"Finviz news fetch failed for {symbol}: {e}")
        return []


def fetch_newsapi(symbol: str, company_name: str = "", api_key: str = "") -> List[dict]:
    """
    NewsAPI에서 종목 관련 뉴스 수집
    무료 플랜: 하루 100회, 24시간 이내 뉴스만
    API키: https://newsapi.org 에서 발급
    """
    api_key = api_key or os.getenv("NEWSAPI_KEY", "")
    if not api_key:
        return []

    query = f"{symbol} stock"
    if company_name:
        query = f"{company_name} OR {symbol}"

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 5,
        "from": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        "apiKey": api_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data.get("status") != "ok":
            return []

        return [
            {
                "headline": a["title"],
                "source": a["source"]["name"],
                "url": a["url"],
                "published": a["publishedAt"],
                "description": a.get("description", ""),
            }
            for a in data.get("articles", [])
        ]

    except Exception as e:
        logger.warning(f"NewsAPI fetch failed for {symbol}: {e}")
        return []


def detect_themes(headlines: List[str]) -> List[str]:
    """뉴스 헤드라인에서 테마 키워드 매칭"""
    combined = " ".join(headlines).lower()
    detected = []

    for theme, keywords in THEME_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in combined:
                detected.append(theme)
                break

    return list(set(detected))


def get_news_summary(symbol: str, company_name: str = "") -> dict:
    """
    종목의 뉴스 요약 정보 반환
    Returns: {
        "news_count": int,
        "headlines": list[str],
        "themes": list[str],
        "top_news": list[dict],  # 상위 3개 뉴스
    }
    """
    # Finviz 뉴스 (무료, 제한 없음)
    finviz_news = fetch_finviz_news(symbol)

    # NewsAPI (API키 있으면 추가)
    api_news = fetch_newsapi(symbol, company_name)

    # 합치기 (중복 제거는 간단히 헤드라인 기준)
    all_headlines = [n["headline"] for n in finviz_news]
    seen = set(all_headlines)
    for n in api_news:
        if n["headline"] not in seen:
            all_headlines.append(n["headline"])
            seen.add(n["headline"])

    # 테마 감지
    themes = detect_themes(all_headlines)

    # 상위 뉴스
    top_news = finviz_news[:3] if finviz_news else api_news[:3]

    return {
        "news_count": len(all_headlines),
        "headlines": all_headlines[:5],
        "themes": themes,
        "top_news": top_news,
    }


def fetch_trending_tickers() -> List[str]:
    """
    Finviz 스크리너에서 오늘 거래량 급등 종목 가져오기
    기존 UNIVERSE 외에 추가 발굴용
    """
    url = "https://finviz.com/screener.ashx?v=111&s=ta_unusualvolume&o=-volume"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        tickers = []
        table = soup.find("table", {"class": "table-light"})
        if table:
            for row in table.find_all("tr")[1:21]:  # 상위 20개
                cells = row.find_all("td")
                if len(cells) > 1:
                    ticker_link = cells[1].find("a")
                    if ticker_link:
                        tickers.append(ticker_link.text.strip())

        return tickers

    except Exception as e:
        logger.warning(f"Trending tickers fetch failed: {e}")
        return []


# ── 테스트 ──
if __name__ == "__main__":
    # 단일 종목 뉴스 테스트
    summary = get_news_summary("NVDA", "NVIDIA")
    print(f"NVDA 뉴스 {summary['news_count']}건")
    print(f"감지 테마: {summary['themes']}")
    for h in summary["headlines"][:3]:
        print(f"  - {h}")

    # 트렌딩 종목
    trending = fetch_trending_tickers()
    print(f"\n오늘 거래량 급등 종목: {trending[:10]}")
