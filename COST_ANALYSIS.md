# BoramClaw 비용 분석 (Cost Analysis)

## 개요

BoramClaw는 **완전 로컬 실행** 시스템으로, 대부분의 기능이 **무료**로 동작합니다.

## 💰 비용 구조

### 1. 무료 구성요소 (Free)

**Phase 1-5 핵심 기능 - 100% 로컬**
- ✅ **Observer Layer** (screenpipe, git, shell, browser)
  - 비용: **$0/월**
  - 모든 데이터가 로컬에서 수집
  - 외부 API 호출 없음

- ✅ **Analyzer Layer** (workday_recap, daily_recap_notifier)
  - 비용: **$0/월**
  - Python으로 로컬 데이터 분석
  - 외부 API 호출 없음

- ✅ **Context Engine** (실시간 맥락 통합)
  - 비용: **$0/월**
  - 로컬 데이터만 사용
  - 외부 API 호출 없음

- ✅ **Rules Engine** (자동 액션)
  - 비용: **$0/월**
  - YAML 규칙 파일 기반
  - 외부 API 호출 없음

- ✅ **MCP Server** (Claude Desktop 연동)
  - 비용: **$0/월**
  - 로컬 stdio 통신
  - 외부 API 호출 없음

**총 핵심 기능 비용: $0/월**

### 2. 유료 구성요소 (Optional)

**2.1. Claude API (Anthropic)**

Claude Desktop을 통해 대화할 때만 발생 (선택적)

**가격 (2024년 기준 - Claude Sonnet 3.5/4):**
- Input: $3 / 1M tokens
- Output: $15 / 1M tokens

**토큰 사용량 추정:**

| 작업 | Input | Output | 총 토큰 | 비용/회 |
|------|-------|--------|---------|---------|
| 일일 리포트 조회 (/today) | 500 | 1,000 | 1,500 | $0.0165 |
| 주간 리포트 조회 (/week) | 2,000 | 3,000 | 5,000 | $0.051 |
| Context 조회 (/context) | 300 | 500 | 800 | $0.0084 |
| 간단한 질문 | 100 | 200 | 300 | $0.0033 |

**월간 예상 비용 (Claude Desktop 사용 시):**

| 시나리오 | 사용량 | 월 비용 |
|---------|-------|---------|
| 경량 사용 | /today 10회/월 | $0.17 |
| 중간 사용 | /today 30회 + /week 4회 | $0.70 |
| 헤비 사용 | /today 30회 + /week 4회 + /context 100회 | $1.54 |
| 대화형 사용 | 위 + 일반 대화 200회 | $2.20 |

**2.2. screenpipe (선택적)**

- **무료 오픈소스**
- 로컬 실행
- 비용: $0/월
- 단, CPU/저장공간 사용

**2.3. 클라우드 저장소 (선택적)**

리포트를 클라우드에 백업하는 경우:
- Google Drive: 15GB 무료
- Dropbox: 2GB 무료
- iCloud: 5GB 무료

예상 저장공간:
- 일일 리포트: ~10KB/일 = 300KB/월 = 3.6MB/년
- 주간 리포트: ~50KB/주 = 200KB/월 = 2.4MB/년

**총 저장공간: ~10MB/년 → 무료 티어로 충분**

## 📊 시나리오별 월간 비용 요약

### 시나리오 1: CLI 전용 (100% 무료)

**사용 방식:**
- CLI에서 `/today`, `/week`, `/context` 직접 실행
- Rules Engine 자동 알림
- 로컬 파일 저장

**월간 비용: $0**

### 시나리오 2: Claude Desktop 연동 - 경량

**사용 방식:**
- 일주일에 2-3번 Claude Desktop에서 리포트 조회
- 나머지는 자동화

**월간 사용량:**
- /today: 10회
- /week: 2회
- /context: 5회

**월간 비용: $0.30**

### 시나리오 3: Claude Desktop 연동 - 헤비

**사용 방식:**
- 매일 Claude Desktop에서 작업
- 자주 리포트 조회
- 일반 대화도 활발

**월간 사용량:**
- /today: 30회
- /week: 4회
- /context: 100회
- 일반 대화: 200회

**월간 비용: $2.20**

### 시나리오 4: 24/7 데몬 + 자동화 (거의 무료)

**사용 방식:**
- BoramClaw 데몬 모드 24/7 실행
- Rules Engine 자동 알림
- 매일 21:00 자동 리포트
- Claude Desktop은 가끔만 사용

**월간 비용: $0.50 (Claude Desktop 가끔 사용)**

## 💡 비용 절감 팁

### 1. CLI 우선 사용

```bash
# CLI로 직접 실행 → 무료
python3 tools/get_current_context.py
python3 tools/workday_recap.py --tool-input-json '{"mode":"daily"}'

# Claude Desktop으로 질문 → 유료
"오늘 무엇 작업했어?"
```

### 2. 자동화 활용

```yaml
# Rules Engine으로 자동 리포트 → 무료
rules:
  - name: daily_recap_9pm
    trigger:
      type: time_based
      schedule:
        time: "21:00"
    actions:
      - type: tool_call
        params:
          tool_name: "daily_recap_notifier"
```

### 3. 로컬 캐싱

- 일일 리포트를 파일로 저장 (`logs/summaries/daily/`)
- 필요할 때 파일 직접 읽기 → 무료
- Claude에 물어보기 → 유료

### 4. 배치 처리

```bash
# 여러 리포트를 한 번에 생성
python3 tools/workday_recap.py --tool-input-json '{"mode":"daily"}' > today.txt
python3 tools/workday_recap.py --tool-input-json '{"mode":"weekly"}' > week.txt

# 나중에 필요할 때 읽기
cat today.txt
```

## 🔋 시스템 리소스 비용

### CPU 사용량

**idle 상태:**
- screenpipe: ~5% CPU (0.2 FPS 설정 시)
- BoramClaw 데몬: ~0.1% CPU

**active 상태 (리포트 생성 중):**
- 일시적 10-20% CPU (1-2초)

### 메모리 사용량

- screenpipe: ~200MB
- BoramClaw: ~50MB
- Python 툴: ~30MB (실행 시)

**총 메모리: ~280MB**

### 저장공간

**screenpipe:**
- OCR 데이터: ~1GB/월 (0.2 FPS 기준)
- 설정 가능 (retention policy)

**BoramClaw:**
- 리포트 파일: ~10MB/년
- 로그 파일: ~50MB/년 (rotation)

**총 저장공간: ~1.5GB/년**

### 전력 소비

- MacBook Pro 기준: ~5W 추가 전력
- 월간 전기료: ~$0.50 (한국 기준)

## 📈 비용 비교: BoramClaw vs 대안

| 서비스 | 월 비용 | 기능 | 프라이버시 |
|--------|---------|------|-----------|
| **BoramClaw (CLI)** | **$0** | ⭐⭐⭐⭐⭐ | ✅ 완전 로컬 |
| **BoramClaw (Claude Desktop)** | **$0.30-$2** | ⭐⭐⭐⭐⭐ | ✅ 완전 로컬 |
| GitHub Copilot | $10 | ⭐⭐⭐ | ❌ 클라우드 |
| Notion AI | $8-$10 | ⭐⭐⭐ | ❌ 클라우드 |
| Granola AI | $10-$20 | ⭐⭐⭐⭐ | ❌ 클라우드 |
| ActivityWatch | $0 | ⭐⭐ | ✅ 로컬 |
| RescueTime | $12 | ⭐⭐⭐ | ❌ 클라우드 |

## 🎯 권장 사용 방식

**최적의 비용 효율:**

1. **기본 자동화 설정** ($0/월)
   - Rules Engine으로 자동 알림
   - 매일 21:00 자동 리포트
   - 로컬 파일로 저장

2. **필요할 때만 Claude Desktop** ($0.50/월)
   - 복잡한 질문
   - 통찰이 필요한 경우
   - 대화형 탐색

3. **주간 리뷰** ($0.20/월)
   - 매주 금요일 `/week` 실행
   - 한 주 회고

**총 예상 비용: $0.70/월**

## 📊 ROI (투자 대비 효과)

**시간 절약:**
- 수동 로그 확인: 30분/일 → 자동화: 0분
- 월 절약 시간: ~15시간
- 시급 $50 기준: $750/월 가치

**생산성 향상:**
- 커밋 알림으로 작업 손실 방지
- 집중 시간 추적으로 효율 증가
- 자동 회고로 개선 가능

**ROI: $750 / $0.70 = 1,070배**

## 🔮 미래 비용 전망

**예상 변화:**
- Claude API 가격 하락 가능 (경쟁 심화)
- 로컬 LLM 통합 → 완전 무료 가능
- 추가 기능 (Phase 6-10) → 여전히 로컬 우선

**장기 전략:**
- 핵심은 항상 로컬 무료
- 클라우드는 선택사항
- Privacy-First 철학 유지

## 💰 최종 요약

**BoramClaw 월간 비용:**
- **CLI 전용**: $0
- **Claude Desktop 경량**: $0.30
- **Claude Desktop 헤비**: $2.20
- **평균 사용자**: $0.70

**비교:**
- ☕ 스타벅스 커피 1잔: $5
- 🎬 넷플릭스: $15.49
- 💼 GitHub Copilot: $10
- **🤖 BoramClaw: $0.70** ✨

**결론: 커피 1/7잔 가격으로 AI 개인 비서를 얻을 수 있습니다!**
