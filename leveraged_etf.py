"""
레버리지 ETF 스크리너 & 추천
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bull 3x / Bear(인버스) 3x ETF를 모멘텀·기술·거래량으로 스코어링

운용 원칙:
  - 레버리지 ETF는 단기 모멘텀 트레이딩용 (장기 보유 비권장)
  - Bull ETF : 해당 지수/섹터 상승 추세에 탑승
  - Bear ETF : 하락 헤지 또는 역방향 매매
  - 변동성이 크므로 반드시 리스크 관리 필수

팩터 가중치 (ETF 전용):
  모멘텀  40% — 지수 ETF는 모멘텀 중심
  기술적  35% — RSI·MACD·이동평균
  거래량  25% — RVOL·20일 돌파

데이터 소스: Yahoo Finance Chart API (finnhub_data.download_bulk)
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict

import pytz

from finnhub_data import download_bulk, download_candles
from advanced_screener import (
    score_momentum, score_technical, score_volume_breakout, assign_grade
)

logger = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ETF 유니버스
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LETF_UNIVERSE: Dict[str, dict] = {
    # ── Bull (상승 추세 추종) ──────────────────────────
    "TQQQ": {
        "name": "ProShares UltraPro QQQ",
        "underlying": "NASDAQ 100",
        "leverage": 3,
        "inverse": False,
        "sector": "나스닥",
    },
    "UPRO": {
        "name": "ProShares UltraPro S&P500",
        "underlying": "S&P 500",
        "leverage": 3,
        "inverse": False,
        "sector": "시장전체",
    },
    "SPXL": {
        "name": "Direxion S&P500 Bull 3X",
        "underlying": "S&P 500",
        "leverage": 3,
        "inverse": False,
        "sector": "시장전체",
    },
    "SOXL": {
        "name": "Direxion Semiconductors Bull 3X",
        "underlying": "PHLX Semiconductor",
        "leverage": 3,
        "inverse": False,
        "sector": "반도체",
    },
    "TECL": {
        "name": "Direxion Technology Bull 3X",
        "underlying": "Technology Select Sector",
        "leverage": 3,
        "inverse": False,
        "sector": "기술",
    },
    "FNGU": {
        "name": "MicroSectors FANG+ 3X",
        "underlying": "NYSE FANG+",
        "leverage": 3,
        "inverse": False,
        "sector": "빅테크",
    },
    "FAS": {
        "name": "Direxion Financial Bull 3X",
        "underlying": "Russell 1000 Financial",
        "leverage": 3,
        "inverse": False,
        "sector": "금융",
    },
    "TNA": {
        "name": "Direxion Small Cap Bull 3X",
        "underlying": "Russell 2000",
        "leverage": 3,
        "inverse": False,
        "sector": "소형주",
    },
    "LABU": {
        "name": "Direxion Biotech Bull 3X",
        "underlying": "S&P Biotech Select",
        "leverage": 3,
        "inverse": False,
        "sector": "바이오",
    },
    "CURE": {
        "name": "Direxion Healthcare Bull 3X",
        "underlying": "Health Care Select Sector",
        "leverage": 3,
        "inverse": False,
        "sector": "헬스케어",
    },
    "ERX": {
        "name": "Direxion Energy Bull 2X",
        "underlying": "Energy Select Sector",
        "leverage": 2,
        "inverse": False,
        "sector": "에너지",
    },
    "DFEN": {
        "name": "Direxion Aerospace & Defense Bull 3X",
        "underlying": "Dow Jones Aerospace & Defense",
        "leverage": 3,
        "inverse": False,
        "sector": "방산",
    },
    "DPST": {
        "name": "Direxion Regional Banks Bull 3X",
        "underlying": "S&P Regional Banks Select",
        "leverage": 3,
        "inverse": False,
        "sector": "금융",
    },
    # ── Bear / Inverse (하락 헤지) ─────────────────────
    "SQQQ": {
        "name": "ProShares UltraPro Short QQQ",
        "underlying": "NASDAQ 100",
        "leverage": -3,
        "inverse": True,
        "sector": "나스닥",
    },
    "SPXS": {
        "name": "Direxion S&P500 Bear 3X",
        "underlying": "S&P 500",
        "leverage": -3,
        "inverse": True,
        "sector": "시장전체",
    },
    "SOXS": {
        "name": "Direxion Semiconductors Bear 3X",
        "underlying": "PHLX Semiconductor",
        "leverage": -3,
        "inverse": True,
        "sector": "반도체",
    },
    "TECS": {
        "name": "Direxion Technology Bear 3X",
        "underlying": "Technology Select Sector",
        "leverage": -3,
        "inverse": True,
        "sector": "기술",
    },
    "FAZ": {
        "name": "Direxion Financial Bear 3X",
        "underlying": "Russell 1000 Financial",
        "leverage": -3,
        "inverse": True,
        "sector": "금융",
    },
    "LABD": {
        "name": "Direxion Biotech Bear 3X",
        "underlying": "S&P Biotech Select",
        "leverage": -3,
        "inverse": True,
        "sector": "바이오",
    },
}

# 섹터 별칭 (한/영 통합)
_SECTOR_ALIASES: Dict[str, str] = {
    "나스닥": "나스닥", "nasdaq": "나스닥", "qqq": "나스닥",
    "sp500": "시장전체", "s&p": "시장전체", "spy": "시장전체", "시장": "시장전체", "전체": "시장전체",
    "반도체": "반도체", "semiconductor": "반도체", "semic": "반도체",
    "기술": "기술", "tech": "기술", "technology": "기술",
    "빅테크": "빅테크", "fang": "빅테크",
    "금융": "금융", "financial": "금융", "finance": "금융",
    "소형주": "소형주", "smallcap": "소형주", "small": "소형주",
    "바이오": "바이오", "biotech": "바이오", "bio": "바이오",
    "헬스케어": "헬스케어", "healthcare": "헬스케어", "health": "헬스케어",
    "에너지": "에너지", "energy": "에너지",
    "방산": "방산", "defense": "방산", "aerospace": "방산",
}


def _resolve_sector(raw: str) -> Optional[str]:
    return _SECTOR_ALIASES.get(raw.lower())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  스코어링
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _letf_score(m: dict, t: dict, v: dict) -> float:
    """ETF 전용 가중 합산: 모멘텀 40% / 기술 35% / 거래량 25%"""
    return round(m["score"] * 0.40 + t["score"] * 0.35 + v["score"] * 0.25, 1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  메인 스크리닝
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def screen_letf(
    mode: str = "bull",
    sector: Optional[str] = None,
    top_n: int = 5,
) -> List[dict]:
    """
    레버리지 ETF 스크리닝

    mode   : "bull" | "bear" | "all"
    sector : None 또는 섹터명 (한/영)
    top_n  : 상위 N개 반환
    """
    # 1) 필터링
    resolved_sector = _resolve_sector(sector) if sector else None

    target: Dict[str, dict] = {}
    for sym, meta in LETF_UNIVERSE.items():
        if mode == "bull" and meta["inverse"]:
            continue
        if mode == "bear" and not meta["inverse"]:
            continue
        if resolved_sector and resolved_sector != meta["sector"]:
            continue
        target[sym] = meta

    if not target:
        logger.warning(f"No ETFs matched: mode={mode}, sector={sector}")
        return []

    # 2) OHLCV 다운로드
    logger.info(f"Downloading LETF candles: {list(target.keys())}")
    candle_map = download_bulk(list(target.keys()), days=90)

    # 3) 스코어 계산
    results = []
    for sym, meta in target.items():
        df = candle_map.get(sym)
        if df is None or len(df) < 15:
            logger.debug(f"Skipping {sym}: insufficient data")
            continue

        try:
            m = score_momentum(df)
            t = score_technical(df)
            v = score_volume_breakout(df)
            total = _letf_score(m, t, v)
            grade = assign_grade(total)

            price = float(df["Close"].iloc[-1])
            chg = round((price / float(df["Close"].iloc[-2]) - 1) * 100, 2)

            # 신호 합산
            signals = t.get("signals", []) + v.get("signals", [])

            results.append({
                "symbol": sym,
                "name": meta["name"],
                "underlying": meta["underlying"],
                "leverage": meta["leverage"],
                "inverse": meta["inverse"],
                "sector": meta["sector"],
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
            logger.debug(f"LETF score {sym}: {ex}")

    results.sort(key=lambda x: x["total_score"], reverse=True)
    return results[:top_n]


def analyze_single_letf(symbol: str) -> dict:
    """단일 레버리지 ETF 상세 분석"""
    meta = LETF_UNIVERSE.get(symbol.upper())
    df = download_candles(symbol.upper(), days=90)
    if df.empty or len(df) < 15:
        return {}

    m = score_momentum(df)
    t = score_technical(df)
    v = score_volume_breakout(df)
    total = _letf_score(m, t, v)
    grade = assign_grade(total)

    price = float(df["Close"].iloc[-1])
    chg = round((price / float(df["Close"].iloc[-2]) - 1) * 100, 2)

    return {
        "symbol": symbol.upper(),
        "name": meta["name"] if meta else symbol,
        "underlying": meta["underlying"] if meta else "Unknown",
        "leverage": meta["leverage"] if meta else 1,
        "inverse": meta.get("inverse", False) if meta else False,
        "sector": meta["sector"] if meta else "기타",
        "price": price,
        "change_pct": chg,
        "total_score": total,
        "grade": grade,
        "momentum": m,
        "technical": t,
        "volume": v,
        "signals": t.get("signals", []) + v.get("signals", []),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  리포트 포맷
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def format_letf_report(results: List[dict], mode: str = "bull") -> str:
    if not results:
        return "📊 조건에 맞는 레버리지 ETF가 없습니다."

    now = datetime.now(KST).strftime("%m/%d %H:%M")
    GRADE_EMOJI = {"S": "🏆", "A": "🔥", "B": "✅", "C": "📌", "D": "⬜"}

    if mode == "bear":
        header = f"🐻 *인버스(Bear) ETF 추천* ({now} KST)"
        mode_note = "⚠️ 하락장 헤지용 — 시장 하락 시 수익"
    elif mode == "all":
        header = f"📊 *레버리지 ETF 전체* ({now} KST)"
        mode_note = "Bull + Bear 통합 스코어 기준"
    else:
        header = f"🚀 *Bull 레버리지 ETF 추천* ({now} KST)"
        mode_note = "📈 상승 추세 추종용 — 지수 상승 시 수익"

    lines = [header, mode_note, ""]

    for i, r in enumerate(results, 1):
        icon = "🟢" if r["change_pct"] > 0 else "🔴"
        sign = "+" if r["change_pct"] > 0 else ""
        ge = GRADE_EMOJI.get(r["grade"], "")
        lev = r["leverage"]
        lev_label = f"{lev:+d}x" if isinstance(lev, int) else f"{lev}x"
        inv_badge = " 🐻인버스" if r["inverse"] else ""
        m, t, v = r["momentum"], r["technical"], r["volume"]

        lines.append(f"{i}. {ge} *{r['symbol']}* [{lev_label}{inv_badge}]")
        lines.append(f"   추종: {r['underlying']} | 섹터: #{r['sector']}")
        lines.append(
            f"   {icon} ${r['price']:.2f} ({sign}{r['change_pct']}%) "
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

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        "⚠️ _레버리지 ETF는 손실이 원금을 초과할 수 있습니다._\n"
        "_장기 보유 시 변동성 감소(decay) 위험. 단기 매매 전용._\n"
        "_투자 결정은 본인 책임이며 정보 제공 목적입니다._"
    )
    return "\n".join(lines)


def get_letf_summary(sector: Optional[str] = None) -> str:
    """섹터별 Bull/Bear 쌍 요약 (단순 현황)"""
    now = datetime.now(KST).strftime("%m/%d %H:%M")
    lines = [f"📊 *레버리지 ETF 현황* ({now} KST)\n"]

    # 섹터 그룹핑
    sector_pairs: Dict[str, dict] = {}
    for sym, meta in LETF_UNIVERSE.items():
        sec = meta["sector"]
        if sector and _resolve_sector(sector) != sec:
            continue
        if sec not in sector_pairs:
            sector_pairs[sec] = {"bull": [], "bear": []}
        key = "bear" if meta["inverse"] else "bull"
        sector_pairs[sec][key].append(sym)

    symbols_all = list(LETF_UNIVERSE.keys())
    candle_map = download_bulk(symbols_all, days=10)

    for sec, pair in sector_pairs.items():
        lines.append(f"*#{sec}*")
        for kind, syms in [("🚀 Bull", pair["bull"]), ("🐻 Bear", pair["bear"])]:
            for sym in syms:
                df = candle_map.get(sym)
                if df is None or len(df) < 2:
                    lines.append(f"  {kind} {sym} — 데이터 없음")
                    continue
                p = float(df["Close"].iloc[-1])
                c = round((p / float(df["Close"].iloc[-2]) - 1) * 100, 2)
                icon = "🟢" if c > 0 else "🔴"
                sign = "+" if c > 0 else ""
                lines.append(f"  {kind} *{sym}* {icon} ${p:.2f} ({sign}{c}%)")
        lines.append("")

    lines.append("_/letf bull · /letf bear · /letf 반도체_")
    return "\n".join(lines)


# ── 단독 실행 테스트 ──
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)

    print("=== Bull ETF Top 5 ===")
    results = screen_letf(mode="bull", top_n=5)
    print(format_letf_report(results, mode="bull"))

    print("\n=== Bear ETF Top 3 ===")
    bear = screen_letf(mode="bear", top_n=3)
    print(format_letf_report(bear, mode="bear"))
