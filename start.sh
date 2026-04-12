#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/bot.pid"
LOG_FILE="$SCRIPT_DIR/bot.log"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "이미 실행 중입니다. (PID: $(cat "$PID_FILE"))"
    exit 1
fi

cd "$SCRIPT_DIR"
set -a && source .env && set +a

nohup "$SCRIPT_DIR/venv/bin/python3" telegram_bot_v2.py >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "봇 시작됨 (PID: $!)"
echo "로그: tail -f $LOG_FILE"
