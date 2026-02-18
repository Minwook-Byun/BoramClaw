# Ollama 통합 가이드 - 완전 무료 운영

## 🎯 개요

**Ollama**는 로컬에서 LLM을 실행할 수 있는 오픈소스 도구입니다. BoramClaw는 Ollama를 통합하여 **Claude API 없이도 완전 무료로 운영**할 수 있습니다.

## 💰 비용 비교

| 모드 | 월 비용 | 장점 | 단점 |
|------|---------|------|------|
| **Claude API** | $0.70 | 고품질 응답 | 인터넷 필요, 유료 |
| **Ollama (로컬)** | **$0** | 완전 무료, 오프라인 | 로컬 리소스 사용 |
| **Hybrid** | $0-0.70 | 최상의 균형 | 설정 필요 |

## 📦 Ollama 설치

### macOS

```bash
# Homebrew로 설치
brew install ollama

# 또는 직접 다운로드
curl -fsSL https://ollama.com/install.sh | sh
```

### Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### Windows

https://ollama.com/download 에서 설치 프로그램 다운로드

## 🚀 빠른 시작

### 1. Ollama 서버 시작

```bash
# 백그라운드에서 실행
ollama serve

# 또는 별도 터미널에서
ollama serve &
```

### 2. 모델 다운로드

```bash
# 가벼운 모델 (권장 - 3GB)
ollama pull llama3.2:3b

# 또는 더 강력한 모델
ollama pull mistral:7b      # 7GB - 균형잡힌 성능
ollama pull qwen2.5:7b      # 7GB - 코딩 특화
ollama pull llama3.1:8b     # 8GB - 범용
```

### 3. BoramClaw 설정

`.env` 파일 수정:

```bash
# Ollama 전용 모드
LLM_PROVIDER=ollama
OLLAMA_API_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
```

### 4. 실행

```bash
python3 main.py

# 또는 대화형 테스트
python3 ollama_gateway.py
```

## 🔀 운영 모드

### 모드 1: Ollama 전용 (완전 무료)

```bash
# .env 설정
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.2:3b

# Claude API 키 불필요!
```

**장점**:
- ✅ 완전 무료
- ✅ 오프라인 동작
- ✅ 데이터 프라이버시 (100% 로컬)

**단점**:
- ⚠️ 응답 품질이 Claude보다 낮을 수 있음
- ⚠️ 로컬 GPU/CPU 리소스 사용
- ⚠️ 초기 모델 다운로드 필요 (3-8GB)

### 모드 2: Claude API 전용 (기존)

```bash
# .env 설정
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-xxxxx
CLAUDE_MODEL=claude-sonnet-4-5-20250929
```

**장점**:
- ✅ 최고 품질 응답
- ✅ Tool calling 완벽 지원
- ✅ 로컬 리소스 절약

**단점**:
- ⚠️ 월 $0.70 비용
- ⚠️ 인터넷 필요
- ⚠️ API 키 관리 필요

### 모드 3: Hybrid (추천) ⭐

```bash
# .env 설정
LLM_PROVIDER=hybrid
ANTHROPIC_API_KEY=sk-ant-xxxxx
OLLAMA_MODEL=llama3.2:3b
PREFER_LOCAL_LLM=1  # 1이면 Ollama 우선, 0이면 Claude 우선
```

**작동 방식**:
- **PREFER_LOCAL_LLM=1**: Ollama 먼저 시도 → 실패 시 Claude
- **PREFER_LOCAL_LLM=0**: Claude 먼저 시도 → 실패 시 Ollama

**장점**:
- ✅ 오프라인 시 자동 로컬 전환
- ✅ 간단한 작업은 무료 (Ollama)
- ✅ 복잡한 작업은 고품질 (Claude)
- ✅ 최적의 비용 효율

**예상 비용**: $0.10-0.30/월 (70-90% 절감)

## 📊 모델 추천

### 개발 비서 용도

| 모델 | 크기 | RAM | 속도 | 품질 | 용도 |
|------|------|-----|------|------|------|
| **llama3.2:3b** ⭐ | 3GB | 8GB | ⚡⚡⚡ | ⭐⭐⭐ | 일반 대화, 빠른 응답 |
| **qwen2.5:7b** | 7GB | 16GB | ⚡⚡ | ⭐⭐⭐⭐ | 코딩, 기술 문서 |
| **mistral:7b** | 7GB | 16GB | ⚡⚡ | ⭐⭐⭐⭐ | 균형잡힌 범용 |
| **llama3.1:8b** | 8GB | 16GB | ⚡⚡ | ⭐⭐⭐⭐ | 복잡한 추론 |

### 시스템 요구사항

**최소**:
- RAM: 8GB
- 디스크: 5GB
- CPU: Apple Silicon 또는 현대적인 x64

**권장**:
- RAM: 16GB
- 디스크: 20GB (여러 모델)
- GPU: Apple M1+ 또는 NVIDIA (CUDA)

## 🎯 사용 예시

### 예시 1: Ollama로 일일 리포트

```bash
# .env
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.2:3b

# 실행
python3 tools/workday_recap.py --tool-input-json '{"mode":"daily"}'

# 결과: 완전 무료!
```

### 예시 2: Hybrid로 Context 조회

```bash
# .env
LLM_PROVIDER=hybrid
PREFER_LOCAL_LLM=1

# 실행
python3 tools/get_current_context.py

# 작동:
# 1. Ollama로 먼저 시도 (무료)
# 2. 실패 시 Claude로 폴백 (유료)
```

### 예시 3: 비용 최적화 전략

```yaml
# config/rules.yaml
rules:
  # 간단한 작업은 Ollama (무료)
  - name: simple_notification
    actions:
      - type: notification
        params:
          llm_provider: ollama

  # 복잡한 분석은 Claude (유료)
  - name: weekly_analysis
    actions:
      - type: tool_call
        params:
          llm_provider: claude
          tool_name: workday_recap
```

## 🔧 Ollama 명령어

### 모델 관리

```bash
# 모델 목록 확인
ollama list

# 모델 다운로드
ollama pull llama3.2:3b

# 모델 삭제
ollama rm llama3.2:3b

# 모델 정보
ollama show llama3.2:3b
```

### 대화형 테스트

```bash
# CLI에서 직접 대화
ollama run llama3.2:3b

# 종료: /bye
```

### 성능 모니터링

```bash
# 실행 중인 모델 확인
ollama ps

# 로그 확인
ollama logs
```

## ⚡ 성능 튜닝

### GPU 가속 (NVIDIA)

```bash
# CUDA 설정 확인
ollama run llama3.2:3b --verbose

# GPU 메모리 제한
OLLAMA_GPU_MEMORY_FRACTION=0.8 ollama serve
```

### Apple Silicon 최적화

```bash
# Metal 가속 자동 활성화 (M1/M2/M3)
ollama serve

# 확인
ollama run llama3.2:3b --verbose
# → "Using Metal" 메시지 확인
```

### 동시 실행 제한

```bash
# 동시 모델 수 제한
OLLAMA_MAX_LOADED_MODELS=1 ollama serve

# 메모리 부족 시 유용
```

## 🐛 문제 해결

### 1. "Connection refused"

```bash
# Ollama 서버가 실행 중인지 확인
ps aux | grep ollama

# 재시작
killall ollama
ollama serve
```

### 2. "Out of memory"

```bash
# 더 작은 모델 사용
ollama pull llama3.2:3b  # 3GB만 필요

# 또는 메모리 정리
ollama rm <unused-model>
```

### 3. 응답이 느림

```bash
# GPU 가속 확인
ollama run llama3.2:3b --verbose

# CPU만 사용 중이면 GPU 드라이버 설치 필요
```

### 4. 한국어 응답 품질

```python
# ollama_gateway.py의 system_prompt 개선
system_prompt = """
당신은 한국어로 대화하는 AI 비서입니다.
간결하고 명확하게 답변하세요.
기술 용어는 영어 그대로 사용하되, 설명은 한국어로 하세요.
"""
```

## 📈 비용 절감 시뮬레이션

### 시나리오 1: 완전 Ollama (100% 무료)

```
월 사용:
- 일일 리포트: 30회
- Context 조회: 100회
- 규칙 평가: 8,640회 (5분마다)

Claude API 비용: $0.70
Ollama 비용: $0
절감: 100%
```

### 시나리오 2: Hybrid (90% Ollama)

```
월 사용:
- Ollama: 간단한 작업 90%
- Claude: 복잡한 분석 10%

Claude API 비용: $0.70
Hybrid 비용: $0.07
절감: 90%
```

### 시나리오 3: 전략적 분리

```
월 사용:
- Rules Engine: Ollama (무료)
- 일일 리포트: Ollama (무료)
- 주간 분석: Claude (유료, 월 4회)

Claude API 비용: $0.70
전략적 비용: $0.20
절감: 71%
```

## 🎓 고급 활용

### 커스텀 모델 파인튜닝

```bash
# Modelfile 생성
cat > Modelfile << EOF
FROM llama3.2:3b
SYSTEM """
당신은 BoramClaw의 개발 비서입니다.
Git, Shell, Browser 활동을 분석하고 요약합니다.
"""
PARAMETER temperature 0.7
PARAMETER top_p 0.9
EOF

# 커스텀 모델 생성
ollama create boramclaw-assistant -f Modelfile

# 사용
ollama run boramclaw-assistant
```

### API 직접 호출

```bash
# REST API로 호출
curl http://localhost:11434/api/generate -d '{
  "model": "llama3.2:3b",
  "prompt": "오늘 뭐 했어?",
  "stream": false
}'
```

## 🌟 Ollama vs Claude 비교

| 기능 | Ollama | Claude API |
|------|--------|------------|
| **비용** | 무료 ⭐⭐⭐⭐⭐ | $0.70/월 ⭐⭐⭐ |
| **응답 품질** | 좋음 ⭐⭐⭐ | 최고 ⭐⭐⭐⭐⭐ |
| **Tool Calling** | 제한적 ⭐⭐ | 완벽 ⭐⭐⭐⭐⭐ |
| **속도** | 빠름 ⭐⭐⭐⭐ | 빠름 ⭐⭐⭐⭐ |
| **오프라인** | ✅ 가능 | ❌ 불가 |
| **프라이버시** | 100% 로컬 ⭐⭐⭐⭐⭐ | 클라우드 ⭐⭐⭐ |
| **설정 난이도** | 중간 ⭐⭐⭐ | 쉬움 ⭐⭐⭐⭐⭐ |

## 💡 권장 사항

### 개인 개발자 (예산 중시)
→ **Ollama 전용** (100% 무료)

### 프로 개발자 (품질 중시)
→ **Hybrid** (Ollama 우선, Claude 폴백)

### 기업/팀 (최고 품질)
→ **Claude API 전용** (월 $0.70은 무시 가능)

## 📚 추가 리소스

- **Ollama 공식**: https://ollama.com
- **모델 라이브러리**: https://ollama.com/library
- **Discord**: https://discord.gg/ollama

---

**BoramClaw + Ollama = 완전 무료 개발 비서!** 🎉

Made with ❤️ by Boram
