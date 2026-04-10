"""
추천 종목 수익률 추적 & 백테스트 엔진
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
기능:
  1. 매일 추천 종목을 DB에 기록
  2. 1일/3일/5일/10일 후 수익률 자동 추적
  3. 승률, 평균 수익률, 최대 수익/손실 통계
  4. 팩터별 성과 분석 (어떤 팩터가 잘 맞았나)
  5. 미니 백테스트 (과거 N일 시뮬레이션)
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import logging

import yfinance as yf
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

DB_PATH = Path("picks_history.db")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DB 초기화
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            theme TEXT,
            pick_price REAL,
            total_score REAL,
            grade TEXT,
            momentum_score REAL,
            technical_score REAL,
            volume_score REAL,
            earnings_score REAL,
            fundamental_score REAL,
            signals TEXT,
            ret_1d REAL,
            ret_3d REAL,
            ret_5d REAL,
            ret_10d REAL,
            max_gain REAL,
            max_loss REAL,
            tracked INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT PRIMARY KEY,
            total_picks INTEGER,
            avg_score REAL,
            avg_ret_1d REAL,
            avg_ret_3d REAL,
            avg_ret_5d REAL,
            win_rate_1d REAL,
            win_rate_3d REAL,
            win_rate_5d REAL,
            best_pick TEXT,
            worst_pick TEXT
        )
    """)

    conn.commit()
    conn.close()
    logger.info("DB initialized")


init_db()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  추천 기록 저장
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_picks(stocks: list) -> int:
    """
    오늘의 추천 종목을 DB에 저장
    stocks: screen_stocks_advanced() 또는 to_json() 결과
    Returns: 저장된 종목 수
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    saved = 0

    for s in stocks:
        # StockAnalysis 객체 또는 dict 모두 지원
        if hasattr(s, "symbol"):
            sym = s.symbol
            name = s.name
            theme = s.theme
            score = s.total_score
            grade = s.grade
            price = s.price_data.get("current_price", 0)
            m_score = s.momentum.get("score", 0)
            t_score = s.technical.get("score", 0)
            v_score = s.volume_breakout.get("score", 0)
            e_score = s.earnings.get("score", 0)
            f_score = s.fundamental.get("score", 0)
            signals = json.dumps(s.all_signals, ensure_ascii=False)
        else:
            sym = s.get("symbol", "")
            name = s.get("name", "")
            theme = s.get("theme", "")
            score = s.get("total_score", 0)
            grade = s.get("grade", "")
            price = s.get("price", {}).get("current_price", 0)
            factors = s.get("factors", {})
            m_score = factors.get("momentum", {}).get("score", 0)
            t_score = factors.get("technical", {}).get("score", 0)
            v_score = factors.get("volume_breakout", {}).get("score", 0)
            e_score = factors.get("earnings", {}).get("score", 0)
            f_score = factors.get("fundamental", {}).get("score", 0)
            signals = json.dumps(s.get("signals", []), ensure_ascii=False)

        # 같은 날 같은 종목 중복 방지
        c.execute("SELECT id FROM picks WHERE date=? AND symbol=?", (today, sym))
        if c.fetchone():
            continue

        c.execute("""
            INSERT INTO picks (date, symbol, name, theme, pick_price, total_score,
                grade, momentum_score, technical_score, volume_score,
                earnings_score, fundamental_score, signals)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (today, sym, name, theme, price, score, grade,
              m_score, t_score, v_score, e_score, f_score, signals))
        saved += 1

    conn.commit()
    conn.close()
    logger.info(f"Saved {saved} picks for {today}")
    return saved


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  수익률 추적
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def track_returns():
    """
    과거 추천 종목의 이후 수익률을 업데이트
    매일 실행하면 1일/3일/5일/10일 수익률이 채워짐
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 아직 추적 안 된 종목 (10일 이상 지난 것)
    cutoff = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    c.execute("""
        SELECT id, date, symbol, pick_price FROM picks
        WHERE tracked = 0 AND date <= ?
    """, (cutoff,))
    rows = c.fetchall()

    if not rows:
        conn.close()
        return 0

    # 종목별로 묶기
    symbols = list(set(r[2] for r in rows))
    logger.info(f"Tracking returns for {len(rows)} picks ({len(symbols)} symbols)")

    # 가격 데이터 한번에 다운로드
    earliest_date = min(r[1] for r in rows)
    try:
        price_data = yf.download(
            symbols, start=earliest_date, progress=False, group_by="ticker"
        )
    except Exception as e:
        logger.error(f"Price download failed: {e}")
        conn.close()
        return 0

    updated = 0
    for row_id, pick_date, symbol, pick_price in rows:
        try:
            if len(symbols) == 1:
                df = price_data
            else:
                df = price_data[symbol]

            df = df.dropna()
            if df.empty or pick_price <= 0:
                continue

            # 추천일 이후의 날짜들 찾기
            pick_dt = pd.Timestamp(pick_date)
            future = df[df.index > pick_dt]
            if len(future) < 2:
                continue  # 아직 데이터 부족

            def get_ret(days):
                if len(future) >= days:
                    return round(float((future["Close"].iloc[days-1] / pick_price - 1) * 100), 2)
                return None

            ret_1d = get_ret(1)
            ret_3d = get_ret(3)
            ret_5d = get_ret(5)
            ret_10d = get_ret(10)

            # 기간 내 최대 수익/손실
            if len(future) >= 1:
                window = future.iloc[:min(10, len(future))]
                max_gain = round(float((window["High"].max() / pick_price - 1) * 100), 2)
                max_loss = round(float((window["Low"].min() / pick_price - 1) * 100), 2)
            else:
                max_gain, max_loss = None, None

            # 10일 지났거나 모든 수익률 채워졌으면 tracked = 1
            days_since = (datetime.now() - datetime.strptime(pick_date, "%Y-%m-%d")).days
            is_complete = days_since >= 12

            c.execute("""
                UPDATE picks SET
                    ret_1d=?, ret_3d=?, ret_5d=?, ret_10d=?,
                    max_gain=?, max_loss=?, tracked=?
                WHERE id=?
            """, (ret_1d, ret_3d, ret_5d, ret_10d, max_gain, max_loss,
                  1 if is_complete else 0, row_id))
            updated += 1

        except Exception as e:
            logger.warning(f"Track failed for {symbol} ({pick_date}): {e}")

    conn.commit()
    conn.close()
    logger.info(f"Updated returns for {updated} picks")
    return updated


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  성과 통계
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_performance_stats(days: int = 30) -> dict:
    """최근 N일간 추천 성과 통계"""
    conn = sqlite3.connect(DB_PATH)
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    df = pd.read_sql_query("""
        SELECT * FROM picks WHERE date >= ? AND ret_1d IS NOT NULL
    """, conn, params=(cutoff,))
    conn.close()

    if df.empty:
        return {"total_picks": 0, "message": "아직 추적된 데이터가 없습니다."}

    stats = {
        "total_picks": len(df),
        "period_days": days,

        # 승률 (수익 > 0%)
        "win_rate_1d": round((df["ret_1d"] > 0).mean() * 100, 1) if df["ret_1d"].notna().any() else None,
        "win_rate_3d": round((df["ret_3d"] > 0).mean() * 100, 1) if df["ret_3d"].notna().any() else None,
        "win_rate_5d": round((df["ret_5d"] > 0).mean() * 100, 1) if df["ret_5d"].notna().any() else None,
        "win_rate_10d": round((df["ret_10d"] > 0).mean() * 100, 1) if df["ret_10d"].notna().any() else None,

        # 평균 수익률
        "avg_ret_1d": round(df["ret_1d"].mean(), 2) if df["ret_1d"].notna().any() else None,
        "avg_ret_3d": round(df["ret_3d"].mean(), 2) if df["ret_3d"].notna().any() else None,
        "avg_ret_5d": round(df["ret_5d"].mean(), 2) if df["ret_5d"].notna().any() else None,
        "avg_ret_10d": round(df["ret_10d"].mean(), 2) if df["ret_10d"].notna().any() else None,

        # 최대/최소
        "best_max_gain": round(df["max_gain"].max(), 2) if df["max_gain"].notna().any() else None,
        "worst_max_loss": round(df["max_loss"].min(), 2) if df["max_loss"].notna().any() else None,

        # 등급별 성과
        "grade_performance": {},
    }

    # 등급별 분석
    for grade in ["S", "A", "B", "C"]:
        g_df = df[df["grade"] == grade]
        if len(g_df) >= 1 and g_df["ret_3d"].notna().any():
            stats["grade_performance"][grade] = {
                "count": len(g_df),
                "avg_ret_3d": round(g_df["ret_3d"].mean(), 2),
                "win_rate_3d": round((g_df["ret_3d"] > 0).mean() * 100, 1),
            }

    return stats


def get_factor_analysis(days: int = 30) -> dict:
    """팩터별 성과 분석 — 어떤 팩터 점수가 높을 때 수익이 좋았나"""
    conn = sqlite3.connect(DB_PATH)
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = pd.read_sql_query("""
        SELECT * FROM picks WHERE date >= ? AND ret_3d IS NOT NULL
    """, conn, params=(cutoff,))
    conn.close()

    if len(df) < 5:
        return {"message": "분석에 충분한 데이터가 없습니다. (최소 5건 필요)"}

    factors = {
        "momentum_score": "모멘텀",
        "technical_score": "기술적",
        "volume_score": "거래량",
        "earnings_score": "실적",
        "fundamental_score": "펀더멘탈",
    }

    analysis = {}
    for col, name in factors.items():
        if col not in df.columns:
            continue
        # 팩터 점수 상위 50% vs 하위 50%
        median = df[col].median()
        high = df[df[col] >= median]
        low = df[df[col] < median]

        analysis[name] = {
            "high_score_avg_ret": round(high["ret_3d"].mean(), 2) if len(high) > 0 else 0,
            "low_score_avg_ret": round(low["ret_3d"].mean(), 2) if len(low) > 0 else 0,
            "high_win_rate": round((high["ret_3d"] > 0).mean() * 100, 1) if len(high) > 0 else 0,
            "correlation": round(df[col].corr(df["ret_3d"]), 3) if len(df) > 3 else 0,
        }

    # 가장 효과적인 팩터
    best_factor = max(analysis.items(), key=lambda x: abs(x[1]["correlation"]))
    analysis["best_factor"] = best_factor[0]
    analysis["best_correlation"] = best_factor[1]["correlation"]

    return analysis


def get_recent_picks_report(days: int = 7) -> str:
    """최근 추천 종목 성적표 (텔레그램 메시지용)"""
    conn = sqlite3.connect(DB_PATH)
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = pd.read_sql_query("""
        SELECT * FROM picks WHERE date >= ? ORDER BY date DESC, total_score DESC
    """, conn, params=(cutoff,))
    conn.close()

    if df.empty:
        return "📋 최근 추천 기록이 없습니다."

    lines = [
        "📋 *추천 종목 성적표*",
        f"📅 최근 {days}일\n",
    ]

    current_date = ""
    for _, row in df.iterrows():
        if row["date"] != current_date:
            current_date = row["date"]
            lines.append(f"\n*{current_date}*")

        # 수익률 표시
        rets = []
        for label, col in [("1D", "ret_1d"), ("3D", "ret_3d"), ("5D", "ret_5d")]:
            val = row[col]
            if pd.notna(val):
                icon = "✅" if val > 0 else "❌"
                rets.append(f"{label}:{'+' if val>0 else ''}{val:.1f}%{icon}")
            else:
                rets.append(f"{label}:⏳")

        # 최대 수익
        mg = row["max_gain"]
        mg_str = f"최대+{mg:.1f}%" if pd.notna(mg) and mg > 0 else ""

        lines.append(
            f"  {row['grade']} *{row['symbol']}* ${row['pick_price']:.1f} "
            f"(점수:{row['total_score']:.0f})"
        )
        lines.append(f"    {' | '.join(rets)} {mg_str}")

    # 요약 통계
    tracked = df[df["ret_3d"].notna()]
    if len(tracked) > 0:
        win_rate = (tracked["ret_3d"] > 0).mean() * 100
        avg_ret = tracked["ret_3d"].mean()
        lines.append(f"\n{'━' * 25}")
        lines.append(f"📊 3일 승률: *{win_rate:.0f}%* ({len(tracked)}건)")
        lines.append(f"📈 3일 평균: {'+' if avg_ret>0 else ''}{avg_ret:.2f}%")

        if tracked["max_gain"].notna().any():
            best_idx = tracked["max_gain"].idxmax()
            best = tracked.loc[best_idx]
            lines.append(f"🏆 최고: {best['symbol']} +{best['max_gain']:.1f}%")

    return "\n".join(lines)


def format_stats_report(days: int = 30) -> str:
    """성과 통계 텔레그램 리포트"""
    stats = get_performance_stats(days)

    if stats.get("total_picks", 0) == 0:
        return stats.get("message", "데이터가 없습니다.")

    lines = [
        "📊 *알고리즘 성과 리포트*",
        f"📅 최근 {days}일 | 총 {stats['total_picks']}건\n",
        "━━ *승률* ━━━━━━━━━━",
    ]

    for label, key in [("1일", "win_rate_1d"), ("3일", "win_rate_3d"),
                        ("5일", "win_rate_5d"), ("10일", "win_rate_10d")]:
        val = stats.get(key)
        if val is not None:
            bar = "🟩" * int(val/10) + "⬜" * (10 - int(val/10))
            lines.append(f"  {label}: {bar} {val:.0f}%")

    lines.append("\n━━ *평균 수익률* ━━━━━")
    for label, key in [("1일", "avg_ret_1d"), ("3일", "avg_ret_3d"),
                        ("5일", "avg_ret_5d"), ("10일", "avg_ret_10d")]:
        val = stats.get(key)
        if val is not None:
            icon = "📈" if val > 0 else "📉"
            lines.append(f"  {icon} {label}: {'+' if val>0 else ''}{val:.2f}%")

    if stats.get("best_max_gain"):
        lines.append(f"\n🏆 최대 수익: +{stats['best_max_gain']:.1f}%")
    if stats.get("worst_max_loss"):
        lines.append(f"💀 최대 손실: {stats['worst_max_loss']:.1f}%")

    # 등급별
    gp = stats.get("grade_performance", {})
    if gp:
        lines.append("\n━━ *등급별 성과 (3일)* ━━")
        for grade in ["S", "A", "B", "C"]:
            g = gp.get(grade)
            if g:
                lines.append(
                    f"  {grade}등급: 승률 {g['win_rate_3d']:.0f}% | "
                    f"수익 {'+' if g['avg_ret_3d']>0 else ''}{g['avg_ret_3d']:.2f}% "
                    f"({g['count']}건)"
                )

    # 팩터 분석
    factor = get_factor_analysis(days)
    if factor.get("best_factor"):
        lines.append(f"\n🔬 가장 효과적 팩터: *{factor['best_factor']}*")
        lines.append(f"   (상관계수: {factor['best_correlation']:.3f})")

    return "\n".join(lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  미니 백테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_backtest(lookback_days: int = 60, hold_days: int = 3, top_n: int = 5) -> str:
    """
    과거 데이터로 전략 시뮬레이션
    - lookback_days일 전부터 매일 스크리닝 시뮬레이션
    - hold_days일 보유 후 수익률 계산
    """
    from advanced_screener import (
        score_momentum, score_technical, score_volume_breakout,
        compute_total_score, UNIVERSE
    )

    logger.info(f"Running backtest: {lookback_days}d lookback, {hold_days}d hold, top {top_n}")

    # 넉넉히 데이터 가져오기
    total_days = lookback_days + hold_days + 70  # RSI 등 초기값 필요
    try:
        all_data = yf.download(
            UNIVERSE, period=f"{total_days}d",
            group_by="ticker", progress=False
        )
    except Exception as e:
        return f"❌ 백테스트 데이터 다운로드 실패: {e}"

    # 매일 시뮬레이션
    results = []
    dates = pd.bdate_range(
        end=datetime.now() - timedelta(days=hold_days+1),
        periods=lookback_days,
    )

    for sim_date in dates:
        day_picks = []
        for sym in UNIVERSE:
            try:
                if len(UNIVERSE) > 1:
                    df = all_data[sym].dropna()
                else:
                    df = all_data.dropna()

                # sim_date까지의 데이터만 사용 (미래 정보 배제)
                df_past = df[df.index <= sim_date]
                if len(df_past) < 25:
                    continue

                m = score_momentum(df_past)
                t = score_technical(df_past)
                v = score_volume_breakout(df_past)
                total = compute_total_score(m, t, v, {"score": 0}, {"score": 0})

                # hold_days 후 실제 수익률
                df_future = df[df.index > sim_date]
                if len(df_future) < hold_days:
                    continue
                entry_price = float(df_past["Close"].iloc[-1])
                exit_price = float(df_future["Close"].iloc[hold_days-1])
                ret = (exit_price / entry_price - 1) * 100
                max_price = float(df_future["High"].iloc[:hold_days].max())
                max_gain = (max_price / entry_price - 1) * 100

                day_picks.append({
                    "symbol": sym, "score": total, "ret": ret, "max_gain": max_gain
                })

            except Exception:
                continue

        # 점수 상위 N개 선택
        day_picks.sort(key=lambda x: x["score"], reverse=True)
        for pick in day_picks[:top_n]:
            results.append({
                "date": sim_date.strftime("%Y-%m-%d"),
                **pick,
            })

    if not results:
        return "❌ 백테스트 결과가 없습니다."

    # 통계
    df_results = pd.DataFrame(results)
    total_trades = len(df_results)
    wins = (df_results["ret"] > 0).sum()
    win_rate = wins / total_trades * 100
    avg_ret = df_results["ret"].mean()
    avg_max_gain = df_results["max_gain"].mean()
    total_ret = df_results["ret"].sum()

    # 등급별
    sharpe = (df_results["ret"].mean() / df_results["ret"].std()) * np.sqrt(252 / hold_days) if df_results["ret"].std() > 0 else 0

    lines = [
        "🧪 *백테스트 결과*",
        f"📅 기간: {lookback_days}거래일",
        f"⏱ 보유기간: {hold_days}일 | 상위 {top_n}종목\n",
        f"━━ *성과* ━━━━━━━━━━",
        f"  총 거래: {total_trades}건",
        f"  승률: *{win_rate:.1f}%* ({wins}/{total_trades})",
        f"  평균 수익: {'+' if avg_ret>0 else ''}{avg_ret:.2f}%",
        f"  누적 수익: {'+' if total_ret>0 else ''}{total_ret:.1f}%",
        f"  평균 최대수익: +{avg_max_gain:.2f}%",
        f"  샤프비율: {sharpe:.2f}",
        "",
        f"━━ *수익 분포* ━━━━━",
        f"  > +5%: {(df_results['ret'] > 5).sum()}건",
        f"  +2~5%: {((df_results['ret'] > 2) & (df_results['ret'] <= 5)).sum()}건",
        f"  0~2%: {((df_results['ret'] > 0) & (df_results['ret'] <= 2)).sum()}건",
        f"  -2~0%: {((df_results['ret'] > -2) & (df_results['ret'] <= 0)).sum()}건",
        f"  < -2%: {(df_results['ret'] <= -2).sum()}건",
        "",
    ]

    # 최고/최저
    best = df_results.loc[df_results["ret"].idxmax()]
    worst = df_results.loc[df_results["ret"].idxmin()]
    lines.append(f"🏆 최고: {best['symbol']} +{best['ret']:.1f}% ({best['date']})")
    lines.append(f"💀 최저: {worst['symbol']} {worst['ret']:.1f}% ({worst['date']})")

    # 종목별 빈도
    freq = df_results["symbol"].value_counts().head(5)
    lines.append(f"\n📊 자주 선정된 종목:")
    for sym, cnt in freq.items():
        sym_avg = df_results[df_results["symbol"] == sym]["ret"].mean()
        lines.append(f"  {sym}: {cnt}회 (평균 {'+' if sym_avg>0 else ''}{sym_avg:.1f}%)")

    lines.append(f"\n_⚠️ 과거 수익률이 미래 수익을 보장하지 않습니다_")

    return "\n".join(lines)


# ── 테스트 ──
if __name__ == "__main__":
    # 더미 데이터로 저장 테스트
    test_picks = [
        {"symbol": "NVDA", "name": "NVIDIA", "theme": "AI", "total_score": 80,
         "grade": "S", "price": {"current_price": 135.0},
         "factors": {"momentum": {"score": 80}, "technical": {"score": 70},
                     "volume_breakout": {"score": 75}, "earnings": {"score": 60},
                     "fundamental": {"score": 65}},
         "signals": ["test"]},
    ]
    save_picks(test_picks)
    print("✅ Pick saved")

    print("\n" + get_recent_picks_report(30))
    print("\n" + format_stats_report(30))
