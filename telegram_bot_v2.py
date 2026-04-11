"""
텔레그램 대화형 주식 봇 (v2)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
기능:
  /report        — 오늘의 테마 종목 리포트
  /top3          — 빠른 상위 3종목
  /check NVDA    — 특정 종목 분석
  /sector AI     — 섹터/테마별 종목
  /alert NVDA 5  — 가격 변동 알림 설정
  /alerts        — 등록된 알림 목록
  /watchlist     — 관심 종목 관리
  /schedule      — 자동 리포트 시간 설정
  /earnings      — 이번 주 실적 발표 종목
  /compare NVDA AMD — 종목 비교
  /help          — 도움말

자연어도 지원:
  "엔비디아 어때?" → NVDA 분석
  "반도체 관련주" → 반도체 섹터
  "오늘 뭐 살까" → 리포트
"""

import os
import asyncio
import json
import re
import logging
from datetime import datetime, time, timedelta
from pathlib import Path

from telegram import (
    Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, JobQueue,
)

from advanced_screener import (
    screen_stocks_advanced, format_advanced_report, to_json,
    score_momentum, score_technical, score_volume_breakout,
    score_earnings, score_fundamental, compute_total_score,
    assign_grade, _bar, SECTOR_MAP, UNIVERSE,
)
from news_fetcher import get_news_summary
from ai_summarizer import generate_ai_summary
from performance_tracker import (
    save_picks, track_returns, get_recent_picks_report,
    format_stats_report, run_backtest,
)
from market_monitor import (
    get_market_status, scan_premarket, scan_volume_surge,
    morning_checklist, calculate_fear_greed, check_exit_signals,
    format_premarket_alert, format_volume_alert, format_exit_alerts,
    format_market_overview, scan_movers,
)

import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 환경 변수 ──
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
USE_AI = os.getenv("USE_AI_SUMMARY", "false").lower() == "true"

# ── 영구 저장 (간단한 JSON 파일) ──
DATA_FILE = Path("bot_data.json")


def load_data() -> dict:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {"watchlist": [], "alerts": [], "schedule_hour": 7, "schedule_min": 0}


def save_data(data: dict):
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 자연어 → 종목 매핑 ──
TICKER_ALIASES = {
    "엔비디아": "NVDA", "엔비": "NVDA", "nvidia": "NVDA",
    "테슬라": "TSLA", "tesla": "TSLA",
    "애플": "AAPL", "apple": "AAPL",
    "마소": "MSFT", "마이크로소프트": "MSFT", "microsoft": "MSFT",
    "아마존": "AMZN", "amazon": "AMZN",
    "메타": "META", "페이스북": "META",
    "구글": "GOOGL", "알파벳": "GOOGL", "google": "GOOGL",
    "넷플릭스": "NFLX", "netflix": "NFLX",
    "amd": "AMD", "에이엠디": "AMD",
    "팔란티어": "PLTR", "palantir": "PLTR",
    "코인베이스": "COIN", "coinbase": "COIN",
    "아이온큐": "IONQ", "ionq": "IONQ",
    "릴리": "LLY", "일라이릴리": "LLY",
    "노보": "NVO", "노보노디스크": "NVO",
    "보잉": "BA", "boeing": "BA",
    "슈퍼마이크로": "SMCI", "smci": "SMCI",
    "arm": "ARM", "아름": "ARM",
    "브로드컴": "AVGO", "broadcom": "AVGO",
    "소파이": "SOFI", "sofi": "SOFI",
    "리비안": "RIVN", "rivian": "RIVN",
    "마이크로스트래티지": "MSTR",
    "로켓랩": "RKLB",
}

THEME_ALIASES = {
    "ai": ["NVDA", "AMD", "AVGO", "ARM", "SMCI", "PLTR", "AI", "CRM", "SNOW"],
    "반도체": ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "MU", "MRVL", "ARM", "SMCI", "TSM"],
    "빅테크": ["AAPL", "MSFT", "GOOGL", "AMZN", "META"],
    "ev": ["TSLA", "RIVN", "LCID"],
    "전기차": ["TSLA", "RIVN", "LCID"],
    "바이오": ["LLY", "NVO", "MRNA", "PFE", "ABBV"],
    "헬스케어": ["LLY", "NVO", "JNJ", "UNH", "ABBV"],
    "에너지": ["XOM", "CVX", "LNG", "FSLR", "ENPH"],
    "태양광": ["FSLR", "ENPH"],
    "방산": ["LMT", "RTX", "BA"],
    "우주": ["RKLB", "LUNR"],
    "양자컴퓨팅": ["IONQ", "RGTI"],
    "양자": ["IONQ", "RGTI"],
    "크립토": ["COIN", "MSTR"],
    "비트코인": ["COIN", "MSTR"],
    "핀테크": ["V", "MA", "SQ", "SOFI", "COIN"],
    "금융": ["JPM", "GS", "V", "MA"],
    "사이버보안": ["CRWD", "PANW", "NET"],
    "클라우드": ["CRM", "SNOW", "DDOG", "NET"],
    "소비재": ["COST", "WMT", "NKE", "DIS"],
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  핵심 분석 함수
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def analyze_single(symbol: str) -> str:
    """단일 종목 상세 분석"""
    try:
        data = yf.download(symbol, period="3mo", progress=False)
        if data.empty or len(data) < 10:
            return f"❌ {symbol} 데이터를 찾을 수 없습니다."

        # MultiIndex 처리
        if isinstance(data.columns, __import__('pandas').MultiIndex):
            data.columns = data.columns.droplevel(1)

        m = score_momentum(data)
        t = score_technical(data)
        v = score_volume_breakout(data)
        e = score_earnings(symbol, data)
        f = score_fundamental(symbol)

        total = compute_total_score(m, t, v, e, f)
        grade = assign_grade(total)
        news = get_news_summary(symbol, f.get("short_name", ""))

        price = float(data["Close"].iloc[-1])
        prev = float(data["Close"].iloc[-2])
        chg = round((price / prev - 1) * 100, 2)
        sign = "+" if chg > 0 else ""
        icon = "🟢" if chg > 0 else "🔴"

        GRADE_EMOJI = {"S": "🏆", "A": "🔥", "B": "✅", "C": "📌", "D": "⬜"}

        lines = [
            f"{GRADE_EMOJI.get(grade, '')} *{symbol}* ({f.get('short_name', symbol)})",
            f"{icon} ${price:.2f} ({sign}{chg}%) | 등급 *{grade}* ({total}/100)",
            "",
            "📊 *팩터 분석:*",
            f"  모멘텀    {_bar(m['score'])} {m['score']}",
            f"  기술적    {_bar(t['score'])} {t['score']}",
            f"  거래량    {_bar(v['score'])} {v['score']}",
            f"  실적      {_bar(e['score'])} {e['score']}",
            f"  펀더멘탈  {_bar(f['score'])} {f['score']}",
            "",
        ]

        # 모멘텀 상세
        lines.append(f"📈 *모멘텀:* 1W {'+' if m['ret_1w']>0 else ''}{m['ret_1w']}% | 1M {'+' if m['ret_1m']>0 else ''}{m['ret_1m']}% | 3M {'+' if m['ret_3m']>0 else ''}{m['ret_3m']}%")

        # 기술적 상세
        rsi_label = "과매수⚠️" if t['rsi']>70 else "강세" if t['rsi']>55 else "중립" if t['rsi']>45 else "약세" if t['rsi']>30 else "과매도"
        lines.append(f"🔧 *기술적:* RSI {t['rsi']:.0f} ({rsi_label}) | MACD {'골든✨' if t.get('macd_cross') else '양수' if t['macd_histogram']>0 else '음수'}")

        # 거래량
        if v['rvol'] > 1.3:
            lines.append(f"🔥 *거래량:* 평소 대비 {v['rvol']}배{'  🚀 52주 신고가!' if v.get('at_52w_high') else '  📊 20일 돌파' if v.get('breakout_20d') else ''}")

        # 펀더멘탈
        parts = []
        if f.get("market_cap_str"):
            parts.append(f"시총 {f['market_cap_str']}")
        if f.get("pe_ratio") and f["pe_ratio"] > 0:
            parts.append(f"PER {f['pe_ratio']}")
        if e.get("earnings_date"):
            parts.append(f"실적 {e['earnings_date']}")
        if e.get("revenue_growth"):
            parts.append(f"매출성장 {e['revenue_growth']}%")
        if parts:
            lines.append(f"💼 {' · '.join(parts)}")

        # 시그널 모음
        all_signals = []
        for src in [t.get("signals", []), v.get("signals", []), e.get("signals", []), f.get("signals", [])]:
            all_signals.extend(src)
        if all_signals:
            lines.append(f"\n🔑 *시그널:* {' | '.join(all_signals[:5])}")

        # 뉴스
        if news.get("headlines"):
            lines.append(f"\n📰 *최신 뉴스:*")
            for h in news["headlines"][:3]:
                lines.append(f"  • {h}")

        # 판단 요약
        lines.append("")
        if total >= 70:
            lines.append("💡 _강한 관심 구간. 모멘텀+거래량+실적이 뒷받침됨_")
        elif total >= 50:
            lines.append("💡 _관심 유지. 일부 팩터가 긍정적_")
        elif total >= 30:
            lines.append("💡 _관망 구간. 뚜렷한 방향성 부족_")
        else:
            lines.append("💡 _약세 구간. 진입 근거 부족_")

        lines.append("\n_⚠️ 정보 제공 목적이며 투자 권유가 아닙니다_")

        return "\n".join(lines)

    except Exception as ex:
        logger.error(f"analyze_single failed for {symbol}: {ex}")
        return f"❌ {symbol} 분석 실패: {str(ex)[:200]}"


def generate_report(top_n: int = 5) -> str:
    """리포트 생성 파이프라인"""
    stocks = screen_stocks_advanced(top_n=top_n)
    if not stocks:
        return "📊 오늘은 특별히 주목할 종목이 없습니다."

    news_data = {}
    for s in stocks:
        news_data[s.symbol] = get_news_summary(s.symbol, s.name)

    if USE_AI:
        return generate_ai_summary(to_json(stocks), news_data)

    report = format_advanced_report(stocks)
    news_lines = []
    for s in stocks:
        headlines = news_data.get(s.symbol, {}).get("headlines", [])
        if headlines:
            news_lines.append(f"\n📰 *{s.symbol}:* {headlines[0]}")
    return report + "\n".join(news_lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  명령어 핸들러
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("/report"), KeyboardButton("/top3")],
            [KeyboardButton("/watchlist"), KeyboardButton("/earnings")],
            [KeyboardButton("/help")],
        ],
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "🤖 *미국 주식 테마 종목 봇*\n\n"
        "아래 버튼을 누르거나 명령어를 입력하세요.\n"
        "종목명을 한국어로 써도 됩니다!\n\n"
        f"📌 채팅 ID: `{update.effective_chat.id}`",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 *사용 가이드*\n\n"
        "*기본 명령어:*\n"
        "  /report — 오늘의 테마 종목 (5개)\n"
        "  /top3 — 빠른 상위 3종목\n"
        "  /check NVDA — 종목 상세 분석\n"
        "  /compare NVDA AMD — 종목 비교\n\n"
        "*테마/섹터:*\n"
        "  /sector AI — AI 관련주 분석\n"
        "  /sector 반도체 — 반도체 섹터\n"
        "  가능: AI, 반도체, 빅테크, EV, 바이오,\n"
        "  에너지, 방산, 우주, 양자, 크립토, 핀테크 등\n\n"
        "*관심 종목:*\n"
        "  /watchlist — 관심 종목 보기\n"
        "  /watch NVDA — 관심 종목 추가\n"
        "  /unwatch NVDA — 관심 종목 제거\n\n"
        "*알림:*\n"
        "  /alert NVDA 5 — NVDA가 5% 이상 변동 시 알림\n"
        "  /alerts — 등록된 알림 목록\n"
        "  /delalert 1 — 알림 삭제\n\n"
        "*스케줄:*\n"
        "  /schedule 7 30 — 매일 오전 7:30에 리포트\n"
        "  /schedule off — 자동 리포트 중지\n\n"
        "*실적:*\n"
        "  /earnings — 이번 주 실적 발표 종목\n\n"
        "*자연어:*\n"
        '  "엔비디아 어때?" → NVDA 분석\n'
        '  "반도체 관련주" → 섹터 분석\n'
        '  "오늘 뭐 살까" → 리포트\n'
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ 멀티팩터 분석 중... (1~2분)")
    report = generate_report(top_n=5)
    await _send_long(update, report)


async def cmd_top3(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ 빠른 분석 중...")
    report = generate_report(top_n=3)
    await _send_long(update, report)


async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("사용법: /check NVDA")
        return
    symbol = ctx.args[0].upper()
    await update.message.reply_text(f"⏳ {symbol} 분석 중...")
    result = analyze_single(symbol)
    await _send_long(update, result)


async def cmd_compare(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """두 종목 비교"""
    if len(ctx.args) < 2:
        await update.message.reply_text("사용법: /compare NVDA AMD")
        return

    sym1, sym2 = ctx.args[0].upper(), ctx.args[1].upper()
    await update.message.reply_text(f"⏳ {sym1} vs {sym2} 비교 중...")

    try:
        data = yf.download([sym1, sym2], period="3mo", group_by="ticker", progress=False)
        lines = [f"⚔️ *{sym1} vs {sym2} 비교*\n"]

        for sym in [sym1, sym2]:
            try:
                df = data[sym].dropna()
                if len(df) < 10:
                    lines.append(f"*{sym}*: 데이터 부족")
                    continue

                m = score_momentum(df)
                t = score_technical(df)
                v = score_volume_breakout(df)
                e = score_earnings(sym, df)
                f = score_fundamental(sym)
                total = compute_total_score(m, t, v, e, f)
                grade = assign_grade(total)

                price = float(df["Close"].iloc[-1])
                chg = round(float((df["Close"].iloc[-1]/df["Close"].iloc[-2]-1)*100), 2)
                sign = "+" if chg > 0 else ""

                lines.append(f"{'─' * 25}")
                lines.append(f"*{sym}* ({f.get('short_name', sym)})")
                lines.append(f"  💰 ${price:.2f} ({sign}{chg}%)")
                lines.append(f"  🏆 등급: *{grade}* ({total}/100)")
                lines.append(f"  모멘텀: {m['score']} | 기술: {t['score']} | 거래량: {v['score']}")
                lines.append(f"  실적: {e['score']} | 펀더멘탈: {f['score']}")
                lines.append(f"  1M {'+' if m['ret_1m']>0 else ''}{m['ret_1m']}% | RSI {t['rsi']:.0f} | RVOL {v['rvol']}x")
                lines.append("")
            except Exception:
                lines.append(f"*{sym}*: 분석 실패")

        lines.append("_⚠️ 정보 제공 목적이며 투자 권유가 아닙니다_")
        await _send_long(update, "\n".join(lines))

    except Exception as ex:
        await update.message.reply_text(f"❌ 비교 실패: {str(ex)[:200]}")


async def cmd_sector(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """섹터/테마별 종목 분석"""
    if not ctx.args:
        available = ", ".join(sorted(THEME_ALIASES.keys()))
        await update.message.reply_text(f"사용법: /sector AI\n\n가능한 테마:\n{available}")
        return

    theme = ctx.args[0].lower()
    symbols = THEME_ALIASES.get(theme)
    if not symbols:
        # 부분 매칭 시도
        for key, syms in THEME_ALIASES.items():
            if theme in key:
                symbols = syms
                theme = key
                break
    if not symbols:
        await update.message.reply_text(f"❌ '{theme}' 테마를 찾을 수 없습니다.")
        return

    await update.message.reply_text(f"⏳ #{theme} 섹터 {len(symbols)}종목 분석 중...")

    try:
        data = yf.download(symbols, period="3mo", group_by="ticker", progress=False)
        results = []

        for sym in symbols:
            try:
                df = data[sym].dropna() if len(symbols) > 1 else data.dropna()
                if len(df) < 10:
                    continue
                m = score_momentum(df)
                t = score_technical(df)
                v = score_volume_breakout(df)
                total = compute_total_score(m, t, v, {"score": 0}, {"score": 0})
                price = float(df["Close"].iloc[-1])
                chg = round(float((df["Close"].iloc[-1]/df["Close"].iloc[-2]-1)*100), 2)
                results.append((sym, total, price, chg, m["ret_1m"], v["rvol"]))
            except Exception:
                continue

        results.sort(key=lambda x: x[1], reverse=True)

        lines = [f"📊 *#{theme} 섹터 분석*\n"]
        for i, (sym, score, price, chg, ret1m, rvol) in enumerate(results, 1):
            icon = "🟢" if chg > 0 else "🔴"
            sign = "+" if chg > 0 else ""
            grade = assign_grade(score)
            lines.append(f"{i}. *{sym}* {icon} ${price:.1f} ({sign}{chg}%)")
            lines.append(f"   점수: {score:.0f} ({grade}) | 1M {'+' if ret1m>0 else ''}{ret1m:.1f}% | 거래량 {rvol:.1f}x")

        lines.append(f"\n_총 {len(results)}종목 분석 완료_")
        await _send_long(update, "\n".join(lines))

    except Exception as ex:
        await update.message.reply_text(f"❌ 섹터 분석 실패: {str(ex)[:200]}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  관심 종목 (Watchlist)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cmd_watchlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    wl = data.get("watchlist", [])
    if not wl:
        await update.message.reply_text("📋 관심 종목이 없습니다.\n/watch NVDA 로 추가하세요.")
        return

    await update.message.reply_text(f"⏳ 관심 종목 {len(wl)}개 분석 중...")

    try:
        dl = yf.download(wl, period="1mo", group_by="ticker", progress=False)
        lines = ["📋 *내 관심 종목*\n"]
        for sym in wl:
            try:
                df = dl[sym].dropna() if len(wl) > 1 else dl.dropna()
                price = float(df["Close"].iloc[-1])
                chg = round(float((df["Close"].iloc[-1]/df["Close"].iloc[-2]-1)*100), 2)
                icon = "🟢" if chg > 0 else "🔴"
                sign = "+" if chg > 0 else ""
                lines.append(f"{icon} *{sym}* ${price:.2f} ({sign}{chg}%)")
            except Exception:
                lines.append(f"⬜ *{sym}* — 데이터 없음")

        lines.append(f"\n/check 종목명 으로 상세 분석")
        await _send_long(update, "\n".join(lines))
    except Exception as ex:
        await update.message.reply_text(f"❌ 실패: {str(ex)[:200]}")


async def cmd_watch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("사용법: /watch NVDA")
        return
    sym = ctx.args[0].upper()
    data = load_data()
    if sym not in data["watchlist"]:
        data["watchlist"].append(sym)
        save_data(data)
    await update.message.reply_text(f"✅ {sym} 관심 종목 추가!\n현재: {', '.join(data['watchlist'])}")


async def cmd_unwatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("사용법: /unwatch NVDA")
        return
    sym = ctx.args[0].upper()
    data = load_data()
    if sym in data["watchlist"]:
        data["watchlist"].remove(sym)
        save_data(data)
        await update.message.reply_text(f"🗑 {sym} 제거. 현재: {', '.join(data['watchlist']) or '없음'}")
    else:
        await update.message.reply_text(f"{sym}는 관심 종목에 없습니다.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  가격 알림 (Alert)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cmd_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/alert NVDA 5 → NVDA가 5% 이상 변동 시 알림"""
    if len(ctx.args) < 2:
        await update.message.reply_text(
            "사용법: /alert NVDA 5\n"
            "(NVDA가 하루 5% 이상 변동 시 알림)"
        )
        return
    sym = ctx.args[0].upper()
    try:
        threshold = float(ctx.args[1])
    except ValueError:
        await update.message.reply_text("퍼센트를 숫자로 입력하세요. 예: /alert NVDA 5")
        return

    data = load_data()
    data["alerts"].append({"symbol": sym, "threshold": threshold, "active": True})
    save_data(data)
    await update.message.reply_text(
        f"🔔 알림 등록!\n{sym} 일일 변동 ±{threshold}% 이상 시 알림\n"
        f"/alerts 로 목록 확인"
    )


async def cmd_alerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    alerts = data.get("alerts", [])
    if not alerts:
        await update.message.reply_text("🔔 등록된 알림이 없습니다.\n/alert NVDA 5 로 추가하세요.")
        return
    lines = ["🔔 *등록된 알림*\n"]
    for i, a in enumerate(alerts, 1):
        status = "✅" if a.get("active", True) else "⏸"
        lines.append(f"{i}. {status} *{a['symbol']}* ±{a['threshold']}%")
    lines.append("\n/delalert 번호 로 삭제")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_delalert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("사용법: /delalert 1")
        return
    try:
        idx = int(ctx.args[0]) - 1
        data = load_data()
        if 0 <= idx < len(data["alerts"]):
            removed = data["alerts"].pop(idx)
            save_data(data)
            await update.message.reply_text(f"🗑 {removed['symbol']} 알림 삭제")
        else:
            await update.message.reply_text("잘못된 번호입니다.")
    except ValueError:
        await update.message.reply_text("번호를 입력하세요.")


async def check_alerts(ctx: ContextTypes.DEFAULT_TYPE):
    """주기적으로 알림 조건 체크 (30분마다)"""
    data = load_data()
    alerts = [a for a in data.get("alerts", []) if a.get("active", True)]
    if not alerts:
        return

    symbols = list(set(a["symbol"] for a in alerts))
    try:
        dl = yf.download(symbols, period="5d", group_by="ticker", progress=False)
        for a in alerts:
            sym = a["symbol"]
            try:
                df = dl[sym].dropna() if len(symbols) > 1 else dl.dropna()
                price = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2])
                chg = (price / prev - 1) * 100
                if abs(chg) >= a["threshold"]:
                    icon = "🚨🟢" if chg > 0 else "🚨🔴"
                    msg = (
                        f"{icon} *{sym} 알림 발동!*\n"
                        f"${price:.2f} ({'+' if chg>0 else ''}{chg:.1f}%)\n"
                        f"설정 기준: ±{a['threshold']}%\n"
                        f"/check {sym} 으로 상세 분석"
                    )
                    chat_id = CHAT_ID or data.get("chat_id", "")
                    if chat_id:
                        await ctx.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
            except Exception:
                continue
    except Exception as e:
        logger.error(f"Alert check failed: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  스케줄 설정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cmd_schedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/schedule 7 30 — 매일 오전 7:30 리포트"""
    if ctx.args and ctx.args[0].lower() == "off":
        # 기존 스케줄 제거
        jobs = ctx.job_queue.get_jobs_by_name("daily_report")
        for job in jobs:
            job.schedule_removal()
        await update.message.reply_text("⏹ 자동 리포트가 중지되었습니다.")
        return

    if len(ctx.args) < 1:
        data = load_data()
        h, m = data.get("schedule_hour", 7), data.get("schedule_min", 0)
        await update.message.reply_text(
            f"현재 스케줄: 매일 {h:02d}:{m:02d} KST\n\n"
            "변경: /schedule 8 00\n"
            "중지: /schedule off"
        )
        return

    try:
        hour = int(ctx.args[0])
        minute = int(ctx.args[1]) if len(ctx.args) > 1 else 0
        assert 0 <= hour <= 23 and 0 <= minute <= 59
    except (ValueError, AssertionError):
        await update.message.reply_text("올바른 시간을 입력하세요. 예: /schedule 7 30")
        return

    # 저장
    data = load_data()
    data["schedule_hour"] = hour
    data["schedule_min"] = minute
    data["chat_id"] = str(update.effective_chat.id)
    save_data(data)

    # 기존 스케줄 제거 후 재등록
    jobs = ctx.job_queue.get_jobs_by_name("daily_report")
    for job in jobs:
        job.schedule_removal()

    # UTC 변환 (KST = UTC+9)
    utc_hour = (hour - 9) % 24
    ctx.job_queue.run_daily(
        scheduled_report,
        time=time(hour=utc_hour, minute=minute),
        name="daily_report",
        chat_id=update.effective_chat.id,
    )

    await update.message.reply_text(f"✅ 매일 {hour:02d}:{minute:02d} KST에 리포트를 보내드립니다!")


async def scheduled_report(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = CHAT_ID or ctx.job.chat_id
    if not chat_id:
        return
    try:
        report = generate_report(top_n=5)
        await ctx.bot.send_message(chat_id=chat_id, text=report, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Scheduled report failed: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  실적 캘린더
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cmd_earnings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """이번 주 실적 발표 종목"""
    await update.message.reply_text("⏳ 실적 캘린더 확인 중...")

    upcoming = []
    for sym in UNIVERSE:
        try:
            info = yf.Ticker(sym).info
            ts = info.get("earningsTimestamp")
            if ts:
                ed = datetime.fromtimestamp(ts)
                days_left = (ed - datetime.now()).days
                if 0 <= days_left <= 7:
                    upcoming.append((sym, ed.strftime("%m/%d"), days_left, info.get("shortName", sym)))
        except Exception:
            continue

    if not upcoming:
        await update.message.reply_text("📅 이번 주 실적 발표 예정 종목이 없습니다.")
        return

    upcoming.sort(key=lambda x: x[2])
    lines = ["📅 *이번 주 실적 발표*\n"]
    for sym, date, days, name in upcoming:
        when = "오늘" if days == 0 else f"{days}일 후"
        lines.append(f"  📌 *{sym}* ({name}) — {date} ({when})")

    lines.append(f"\n/check 종목명 으로 실적 전 분석")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  수익률 추적 & 백테스트 명령어
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """알고리즘 성과 통계"""
    days = 30
    if ctx.args:
        try:
            days = int(ctx.args[0])
        except ValueError:
            pass
    await update.message.reply_text(f"⏳ 최근 {days}일 성과 분석 중...")
    report = format_stats_report(days)
    await _send_long(update, report)


async def cmd_picks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """최근 추천 종목 성적표"""
    days = 7
    if ctx.args:
        try:
            days = int(ctx.args[0])
        except ValueError:
            pass
    report = get_recent_picks_report(days)
    await _send_long(update, report)


async def cmd_backtest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/backtest 60 3 — 60일 백테스트, 3일 보유"""
    lookback = 60
    hold = 3
    if ctx.args:
        try:
            lookback = int(ctx.args[0])
            if len(ctx.args) > 1:
                hold = int(ctx.args[1])
        except ValueError:
            pass

    await update.message.reply_text(
        f"🧪 백테스트 실행 중...\n"
        f"기간: {lookback}거래일 | 보유: {hold}일\n"
        f"(2~5분 소요)"
    )
    result = run_backtest(lookback_days=lookback, hold_days=hold)
    await _send_long(update, result)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  시장 모니터링 명령어
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cmd_market(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """시장 현황 종합"""
    await update.message.reply_text("⏳ 시장 현황 확인 중...")
    result = format_market_overview()
    await _send_long(update, result)


async def cmd_premarket(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """프리마켓 급등락"""
    await update.message.reply_text("⏳ 프리마켓 스캔 중...")
    movers = scan_premarket(threshold=2.0)
    if movers:
        await _send_long(update, format_premarket_alert(movers))
    else:
        await update.message.reply_text("🌅 프리마켓에서 큰 변동이 없습니다.")


async def cmd_morning(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """장 시작 전 체크리스트"""
    await update.message.reply_text("☀️ 체크리스트 생성 중...")
    data = load_data()
    result = morning_checklist(data.get("watchlist"))
    await _send_long(update, result)


async def cmd_fear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """공포탐욕지수"""
    fg = calculate_fear_greed()
    msg = (
        f"{fg['emoji']} *공포탐욕지수: {fg['score']}/100*\n"
        f"상태: {fg['label']}\n"
        f"💡 {fg['description']}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_position(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/position NVDA 130 — 보유 종목 등록 (종목 매수가)"""
    if len(ctx.args) < 2:
        await update.message.reply_text(
            "사용법: /position NVDA 130\n"
            "(NVDA를 $130에 매수 등록)\n\n"
            "/positions — 보유 종목 현황\n"
            "/delposition NVDA — 보유 종목 삭제"
        )
        return

    sym = ctx.args[0].upper()
    try:
        entry_price = float(ctx.args[1])
    except ValueError:
        await update.message.reply_text("매수가를 숫자로 입력하세요.")
        return

    data = load_data()
    if "positions" not in data:
        data["positions"] = []

    # 기존 포지션 업데이트 또는 추가
    for p in data["positions"]:
        if p["symbol"] == sym:
            p["entry_price"] = entry_price
            p["entry_date"] = datetime.now().strftime("%Y-%m-%d")
            save_data(data)
            await update.message.reply_text(f"✅ {sym} 매수가 ${entry_price}로 업데이트")
            return

    data["positions"].append({
        "symbol": sym,
        "entry_price": entry_price,
        "entry_date": datetime.now().strftime("%Y-%m-%d"),
    })
    save_data(data)
    await update.message.reply_text(f"✅ {sym} ${entry_price} 포지션 등록!")


async def cmd_positions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """보유 종목 현황 + 손익"""
    data = load_data()
    positions = data.get("positions", [])
    if not positions:
        await update.message.reply_text(
            "📦 등록된 보유 종목이 없습니다.\n"
            "/position NVDA 130 으로 추가하세요."
        )
        return

    await update.message.reply_text("⏳ 보유 종목 분석 중...")

    symbols = [p["symbol"] for p in positions]
    try:
        dl = yf.download(symbols, period="5d", group_by="ticker", progress=False)
    except Exception as ex:
        await update.message.reply_text(f"❌ 데이터 로드 실패: {str(ex)[:200]}")
        return

    lines = ["📦 *보유 종목 현황*\n"]
    total_pnl = 0
    total_count = 0

    for p in positions:
        sym = p["symbol"]
        entry = p["entry_price"]
        try:
            df = dl[sym].dropna() if len(symbols) > 1 else dl.dropna()
            current = float(df["Close"].iloc[-1])
            pnl = (current / entry - 1) * 100
            icon = "📈" if pnl > 0 else "📉"
            total_pnl += pnl
            total_count += 1
            lines.append(
                f"{icon} *{sym}* ${entry} → ${current:.2f} "
                f"({'+' if pnl>0 else ''}{pnl:.1f}%)"
            )
        except Exception:
            lines.append(f"⬜ *{sym}* ${entry} — 가격 조회 실패")

    if total_count > 0:
        avg_pnl = total_pnl / total_count
        lines.append(f"\n📊 평균 수익률: {'+' if avg_pnl>0 else ''}{avg_pnl:.1f}%")

    # 손절/익절 알림 체크
    exit_alerts = check_exit_signals(positions)
    if exit_alerts:
        lines.append(f"\n{'━' * 25}")
        lines.append(format_exit_alerts(exit_alerts))

    await _send_long(update, "\n".join(lines))


async def cmd_delposition(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("사용법: /delposition NVDA")
        return
    sym = ctx.args[0].upper()
    data = load_data()
    positions = data.get("positions", [])
    data["positions"] = [p for p in positions if p["symbol"] != sym]
    save_data(data)
    await update.message.reply_text(f"🗑 {sym} 포지션 삭제")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  자동 모니터링 작업 (JobQueue)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def job_morning_checklist(ctx: ContextTypes.DEFAULT_TYPE):
    """매일 아침 자동 체크리스트 (KST 21:00 = 프리마켓 시작)"""
    chat_id = CHAT_ID or load_data().get("chat_id", "")
    if not chat_id:
        return
    try:
        data = load_data()
        report = morning_checklist(data.get("watchlist"))
        await ctx.bot.send_message(chat_id=chat_id, text=report, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Morning checklist failed: {e}")


async def job_premarket_scan(ctx: ContextTypes.DEFAULT_TYPE):
    """프리마켓 급등락 감지 (15분마다, 프리마켓 시간에만)"""
    mkt = get_market_status()
    if mkt["phase"] not in ("premarket", "regular"):
        return

    chat_id = CHAT_ID or load_data().get("chat_id", "")
    if not chat_id:
        return

    try:
        movers = scan_premarket(threshold=4.0)  # 4% 이상만 알림
        if movers:
            msg = format_premarket_alert(movers)
            await ctx.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Premarket scan failed: {e}")


async def job_volume_scan(ctx: ContextTypes.DEFAULT_TYPE):
    """장중 거래량 폭발 감지 (30분마다)"""
    mkt = get_market_status()
    if mkt["phase"] != "regular":
        return

    chat_id = CHAT_ID or load_data().get("chat_id", "")
    if not chat_id:
        return

    try:
        surges = scan_volume_surge(rvol_threshold=3.0)  # 3배 이상만
        if surges:
            msg = format_volume_alert(surges)
            await ctx.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Volume scan failed: {e}")


async def job_exit_monitor(ctx: ContextTypes.DEFAULT_TYPE):
    """보유 종목 손절/익절 모니터 (30분마다)"""
    mkt = get_market_status()
    if not mkt.get("is_trading"):
        return

    data = load_data()
    positions = data.get("positions", [])
    if not positions:
        return

    chat_id = CHAT_ID or data.get("chat_id", "")
    if not chat_id:
        return

    try:
        alerts = check_exit_signals(positions)
        if alerts:
            msg = format_exit_alerts(alerts)
            await ctx.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Exit monitor failed: {e}")


async def job_track_returns(ctx: ContextTypes.DEFAULT_TYPE):
    """매일 수익률 추적 업데이트"""
    try:
        updated = track_returns()
        logger.info(f"Tracked returns for {updated} picks")
    except Exception as e:
        logger.error(f"Return tracking failed: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  자연어 처리
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """명령어가 아닌 일반 텍스트 처리"""
    text = update.message.text.strip().lower()

    # 시장 현황 트리거
    if any(kw in text for kw in ["시장", "마켓", "지수", "현황"]):
        await update.message.reply_text("⏳ 시장 현황 확인 중...")
        result = format_market_overview()
        await _send_long(update, result)
        return

    # 성과 트리거
    if any(kw in text for kw in ["성과", "성적", "수익률", "백테스트", "승률"]):
        await cmd_stats(update, ctx)
        return

    # 리포트 트리거
    if any(kw in text for kw in ["리포트", "오늘 뭐", "추천", "뭐 살", "분석해", "알려줘"]):
        await cmd_report(update, ctx)
        return

    # 섹터 트리거
    for theme_key, symbols in THEME_ALIASES.items():
        if theme_key in text and ("관련" in text or "섹터" in text or "종목" in text or "어때" in text):
            ctx.args = [theme_key]
            await cmd_sector(update, ctx)
            return

    # 종목명 매칭
    for alias, ticker in TICKER_ALIASES.items():
        if alias in text:
            await update.message.reply_text(f"⏳ {ticker} 분석 중...")
            result = analyze_single(ticker)
            await _send_long(update, result)
            return

    # 영문 티커 직접 입력 (1~5글자 대문자)
    match = re.search(r'\b([A-Z]{1,5})\b', update.message.text)
    if match:
        possible_ticker = match.group(1)
        if possible_ticker in UNIVERSE or len(possible_ticker) >= 2:
            # 인라인 버튼으로 확인
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(f"📊 {possible_ticker} 분석", callback_data=f"check_{possible_ticker}"),
                    InlineKeyboardButton("❌ 아니요", callback_data="cancel"),
                ]
            ])
            await update.message.reply_text(
                f"*{possible_ticker}* 종목을 분석할까요?",
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            return

    # 매칭 안 되면 도움말
    await update.message.reply_text(
        "무엇을 도와드릴까요?\n\n"
        '• 종목: "엔비디아 어때?" 또는 /check NVDA\n'
        '• 리포트: "오늘 추천" 또는 /report\n'
        '• 섹터: "반도체 관련주" 또는 /sector 반도체\n'
        "• /help 로 전체 기능 보기"
    )


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """인라인 버튼 콜백"""
    query = update.callback_query
    await query.answer()

    if query.data.startswith("check_"):
        symbol = query.data.replace("check_", "")
        await query.edit_message_text(f"⏳ {symbol} 분석 중...")
        result = analyze_single(symbol)
        await query.message.reply_text(result, parse_mode="Markdown")

    elif query.data == "cancel":
        await query.edit_message_text("취소되었습니다.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  유틸리티
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _send_long(update: Update, text: str):
    """텔레그램 4096자 제한 대응"""
    if len(text) <= 4000:
        try:
            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(text)  # 마크다운 실패 시 일반 텍스트
    else:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            try:
                await update.message.reply_text(chunk, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(chunk)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  메인 실행
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN 환경 변수를 설정하세요.")
        print("   1. @BotFather에서 봇 생성")
        print("   2. export TELEGRAM_BOT_TOKEN=여기에토큰")
        return

    app = Application.builder().token(TOKEN).build()

    # 명령어
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("top3", cmd_top3))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("compare", cmd_compare))
    app.add_handler(CommandHandler("sector", cmd_sector))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("unwatch", cmd_unwatch))
    app.add_handler(CommandHandler("alert", cmd_alert))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("delalert", cmd_delalert))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("earnings", cmd_earnings))
    # 신규: 성과 & 백테스트
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("picks", cmd_picks))
    app.add_handler(CommandHandler("backtest", cmd_backtest))
    # 신규: 시장 모니터링
    app.add_handler(CommandHandler("market", cmd_market))
    app.add_handler(CommandHandler("premarket", cmd_premarket))
    app.add_handler(CommandHandler("morning", cmd_morning))
    app.add_handler(CommandHandler("fear", cmd_fear))
    # 신규: 포지션 관리
    app.add_handler(CommandHandler("position", cmd_position))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("delposition", cmd_delposition))

    # 인라인 버튼
    app.add_handler(CallbackQueryHandler(handle_callback))

    # 자연어 텍스트
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # 스케줄 작업
    jq = app.job_queue
    if jq:
        # 기본 스케줄: KST 07:00 (UTC 22:00)
        data = load_data()
        h = data.get("schedule_hour", 7)
        m = data.get("schedule_min", 0)
        utc_h = (h - 9) % 24
        jq.run_daily(scheduled_report, time=time(hour=utc_h, minute=m), name="daily_report")

        # 알림 체크: 30분마다 (미장 개장 시간에만)
        jq.run_repeating(check_alerts, interval=1800, first=60)

        # 신규: 아침 체크리스트 (KST 21:00 = 프리마켓 시작, UTC 12:00)
        jq.run_daily(job_morning_checklist, time=dtime(hour=12, minute=0), name="morning_checklist")

        # 신규: 프리마켓 스캔 (15분마다)
        jq.run_repeating(job_premarket_scan, interval=900, first=120)

        # 신규: 거래량 폭발 감지 (30분마다)
        jq.run_repeating(job_volume_scan, interval=1800, first=180)

        # 신규: 손절/익절 모니터 (30분마다)
        jq.run_repeating(job_exit_monitor, interval=1800, first=240)

        # 신규: 수익률 추적 (매일 1회, UTC 23:00 = KST 08:00)
        jq.run_daily(job_track_returns, time=dtime(hour=23, minute=0), name="track_returns")

        logger.info(f"Scheduled: daily report at KST {h:02d}:{m:02d}, alerts every 30min")

    print("🚀 Bot is running!")
    print("   명령어: /start, /report, /check, /sector, /help")
    print("   자연어: '엔비디아 어때?', '오늘 뭐 살까'")
    print("   Ctrl+C to stop")
    app.run_polling()


if __name__ == "__main__":
    main()
