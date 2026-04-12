"""
데이터 프로바이더 (하이브리드)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OHLCV 과거 데이터  → yfinance  (무료, API키 불필요)
현재가·펀더멘탈·실적 → Finnhub API (무료 플랜)

Finnhub 무료 플랜 note:
  /stock/candle (과거 OHLCV)는 유료 전용 → yfinance로 대체
  /quote, /stock/profile2, /company/basic-financials,
  /stock/recommendation, /calendar/earnings 는 무료 사용 가능

주요 함수:
  download_candles(symbol, days)  → pd.DataFrame (OHLCV, via yfinance)
  download_bulk(symbols, days)    → {symbol: DataFrame} (via yfinance)
  get_stock_info(symbol)          → dict (via Finnhub)
  get_quote(symbol)               → dict (현재가, via Finnhub)
  get_quotes_bulk(symbols)        → {symbol: quote}
  get_earnings_upcoming(days)     → list (via Finnhub)
"""

import os
import time as _time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests
import pandas as pd

logger = logging.getLogger(__name__)

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
_BASE = "https://finnhub.io/api/v1"

# ── 레이트리밋 ────────────────────────────────────────────
_last_call = 0.0
_MIN_INTERVAL = 1.05  # 60회/분 안전 마진


def _throttle():
    global _last_call
    elapsed = _time.time() - _last_call
    if elapsed < _MIN_INTERVAL:
        _time.sleep(_MIN_INTERVAL - elapsed)
    _last_call = _time.time()


# ── 캐시 ──────────────────────────────────────────────────
_CACHE: Dict[str, dict] = {}


def _cache_get(key: str, ttl: int) -> Optional[dict]:
    c = _CACHE.get(key)
    if c and _time.time() - c.get("_ts", 0) < ttl:
        return c
    return None


def _cache_set(key: str, data: dict) -> dict:
    data["_ts"] = _time.time()
    _CACHE[key] = data
    return data


# ── HTTP ──────────────────────────────────────────────────
def _get(endpoint: str, params: dict = None, retries: int = 2) -> dict:
    if not FINNHUB_API_KEY:
        logger.error("FINNHUB_API_KEY 환경 변수가 설정되지 않았습니다")
        return {}

    req_params = dict(params or {})
    req_params["token"] = FINNHUB_API_KEY

    for attempt in range(retries + 1):
        _throttle()  # 재시도마다 throttle 준수
        try:
            resp = requests.get(f"{_BASE}{endpoint}", params=req_params, timeout=15)
            if resp.status_code == 200:
                if not resp.content:
                    logger.warning(f"Finnhub 빈 응답: {endpoint} (attempt {attempt + 1})")
                    _time.sleep(2.0)
                    continue
                return resp.json()
            if resp.status_code == 429:
                wait = 10.0 * (attempt + 1)
                logger.warning(f"Finnhub 429, {wait}s 대기 (attempt {attempt + 1})")
                _time.sleep(wait)
                continue
            logger.warning(f"Finnhub {resp.status_code}: {endpoint}")
            return {}
        except Exception as ex:
            logger.error(f"Finnhub request error ({endpoint}): {ex}")
            if attempt < retries:
                _time.sleep(2.0 * (attempt + 1))
    return {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  OHLCV 캔들 데이터 (Yahoo Finance Chart API 직접 호출)
#  Finnhub 무료 플랜은 /stock/candle 미지원 → 대체 사용
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_YF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
_YF_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"


def _days_to_range(days: int) -> str:
    if days <= 5:   return "5d"
    if days <= 30:  return "1mo"
    if days <= 90:  return "3mo"
    if days <= 180: return "6mo"
    if days <= 365: return "1y"
    if days <= 730: return "2y"
    return "5y"


def _yf_fetch(symbol: str, days: int) -> pd.DataFrame:
    """Yahoo Finance Chart API v8 직접 호출 → DataFrame"""
    try:
        r = requests.get(
            f"{_YF_BASE}/{symbol}",
            headers=_YF_HEADERS,
            params={"interval": "1d", "range": _days_to_range(days)},
            timeout=15,
        )
        if r.status_code != 200:
            logger.warning(f"Yahoo Finance {r.status_code}: {symbol}")
            return pd.DataFrame()

        result = r.json()["chart"]["result"]
        if not result:
            return pd.DataFrame()

        res = result[0]
        timestamps = res["timestamp"]
        q = res["indicators"]["quote"][0]
        adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")

        df = pd.DataFrame({
            "Open":   q.get("open", []),
            "High":   q.get("high", []),
            "Low":    q.get("low", []),
            "Close":  adj if adj else q.get("close", []),
            "Volume": q.get("volume", []),
        }, index=pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None))
        df.index.name = "Date"
        return df.dropna()

    except Exception as ex:
        logger.error(f"Yahoo Finance fetch error ({symbol}): {ex}")
        return pd.DataFrame()


def download_candles(symbol: str, days: int = 90, **_kwargs) -> pd.DataFrame:
    """단일 종목 OHLCV → pandas DataFrame"""
    cache_key = f"candle:{symbol}:{days}"
    cached = _cache_get(cache_key, ttl=3600)
    if cached and "_df" in cached:
        return cached["_df"]

    df = _yf_fetch(symbol, days)
    if not df.empty:
        _CACHE[cache_key] = {"_ts": _time.time(), "_df": df}
    return df


def download_bulk(symbols: List[str], days: int = 90) -> Dict[str, pd.DataFrame]:
    """여러 종목 OHLCV — 순차 다운로드"""
    result: Dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols):
        df = download_candles(sym, days=days)
        if not df.empty:
            result[sym] = df
        if (i + 1) % 10 == 0:
            logger.info(f"  candles {i + 1}/{len(symbols)} done")
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  기업 정보 (yfinance .info 호환 dict)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_stock_info(symbol: str) -> dict:
    """회사 정보 반환
    Finnhub 무료 플랜 가용 엔드포인트:
      - /stock/profile2      → 회사명, 시가총액, 업종  ✅
      - /stock/recommendation → 애널리스트 매수/매도  ✅
      - /company/basic-financials → PER·EPS 등        ❌ 유료 전용
    PER·EPS·매출성장률 미제공 → 해당 팩터는 기본값 사용
    """
    cache_key = f"info:{symbol}"
    cached = _cache_get(cache_key, ttl=1800)
    if cached:
        return cached

    info: dict = {"symbol": symbol}

    # 1) 프로필 — 회사명, 시가총액, 업종 (Finnhub ✅)
    profile = _get("/stock/profile2", {"symbol": symbol})
    if profile:
        info["shortName"] = profile.get("name", symbol)
        mc = profile.get("marketCapitalization", 0)
        info["marketCap"] = mc * 1_000_000 if mc else 0
        info["industry"] = profile.get("finnhubIndustry", "")

    # 2) 52주 고가/저가 — Yahoo Finance v8 meta (무료 ✅)
    try:
        r = requests.get(
            f"{_YF_BASE}/{symbol}",
            headers=_YF_HEADERS,
            params={"interval": "1d", "range": "5d"},
            timeout=10,
        )
        if r.status_code == 200 and r.content:
            meta = r.json()["chart"]["result"][0]["meta"]
            info["52WeekHigh"] = meta.get("fiftyTwoWeekHigh")
            info["52WeekLow"] = meta.get("fiftyTwoWeekLow")
            if not info.get("shortName"):
                info["shortName"] = meta.get("shortName", symbol)
    except Exception:
        pass

    # 3) 애널리스트 추천 (Finnhub ✅)
    recs = _get("/stock/recommendation", {"symbol": symbol})
    if recs and isinstance(recs, list) and recs:
        latest = recs[0]
        buy = latest.get("buy", 0) + latest.get("strongBuy", 0)
        sell = latest.get("sell", 0) + latest.get("strongSell", 0)
        if buy > sell * 2:
            info["recommendationKey"] = "strong_buy"
        elif buy > sell:
            info["recommendationKey"] = "buy"
        elif sell > buy:
            info["recommendationKey"] = "sell"
        else:
            info["recommendationKey"] = "hold"

    # PER·EPS·매출성장률·이익률은 무료 플랜 미지원 → None
    info.setdefault("trailingPE", None)
    info.setdefault("forwardPE", None)
    info.setdefault("trailingEps", None)
    info.setdefault("forwardEps", None)
    info.setdefault("revenueGrowth", None)
    info.setdefault("profitMargins", None)

    return _cache_set(cache_key, info)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  실시간 시세
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_quote(symbol: str) -> dict:
    """현재가 조회 → yfinance .info 호환 키로 반환"""
    cache_key = f"quote:{symbol}"
    cached = _cache_get(cache_key, ttl=60)  # 1분 캐시
    if cached:
        return cached

    data = _get("/quote", {"symbol": symbol})
    if not data or not data.get("c"):
        return {}

    result = {
        "regularMarketPrice": data.get("c", 0),
        "previousClose": data.get("pc", 0),
        "change": data.get("d", 0),
        "changePercent": data.get("dp", 0),
        "dayHigh": data.get("h", 0),
        "dayLow": data.get("l", 0),
        "open": data.get("o", 0),
    }
    return _cache_set(cache_key, result)


def get_quotes_bulk(symbols: List[str]) -> Dict[str, dict]:
    """여러 종목 현재가 (순차)"""
    result = {}
    for sym in symbols:
        q = get_quote(sym)
        if q:
            result[sym] = q
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  실적 캘린더
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_earnings_upcoming(target_symbols: List[str] = None, days: int = 14) -> list:
    """향후 N일 내 실적 발표 종목 (1회 API 호출로 전체 조회)"""
    from_str = datetime.now().strftime("%Y-%m-%d")
    to_str = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")

    cache_key = f"earnings:{from_str}:{to_str}"
    cached = _cache_get(cache_key, ttl=3600)
    if cached and "_list" in cached:
        entries = cached["_list"]
    else:
        data = _get("/calendar/earnings", {"from": from_str, "to": to_str})
        entries = data.get("earningsCalendar", [])
        _CACHE[cache_key] = {"_ts": _time.time(), "_list": entries}

    if target_symbols:
        target_set = set(target_symbols)
        entries = [e for e in entries if e.get("symbol") in target_set]

    return entries


def get_yf_meta(symbol: str) -> dict:
    """Yahoo Finance v8 chart meta 조회 (임의 심볼, API키 불필요)
    한국 주식(.KS/.KQ), ETF, 지수(^KS11) 등 모든 심볼 지원
    """
    cache_key = f"yf_meta:{symbol}"
    cached = _cache_get(cache_key, ttl=300)
    if cached:
        return cached
    try:
        r = requests.get(
            f"{_YF_BASE}/{symbol}",
            headers=_YF_HEADERS,
            params={"interval": "1d", "range": "5d"},
            timeout=10,
        )
        if r.status_code == 200 and r.content:
            result = r.json().get("chart", {}).get("result")
            if not result:
                return {}
            meta = result[0]["meta"]
            return _cache_set(cache_key, {
                "shortName": meta.get("shortName", symbol),
                "currency": meta.get("currency", "USD"),
                "regularMarketPrice": meta.get("regularMarketPrice"),
                "previousClose": meta.get("previousClose") or meta.get("chartPreviousClose"),
                "52WeekHigh": meta.get("fiftyTwoWeekHigh"),
                "52WeekLow": meta.get("fiftyTwoWeekLow"),
                "marketCap": meta.get("marketCap", 0),
                "exchangeName": meta.get("exchangeName", ""),
            })
    except Exception as ex:
        logger.error(f"get_yf_meta error ({symbol}): {ex}")
    return {}


def get_earnings_date(symbol: str) -> Optional[int]:
    """특정 종목의 다음 실적 발표일 → Unix timestamp (없으면 None)"""
    from_str = datetime.now().strftime("%Y-%m-%d")
    to_str = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")

    cache_key = f"earnings_sym:{symbol}"
    cached = _cache_get(cache_key, ttl=3600)
    if cached and "ts" in cached:
        return cached["ts"]

    data = _get("/calendar/earnings", {"symbol": symbol, "from": from_str, "to": to_str})
    cal = data.get("earningsCalendar", [])
    if cal:
        ed_str = cal[0].get("date", "")
        if ed_str:
            ts = int(datetime.strptime(ed_str, "%Y-%m-%d").timestamp())
            _CACHE[cache_key] = {"_ts": _time.time(), "ts": ts}
            return ts
    return None
