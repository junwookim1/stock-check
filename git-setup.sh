#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 미국 주식 테마 종목 봇 — GitHub Push 스크립트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# 사전 준비:
#   1. https://github.com/new 에서 저장소 생성
#      - 이름: stock-theme-bot (또는 원하는 이름)
#      - Private 선택 (API키 보호)
#      - README 체크 해제
#
#   2. GitHub 토큰 생성 (비밀번호 대신 사용)
#      https://github.com/settings/tokens → Generate new token (classic)
#      - 권한: repo 체크
#      - 생성된 토큰 복사해두기
#
# 사용법:
#   chmod +x git_setup.sh
#   ./git_setup.sh
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -e

echo "🚀 GitHub 저장소 설정 시작"
echo ""

# ── 1. 프로젝트 폴더 확인 ──
if [ ! -f "advanced_screener.py" ]; then
    echo "❌ 프로젝트 폴더에서 실행해주세요."
    echo "   cd ~/stock-bot (또는 코드가 있는 폴더)"
    exit 1
fi

# ── 2. .gitignore 생성 ──
cat > .gitignore << 'EOF'
# 환경 변수 (API키 보호!)
.env
load_env.sh

# Python
venv/
__pycache__/
*.pyc
*.pyo

# DB
*.db
picks_history.db

# 봇 데이터
bot_data.json
daily_picks*.json

# OS
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/
*.swp
EOF

echo "✅ .gitignore 생성"

# ── 3. README 생성 ──
cat > README.md << 'EOF'
# 📊 미국 주식 테마 종목 봇

매일 미국 주식에서 테마가 되는 종목을 자동 분석하여 텔레그램으로 전송하는 봇

## 기능
- 🧠 멀티팩터 종목 스크리닝 (모멘텀/기술적/거래량/실적/펀더멘탈)
- 📰 뉴스 기반 테마 감지
- 🌅 프리마켓/장중 실시간 알림
- 📋 추천 종목 수익률 자동 추적 & 백테스트
- 📦 보유 종목 손절/익절 모니터링
- 💬 자연어 지원 (한국어)

## 텔레그램 명령어
| 명령어 | 기능 |
|--------|------|
| /report | 오늘의 테마 종목 |
| /check NVDA | 종목 상세 분석 |
| /sector AI | 섹터별 분석 |
| /morning | 장 전 체크리스트 |
| /positions | 보유 종목 현황 |
| /stats | 알고리즘 성과 |
| /backtest 60 3 | 백테스트 |

## 설치
```bash
pip install -r requirements.txt
cp .env.example .env  # API키 입력
python telegram_bot_v2.py
```

자세한 배포 가이드: GCP_DEPLOY_GUIDE.md
EOF

echo "✅ README.md 생성"

# ── 4. .env.example 생성 (키 값은 빈칸) ──
cat > .env.example << 'EOF'
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
ANTHROPIC_API_KEY=your_api_key_here
NEWSAPI_KEY=your_newsapi_key_here
USE_AI_SUMMARY=false
EOF

echo "✅ .env.example 생성"

# ── 5. Git 초기화 & 커밋 ──
git init
git add -A
git commit -m "Initial commit: 미국 주식 테마 종목 봇

- 멀티팩터 스크리닝 엔진
- 뉴스/테마 감지
- 텔레그램 대화형 봇
- 수익률 추적 & 백테스트
- 실시간 시장 모니터링
- GCP 배포 가이드"

echo ""
echo "✅ Git 커밋 완료"
echo ""

# ── 6. GitHub Push ──
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "GitHub에 Push하려면 아래를 실행하세요:"
echo ""
echo "  # GitHub 사용자 설정 (처음 한번만)"
echo "  git config --global user.name \"Your Name\""
echo "  git config --global user.email \"your@email.com\""
echo ""
echo "  # 원격 저장소 연결 & Push"
echo "  git remote add origin https://github.com/YOUR_USERNAME/stock-theme-bot.git"
echo "  git branch -M main"
echo "  git push -u origin main"
echo ""
echo "  # 비밀번호 입력 시 → GitHub 토큰을 입력하세요"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "⚠️  .env 파일은 .gitignore에 포함되어 Push되지 않습니다 (안전)"
echo ""
echo "🎉 완료! 위의 git remote / push 명령어를 실행하세요."
