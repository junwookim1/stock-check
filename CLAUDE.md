# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Telegram-based US stock theme-picking bot that runs daily analysis, identifies theme-based stocks (AI, semiconductors, EV, biotech, etc.) via multi-factor scoring, and sends real-time market alerts.

## Environment Setup

Required environment variables (create a `.env` file based on `.env.example`):
```
TELEGRAM_BOT_TOKEN=<required>
TELEGRAM_CHAT_ID=<required>
ANTHROPIC_API_KEY=<optional, for AI summaries>
NEWSAPI_KEY=<optional, for news fetching>
USE_AI_SUMMARY=false
```

Install dependencies:
```bash
pip install -r requirements.txt
```

Run the bot:
```bash
python telegram-bot-v2.py
```

## Architecture

Three core modules plus three missing modules that still need to be implemented:

### Implemented Modules

**[telegram-bot-v2.py](telegram-bot-v2.py)** — Main bot entry point (1174 lines)
- Registers Telegram command handlers (`/report`, `/top3`, `/check`, `/sector`, `/alert`, `/watchlist`, `/earnings`, `/compare`)
- Handles natural language with Korean/English ticker aliases (e.g., 엔비디아 → NVDA)
- Contains 14+ predefined theme mappings (AI, semiconductors, EV, biotech, etc.) with constituent stocks
- Persists user watchlists and alert preferences in `bot_data.json`
- Schedules daily reports via `telegram.ext.JobQueue`

**[market-monitor.py](market-monitor.py)** — Real-time market monitoring (617 lines)
- Detects market phase (premarket/regular/aftermarket/closed) and adjusts behavior accordingly
- Scans for gap moves (>3%), volume surges, and daily movers
- Calculates a custom Fear & Greed index from VIX, S&P momentum, volume, and RSI
- Monitors held positions for ATR-based stop-loss / RSI-based take-profit exit signals

**[performance-tracker.py](performance-tracker.py)** — Backtesting and analytics (607 lines)
- Initializes SQLite DB (`picks_history.db`) on import — tables for picks and daily stats
- Records daily recommendations with multi-factor scores and auto-calculates 1d/3d/5d/10d returns
- Runs backtests: screens stocks daily, selects top-N, measures hold-period returns, computes Sharpe ratio
- Grades picks S/A/B/C and identifies which factors (momentum, technical, volume, earnings, fundamental) predict returns best

### Missing Modules (need to be created)

`telegram-bot-v2.py` imports these three modules which do not yet exist:
- **advanced_screener.py** — Multi-factor stock screener (momentum, technical, volume, earnings, fundamental scoring)
- **news_fetcher.py** — Theme detection from news (uses `NEWSAPI_KEY` and BeautifulSoup)
- **ai_summarizer.py** — Claude API integration for AI-powered pick summaries (uses `ANTHROPIC_API_KEY`)

## Data Flow

```
Telegram User → telegram-bot-v2.py
                  ├── advanced_screener.py  → yfinance (OHLCV, fundamentals)
                  ├── news_fetcher.py       → NewsAPI / web scraping
                  ├── ai_summarizer.py      → Anthropic Claude API
                  ├── performance-tracker.py → picks_history.db (SQLite)
                  └── market-monitor.py     → yfinance (real-time quotes)
```

## Known Issue: File Naming

`telegram-bot-v2.py` imports using underscores (`from market_monitor import ...`, `from performance_tracker import ...`), but the actual files use hyphens (`market-monitor.py`, `performance-tracker.py`). Python cannot import hyphenated filenames with standard `import` syntax. Before the bot can run, rename:

```bash
mv market-monitor.py market_monitor.py
mv performance-tracker.py performance_tracker.py
```

## Deployment

See [gcp-deploy-guide.txt](gcp-deploy-guide.txt) for full GCP deployment (free e2-micro VM, systemd service).
