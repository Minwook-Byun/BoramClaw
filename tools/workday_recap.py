#!/usr/bin/env python3
"""
workday_recap.py
하루/주간 개발 활동 통합 리포트 생성 툴

5개 데이터 소스 통합:
- screenpipe (화면 활동)
- git (커밋 이력)
- shell (명령어 패턴)
- browser (연구 활동)
- prompts (Claude Code, Codex, BoramClaw 등 프롬프트)
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any

# 다른 툴들 import
sys.path.insert(0, str(Path(__file__).parent))
from screen_search import run as screen_search_run
from git_daily_summary import run as git_summary_run
from shell_pattern_analyzer import run as shell_analyzer_run
from browser_research_digest import run as browser_digest_run
from universal_prompt_collector import run as prompt_collector_run
from study_tracker import run as study_tracker_run, format_report_markdown as study_format_md

__version__ = "2.2.0"

TOOL_SPEC = {
    "name": "workday_recap",
    "description": """하루 또는 주간 개발 활동을 통합 리포트로 생성합니다.

    사용자가 다음과 같은 질문을 하면 이 도구를 사용하세요:
    - "어제/오늘 뭐 했어?", "오늘 작업", "daily report"
    - "이번 주 뭐 했어?", "주간 리포트", "weekly summary"
    - "코드 변경 보여줘", "diff 포함", "상세 리포트"
    - "시간대별로", "타임라인", "언제 일했어?"

    자동으로 다음 정보를 포함:
    - Git 커밋 (메시지, 변경 파일, diff)
    - 브라우저 활동 (페이지 제목, 도메인)
    - 터미널 명령어 통계
    - 시간대별 타임라인 (피크 시간 분석)
    - 작업 패턴 (오전/오후/저녁/밤)
    - 프롬프트 히스토리 (Claude Code, Codex, BoramClaw 등)

    모든 Git 저장소를 자동으로 스캔합니다.
    - ML 학습 진도 체크 (16주 커리큘럼 자동 추적)""",
    "version": "2.2.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["daily", "weekly"],
                "description": "daily=오늘, weekly=최근 7일",
            },
            "scan_all_repos": {
                "type": "boolean",
                "description": "홈 디렉토리의 모든 Git 저장소를 스캔할지 여부 (기본값: true)",
            },
            "repo_path": {
                "type": "string",
                "description": "특정 Git 리포지토리 경로 (scan_all_repos=false일 때만)",
            },
            "focus_keyword": {
                "type": "string",
                "description": "화면 검색 키워드 (선택, 입력 시 해당 키워드 관련 활동만)",
            },
            "include_diff": {
                "type": "boolean",
                "description": "Git 커밋의 실제 코드 변경 내역(diff)도 포함할지 여부 (기본값: false)",
            },
        },
        "required": ["mode"],
    },
}


def run(input_data: dict, context: dict) -> Any:
    """
    통합 리포트 생성

    Args:
        input_data: {"mode": "daily"|"weekly", "scan_all_repos": true, "focus_keyword": "..."}
        context: 실행 컨텍스트

    Returns:
        통합 리포트 dict
    """
    mode = input_data.get("mode", "daily")
    scan_all_repos = input_data.get("scan_all_repos", True)
    repo_path = input_data.get("repo_path", ".")
    focus_keyword = input_data.get("focus_keyword")
    include_diff = input_data.get("include_diff", False)

    days = 1 if mode == "daily" else 7
    hours_back = 24 if mode == "daily" else 168

    report = {
        "mode": mode,
        "generated_at": datetime.now().isoformat(),
        "period": f"최근 {days}일",
        "sections": {},
        "errors": [],
    }

    # 1. Screen Activity (screenpipe) - focus_keyword가 있을 때만 실행
    if focus_keyword:
        try:
            screen_result = screen_search_run(
                {"query": focus_keyword, "content_type": "ocr", "hours_back": hours_back, "limit": 50},
                context
            )

            if screen_result.get("ok") is True:
                results = screen_result.get("results", [])
                apps = {}
                for r in results:
                    app = r.get("app_name", "Unknown")
                    apps[app] = apps.get(app, 0) + 1

                report["sections"]["screen"] = {
                    "total_captures": len(results),
                    "top_apps": sorted(apps.items(), key=lambda x: x[1], reverse=True)[:5],
                    "focus_keyword": focus_keyword,
                }
            else:
                report["errors"].append(f"screen_search 실패: {screen_result.get('error')}")
        except Exception as e:
            report["errors"].append(f"screen_search 예외: {str(e)}")

    # 2. Git Activity
    try:
        if scan_all_repos:
            # 홈 디렉토리의 모든 Git 저장소 찾기 (강건한 버전)
            import subprocess
            home = Path.home()

            # 캐시된 저장소 목록 사용 (성능 향상)
            cache_file = home / ".boramclaw_repos_cache"
            repo_paths = []

            try:
                # find 명령어 실행 (타임아웃 15초)
                result = subprocess.run(
                    ["find", str(home), "-maxdepth", "3", "-name", ".git", "-type", "d"],
                    capture_output=True, text=True, timeout=15,
                    stderr=subprocess.DEVNULL  # 에러 무시
                )
                if result.returncode == 0:
                    repo_paths = [Path(line).parent for line in result.stdout.strip().split("\n") if line]
                    # 캐시 저장
                    if repo_paths:
                        cache_file.write_text("\n".join(str(p) for p in repo_paths))
            except subprocess.TimeoutExpired:
                # 타임아웃 시 캐시 사용
                if cache_file.exists():
                    repo_paths = [Path(line) for line in cache_file.read_text().strip().split("\n") if line]
                else:
                    # 캐시도 없으면 현재 디렉토리만
                    repo_paths = [Path(".")]
            except Exception:
                # 기타 에러 시 캐시 또는 현재 디렉토리
                if cache_file.exists():
                    repo_paths = [Path(line) for line in cache_file.read_text().strip().split("\n") if line]
                else:
                    repo_paths = [Path(".")]
        else:
            repo_paths = [Path(repo_path)]

        all_commits = []
        total_files = 0
        total_ins = 0
        total_dels = 0

        for rpath in repo_paths:
            git_result = git_summary_run(
                {"repo_path": str(rpath), "days": days, "include_diff": include_diff},
                context
            )
            if git_result.get("ok") is True:
                commits = git_result.get("commits", [])
                for c in commits:
                    c["repo"] = rpath.name  # 저장소 이름 추가
                all_commits.extend(commits)
                total_files += git_result.get("files_changed", 0)
                total_ins += git_result.get("insertions", 0)
                total_dels += git_result.get("deletions", 0)

        if all_commits:
            # 시간순 정렬
            all_commits.sort(key=lambda x: x.get("date", ""), reverse=True)

            # 시간대별 분포 계산
            hour_dist = {}
            for c in all_commits:
                try:
                    dt = datetime.fromisoformat(c["date"])
                    hour = dt.hour
                    hour_dist[hour] = hour_dist.get(hour, 0) + 1
                except Exception:
                    pass

            report["sections"]["git"] = {
                "total_commits": len(all_commits),
                "commits": all_commits[:20],  # 최근 20개만
                "files_changed": total_files,
                "insertions": total_ins,
                "deletions": total_dels,
                "repositories": len([r for r in repo_paths if any(c["repo"] == r.name for c in all_commits)]),
                "time_distribution": hour_dist,
            }
    except Exception as e:
        report["errors"].append(f"git_daily_summary 예외: {str(e)}")

    # 3. Shell Patterns
    try:
        shell_result = shell_analyzer_run(
            {"days": days},
            context
        )

        if shell_result.get("ok") is True:
            report["sections"]["shell"] = {
                "total_commands": shell_result.get("total_commands", 0),
                "unique_commands": shell_result.get("unique_commands", 0),
                "top_commands": shell_result.get("top_commands", [])[:10],
                "alias_suggestions": shell_result.get("alias_suggestions", [])[:5],
            }
        else:
            report["errors"].append(f"shell_pattern_analyzer 실패: {shell_result.get('error')}")
    except Exception as e:
        report["errors"].append(f"shell_pattern_analyzer 예외: {str(e)}")

    # 4. Browser Research
    try:
        browser_result = browser_digest_run(
            {"hours": hours_back, "min_cluster_size": 1},
            context
        )

        if browser_result.get("ok") is True:
            domain_clusters = browser_result.get("domain_clusters", [])
            time_sessions = browser_result.get("time_sessions", [])

            # 시간대별 분포 계산
            hour_dist = {}
            for session in time_sessions:
                try:
                    dt = datetime.fromisoformat(session["start_time"])
                    hour = dt.hour
                    hour_dist[hour] = hour_dist.get(hour, 0) + session.get("page_count", 1)
                except Exception:
                    pass

            report["sections"]["browser"] = {
                "total_visits": browser_result.get("total_pages", 0),
                "unique_domains": browser_result.get("unique_domains", 0),
                "top_domains": browser_result.get("top_domains", [])[:10],
                "page_titles": domain_clusters[:5],  # 상위 5개 도메인의 페이지 제목
                "sessions": time_sessions[:10],  # 최근 10개 세션
                "time_distribution": hour_dist,
            }
        else:
            report["errors"].append(f"browser_research_digest 실패: {browser_result.get('error')}")
    except Exception as e:
        report["errors"].append(f"browser_research_digest 예외: {str(e)}")

    # 5. Prompt Activity (Claude Code, Codex, BoramClaw 등)
    try:
        prompt_result = prompt_collector_run(
            {"days_back": days + 1, "sources": ["all"], "min_length": 5},  # +1: 당일 시작 이전 세션 포함
            context
        )

        if prompt_result.get("success"):
            all_prompts = prompt_result.get("sample", [])  # 최근 10개
            by_source = prompt_result.get("by_source", {})
            total = prompt_result.get("total_prompts", 0)

            # 오늘 날짜 기준 필터 (daily 모드)
            today_str = datetime.now().strftime("%Y-%m-%d")
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            # 소스별 시간대 분포
            hour_dist = {}
            filtered_prompts = []
            for p in all_prompts:
                p_date = p.get("date", "")
                p_time = p.get("time", "")
                if p_date >= cutoff_date:
                    filtered_prompts.append(p)
                    if p_time:
                        try:
                            hour = int(p_time.split(":")[0])
                            hour_dist[hour] = hour_dist.get(hour, 0) + 1
                        except (ValueError, IndexError):
                            pass

            # 전체 수집 파일에서 날짜 필터 적용한 카운트 재계산
            output_file = Path(context.get("workdir", ".")) / "logs" / f"prompts_collected_{datetime.now().strftime('%Y%m%d')}.jsonl"
            date_filtered_total = 0
            date_filtered_by_source = {}
            if output_file.exists():
                with open(output_file, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            p = json.loads(line)
                            if p.get("date", "") >= cutoff_date:
                                date_filtered_total += 1
                                src = p.get("source", "unknown")
                                date_filtered_by_source[src] = date_filtered_by_source.get(src, 0) + 1
                        except json.JSONDecodeError:
                            continue

            report["sections"]["prompts"] = {
                "total_prompts": date_filtered_total or total,
                "by_source": date_filtered_by_source or by_source,
                "recent_prompts": filtered_prompts[:10],
                "time_distribution": hour_dist,
            }
        else:
            report["errors"].append("prompt_collector 실패")
    except Exception as e:
        report["errors"].append(f"prompt_collector 예외: {str(e)}")

    # 6. ML Study Progress (16주 커리큘럼 진도 체크)
    try:
        study_result = study_tracker_run(
            {"mode": mode, "days_back": days},
            context
        )
        if study_result.get("success"):
            tracking = study_result.get("tracking", {})
            report["sections"]["study"] = tracking
            # 마크다운 섹션도 미리 생성해두기
            if tracking.get("status") == "active":
                report["sections"]["study"]["_markdown"] = study_format_md(tracking)
    except Exception as e:
        report["errors"].append(f"study_tracker 예외: {str(e)}")

    # Summary 생성
    report["summary"] = _generate_summary(report)

    # 시간대별 종합 타임라인 생성
    report["timeline"] = _generate_timeline(report)

    return {
        "status": "success",
        "report": report,
    }


def _generate_summary(report: dict) -> str:
    """리포트에서 한줄 요약 생성"""
    sections = report.get("sections", {})
    mode = report.get("mode", "daily")
    period = "오늘" if mode == "daily" else "이번 주"

    parts = []

    if "git" in sections:
        commits = sections["git"].get("total_commits", 0)
        if commits > 0:
            parts.append(f"커밋 {commits}개")

    if "shell" in sections:
        cmds = sections["shell"].get("total_commands", 0)
        if cmds > 0:
            parts.append(f"명령어 {cmds}개")

    if "browser" in sections:
        visits = sections["browser"].get("total_visits", 0)
        if visits > 0:
            parts.append(f"웹 방문 {visits}개")

    if "screen" in sections:
        captures = sections["screen"].get("total_captures", 0)
        if captures > 0:
            parts.append(f"화면 캡처 {captures}개")

    if "prompts" in sections:
        total_p = sections["prompts"].get("total_prompts", 0)
        if total_p > 0:
            by_src = sections["prompts"].get("by_source", {})
            src_summary = ", ".join(f"{k}:{v}" for k, v in sorted(by_src.items(), key=lambda x: -x[1]))
            parts.append(f"프롬프트 {total_p}개 ({src_summary})")

    if "study" in sections:
        study = sections["study"]
        if study.get("status") == "active":
            week = study.get("week", "?")
            topic = study.get("topic", "?")
            warning_lvl = study.get("warning", {}).get("level", "")
            matched = study.get("study_evidence", {}).get("total_matched", 0)
            parts.append(f"ML공부 Week{week}({topic}) {warning_lvl} {matched}개")

    if parts:
        return f"{period} 활동: " + ", ".join(parts)
    else:
        return f"{period} 활동 데이터 없음"


def _generate_timeline(report: dict) -> dict:
    """시간대별 활동 타임라인 생성"""
    sections = report.get("sections", {})

    # 24시간 타임라인 초기화
    timeline = {hour: {"git": 0, "browser": 0, "prompts": 0, "total": 0} for hour in range(24)}

    # Git 커밋 시간대 추가
    if "git" in sections:
        git_time = sections["git"].get("time_distribution", {})
        for hour, count in git_time.items():
            timeline[int(hour)]["git"] = count
            timeline[int(hour)]["total"] += count

    # Browser 활동 시간대 추가
    if "browser" in sections:
        browser_time = sections["browser"].get("time_distribution", {})
        for hour, count in browser_time.items():
            timeline[int(hour)]["browser"] = count
            timeline[int(hour)]["total"] += count

    # Prompt 활동 시간대 추가
    if "prompts" in sections:
        prompt_time = sections["prompts"].get("time_distribution", {})
        for hour, count in prompt_time.items():
            h = int(hour)
            timeline[h]["prompts"] = timeline[h].get("prompts", 0) + count
            timeline[h]["total"] += count

    # 활동이 있는 시간대만 추출
    active_hours = {h: data for h, data in timeline.items() if data["total"] > 0}

    # 가장 활발한 시간대 찾기
    peak_hour = None
    peak_count = 0
    for hour, data in active_hours.items():
        if data["total"] > peak_count:
            peak_count = data["total"]
            peak_hour = hour

    return {
        "hourly": timeline,
        "active_hours": sorted(active_hours.keys()),
        "peak_hour": peak_hour,
        "peak_count": peak_count,
    }


def main():
    parser = argparse.ArgumentParser(description=TOOL_SPEC["description"])
    parser.add_argument(
        "--tool-spec-json",
        action="store_true",
        help="Print tool specification as JSON",
    )
    parser.add_argument(
        "--tool-input-json",
        type=str,
        help="Tool input as JSON string",
    )
    parser.add_argument(
        "--tool-context-json",
        type=str,
        default="{}",
        help="Tool context as JSON string",
    )

    args = parser.parse_args()

    if args.tool_spec_json:
        print(json.dumps(TOOL_SPEC, ensure_ascii=False, indent=2))
        return

    if not args.tool_input_json:
        print(json.dumps({"error": "--tool-input-json is required"}, ensure_ascii=False))
        sys.exit(1)

    try:
        input_data = json.loads(args.tool_input_json)
        context = json.loads(args.tool_context_json)
        result = run(input_data, context)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
