"""
한국 주식 멀티팩터 스크리너
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
데이터: Yahoo Finance Chart API v8 (API키 불필요)
  - KOSPI 종목: 종목코드.KS  (예: 005930.KS)
  - KOSDAQ 종목: 종목코드.KQ (예: 086520.KQ)
  - KOSPI 지수: ^KS11 / KOSDAQ 지수: ^KQ11

팩터 가중치:
  모멘텀  40%  (1W/1M/3M 수익률)
  기술적  35%  (RSI·MACD·이동평균)
  거래량  25%  (RVOL·20일 돌파)
  ※ Finnhub 미지원 → 실적·펀더멘탈 팩터 제외

장 운영시간: KST 09:00~15:30 (평일)
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

import pytz

from finnhub_data import download_bulk, download_candles, get_yf_meta
from advanced_screener import (
    score_momentum, score_technical, score_volume_breakout,
    assign_grade, _bar,
)

logger = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  종목 유니버스
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

KR_UNIVERSE: Dict[str, dict] = {
    # ── 반도체 ─────────────────────────────────────────
    "005930.KS": {"name": "삼성전자",       "sector": "반도체"},
    "000660.KS": {"name": "SK하이닉스",     "sector": "반도체"},
    "042700.KS": {"name": "한미반도체",     "sector": "반도체"},
    "005290.KS": {"name": "동진쎄미켐",     "sector": "반도체"},
    # ── 2차전지 ────────────────────────────────────────
    "373220.KS": {"name": "LG에너지솔루션", "sector": "2차전지"},
    "006400.KS": {"name": "삼성SDI",        "sector": "2차전지"},
    "051910.KS": {"name": "LG화학",         "sector": "2차전지"},
    "086520.KQ": {"name": "에코프로",       "sector": "2차전지"},
    "247540.KQ": {"name": "에코프로비엠",   "sector": "2차전지"},
    "003670.KS": {"name": "포스코퓨처엠",   "sector": "2차전지"},
    # ── 자동차 ─────────────────────────────────────────
    "005380.KS": {"name": "현대차",         "sector": "자동차"},
    "000270.KS": {"name": "기아",           "sector": "자동차"},
    "012330.KS": {"name": "현대모비스",     "sector": "자동차"},
    # ── 인터넷/플랫폼 ──────────────────────────────────
    "035420.KS": {"name": "NAVER",          "sector": "인터넷"},
    "035720.KS": {"name": "카카오",         "sector": "인터넷"},
    "323410.KS": {"name": "카카오뱅크",     "sector": "핀테크"},
    # ── 바이오/헬스케어 ────────────────────────────────
    "207940.KS": {"name": "삼성바이오로직스", "sector": "바이오"},
    "068270.KS": {"name": "셀트리온",       "sector": "바이오"},
    "128940.KS": {"name": "한미약품",       "sector": "바이오"},
    "028300.KQ": {"name": "HLB",            "sector": "바이오"},
    "196170.KQ": {"name": "알테오젠",       "sector": "바이오"},
    # ── 금융 ───────────────────────────────────────────
    "105560.KS": {"name": "KB금융",         "sector": "금융"},
    "055550.KS": {"name": "신한지주",       "sector": "금융"},
    "086790.KS": {"name": "하나금융지주",   "sector": "금융"},
    # ── 철강/소재 ──────────────────────────────────────
    "005490.KS": {"name": "POSCO홀딩스",    "sector": "철강/소재"},
    # ── 엔터/게임 ──────────────────────────────────────
    "352820.KS": {"name": "HYBE",           "sector": "엔터"},
    "041510.KQ": {"name": "SM엔터테인먼트", "sector": "엔터"},
    "036570.KS": {"name": "엔씨소프트",     "sector": "게임"},
    "259960.KS": {"name": "크래프톤",       "sector": "게임"},
    # ── 방산 ───────────────────────────────────────────
    "012450.KS": {"name": "한화에어로스페이스", "sector": "방산"},
    "079550.KS": {"name": "LIG넥스원",      "sector": "방산"},
    # ── 로봇/AI ────────────────────────────────────────
    "277810.KQ": {"name": "레인보우로보틱스", "sector": "로봇/AI"},
    "454910.KS": {"name": "두산로보틱스",   "sector": "로봇/AI"},
}

# ── 섹터별 심볼 목록 ──────────────────────────────────────
KR_SECTOR_MAP: Dict[str, List[str]] = {}
for _sym, _meta in KR_UNIVERSE.items():
    KR_SECTOR_MAP.setdefault(_meta["sector"], []).append(_sym)

# ── 한글 이름 → 심볼 별칭 ─────────────────────────────────
KR_ALIASES: Dict[str, str] = {
    # 반도체
    "삼성전자": "005930.KS", "삼성": "005930.KS", "삼전": "005930.KS",
    "sk하이닉스": "000660.KS", "하이닉스": "000660.KS", "skh": "000660.KS",
    "한미반도체": "042700.KS", "한미": "042700.KS",
    "동진쎄미켐": "005290.KS", "동진": "005290.KS",
    # 2차전지
    "lg에너지솔루션": "373220.KS", "lg에너지": "373220.KS", "lges": "373220.KS",
    "삼성sdi": "006400.KS", "sdi": "006400.KS",
    "lg화학": "051910.KS",
    "에코프로": "086520.KQ",
    "에코프로비엠": "247540.KQ",
    "포스코퓨처엠": "003670.KS", "퓨처엠": "003670.KS",
    # 자동차
    "현대차": "005380.KS", "현대자동차": "005380.KS", "현대": "005380.KS",
    "기아": "000270.KS", "기아차": "000270.KS",
    "현대모비스": "012330.KS", "모비스": "012330.KS",
    # 인터넷
    "naver": "035420.KS", "네이버": "035420.KS",
    "카카오": "035720.KS",
    "카카오뱅크": "323410.KS",
    # 바이오
    "삼성바이오로직스": "207940.KS", "삼바": "207940.KS", "삼성바이오": "207940.KS",
    "셀트리온": "068270.KS",
    "한미약품": "128940.KS",
    "hlb": "028300.KQ",
    "알테오젠": "196170.KQ",
    # 금융
    "kb금융": "105560.KS", "kb": "105560.KS",
    "신한지주": "055550.KS", "신한": "055550.KS",
    "하나금융지주": "086790.KS", "하나금융": "086790.KS",
    # 철강
    "posco홀딩스": "005490.KS", "포스코": "005490.KS", "posco": "005490.KS",
    # 엔터
    "hybe": "352820.KS", "하이브": "352820.KS",
    "sm엔터테인먼트": "041510.KQ", "sm": "041510.KQ",
    # 게임
    "엔씨소프트": "036570.KS", "엔씨": "036570.KS",
    "크래프톤": "259960.KS",
    # 방산
    "한화에어로스페이스": "012450.KS", "한화에어로": "012450.KS",
    "lig넥스원": "079550.KS", "넥스원": "079550.KS",
    # 로봇
    "레인보우로보틱스": "277810.KQ", "레인보우": "277810.KQ",
    "두산로보틱스": "454910.KS", "두산로봇": "454910.KS",
}

# 섹터 별칭 (한/영)
_KR_SECTOR_ALIASES: Dict[str, str] = {
    "반도체": "반도체", "semiconductor": "반도체",
    "2차전지": "2차전지", "배터리": "2차전지", "battery": "2차전지",
    "자동차": "자동차", "auto": "자동차", "ev": "자동차",
    "인터넷": "인터넷", "internet": "인터넷", "플랫폼": "인터넷",
    "바이오": "바이오", "bio": "바이오", "biotech": "바이오", "헬스케어": "바이오",
    "금융": "금융", "finance": "금융", "financial": "금융",
    "철강": "철강/소재", "소재": "철강/소재", "posco": "철강/소재",
    "엔터": "엔터", "엔터테인먼트": "엔터", "entertainment": "엔터",
    "게임": "게임", "game": "게임",
    "방산": "방산", "defense": "방산", "방위": "방산",
    "로봇": "로봇/AI", "robot": "로봇/AI", "ai": "로봇/AI",
    "핀테크": "핀테크", "fintech": "핀테크",
}


def resolve_kr_sector(raw: str) -> Optional[str]:
    return _KR_SECTOR_ALIASES.get(raw.lower())


def resolve_kr_symbol(query: str) -> Optional[str]:
    """한국 종목명/코드 → 심볼 변환"""
    q = query.strip()

    # .KS/.KQ 붙은 경우 그대로 사용
    if q.upper() in KR_UNIVERSE:
        return q.upper()

    # 별칭 검색 (소문자)
    alias_result = KR_ALIASES.get(q.lower())
    if alias_result:
        return alias_result

    # 숫자 코드만 입력한 경우 (005930 → 005930.KS 또는 .KQ)
    code = q.zfill(6)
    for sym in KR_UNIVERSE:
        if sym.startswith(code + "."):
            return sym

    # 부분 매칭
    for alias, sym in KR_ALIASES.items():
        if q.lower() in alias:
            return sym

    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  스코어링
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _kr_score(m: dict, t: dict, v: dict) -> float:
    """한국 주식 전용 가중합: 모멘텀 40% / 기술 35% / 거래량 25%"""
    return round(m["score"] * 0.40 + t["score"] * 0.35 + v["score"] * 0.25, 1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  시장 상태
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_kr_market_status() -> dict:
    """현재 한국 장 상태 반환 (KST 기준)"""
    now = datetime.now(KST)
    weekday = now.weekday()   # 0=월요일, 6=일요일
    total_min = now.hour * 60 + now.minute

    if weekday >= 5:
        return {"is_open": False, "phase": "휴장", "message": "주말 휴장", "now_kst": now}

    if total_min < 8 * 60:
        return {"is_open": False, "phase": "야간", "message": "야간 (장 전)", "now_kst": now}
    if total_min < 9 * 60:
        return {"is_open": False, "phase": "프리", "message": "장 시작 전 (08:00~09:00)", "now_kst": now}
    if total_min < 15 * 60 + 30:
        return {"is_open": True, "phase": "장중", "message": "장 중 (09:00~15:30)", "now_kst": now}
    if total_min < 18 * 60:
        return {"is_open": False, "phase": "장후", "message": "장 후 (15:30~18:00)", "now_kst": now}
    return {"is_open": False, "phase": "야간", "message": "야간 (장 종료)", "now_kst": now}


def get_kr_index_status() -> dict:
    """KOSPI / KOSDAQ 지수 현황"""
    result = {}
    indices = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11"}
    for name, sym in indices.items():
        try:
            df = download_candles(sym, days=10)
            if df.empty or len(df) < 2:
                continue
            price = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2])
            chg = round((price / prev - 1) * 100, 2)
            result[name] = {"price": price, "change_pct": chg}
        except Exception as ex:
            logger.debug(f"Index fetch {sym}: {ex}")
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  메인 스크리닝
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def screen_kr_stocks(top_n: int = 5, sector: Optional[str] = None) -> List[dict]:
    """
    한국 주식 스크리닝 → 상위 top_n 반환

    sector: None 또는 KR_SECTOR_MAP 키
    """
    resolved = resolve_kr_sector(sector) if sector else None
    if resolved:
        symbols = KR_SECTOR_MAP.get(resolved, [])
    else:
        symbols = list(KR_UNIVERSE.keys())

    if not symbols:
        return []

    logger.info(f"KR Screening: {len(symbols)} symbols, sector={resolved or '전체'}")
    candle_map = download_bulk(symbols, days=90)

    results = []
    for sym in symbols:
        df = candle_map.get(sym)
        if df is None or len(df) < 15:
            logger.debug(f"Skip {sym}: data insufficient")
            continue
        try:
            m = score_momentum(df)
            t = score_technical(df)
            v = score_volume_breakout(df)
            total = _kr_score(m, t, v)
            grade = assign_grade(total)

            price = float(df["Close"].iloc[-1])
            chg = round((price / float(df["Close"].iloc[-2]) - 1) * 100, 2)

            meta = KR_UNIVERSE.get(sym, {})
            signals = t.get("signals", []) + v.get("signals", [])

            results.append({
                "symbol": sym,
                "name": meta.get("name", sym),
                "sector": meta.get("sector", "기타"),
                "price": price,
                "change_pct": chg,
                "total_score": total,
                "grade": grade,
                "momentum": m,
                "technical": t,
                "volume": v,
                "signals": signals[:4],
            })
        except Exception as ex:
            logger.debug(f"Score {sym}: {ex}")

    results.sort(key=lambda x: x["total_score"], reverse=True)
    return results[:top_n]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  단일 종목 상세 분석
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def analyze_single_kr(symbol: str) -> str:
    """단일 한국 종목 상세 분석 → 텔레그램 Markdown 문자열"""
    sym = resolve_kr_symbol(symbol) or symbol.upper()
    if not sym.endswith((".KS", ".KQ")):
        # 자동으로 .KS 시도
        candidate = sym + ".KS"
        test_df = download_candles(candidate, days=10)
        if not test_df.empty:
            sym = candidate
        else:
            candidate2 = sym + ".KQ"
            test_df2 = download_candles(candidate2, days=10)
            if not test_df2.empty:
                sym = candidate2
            else:
                return f"❌ *{symbol}* — 데이터를 찾을 수 없습니다.\n종목코드를 `005930.KS` 형식으로 입력하거나 종목명(예: 삼성전자)을 사용해 보세요."

    df = download_candles(sym, days=90)
    if df.empty or len(df) < 10:
        return f"❌ *{sym}* — 데이터 부족"

    meta_info = KR_UNIVERSE.get(sym, {})
    yf_meta = get_yf_meta(sym)

    name = meta_info.get("name") or yf_meta.get("shortName", sym)
    sector = meta_info.get("sector", "")
    market_label = "KOSPI" if sym.endswith(".KS") else "KOSDAQ"

    m = score_momentum(df)
    t = score_technical(df)
    v = score_volume_breakout(df)
    total = _kr_score(m, t, v)
    grade = assign_grade(total)

    price = float(df["Close"].iloc[-1])
    prev = float(df["Close"].iloc[-2])
    chg = round((price / prev - 1) * 100, 2)
    sign = "+" if chg > 0 else ""
    icon = "🟢" if chg > 0 else "🔴"

    GRADE_EMOJI = {"S": "🏆", "A": "🔥", "B": "✅", "C": "📌", "D": "⬜"}
    ge = GRADE_EMOJI.get(grade, "")

    lines = [
        f"{ge} *{name}* ({sym} / {market_label})",
        f"{icon} ₩{price:,.0f} ({sign}{chg}%) | 등급 *{grade}* ({total}/100)",
        "",
        "📊 *팩터 분석:*",
        f"  모멘텀    {_bar(m['score'])} {m['score']}",
        f"  기술적    {_bar(t['score'])} {t['score']}",
        f"  거래량    {_bar(v['score'])} {v['score']}",
        "",
        f"📈 *모멘텀:* 1W {'+' if m['ret_1w']>0 else ''}{m['ret_1w']}% "
        f"| 1M {'+' if m['ret_1m']>0 else ''}{m['ret_1m']}% "
        f"| 3M {'+' if m['ret_3m']>0 else ''}{m['ret_3m']}%",
    ]

    rsi_label = ("과매수⚠️" if t["rsi"] > 70 else
                 "강세" if t["rsi"] > 55 else
                 "중립" if t["rsi"] > 45 else
                 "약세" if t["rsi"] > 30 else "과매도")
    macd_label = ("골든크로스✨" if t.get("macd_cross") else
                  "양수" if t["macd_histogram"] > 0 else "음수")
    lines.append(f"🔧 *기술적:* RSI {t['rsi']:.0f} ({rsi_label}) | MACD {macd_label}")

    if v["rvol"] > 1.3:
        extra = "  🚀 52주 신고가!" if v.get("at_52w_high") else ("  📊 20일 돌파" if v.get("breakout_20d") else "")
        lines.append(f"🔥 *거래량:* 평소 대비 {v['rvol']}배{extra}")

    # 시가총액
    mc = yf_meta.get("marketCap", 0)
    if mc and mc > 0:
        if mc >= 1e12:
            mc_str = f"₩{mc/1e12:.1f}조"
        elif mc >= 1e8:
            mc_str = f"₩{mc/1e8:.0f}억"
        else:
            mc_str = f"₩{mc:,.0f}"
        lines.append(f"💰 *시총:* {mc_str}")

    # 52주 고저
    hi = yf_meta.get("52WeekHigh")
    lo = yf_meta.get("52WeekLow")
    if hi and lo:
        pos = round((price - lo) / (hi - lo) * 100) if hi != lo else 0
        lines.append(f"📉 *52주:* ₩{lo:,.0f} ~ ₩{hi:,.0f} (현재 {pos}% 위치)")

    # 시그널
    all_signals = t.get("signals", []) + v.get("signals", [])
    if all_signals:
        lines.append(f"\n🔑 *시그널:* {' | '.join(all_signals[:5])}")

    # 판단 코멘트
    lines.append("")
    if total >= 70:
        lines.append("💡 _강한 관심 구간. 모멘텀+거래량이 뒷받침됨_")
    elif total >= 50:
        lines.append("💡 _관심 유지. 일부 팩터가 긍정적_")
    elif total >= 35:
        lines.append("💡 _관망 구간. 뚜렷한 방향성 부족_")
    else:
        lines.append("💡 _약세 구간. 진입 근거 부족_")

    lines.append("\n_⚠️ 정보 제공 목적이며 투자 권유가 아닙니다_")
    return "\n".join(lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  리포트 포맷
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def format_kr_report(results: List[dict], sector: Optional[str] = None) -> str:
    """screen_kr_stocks() 결과 → 텔레그램 Markdown"""
    if not results:
        return "📊 조건에 맞는 한국 주식이 없습니다."

    now = datetime.now(KST).strftime("%m/%d %H:%M")
    GRADE_EMOJI = {"S": "🏆", "A": "🔥", "B": "✅", "C": "📌", "D": "⬜"}
    sector_label = f" #{sector}" if sector else ""
    lines = [f"🇰🇷 *한국 주식 추천{sector_label}* ({now} KST)\n"]

    for i, r in enumerate(results, 1):
        icon = "🟢" if r["change_pct"] > 0 else "🔴"
        sign = "+" if r["change_pct"] > 0 else ""
        ge = GRADE_EMOJI.get(r["grade"], "")
        m, t, v = r["momentum"], r["technical"], r["volume"]
        market_tag = "KS" if r["symbol"].endswith(".KS") else "KQ"

        lines.append(f"{i}. {ge} *{r['name']}* [{market_tag}]")
        lines.append(f"   #{r['sector']} | {r['symbol']}")
        lines.append(
            f"   {icon} ₩{r['price']:,.0f} ({sign}{r['change_pct']}%) "
            f"| 점수 *{r['total_score']}* ({r['grade']})"
        )
        lines.append(
            f"   모멘텀 {m['score']} | 기술 {t['score']} | 거래량 {v['score']}"
        )
        lines.append(
            f"   1W {'+' if m['ret_1w']>0 else ''}{m['ret_1w']}% "
            f"| 1M {'+' if m['ret_1m']>0 else ''}{m['ret_1m']}% "
            f"| RSI {t['rsi']:.0f} | RVOL {v['rvol']}x"
        )
        if r["signals"]:
            lines.append(f"   🔑 {' · '.join(r['signals'][:3])}")
        lines.append("")

    lines.append("_⚠️ 정보 제공 목적이며 투자 권유가 아닙니다_")
    return "\n".join(lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  시장 현황 포맷
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def format_kr_market(index_data: dict, market_status: dict) -> str:
    now = datetime.now(KST).strftime("%m/%d %H:%M")
    phase = market_status.get("message", "")
    lines = [f"🇰🇷 *한국 시장 현황* ({now} KST)", f"📌 {phase}\n"]

    for idx_name, data in index_data.items():
        price = data["price"]
        chg = data["change_pct"]
        icon = "🟢" if chg > 0 else "🔴"
        sign = "+" if chg > 0 else ""
        lines.append(f"{icon} *{idx_name}* {price:,.2f} ({sign}{chg}%)")

    lines.append("")
    lines.append("_/krcheck 삼성전자 · /kreport · /krsector 반도체_")
    return "\n".join(lines)


# ── 단독 실행 테스트 ──
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)

    status = get_kr_market_status()
    print(f"장 상태: {status['message']}")

    index_data = get_kr_index_status()
    print(format_kr_market(index_data, status))

    print("\n=== 한국 주식 Top 5 ===")
    results = screen_kr_stocks(top_n=5)
    print(format_kr_report(results))

    print("\n=== 반도체 섹터 ===")
    semi = screen_kr_stocks(top_n=3, sector="반도체")
    print(format_kr_report(semi, sector="반도체"))
