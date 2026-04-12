# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Telegram-based US stock theme-picking bot that runs daily analysis, identifies theme-based stocks (AI, semiconductors, EV, biotech, etc.) via multi-factor scoring, and sends real-time market alerts.

## Environment Setup

Required environment variables (create a `.env` file):
```
TELEGRAM_BOT_TOKEN=<required>
TELEGRAM_CHAT_ID=<required>
FINNHUB_API_KEY=<required, free tier 60 calls/min>
NEWSAPI_KEY=<optional, for news fetching>
```

```bash
pip install -r requirements.txt
python telegram_bot_v2.py
```

## Module Testing (no formal test suite)

Each module has a `if __name__ == "__main__"` block for manual testing:

```bash
python advanced_screener.py      # runs multi-factor screen, prints results to stdout
python news_fetcher.py           # fetches & displays NVDA news
python performance_tracker.py    # initializes DB and prints stats
python market_monitor.py         # shows current market status and Fear & Greed index
python stock_screener.py         # legacy screener, outputs daily_picks.json
```

## Architecture

```
telegram_bot_v2.py (async Telegram command handlers + JobQueue scheduling)
├── finnhub_data.py       → Finnhub REST API wrapper (OHLCV, quotes, fundamentals, earnings)
├── advanced_screener.py  → finnhub_data (OHLCV, fundamentals) → StockResult objects
├── news_fetcher.py       → Finviz scraping + NewsAPI → theme keyword detection
├── performance_tracker.py → picks_history.db (SQLite, auto-initialized on import)
└── market_monitor.py     → finnhub_data (real-time quotes) → alerts + exit signals
```

**telegram_bot_v2.py** — Command handlers: `/report`, `/top3`, `/check`, `/sector`, `/alert`, `/watchlist`, `/earnings`, `/compare`. Handles Korean/English natural language (e.g., 엔비디아 → NVDA). 14+ predefined theme mappings. User state (watchlists, alerts, schedule prefs) persisted in `bot_data.json`.

**advanced_screener.py** — Multi-factor scoring (0–100, grades S/A/B/C/D):
- Momentum 30%: 1W/1M/3M returns
- Technical 25%: RSI, MACD, moving averages
- Volume 20%: RVOL, 52-week highs, 20-day breakouts
- Earnings 15%: Growth rate, proximity to earnings date
- Fundamental 10%: P/E, market cap, analyst ratings

**finnhub_data.py** — 하이브리드 데이터 프로바이더. OHLCV 과거 데이터는 Yahoo Finance Chart API(v8)를 직접 호출(API키 불필요), 현재가·펀더멘탈·실적 캘린더는 Finnhub REST API 사용. 인메모리 캐싱 내장. Finnhub 무료 플랜은 `/stock/candle` 미지원이므로 OHLCV는 Yahoo Finance로 대체.

**market_monitor.py** — Detects market phase (premarket 4–9:30 AM ET / regular / aftermarket 4–8 PM / closed). Scans gap moves (>3%), volume surges. Fear & Greed index from VIXY + SPY momentum + SPY volume + QQQ RSI. ATR-based stop-loss (2× ATR or 3% min) and RSI-based take-profit (>70) exit signals.

**performance_tracker.py** — SQLite schema: `picks` (daily recommendations with scores) + `daily_stats`. Auto-tracks 1d/3d/5d/10d returns. Runs backtests with Sharpe ratio computation. Identifies which scoring factors best predict returns.

**news_fetcher.py** — Scrapes Finviz (no API key) and NewsAPI (optional). Deduplicates headlines, maps to themes.

**stock_screener.py** — Legacy simpler screener (volume spike + fundamental). Predates `advanced_screener.py`; outputs `daily_picks.json`. Rarely used.

## Persistence Files

- `bot_data.json` — User watchlists, alert preferences, schedule settings
- `picks_history.db` — SQLite DB (auto-created on first `performance_tracker` import)
- `daily_picks.json` — Output from legacy `stock_screener.py`

## Deployment

See [gcp-deploy-guide.txt](gcp-deploy-guide.txt) for GCP free-tier deployment (e2-micro VM, systemd service with auto-restart).

## Python Version

All dependency versions are pinned for Python 3.8 compatibility (e.g., `pandas<2.2`, `numpy<2.0`).
