"""
실시간 시장 감지 & 알림 시스템
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
기능:
  1. 프리마켓/애프터마켓 급등락 감지
  2. 장중 거래량 폭발 종목 실시간 스캔
  3. 장 시작 전 체크리스트 (갭업/갭다운)
  4. 공포탐욕지수 (Fear & Greed 간이 버전)
  5. 주요 지수/선물 모니터링
  6. 손절/익절 타이밍 알림
"""

import os
import logging
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

import yfinance as yf
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")

# 모니터링 대상
WATCHLIST_DEFAULT = [
    "NVDA", "AMD", "TSLA", "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "PLTR", "SMCI", "ARM", "AVGO", "COIN", "MSTR",
    "IONQ", "RGTI", "RKLB", "SOFI", "RIVN",
]

# 주요 지수/ETF
INDICES = {
    "^GSPC": "S&P 500",
    "^IXIC": "나스닥",
    "^DJI": "다우",
    "^VIX": "VIX(공포지수)",
    "^TNX": "미국10년물",
    "GC=F": "금",
    "CL=F": "원유(WTI)",
    "BTC-USD": "비트코인",
    "KRW=X": "원/달러",
}

INDEX_ETFS = {
    "SPY": "S&P500 ETF",
    "QQQ": "나스닥100 ETF",
    "SOXL": "반도체3x",
    "TQQQ": "나스닥3x",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  시장 시간 판단
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_market_status() -> dict:
    """현재 미국 시장 상태"""
    now_et = datetime.now(ET)
    now_kst = datetime.now(KST)
    t = now_et.time()

    if now_et.weekday() >= 5:
        status = "주말 휴장"
        phase = "closed"
    elif t < dtime(4, 0):
        status = "장 전 (프리마켓 전)"
        phase = "pre_premarket"
    elif t < dtime(9, 30):
        status = "프리마켓"
        phase = "premarket"
    elif t < dtime(16, 0):
        status = "정규장"
        phase = "regular"
    elif t < dtime(20, 0):
        status = "애프터마켓"
        phase = "aftermarket"
    else:
        status = "장 마감"
        phase = "closed"

    return {
        "status": status,
        "phase": phase,
        "time_et": now_et.strftime("%H:%M ET"),
        "time_kst": now_kst.strftime("%H:%M KST"),
        "is_trading": phase in ("premarket", "regular", "aftermarket"),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 프리마켓/애프터마켓 스캔
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def scan_premarket(symbols: list = None, threshold: float = 3.0) -> list[dict]:
    """
    프리마켓/애프터마켓 급등락 종목 감지
    threshold: 변동률 기준 (%)
    """
    symbols = symbols or WATCHLIST_DEFAULT
    movers = []

    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            # 최근 2일 데이터 (1분봉으로 프리마켓 포함)
            df = ticker.history(period="2d", interval="1m", prepost=True)
            if df.empty:
                continue

            info = ticker.info
            prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose", 0)
            current = info.get("regularMarketPrice") or info.get("currentPrice", 0)
            pre_price = info.get("preMarketPrice", 0)
            post_price = info.get("postMarketPrice", 0)

            # 프리마켓 또는 애프터마켓 가격 사용
            active_price = pre_price or post_price or current
            if not active_price or not prev_close:
                continue

            change_pct = (active_price / prev_close - 1) * 100

            if abs(change_pct) >= threshold:
                movers.append({
                    "symbol": sym,
                    "name": info.get("shortName", sym),
                    "prev_close": round(prev_close, 2),
                    "current_price": round(active_price, 2),
                    "change_pct": round(change_pct, 2),
                    "source": "premarket" if pre_price else "aftermarket" if post_price else "regular",
                    "volume": info.get("volume", 0),
                })

        except Exception as e:
            logger.debug(f"Premarket scan failed for {sym}: {e}")

    movers.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    return movers


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 장중 거래량 폭발 스캔
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def scan_volume_surge(symbols: list = None, rvol_threshold: float = 2.5) -> list[dict]:
    """장중 거래량 급등 종목 감지"""
    symbols = symbols or WATCHLIST_DEFAULT
    surges = []

    try:
        data = yf.download(symbols, period="1mo", progress=False, group_by="ticker")
    except Exception:
        return []

    for sym in symbols:
        try:
            df = data[sym].dropna() if len(symbols) > 1 else data.dropna()
            if len(df) < 10:
                continue

            avg_vol = float(df["Volume"].iloc[-21:-1].mean()) if len(df) > 21 else float(df["Volume"].iloc[:-1].mean())
            latest_vol = float(df["Volume"].iloc[-1])
            rvol = latest_vol / avg_vol if avg_vol > 0 else 0

            if rvol >= rvol_threshold:
                price = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2])
                chg = (price / prev - 1) * 100

                surges.append({
                    "symbol": sym,
                    "rvol": round(rvol, 2),
                    "volume": int(latest_vol),
                    "avg_volume": int(avg_vol),
                    "price": round(price, 2),
                    "change_pct": round(chg, 2),
                })
        except Exception:
            continue

    surges.sort(key=lambda x: x["rvol"], reverse=True)
    return surges


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 장 시작 전 체크리스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def morning_checklist(watchlist: list = None) -> str:
    """장 시작 전 체크리스트 — 매일 아침 전송"""
    mkt = get_market_status()

    lines = [
        "☀️ *장 시작 전 체크리스트*",
        f"⏰ {mkt['time_kst']} ({mkt['time_et']})",
        f"📍 {mkt['status']}\n",
    ]

    # 주요 지수/선물
    lines.append("━━ *주요 지수* ━━━━━━━")
    for sym, name in INDICES.items():
        try:
            t = yf.Ticker(sym)
            info = t.info
            price = info.get("regularMarketPrice", 0) or info.get("previousClose", 0)
            prev = info.get("regularMarketPreviousClose") or info.get("previousClose", 0)
            if price and prev:
                chg = (price / prev - 1) * 100
                icon = "🟢" if chg > 0 else "🔴" if chg < 0 else "⚪"

                if sym == "^VIX":
                    # VIX는 절대값이 중요
                    fear = "😰공포" if price > 25 else "😟불안" if price > 20 else "😐보통" if price > 15 else "😊안정"
                    lines.append(f"  {icon} {name}: {price:.1f} ({'+' if chg>0 else ''}{chg:.1f}%) {fear}")
                elif sym == "KRW=X":
                    lines.append(f"  {icon} {name}: ₩{price:.0f} ({'+' if chg>0 else ''}{chg:.1f}%)")
                else:
                    lines.append(f"  {icon} {name}: {price:,.1f} ({'+' if chg>0 else ''}{chg:.1f}%)")
        except Exception:
            continue

    # 프리마켓 급등락
    lines.append("\n━━ *프리마켓 급등락* ━━━")
    movers = scan_premarket(watchlist, threshold=2.0)
    if movers:
        for m in movers[:8]:
            icon = "🚀" if m["change_pct"] > 5 else "🟢" if m["change_pct"] > 0 else "🔴" if m["change_pct"] > -5 else "💥"
            lines.append(
                f"  {icon} *{m['symbol']}* ${m['current_price']} "
                f"({'+' if m['change_pct']>0 else ''}{m['change_pct']}%)"
            )
    else:
        lines.append("  큰 변동 없음")

    # 갭 분석
    gap_ups = [m for m in movers if m["change_pct"] > 3]
    gap_downs = [m for m in movers if m["change_pct"] < -3]
    if gap_ups or gap_downs:
        lines.append(f"\n  📊 갭업 {len(gap_ups)}개 | 갭다운 {len(gap_downs)}개")

    # 간이 Fear & Greed
    fg = calculate_fear_greed()
    lines.append(f"\n━━ *시장 심리* ━━━━━━━")
    lines.append(f"  {fg['emoji']} {fg['label']}: {fg['score']}/100")
    lines.append(f"  {fg['description']}")

    lines.append(f"\n/report 로 오늘의 추천 종목 받기")

    return "\n".join(lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 간이 Fear & Greed 지수
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calculate_fear_greed() -> dict:
    """
    간이 공포탐욕 지수 (CNN Fear & Greed 방식 간소화)
    지표: VIX, 시장 모멘텀, 거래량, 52주 신고/신저 비율
    """
    signals = []

    # 1) VIX (공포지수)
    try:
        vix = yf.Ticker("^VIX").info.get("regularMarketPrice", 20)
        if vix < 15:
            signals.append(80)  # 극도의 탐욕
        elif vix < 20:
            signals.append(60)
        elif vix < 25:
            signals.append(40)
        elif vix < 30:
            signals.append(25)
        else:
            signals.append(10)  # 극도의 공포
    except Exception:
        signals.append(50)

    # 2) S&P 500 모멘텀 (vs 125일 이평)
    try:
        sp = yf.download("^GSPC", period="6mo", progress=False)
        if len(sp) > 125:
            current = float(sp["Close"].iloc[-1])
            ma125 = float(sp["Close"].iloc[-125:].mean())
            ratio = current / ma125
            if ratio > 1.05:
                signals.append(80)
            elif ratio > 1.02:
                signals.append(65)
            elif ratio > 0.98:
                signals.append(45)
            elif ratio > 0.95:
                signals.append(30)
            else:
                signals.append(15)
    except Exception:
        signals.append(50)

    # 3) 시장 거래량 (SPY)
    try:
        spy = yf.download("SPY", period="1mo", progress=False)
        if len(spy) > 10:
            avg_vol = float(spy["Volume"].iloc[-11:-1].mean())
            last_vol = float(spy["Volume"].iloc[-1])
            vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1
            if vol_ratio > 1.5:
                signals.append(35)  # 패닉 매도 or 광란 매수
            elif vol_ratio > 1.2:
                signals.append(55)
            else:
                signals.append(50)
    except Exception:
        signals.append(50)

    # 4) 나스닥 RSI
    try:
        qqq = yf.download("QQQ", period="1mo", progress=False)
        if len(qqq) > 14:
            delta = qqq["Close"].diff()
            gain = delta.where(delta > 0, 0).ewm(alpha=1/14, min_periods=14).mean()
            loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, min_periods=14).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi = float(100 - (100 / (1 + rs.iloc[-1])))

            if rsi > 70:
                signals.append(85)  # 탐욕
            elif rsi > 55:
                signals.append(65)
            elif rsi > 45:
                signals.append(50)
            elif rsi > 30:
                signals.append(30)
            else:
                signals.append(15)  # 공포
    except Exception:
        signals.append(50)

    # 종합 점수
    score = int(np.mean(signals))

    if score >= 75:
        return {"score": score, "label": "극도의 탐욕", "emoji": "🤑", "description": "시장 과열 주의, 차익실현 고려"}
    elif score >= 60:
        return {"score": score, "label": "탐욕", "emoji": "😊", "description": "낙관적 분위기, 추세 추종 유리"}
    elif score >= 45:
        return {"score": score, "label": "중립", "emoji": "😐", "description": "방향성 탐색 중, 선별적 접근"}
    elif score >= 30:
        return {"score": score, "label": "공포", "emoji": "😟", "description": "약세 심리, 반등 가능성 주시"}
    else:
        return {"score": score, "label": "극도의 공포", "emoji": "😱", "description": "패닉 구간, 역발상 매수 기회 가능"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 손절/익절 모니터
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_exit_signals(positions: list[dict]) -> list[dict]:
    """
    보유 종목 손절/익절 신호 체크

    positions: [{"symbol": "NVDA", "entry_price": 130, "entry_date": "2026-04-01"}, ...]

    Returns: 신호 발생한 종목 리스트
    """
    alerts = []

    for pos in positions:
        sym = pos["symbol"]
        entry = pos["entry_price"]
        try:
            df = yf.download(sym, period="1mo", progress=False)
            if df.empty:
                continue

            # MultiIndex 처리
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)

            current = float(df["Close"].iloc[-1])
            pnl_pct = (current / entry - 1) * 100

            # ATR 기반 동적 손절 (변동성 고려)
            if len(df) >= 14:
                high = df["High"]
                low = df["Low"]
                close_prev = df["Close"].shift(1)
                tr = pd.concat([
                    high - low, (high - close_prev).abs(), (low - close_prev).abs()
                ], axis=1).max(axis=1)
                atr = float(tr.rolling(14).mean().iloc[-1])
                atr_pct = (atr / current) * 100
                stop_loss = -max(atr_pct * 2, 3.0)  # ATR 2배 또는 최소 3%
            else:
                atr_pct = 2.0
                stop_loss = -5.0

            # RSI 확인
            delta = df["Close"].diff()
            gain = delta.where(delta > 0, 0).ewm(alpha=1/14, min_periods=14).mean()
            loss_s = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, min_periods=14).mean()
            rs = gain / loss_s.replace(0, np.nan)
            rsi = float(100 - (100 / (1 + rs.iloc[-1])))

            alert_type = None
            reason = ""

            # 손절 조건
            if pnl_pct <= stop_loss:
                alert_type = "stop_loss"
                reason = f"ATR 기반 손절선({stop_loss:.1f}%) 도달"
            elif pnl_pct <= -7:
                alert_type = "stop_loss"
                reason = "최대 손절선(-7%) 도달"

            # 익절 조건
            elif pnl_pct >= 15 and rsi > 75:
                alert_type = "take_profit"
                reason = f"목표 수익 도달 + RSI 과매수({rsi:.0f})"
            elif pnl_pct >= 10 and rsi > 70:
                alert_type = "take_profit_warning"
                reason = f"+10% 수익 + RSI {rsi:.0f} (익절 고려)"
            elif pnl_pct >= 20:
                alert_type = "take_profit"
                reason = "+20% 수익 도달 (부분 익절 권장)"

            # 추세 전환 경고
            elif pnl_pct > 5:
                # MACD 데드크로스 확인
                ema12 = df["Close"].ewm(span=12).mean()
                ema26 = df["Close"].ewm(span=26).mean()
                macd = ema12 - ema26
                signal = macd.ewm(span=9).mean()
                hist = macd - signal
                if float(hist.iloc[-1]) < 0 and float(hist.iloc[-2]) >= 0:
                    alert_type = "trend_warning"
                    reason = f"MACD 데드크로스 (수익 {pnl_pct:+.1f}% 보호)"

            if alert_type:
                alerts.append({
                    "symbol": sym,
                    "entry_price": entry,
                    "current_price": round(current, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "alert_type": alert_type,
                    "reason": reason,
                    "rsi": round(rsi, 1),
                    "atr_pct": round(atr_pct, 2),
                })

        except Exception as e:
            logger.warning(f"Exit check failed for {sym}: {e}")

    return alerts


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 급등락 실시간 감지
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def scan_movers(symbols: list = None, threshold: float = 4.0) -> dict:
    """장중 급등락 종목 감지"""
    symbols = symbols or WATCHLIST_DEFAULT
    gainers = []
    losers = []

    try:
        data = yf.download(symbols, period="5d", group_by="ticker", progress=False)
    except Exception:
        return {"gainers": [], "losers": []}

    for sym in symbols:
        try:
            df = data[sym].dropna() if len(symbols) > 1 else data.dropna()
            if len(df) < 2:
                continue
            price = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2])
            chg = (price / prev - 1) * 100

            entry = {
                "symbol": sym,
                "price": round(price, 2),
                "change_pct": round(chg, 2),
            }

            if chg >= threshold:
                gainers.append(entry)
            elif chg <= -threshold:
                losers.append(entry)
        except Exception:
            continue

    gainers.sort(key=lambda x: x["change_pct"], reverse=True)
    losers.sort(key=lambda x: x["change_pct"])

    return {"gainers": gainers, "losers": losers}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  포맷 함수들
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def format_premarket_alert(movers: list) -> str:
    if not movers:
        return ""
    lines = ["🌅 *프리마켓 급등락 알림*\n"]
    for m in movers[:10]:
        icon = "🚀" if m["change_pct"] > 5 else "🟢" if m["change_pct"] > 0 else "🔴" if m["change_pct"] > -5 else "💥"
        lines.append(
            f"{icon} *{m['symbol']}* ${m['current_price']} "
            f"({'+' if m['change_pct']>0 else ''}{m['change_pct']}%) "
            f"← ${m['prev_close']}"
        )
    lines.append(f"\n/check 종목명 으로 상세 분석")
    return "\n".join(lines)


def format_volume_alert(surges: list) -> str:
    if not surges:
        return ""
    lines = ["🔥 *거래량 폭발 알림*\n"]
    for s in surges[:8]:
        icon = "🟢" if s["change_pct"] > 0 else "🔴"
        lines.append(
            f"{icon} *{s['symbol']}* 거래량 *{s['rvol']}배* "
            f"| ${s['price']} ({'+' if s['change_pct']>0 else ''}{s['change_pct']}%)"
        )
    return "\n".join(lines)


def format_exit_alerts(alerts: list) -> str:
    if not alerts:
        return ""

    TYPE_EMOJI = {
        "stop_loss": "🚨",
        "take_profit": "💰",
        "take_profit_warning": "💡",
        "trend_warning": "⚠️",
    }
    TYPE_LABEL = {
        "stop_loss": "손절 신호",
        "take_profit": "익절 신호",
        "take_profit_warning": "익절 고려",
        "trend_warning": "추세 전환 경고",
    }

    lines = ["📢 *보유 종목 알림*\n"]
    for a in alerts:
        emoji = TYPE_EMOJI.get(a["alert_type"], "📌")
        label = TYPE_LABEL.get(a["alert_type"], "알림")
        pnl_icon = "📈" if a["pnl_pct"] > 0 else "📉"

        lines.append(f"{emoji} *{a['symbol']}* — {label}")
        lines.append(f"  {pnl_icon} 수익률: {'+' if a['pnl_pct']>0 else ''}{a['pnl_pct']:.1f}%")
        lines.append(f"  💲 진입 ${a['entry_price']} → 현재 ${a['current_price']}")
        lines.append(f"  📋 {a['reason']}")
        lines.append("")

    lines.append("_⚠️ 최종 매매 판단은 본인 책임입니다_")
    return "\n".join(lines)


def format_market_overview() -> str:
    """시장 전체 현황 요약"""
    mkt = get_market_status()
    fg = calculate_fear_greed()

    lines = [
        "🌍 *시장 현황*",
        f"⏰ {mkt['time_kst']} | {mkt['status']}",
        f"{fg['emoji']} 심리: {fg['label']} ({fg['score']}/100)\n",
    ]

    # 주요 지수
    for sym, name in list(INDICES.items())[:6]:
        try:
            info = yf.Ticker(sym).info
            price = info.get("regularMarketPrice", 0) or info.get("previousClose", 0)
            prev = info.get("regularMarketPreviousClose", 0) or info.get("previousClose", 0)
            if price and prev:
                chg = (price / prev - 1) * 100
                icon = "🟢" if chg > 0 else "🔴" if chg < 0 else "⚪"
                if "KRW" in sym:
                    lines.append(f"  {icon} {name}: ₩{price:.0f} ({'+' if chg>0 else ''}{chg:.1f}%)")
                elif "BTC" in sym:
                    lines.append(f"  {icon} {name}: ${price:,.0f} ({'+' if chg>0 else ''}{chg:.1f}%)")
                else:
                    lines.append(f"  {icon} {name}: {price:,.1f} ({'+' if chg>0 else ''}{chg:.1f}%)")
        except Exception:
            continue

    # 급등락
    movers = scan_movers(threshold=3.0)
    if movers["gainers"]:
        lines.append(f"\n🚀 *급등:*")
        for g in movers["gainers"][:3]:
            lines.append(f"  {g['symbol']} +{g['change_pct']}%")
    if movers["losers"]:
        lines.append(f"💥 *급락:*")
        for l in movers["losers"][:3]:
            lines.append(f"  {l['symbol']} {l['change_pct']}%")

    return "\n".join(lines)


# ── 테스트 ──
if __name__ == "__main__":
    print(get_market_status())
    print()
    print(morning_checklist())
    print()
    fg = calculate_fear_greed()
    print(f"Fear & Greed: {fg}")
