#!/usr/bin/env python3
"""
텔레그램 봇 리스너 - 양방향 대화
24/7 백그라운드로 실행되면서 텔레그램 메시지를 듣고 자동 응답

사용법:
  python3 telegram_bot_listener.py           # 포그라운드 실행
  python3 telegram_bot_listener.py &         # 백그라운드 실행
  python3 telegram_bot_listener.py --daemon  # 데몬 모드
"""
import sys
import os
import json
import time
import signal
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from runtime_commands import parse_deep_weekly_quick_request

# KST 타임존
KST = ZoneInfo("Asia/Seoul")

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).parent

# 대기 중인 메시지 (chat_id별로 분할된 메시지 목록)
pending_messages = {}

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(PROJECT_ROOT / "logs" / "telegram_bot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 환경 변수 로드
def load_env():
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return None, None, None

    bot_token = None
    allowed_chat_id = None
    enabled = None

    for line in env_file.read_text().split("\n"):
        line = line.strip()
        if line.startswith("TELEGRAM_BOT_TOKEN=") and not line.startswith("#"):
            bot_token = line.split("=", 1)[1].strip()
        elif line.startswith("TELEGRAM_ALLOWED_CHAT_ID=") and not line.startswith("#"):
            allowed_chat_id = line.split("=", 1)[1].strip()
        elif line.startswith("TELEGRAM_ENABLED=") and not line.startswith("#"):
            enabled = line.split("=", 1)[1].strip()

    return bot_token, allowed_chat_id, enabled


# 텔레그램 getUpdates 호출
def get_updates(bot_token: str, offset: int = 0, timeout: int = 30):
    import urllib.request
    import urllib.parse

    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params = {"offset": offset, "timeout": timeout}
    url_with_params = f"{url}?{urllib.parse.urlencode(params)}"

    try:
        with urllib.request.urlopen(url_with_params, timeout=timeout + 5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                return data.get("result", [])
    except Exception as e:
        logger.warning(f"getUpdates 오류: {e}")

    return []


# 긴 메시지 분할 (텔레그램 4096자 제한)
def split_message(text: str, max_length: int = 4000):
    """
    긴 메시지를 4096자 제한에 맞춰 분할
    max_length=4000 (안전 마진)
    """
    if len(text) <= max_length:
        return [text]

    parts = []
    lines = text.split("\n")
    current_part = []
    current_length = 0

    for line in lines:
        line_length = len(line) + 1  # \n 포함

        if current_length + line_length > max_length:
            # 현재 파트 저장
            if current_part:
                parts.append("\n".join(current_part))
            current_part = [line]
            current_length = line_length
        else:
            current_part.append(line)
            current_length += line_length

    # 마지막 파트
    if current_part:
        parts.append("\n".join(current_part))

    return parts


# 텔레그램 메시지 전송
def send_message(bot_token: str, chat_id: str, text: str):
    import urllib.request
    import urllib.parse

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("ok", False)
    except Exception as e:
        logger.warning(f"sendMessage 오류: {e}")
        return False


# 명령어 파싱
def parse_command(text: str):
    """
    텍스트에서 명령어 추출

    Returns:
        ("more", None) for "이어서" commands
        ("deep_weekly", days_back) for deep weekly retrospective
        (mode, include_diff) for daily/weekly report commands
        None for unknown commands
    """
    text_lower = text.lower()

    # "이어서" 명령 감지
    if any(keyword in text_lower for keyword in ["이어서", "더보기", "계속", "more", "next"]):
        return "more", None

    # 깊이 있는 주간 회고 감지 (runtime_commands와 동일 규칙 사용)
    deep_weekly_input = parse_deep_weekly_quick_request(text)
    if deep_weekly_input is not None:
        return "deep_weekly", int(deep_weekly_input.get("days_back", 7))

    # 모드 감지
    mode = None
    if any(keyword in text_lower for keyword in ["오늘", "today", "투데이"]):
        mode = "daily"
    elif any(keyword in text_lower for keyword in ["주", "week", "위크", "7일"]):
        mode = "weekly"
    else:
        return None

    # diff 포함 여부
    include_diff = any(keyword in text_lower for keyword in ["상세", "diff", "디프", "코드"])

    return mode, include_diff


# 리포트 실행
def run_report(mode: str, include_diff: bool):
    """workday_recap 실행 및 결과 반환"""
    tool_path = PROJECT_ROOT / "tools" / "workday_recap.py"

    cmd = [
        "python3", str(tool_path),
        "--tool-input-json", json.dumps({
            "mode": mode,
            "scan_all_repos": True,
            "include_diff": include_diff
        }),
        "--tool-context-json", "{}"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("report")
    except Exception as e:
        logger.warning(f"리포트 실행 오류: {e}")

    return None


def run_deep_weekly(days_back: int):
    """deep_weekly_retrospective 실행 및 결과 반환"""
    tool_path = PROJECT_ROOT / "tools" / "deep_weekly_retrospective.py"

    cmd = [
        "python3", str(tool_path),
        "--tool-input-json", json.dumps({"days_back": days_back}),
        "--tool-context-json", json.dumps({"workdir": str(PROJECT_ROOT)})
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if isinstance(data, dict):
                return data
            return None
        logger.warning(f"deep_weekly_retrospective 실행 실패: returncode={result.returncode}, stderr={result.stderr[:200]}")
    except Exception as e:
        logger.warning(f"deep_weekly_retrospective 실행 오류: {e}")

    return None


# 리포트 포맷팅 (텔레그램용)
def format_report(report: dict, mode: str):
    """리포트를 텔레그램 메시지로 포맷팅"""
    period = "오늘" if mode == "daily" else "이번 주"
    sections = report.get("sections", {})

    # 헤더 (KST 기준)
    now = datetime.now(KST)
    if mode == "daily":
        weekday = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]
        lines = [
            f"📊 {now.month}/{now.day}({weekday}) 작업 회고",
            f"⏰ {now.strftime('%H:%M')} KST",
            "━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
    else:
        week_start = now - timedelta(days=6)
        lines = [
            f"📊 주간 작업 회고 (Week {now.isocalendar()[1]})",
            f"📅 {week_start.strftime('%m/%d')} ~ {now.strftime('%m/%d')}",
            f"⏰ {now.strftime('%H:%M')} KST",
            "━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]

    # Git
    if "git" in sections:
        git = sections["git"]
        total_commits = git['total_commits']

        if mode == "daily":
            lines.append(f"💻 개발 활동 (오늘)")
            lines.append(f"   저장소: {git['repositories']}개 | 커밋: {total_commits}개")
            lines.append(f"   코드: +{git['insertions']}줄 -{git['deletions']}줄")
            lines.append(f"   파일: {git.get('files_changed', 0)}개 수정")
            lines.append("")

            # 오늘 커밋 상세 (최대 5개)
            for i, c in enumerate(git.get("commits", [])[:5], 1):
                repo = c.get("repo", "")
                msg = c.get("message", "")[:60]  # 60자로 늘림

                # KST 시간으로 변환
                date_str = c.get("date", "")
                if date_str and "T" in date_str:
                    try:
                        dt = datetime.fromisoformat(date_str).astimezone(KST)
                        time = dt.strftime("%H:%M")
                    except:
                        time = date_str.split("T")[1].split("+")[0][:5]
                else:
                    time = ""

                # 파일 정보
                files = c.get("files", [])
                file_count = len(files)
                lines.append(f"{i}. [{time}] {msg} ({file_count}개 파일)")

                # 파일 목록 (맥 터미널처럼 자세하게)
                if files and len(files) <= 5:
                    # 5개 이하: 전체 표시
                    for f in files:
                        status = f["status"]
                        icon = {"A": "➕", "M": "✏️", "D": "🗑️"}.get(status, "•")
                        lines.append(f"      {icon} {f['file']}")
                elif files:
                    # 6개 이상: 3개만 + "...외 N개"
                    for f in files[:3]:
                        status = f["status"]
                        icon = {"A": "➕", "M": "✏️", "D": "🗑️"}.get(status, "•")
                        lines.append(f"      {icon} {f['file']}")
                    lines.append(f"      ... 외 {len(files)-3}개")
                lines.append("")
        else:
            # Weekly: 요약 + 통계 + 인사이트
            lines.append(f"💻 개발 활동 (7일간)")
            lines.append(f"   저장소: {git['repositories']}개")
            lines.append(f"   총 커밋: {total_commits}개")

            # 생산성 분석
            avg_per_day = total_commits / 7
            if avg_per_day >= 3:
                productivity = "🔥 매우 활발"
            elif avg_per_day >= 1.5:
                productivity = "✅ 꾸준함"
            elif avg_per_day >= 0.5:
                productivity = "🐢 느림"
            else:
                productivity = "😴 거의 없음"

            lines.append(f"   하루 평균: {avg_per_day:.1f}개 ({productivity})")
            lines.append(f"   코드 변경: +{git['insertions']}줄 -{git['deletions']}줄")

            # 순증감 분석
            net_change = git['insertions'] - git['deletions']
            if net_change > 500:
                lines.append(f"   💡 대규모 기능 추가 (+{net_change}줄)")
            elif net_change < -500:
                lines.append(f"   🧹 대규모 리팩토링 (-{abs(net_change)}줄)")
            elif net_change > 0:
                lines.append(f"   📈 점진적 성장 (+{net_change}줄)")
            else:
                lines.append(f"   ⚖️ 균형잡힌 수정 ({net_change}줄)")

            lines.append("")

            # 일별 활동 분포
            lines.append("📅 일별 활동 분포:")
            commits_by_day = {}
            for c in git.get("commits", []):
                date = c.get("date", "").split("T")[0] if "T" in c.get("date", "") else ""
                if date:
                    if date not in commits_by_day:
                        commits_by_day[date] = []
                    commits_by_day[date].append(c)

            # 모든 날짜 정렬
            sorted_days = sorted(commits_by_day.items(), key=lambda x: x[0], reverse=True)
            for date, day_commits in sorted_days[:7]:  # 최근 7일
                # KST로 변환
                try:
                    dt_kst = datetime.fromisoformat(day_commits[0]["date"]).astimezone(KST)
                    day_name = dt_kst.strftime("%m/%d(%a)")
                except:
                    day_name = date

                # 막대 그래프
                bar = "▓" * min(len(day_commits), 10)
                lines.append(f"  {day_name}: {bar} {len(day_commits)}개")

            lines.append("")

            # 가장 활발했던 날 TOP 3 (상세)
            lines.append("🏆 최고 생산성 TOP 3:")
            top_days = sorted(commits_by_day.items(), key=lambda x: len(x[1]), reverse=True)[:3]
            for rank, (date, day_commits) in enumerate(top_days, 1):
                # KST로 변환
                try:
                    dt_kst = datetime.fromisoformat(day_commits[0]["date"]).astimezone(KST)
                    day_name = dt_kst.strftime("%m/%d(%a)")
                except:
                    day_name = date

                medal = ["🥇", "🥈", "🥉"][rank-1]
                lines.append(f"  {medal} {day_name}: {len(day_commits)}개 커밋")

                # 주요 커밋 2개
                for c in day_commits[:2]:
                    lines.append(f"    • {c['message'][:35]}")

        lines.append("")

    # Timeline + 생산성 패턴
    timeline = report.get("timeline", {})
    if timeline and timeline.get("peak_hour") is not None:
        peak_hour = timeline['peak_hour']
        peak_count = timeline['peak_count']
        active_hours = timeline.get("active_hours", [])

        lines.append(f"⏰ 생산성 패턴")
        lines.append(f"   피크 시간: {peak_hour:02d}:00 ({peak_count}건)")

        # 시간대별 분류
        morning = [h for h in active_hours if 6 <= h < 12]
        afternoon = [h for h in active_hours if 12 <= h < 18]
        evening = [h for h in active_hours if 18 <= h < 22]
        night = [h for h in active_hours if h >= 22 or h < 6]

        if mode == "weekly":
            work_patterns = []
            if morning:
                work_patterns.append(f"🌅 오전형 ({len(morning)}시간)")
            if afternoon:
                work_patterns.append(f"☀️ 오후형 ({len(afternoon)}시간)")
            if evening:
                work_patterns.append(f"🌆 저녁형 ({len(evening)}시간)")
            if night:
                work_patterns.append(f"🌙 야간형 ({len(night)}시간)")

            if work_patterns:
                lines.append(f"   작업 유형: {', '.join(work_patterns)}")

            # 추천
            if len(evening) + len(night) > len(morning) + len(afternoon):
                lines.append(f"   💡 야간 작업이 많네요. 수면 패턴 체크!")
            elif len(morning) > len(afternoon):
                lines.append(f"   ✨ 오전 집중형! 중요한 일은 오전에!")

        lines.append("")

    # Browser
    if "browser" in sections:
        browser = sections["browser"]
        if mode == "daily":
            lines.append(f"🌐 웹 활동 (오늘 {browser['total_visits']}개 페이지)")
            for cluster in browser.get("page_titles", [])[:3]:
                lines.append(f"   • {cluster['domain']} ({cluster['page_count']}회)")
        else:
            lines.append(f"🌐 웹 활동 (7일간 {browser['total_visits']}개 페이지)")
            lines.append(f"   하루 평균: {browser['total_visits']/7:.0f}개")
            for cluster in browser.get("page_titles", [])[:2]:
                lines.append(f"   • {cluster['domain']} ({cluster['page_count']}회)")
        lines.append("")

    # Shell
    if "shell" in sections:
        shell = sections["shell"]
        if mode == "daily":
            lines.append(f"🖥️ 터미널 (오늘 {shell['total_commands']}개 명령어)")
            for cmd in shell.get("top_commands", [])[:5]:
                lines.append(f"   • {cmd['command'][:25]} ({cmd['count']}회)")
        else:
            lines.append(f"🖥️ 터미널 (7일간 {shell['total_commands']}개 명령어)")
            lines.append(f"   하루 평균: {shell['total_commands']/7:.0f}개")
            for cmd in shell.get("top_commands", [])[:3]:
                lines.append(f"   • {cmd['command'][:25]} ({cmd['count']}회)")

    # 다음 액션 (Weekly only)
    if mode == "weekly":
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("🎯 다음 주 액션")
        lines.append("")

        # Git 기반 추천
        if "git" in sections:
            git = sections["git"]
            avg_commits = git['total_commits'] / 7
            if avg_commits < 1:
                lines.append("  • 커밋 빈도 높이기 (작은 단위로 자주)")
            elif avg_commits > 5:
                lines.append("  • 커밋 품질 체크 (너무 작게 쪼개지 않았나?)")

            # 최근 커밋 메시지에서 TODO/FIXME 감지
            recent_commits = git.get("commits", [])[:10]
            has_wip = any("WIP" in c.get("message", "").upper() or "TODO" in c.get("message", "").upper() for c in recent_commits)
            if has_wip:
                lines.append("  • WIP/TODO 커밋 정리하기")

        # Shell 기반 추천
        if "shell" in sections:
            shell = sections["shell"]
            top_cmds = shell.get("top_commands", [])
            if any(cmd["command"] in ["pytest", "npm test", "cargo test"] for cmd in top_cmds):
                lines.append("  • ✅ 테스트 습관 유지 중!")
            else:
                lines.append("  • 테스트 작성 고려하기")

        # Browser 기반 추천
        if "browser" in sections:
            browser = sections["browser"]
            if browser['total_visits'] > 300:
                lines.append("  • 웹 서핑 시간 줄이기 (집중력 향상)")

        # Timeline 기반 추천
        if timeline and timeline.get("peak_hour"):
            peak = timeline['peak_hour']
            if peak < 8 or peak > 22:
                lines.append("  • 작업 시간 정상화 (건강 우선)")

        lines.append("")
        lines.append("📚 주말 학습 추천:")

        # 프로젝트/기술 스택 감지 및 학습 추천
        learning_topics = []

        if "git" in sections:
            git = sections["git"]
            all_commits = git.get("commits", [])
            all_messages = " ".join([c.get("message", "") for c in all_commits]).lower()

            # 키워드 기반 프로젝트 감지
            if "telegram" in all_messages or "bot" in all_messages:
                learning_topics.append("  • Telegram Bot API 고급 기능 (inline buttons, webhooks)")
                learning_topics.append("  • 대화형 AI 디자인 패턴")

            if "mcp" in all_messages or "agent" in all_messages:
                learning_topics.append("  • React Agent 논문 복습 (Planning, Reasoning)")
                learning_topics.append("  • Multi-Agent 시스템 아키텍처")

            if "queue" in all_messages or "lane" in all_messages or "serialize" in all_messages:
                learning_topics.append("  • LaneQueue 패턴과 동시성 제어")
                learning_topics.append("  • Request Serialization 실무 사례")

            if "guardian" in all_messages or "watchdog" in all_messages or "4-tier" in all_messages:
                learning_topics.append("  • 4-Tier Reliability 아키텍처 심화")
                learning_topics.append("  • Self-Healing 시스템 설계")

            if "screenpipe" in all_messages or "ocr" in all_messages:
                learning_topics.append("  • Computer Vision과 OCR 최적화")
                learning_topics.append("  • 로컬 데이터 압축 알고리즘")

            # 파일 확장자 기반 기술 스택 감지
            all_files = []
            for c in all_commits:
                all_files.extend([f.get("file", "") for f in c.get("files", [])])

            file_exts = {f.split(".")[-1] for f in all_files if "." in f}

            if "py" in file_exts:
                if "async" in all_messages or "await" in all_messages:
                    learning_topics.append("  • Python asyncio 고급 패턴")

            if "ts" in file_exts or "tsx" in file_exts:
                learning_topics.append("  • TypeScript 고급 타입 시스템")

            if "rs" in file_exts:
                learning_topics.append("  • Rust 소유권과 라이프타임")

        # 학습 주제 출력 (최대 4개)
        if learning_topics:
            for topic in learning_topics[:4]:
                lines.append(topic)
        else:
            # 기본 추천
            lines.append("  • 이번 주 작업한 코드 리뷰 및 리팩토링")
            lines.append("  • 관련 기술 블로그/논문 읽기")

    # 에러
    errors = report.get("errors", [])
    if errors:
        lines.append("")
        lines.append("⚠️ 데이터 수집 이슈:")
        for err in errors[:2]:
            lines.append(f"   • {err[:40]}")

    # 푸터
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    if mode == "daily":
        lines.append("💬 '이번주'로 주간 회고 보기")
    else:
        lines.append("🚀 생산적인 한 주 되세요!")

    return "\n".join(lines)


# 메인 리스너 루프
def listen_loop():
    """메시지를 듣고 자동 응답"""
    print("\n🤖 BoramClaw 텔레그램 봇 시작\n", flush=True)

    # 환경 변수 로드
    bot_token, allowed_chat_id, enabled = load_env()

    if not bot_token:
        print("❌ TELEGRAM_BOT_TOKEN이 설정되지 않았습니다!")
        print("   .env 파일을 확인하세요.")
        sys.exit(1)

    if not allowed_chat_id:
        print("❌ TELEGRAM_ALLOWED_CHAT_ID가 설정되지 않았습니다!")
        print("   .env 파일을 확인하세요.")
        sys.exit(1)

    if enabled != "1":
        print("⚠️  TELEGRAM_ENABLED=1로 설정되지 않았습니다!")
        print("   .env 파일을 확인하세요.")
        sys.exit(1)

    print(f"✅ 봇 토큰: {bot_token[:20]}...")
    print(f"✅ Chat ID: {allowed_chat_id}")
    print(f"\n👂 메시지 수신 대기 중...\n")

    last_update_id = 0

    # 시그널 핸들러 (Ctrl+C)
    def signal_handler(sig, frame):
        print("\n\n👋 봇을 종료합니다...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # 무한 루프
    while True:
        try:
            # getUpdates 호출 (long polling)
            updates = get_updates(bot_token, offset=last_update_id + 1, timeout=30)

            for update in updates:
                last_update_id = update.get("update_id", last_update_id)

                message = update.get("message", {})
                if not message:
                    continue

                chat = message.get("chat", {})
                chat_id = str(chat.get("id", ""))
                text = message.get("text", "")
                username = chat.get("username", "Unknown")

                # 허용된 Chat ID만 처리
                if chat_id != allowed_chat_id:
                    print(f"⚠️  무시: 허용되지 않은 Chat ID {chat_id}")
                    continue

                if not text:
                    continue

                logger.info(f"📩 메시지 수신: @{username} (chat_id={chat_id}) - \"{text}\"")

                # 명령어 파싱
                parsed = parse_command(text)
                logger.info(f"   명령어 파싱 결과: {parsed}")
                if not parsed:
                    # 인식 못 한 메시지
                    send_message(bot_token, chat_id,
                        "🤔 명령어를 인식하지 못했어요.\n\n"
                        "사용 가능한 명령어:\n"
                        "• 오늘 / today\n"
                        "• 이번 주 / week\n"
                        "• 이번 주 깊이 있는 회고 작성해줘\n"
                        "• 지난 14일 깊은 회고 생성해줘\n"
                        "• 오늘 상세히 / today diff\n"
                        "• 이번 주 코드까지 / week diff\n"
                        "• 이어서 / 더보기 (긴 메시지 계속 보기)"
                    )
                    continue

                mode, command_arg = parsed

                # "이어서" 명령 처리
                if mode == "more":
                    if chat_id in pending_messages and pending_messages[chat_id]:
                        # 다음 메시지 전송
                        next_part = pending_messages[chat_id].pop(0)

                        # 마지막 메시지가 아니면 "이어서" 안내 추가
                        if pending_messages[chat_id]:
                            next_part += f"\n\n📎 이어서 보기: '이어서' 입력 ({len(pending_messages[chat_id])}개 남음)"

                        send_message(bot_token, chat_id, next_part)
                        logger.info(f"   ✅ 이어서 전송 완료 (남은 메시지: {len(pending_messages[chat_id])})\n")
                    else:
                        send_message(bot_token, chat_id, "📭 이어서 볼 내용이 없습니다.")
                    continue

                # 깊이 있는 주간 회고 처리
                if mode == "deep_weekly":
                    days_back = int(command_arg or 7)
                    send_message(bot_token, chat_id, f"⏳ 최근 {days_back}일 깊은 주간 회고 생성 중...")
                    logger.info(f"   → 깊은 회고 생성: days_back={days_back}")
                    deep_result = run_deep_weekly(days_back)
                    if not deep_result or not deep_result.get("success"):
                        logger.error("   ❌ 깊은 회고 생성 실패")
                        send_message(bot_token, chat_id, "❌ 깊은 주간 회고 생성 실패")
                        continue

                    output_file = str(deep_result.get("output_file", ""))
                    char_count = int(deep_result.get("char_count", 0) or 0)
                    summary = deep_result.get("summary", {})
                    prompts = int(summary.get("prompts", 0) or 0) if isinstance(summary, dict) else 0
                    commits = int(summary.get("commits", 0) or 0) if isinstance(summary, dict) else 0
                    sections = int(summary.get("sections", 0) or 0) if isinstance(summary, dict) else 0

                    report_body = ""
                    if output_file:
                        out_path = Path(output_file)
                        if out_path.exists():
                            try:
                                report_body = out_path.read_text(encoding="utf-8")
                            except Exception as e:
                                logger.warning(f"   ⚠️ 회고 파일 읽기 실패: {e}")

                    header_lines = [
                        "✅ 깊은 주간 회고 생성 완료",
                        f"📅 기간: 최근 {days_back}일",
                        f"📝 분량: {char_count:,}자",
                        f"📊 데이터: 프롬프트 {prompts}개 / 커밋 {commits}개 / 섹션 {sections}개",
                    ]
                    if output_file:
                        header_lines.append(f"📁 파일: {Path(output_file).name}")

                    if report_body.strip():
                        full_text = "\n".join(header_lines) + "\n\n━━━━━━━━━━━━━━━━━━━━━━\n📄 회고 본문\n\n" + report_body
                    else:
                        full_text = "\n".join(header_lines) + "\n\n⚠️ 본문을 읽지 못했습니다. 로컬 파일을 확인해주세요."

                    parts = split_message(full_text, max_length=3800)
                    if len(parts) == 1:
                        send_message(bot_token, chat_id, parts[0])
                        logger.info("   ✅ 깊은 회고 결과 전송 완료 (1개 파트)\n")
                    else:
                        first_part = parts[0] + f"\n\n📎 이어서 보기: '이어서' 입력 ({len(parts)-1}개 남음)"
                        success = send_message(bot_token, chat_id, first_part)
                        if success:
                            pending_messages[chat_id] = parts[1:]
                            logger.info(f"   ✅ 깊은 회고 첫 부분 전송 완료 (총 {len(parts)}개 파트)\n")
                        else:
                            logger.error("   ❌ 깊은 회고 첫 부분 전송 실패\n")
                    continue

                include_diff = bool(command_arg)

                period_text = "오늘" if mode == "daily" else "이번 주"

                # "처리 중..." 메시지
                send_message(bot_token, chat_id, f"⏳ {period_text} 리포트 생성 중...")

                # 리포트 실행
                logger.info(f"   → 리포트 생성: mode={mode}, diff={include_diff}")
                report = run_report(mode, include_diff)

                if not report:
                    logger.error("   ❌ 리포트 생성 실패")
                    send_message(bot_token, chat_id, "❌ 리포트 생성 실패")
                    continue

                # 결과 포맷팅
                formatted = format_report(report, mode)
                logger.info(f"   → 메시지 길이: {len(formatted)} 문자")

                # 메시지 분할 (4096자 제한)
                parts = split_message(formatted, max_length=4000)

                if len(parts) == 1:
                    # 짧은 메시지: 한 번에 전송
                    success = send_message(bot_token, chat_id, parts[0])
                    if success:
                        logger.info(f"   ✅ 응답 전송 완료\n")
                    else:
                        logger.error(f"   ❌ 응답 전송 실패\n")
                else:
                    # 긴 메시지: 첫 부분만 전송, 나머지는 pending에 저장
                    first_part = parts[0] + f"\n\n📎 이어서 보기: '이어서' 입력 ({len(parts)-1}개 남음)"
                    success = send_message(bot_token, chat_id, first_part)

                    if success:
                        pending_messages[chat_id] = parts[1:]
                        logger.info(f"   ✅ 첫 부분 전송 완료 (총 {len(parts)}개 파트)\n")
                    else:
                        logger.error(f"   ❌ 응답 전송 실패\n")

        except Exception as e:
            print(f"⚠️  예외 발생: {e}")
            time.sleep(5)  # 에러 시 5초 대기


def main():
    import argparse

    parser = argparse.ArgumentParser(description="텔레그램 봇 리스너")
    parser.add_argument("--daemon", action="store_true", help="데몬 모드로 실행")
    args = parser.parse_args()

    if args.daemon:
        # TODO: 실제 데몬화 (nohup, systemd 등)
        print("데몬 모드는 아직 구현되지 않았습니다.")
        print("대신 백그라운드로 실행하세요: python3 telegram_bot_listener.py &")
        sys.exit(1)

    listen_loop()


if __name__ == "__main__":
    main()
