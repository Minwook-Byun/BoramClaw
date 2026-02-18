#!/usr/bin/env python3
"""
context_engine.py
Context Engine - 실시간 맥락 통합 시스템

4개 데이터 소스를 통합하여 현재 작업 맥락을 파악:
- Screen Activity (screenpipe): 최근 활성 앱, 화면 내용
- Git Activity: 최근 커밋, 변경된 파일
- Shell Activity: 최근 명령어
- Browser Activity: 최근 웹 검색

기능:
1. Current Context Assembly: 현재 작업 중인 내용 자동 파악
2. Work Session Detection: 작업 세션 자동 감지
3. Context Switching Detection: 작업 전환 감지
4. Intelligent Summarization: 지능적 요약
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Optional
from collections import Counter

# 툴 모듈 import
sys.path.insert(0, str(Path(__file__).parent / "tools"))
from screen_search import run as screen_search_run
from git_daily_summary import run as git_summary_run
from shell_pattern_analyzer import run as shell_analyzer_run
from browser_research_digest import run as browser_digest_run


class ContextEngine:
    """실시간 맥락 통합 엔진"""

    def __init__(self, lookback_minutes: int = 30):
        """
        Args:
            lookback_minutes: 최근 몇 분간의 활동을 조회할지 (기본 30분)
        """
        self.lookback_minutes = lookback_minutes
        self.context: dict[str, Any] = {}

    def get_current_context(
        self,
        repo_path: str = ".",
        include_screen: bool = False,
        screen_keyword: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        현재 작업 맥락 조회

        Args:
            repo_path: Git 저장소 경로
            include_screen: Screen 활동 포함 여부
            screen_keyword: Screen 검색 키워드 (선택)

        Returns:
            통합 컨텍스트 dict
        """
        context = {
            "timestamp": datetime.now().isoformat(),
            "lookback_minutes": self.lookback_minutes,
            "activities": {},
            "summary": {},
            "errors": [],
        }

        # 1. Git Activity (최근 변경 파일)
        try:
            git_result = git_summary_run(
                {"repo_path": repo_path, "days": 1},
                {}
            )
            if git_result.get("ok"):
                recent_commits = git_result.get("recent_commits", [])
                if recent_commits:
                    # 최근 커밋의 변경 파일 추출
                    changed_files = []
                    for commit in recent_commits[:3]:  # 최근 3개 커밋
                        files = commit.get("files_changed", [])
                        changed_files.extend(files)

                    context["activities"]["git"] = {
                        "recent_commits": len(recent_commits),
                        "changed_files": list(set(changed_files))[:10],
                        "latest_commit_message": recent_commits[0].get("message", "") if recent_commits else "",
                        "latest_commit_time": recent_commits[0].get("date", "") if recent_commits else "",
                    }
        except Exception as e:
            context["errors"].append(f"Git 활동 조회 실패: {str(e)}")

        # 2. Shell Activity (최근 명령어)
        try:
            shell_result = shell_analyzer_run(
                {"days": 1},
                {}
            )
            if shell_result.get("ok"):
                all_commands = shell_result.get("all_commands", [])
                # 최근 N분 이내 명령어만 필터링
                cutoff_time = datetime.now().timestamp() - (self.lookback_minutes * 60)
                recent_commands = [
                    cmd for cmd in all_commands
                    if cmd.get("timestamp", 0) >= cutoff_time
                ]

                if recent_commands:
                    # 최근 명령어 패턴 분석
                    command_names = [cmd.get("command", "").split()[0] for cmd in recent_commands]
                    command_counts = Counter(command_names)

                    context["activities"]["shell"] = {
                        "recent_commands_count": len(recent_commands),
                        "top_commands": [
                            {"command": cmd, "count": count}
                            for cmd, count in command_counts.most_common(5)
                        ],
                        "latest_commands": [
                            cmd.get("command", "") for cmd in recent_commands[-5:]
                        ],
                    }
        except Exception as e:
            context["errors"].append(f"Shell 활동 조회 실패: {str(e)}")

        # 3. Browser Activity (최근 웹 검색)
        try:
            hours_back = max(1, self.lookback_minutes // 60)
            browser_result = browser_digest_run(
                {"hours_back": hours_back},
                {}
            )
            if browser_result.get("ok"):
                sessions = browser_result.get("sessions", [])
                if sessions:
                    latest_session = sessions[-1]  # 가장 최근 세션
                    context["activities"]["browser"] = {
                        "session_count": len(sessions),
                        "latest_session_pages": len(latest_session.get("pages", [])),
                        "latest_session_domains": list(set(
                            page.get("domain", "") for page in latest_session.get("pages", [])
                        ))[:5],
                        "latest_page_title": latest_session.get("pages", [{}])[-1].get("title", "") if latest_session.get("pages") else "",
                    }
        except Exception as e:
            context["errors"].append(f"Browser 활동 조회 실패: {str(e)}")

        # 4. Screen Activity (선택적)
        if include_screen and screen_keyword:
            try:
                screen_result = screen_search_run(
                    {
                        "query": screen_keyword,
                        "content_type": "ocr",
                        "hours_back": hours_back,
                        "limit": 10,
                    },
                    {}
                )
                if screen_result.get("ok"):
                    results = screen_result.get("results", [])
                    if results:
                        apps = Counter(r.get("app_name", "Unknown") for r in results)
                        context["activities"]["screen"] = {
                            "keyword": screen_keyword,
                            "captures": len(results),
                            "top_apps": [
                                {"app": app, "count": count}
                                for app, count in apps.most_common(3)
                            ],
                        }
            except Exception as e:
                context["errors"].append(f"Screen 활동 조회 실패: {str(e)}")

        # Summary 생성
        context["summary"] = self._generate_summary(context)

        return context

    def _generate_summary(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        컨텍스트에서 지능적 요약 생성

        Args:
            context: 통합 컨텍스트

        Returns:
            요약 dict
        """
        summary = {
            "is_active": False,
            "primary_activity": "unknown",
            "confidence": 0.0,
            "description": "",
        }

        activities = context.get("activities", {})

        # 활성 여부 판단
        has_recent_activity = any([
            activities.get("git"),
            activities.get("shell"),
            activities.get("browser"),
            activities.get("screen"),
        ])
        summary["is_active"] = has_recent_activity

        if not has_recent_activity:
            summary["description"] = f"최근 {context['lookback_minutes']}분간 활동 없음"
            return summary

        # 주요 활동 판단 (우선순위: Git > Shell > Browser)
        if activities.get("git"):
            git_info = activities["git"]
            if git_info.get("recent_commits", 0) > 0:
                summary["primary_activity"] = "coding"
                summary["confidence"] = 0.9
                latest_msg = git_info.get("latest_commit_message", "")
                summary["description"] = f"코딩 중: {latest_msg[:50]}..."
                return summary

        if activities.get("shell"):
            shell_info = activities["shell"]
            top_commands = shell_info.get("top_commands", [])
            if top_commands:
                top_cmd = top_commands[0]["command"]
                if top_cmd in {"python3", "python", "node", "npm", "cargo", "go"}:
                    summary["primary_activity"] = "development"
                    summary["confidence"] = 0.8
                    summary["description"] = f"개발 작업 중: {top_cmd} 명령어 실행"
                elif top_cmd in {"git", "gh"}:
                    summary["primary_activity"] = "version_control"
                    summary["confidence"] = 0.8
                    summary["description"] = "Git 작업 중"
                elif top_cmd in {"vim", "code", "nano", "emacs"}:
                    summary["primary_activity"] = "editing"
                    summary["confidence"] = 0.8
                    summary["description"] = f"{top_cmd}로 파일 편집 중"
                else:
                    summary["primary_activity"] = "terminal"
                    summary["confidence"] = 0.6
                    summary["description"] = f"터미널 작업 중: {top_cmd}"
                return summary

        if activities.get("browser"):
            browser_info = activities["browser"]
            domains = browser_info.get("latest_session_domains", [])
            if domains:
                # 도메인 패턴으로 활동 유형 추론
                research_domains = {"github.com", "stackoverflow.com", "arxiv.org", "scholar.google.com"}
                if any(d in research_domains for d in domains):
                    summary["primary_activity"] = "research"
                    summary["confidence"] = 0.7
                    summary["description"] = f"리서치 중: {', '.join(domains[:2])}"
                else:
                    summary["primary_activity"] = "browsing"
                    summary["confidence"] = 0.5
                    latest_title = browser_info.get("latest_page_title", "")
                    summary["description"] = f"웹 브라우징 중: {latest_title[:50]}..."
                return summary

        summary["description"] = "활동 중 (유형 미상)"
        summary["confidence"] = 0.3
        return summary

    def detect_work_session(
        self,
        repo_path: str = ".",
        min_duration_minutes: int = 10,
    ) -> dict[str, Any]:
        """
        작업 세션 감지

        Args:
            repo_path: Git 저장소 경로
            min_duration_minutes: 최소 세션 지속 시간 (분)

        Returns:
            세션 정보 dict
        """
        session = {
            "is_session_active": False,
            "start_time": None,
            "duration_minutes": 0,
            "activity_count": 0,
            "session_type": "unknown",
        }

        # Shell 명령어 기록으로 세션 감지
        try:
            shell_result = shell_analyzer_run(
                {"days": 1},
                {}
            )
            if shell_result.get("ok"):
                all_commands = shell_result.get("all_commands", [])
                if all_commands:
                    # 가장 오래된 명령어 찾기
                    oldest_cmd = min(all_commands, key=lambda x: x.get("timestamp", float("inf")))
                    newest_cmd = max(all_commands, key=lambda x: x.get("timestamp", 0))

                    oldest_time = oldest_cmd.get("timestamp", 0)
                    newest_time = newest_cmd.get("timestamp", 0)

                    duration_seconds = newest_time - oldest_time
                    duration_minutes = duration_seconds / 60

                    if duration_minutes >= min_duration_minutes:
                        session["is_session_active"] = True
                        session["start_time"] = datetime.fromtimestamp(oldest_time).isoformat()
                        session["duration_minutes"] = int(duration_minutes)
                        session["activity_count"] = len(all_commands)

                        # 세션 타입 추론
                        command_names = [cmd.get("command", "").split()[0] for cmd in all_commands]
                        command_counts = Counter(command_names)
                        top_cmd = command_counts.most_common(1)[0][0] if command_counts else ""

                        if top_cmd in {"python3", "python", "node", "npm", "cargo", "go"}:
                            session["session_type"] = "development"
                        elif top_cmd in {"git", "gh"}:
                            session["session_type"] = "version_control"
                        else:
                            session["session_type"] = "general"
        except Exception:
            pass

        return session


def format_context_display(context: dict[str, Any]) -> str:
    """
    컨텍스트를 사용자 친화적으로 포맷팅

    Args:
        context: get_current_context()의 결과

    Returns:
        포맷된 문자열
    """
    lines = [
        f"🔍 현재 작업 맥락 (최근 {context['lookback_minutes']}분)",
        f"조회 시간: {context['timestamp']}",
        "",
    ]

    summary = context.get("summary", {})
    if summary.get("is_active"):
        lines.append(f"✨ {summary['description']}")
        lines.append(f"신뢰도: {summary['confidence']:.0%}")
        lines.append("")
    else:
        lines.append(f"💤 {summary.get('description', '활동 없음')}")
        lines.append("")
        return "\n".join(lines)

    activities = context.get("activities", {})

    # Git 활동
    if "git" in activities:
        git = activities["git"]
        lines.append("### 📝 Git 활동")
        lines.append(f"- 최근 커밋: {git['recent_commits']}개")
        if git.get("latest_commit_message"):
            lines.append(f"- 최근 커밋 메시지: {git['latest_commit_message']}")
        if git.get("changed_files"):
            lines.append(f"- 변경된 파일: {', '.join(git['changed_files'][:3])}")
        lines.append("")

    # Shell 활동
    if "shell" in activities:
        shell = activities["shell"]
        lines.append("### 💻 Shell 활동")
        lines.append(f"- 최근 명령어 실행: {shell['recent_commands_count']}개")
        top_cmds = shell.get("top_commands", [])
        if top_cmds:
            lines.append("- 자주 실행한 명령어:")
            for cmd_info in top_cmds[:3]:
                lines.append(f"  • {cmd_info['command']}: {cmd_info['count']}회")
        latest_cmds = shell.get("latest_commands", [])
        if latest_cmds:
            lines.append("- 최근 명령어:")
            for cmd in latest_cmds[-3:]:
                lines.append(f"  • {cmd}")
        lines.append("")

    # Browser 활동
    if "browser" in activities:
        browser = activities["browser"]
        lines.append("### 🌐 Browser 활동")
        lines.append(f"- 세션: {browser['session_count']}개")
        if browser.get("latest_page_title"):
            lines.append(f"- 최근 페이지: {browser['latest_page_title']}")
        domains = browser.get("latest_session_domains", [])
        if domains:
            lines.append(f"- 방문 도메인: {', '.join(domains)}")
        lines.append("")

    # Screen 활동
    if "screen" in activities:
        screen = activities["screen"]
        lines.append("### 🖥️  Screen 활동")
        lines.append(f"- 검색 키워드: '{screen['keyword']}'")
        lines.append(f"- 캡처: {screen['captures']}개")
        top_apps = screen.get("top_apps", [])
        if top_apps:
            lines.append("- 자주 사용한 앱:")
            for app_info in top_apps:
                lines.append(f"  • {app_info['app']}: {app_info['count']}회")
        lines.append("")

    # 에러
    errors = context.get("errors", [])
    if errors:
        lines.append("### ⚠️  경고")
        for err in errors:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # 테스트
    engine = ContextEngine(lookback_minutes=30)
    context = engine.get_current_context()
    print(format_context_display(context))

    print("\n" + "="*60 + "\n")

    session = engine.detect_work_session()
    if session["is_session_active"]:
        print(f"🔥 활성 작업 세션 감지")
        print(f"- 시작 시간: {session['start_time']}")
        print(f"- 지속 시간: {session['duration_minutes']}분")
        print(f"- 활동 수: {session['activity_count']}개")
        print(f"- 세션 유형: {session['session_type']}")
    else:
        print("💤 활성 세션 없음")
