#!/usr/bin/env python3
"""
workday_recap.py
하루/주간 개발 활동 통합 리포트 생성 툴

4개 데이터 소스 통합:
- screenpipe (화면 활동)
- git (커밋 이력)
- shell (명령어 패턴)
- browser (연구 활동)
"""
import sys
import json
import argparse
from collections import Counter
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any

# 다른 툴들 import
sys.path.insert(0, str(Path(__file__).parent))
from screen_search import run as screen_search_run
from git_daily_summary import run as git_summary_run
from shell_pattern_analyzer import run as shell_analyzer_run
from browser_research_digest import run as browser_digest_run

__version__ = "3.0.0"

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

    모든 Git 저장소를 자동으로 스캔합니다.""",
    "version": __version__,
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
        "meta": {
            "scan_all_repos": scan_all_repos,
            "repo_path": repo_path,
        },
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
                stats = git_result.get("stats", {}) if isinstance(git_result.get("stats"), dict) else {}
                total_files += int(stats.get("files_changed", git_result.get("files_changed", 0)) or 0)
                total_ins += int(stats.get("insertions", git_result.get("insertions", 0)) or 0)
                total_dels += int(stats.get("deletions", git_result.get("deletions", 0)) or 0)

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
                "time_distribution": shell_result.get("time_distribution", {}),
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

    # 5. Prompt Analysis (Claude + Codex)
    try:
        from universal_prompt_collector import run as prompt_collector_run

        prompt_result = prompt_collector_run(
            {"days_back": days, "sources": ["claude_code", "codex"], "min_length": 5},
            {"workdir": context.get("workdir", ".")},
        )
        if isinstance(prompt_result, dict) and prompt_result.get("success"):
            by_source = prompt_result.get("by_source", {})
            sample = prompt_result.get("sample", [])
            report["sections"]["prompts"] = {
                "total_prompts": prompt_result.get("total_prompts", 0),
                "by_source": by_source,
                "claude_code_count": by_source.get("claude_code", 0),
                "codex_count": by_source.get("codex", 0) + by_source.get("codex_session", 0),
                "recent_samples": [
                    {
                        "content": p.get("content", "")[:120],
                        "source": p.get("source", ""),
                        "time": p.get("time", ""),
                    }
                    for p in sample[:5]
                ],
            }
    except Exception as e:
        report["errors"].append(f"prompt_collector 예외: {str(e)}")

    # 6. YouTube & Web Search (browser_research_digest 확장 데이터)
    browser_section = report.get("sections", {}).get("browser", {})
    if "youtube" not in browser_section:
        # browser_digest가 이미 youtube 데이터를 포함하지 않으면 별도 추출
        try:
            browser_result_ext = browser_digest_run(
                {"hours": hours_back, "min_cluster_size": 1},
                context,
            )
            if isinstance(browser_result_ext, dict) and browser_result_ext.get("ok"):
                yt = browser_result_ext.get("youtube", {})
                sq = browser_result_ext.get("search_queries", [])
                ab = browser_result_ext.get("activity_breakdown", {})

                if yt or sq:
                    report["sections"]["youtube_search"] = {
                        "youtube_videos": yt.get("total_videos", 0),
                        "youtube_video_titles": [
                            v.get("title", "")
                            for v in (yt.get("videos", []) or [])[:10]
                        ],
                        "search_queries": [
                            {"query": s.get("query", ""), "engine": s.get("engine", "")}
                            for s in (sq or [])[:15]
                        ],
                        "activity_breakdown": ab,
                    }
        except Exception as e:
            report["errors"].append(f"youtube_search 예외: {str(e)}")

    # 7. Impact Score (커밋 분류)
    try:
        from weekly_goal_manager import _classify_commit, _compute_impact_score

        git_section = report.get("sections", {}).get("git", {})
        commits_list = git_section.get("commits", [])
        classified = []
        for c in commits_list:
            msg = c.get("message", c.get("subject", ""))
            classified.append({
                "message": msg,
                "impact_type": _classify_commit(msg),
            })
        if classified:
            report["sections"]["impact_score"] = _compute_impact_score(classified)
            report["sections"]["impact_score"]["commits_classified"] = classified[:15]
    except Exception as e:
        report["errors"].append(f"impact_score 예외: {str(e)}")

    # Summary 생성
    report["summary"] = _generate_summary(report)

    # 시간대별 종합 타임라인 생성
    report["timeline"] = _build_timeline(report)
    report["productivity_analysis"] = _analyze_productivity(report["timeline"])

    if mode == "daily":
        today_key = datetime.now().strftime("%Y-%m-%d")
        prediction_file = str(Path("logs") / "predictions" / f"{today_key}.json")
        prediction_accuracy = _compare_with_predictions(report, prediction_file)
        report["prediction_accuracy"] = prediction_accuracy or {"available": False}
        _save_tomorrow_prediction(report)
    else:
        report["feedback_learning"] = _summarize_weekly_feedback(days_back=7)

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
        prompts = sections["prompts"].get("total_prompts", 0)
        if prompts > 0:
            parts.append(f"프롬프트 {prompts}개")

    if "youtube_search" in sections:
        yt_count = sections["youtube_search"].get("youtube_videos", 0)
        sq_count = len(sections["youtube_search"].get("search_queries", []))
        if yt_count > 0:
            parts.append(f"YouTube {yt_count}개")
        if sq_count > 0:
            parts.append(f"웹검색 {sq_count}개")

    if "impact_score" in sections:
        score = sections["impact_score"].get("impact_score", 0)
        grade = sections["impact_score"].get("grade", "")
        if score > 0:
            parts.append(f"Impact {score:.0f}점({grade})")

    if parts:
        return f"{period} 활동: " + ", ".join(parts)
    else:
        return f"{period} 활동 데이터 없음"


def _parse_hour_key(raw_hour: Any) -> int | None:
    if isinstance(raw_hour, int):
        return raw_hour if 0 <= raw_hour <= 23 else None
    text = str(raw_hour).strip()
    if not text:
        return None
    if ":" in text:
        text = text.split(":", 1)[0]
    if "-" in text:
        text = text.split("-", 1)[0]
    try:
        hour = int(text)
    except ValueError:
        return None
    return hour if 0 <= hour <= 23 else None


def _build_timeline(report: dict) -> dict:
    """시간대별 활동 타임라인 생성 (git/browser/shell 통합)."""
    sections = report.get("sections", {})

    timeline = {hour: {"git": 0, "browser": 0, "shell": 0, "total": 0} for hour in range(24)}

    # Git
    if "git" in sections:
        git_time = sections["git"].get("time_distribution", {})
        for raw_hour, raw_count in git_time.items():
            hour = _parse_hour_key(raw_hour)
            if hour is None:
                continue
            count = int(raw_count or 0)
            timeline[hour]["git"] += count
            timeline[hour]["total"] += count

    # Browser
    if "browser" in sections:
        browser_time = sections["browser"].get("time_distribution", {})
        for raw_hour, raw_count in browser_time.items():
            hour = _parse_hour_key(raw_hour)
            if hour is None:
                continue
            count = int(raw_count or 0)
            timeline[hour]["browser"] += count
            timeline[hour]["total"] += count

    # Shell
    if "shell" in sections:
        shell_time = sections["shell"].get("time_distribution", {})
        for raw_hour, raw_count in shell_time.items():
            hour = _parse_hour_key(raw_hour)
            if hour is None:
                continue
            count = int(raw_count or 0)
            timeline[hour]["shell"] += count
            timeline[hour]["total"] += count

    active_hours = {h: data for h, data in timeline.items() if data["total"] > 0}

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


def _generate_timeline(report: dict) -> dict:
    """호환성 유지용 래퍼."""
    return _build_timeline(report)


def _analyze_productivity(timeline: dict) -> dict:
    """시간대별 생산성 패턴 분석"""
    hourly = timeline.get("hourly", {})
    hourly_data = {
        hour: (hourly.get(hour, {}) if isinstance(hourly, dict) else {})
        for hour in range(24)
    }

    # 연속 2시간 최고 활동 블록
    peak_start = 0
    peak_total = 0
    for start in range(23):
        total = int(hourly_data[start].get("total", 0) or 0) + int(hourly_data[start + 1].get("total", 0) or 0)
        if total > peak_total:
            peak_total = total
            peak_start = start

    peak_block = {
        "start": f"{peak_start:02d}",
        "end": f"{(peak_start + 2):02d}",
        "total": peak_total,
    }

    morning_score = sum(int(hourly_data[h].get("total", 0) or 0) for h in range(6, 12))
    afternoon_score = sum(int(hourly_data[h].get("total", 0) or 0) for h in range(12, 18))
    evening_score = sum(int(hourly_data[h].get("total", 0) or 0) for h in range(18, 24))

    focus_blocks: list[dict[str, Any]] = []
    block_start: int | None = None
    block_total = 0
    block_len = 0
    for hour in range(24):
        total = int(hourly_data[hour].get("total", 0) or 0)
        if total > 0:
            if block_start is None:
                block_start = hour
                block_total = 0
                block_len = 0
            block_total += total
            block_len += 1
        else:
            if block_start is not None and block_len >= 2:
                focus_blocks.append(
                    {
                        "start": f"{block_start:02d}",
                        "end": f"{hour:02d}",
                        "total": block_total,
                    }
                )
            block_start = None
            block_total = 0
            block_len = 0
    if block_start is not None and block_len >= 2:
        focus_blocks.append(
            {
                "start": f"{block_start:02d}",
                "end": f"{((block_start + block_len) % 24):02d}",
                "total": block_total,
            }
        )

    # 시간 단위 주요 활동 타입 전환 수
    context_switches = 0
    prev_type: str | None = None
    for hour in range(24):
        row = hourly_data[hour]
        candidates = {
            "git": int(row.get("git", 0) or 0),
            "browser": int(row.get("browser", 0) or 0),
            "shell": int(row.get("shell", 0) or 0),
        }
        if sum(candidates.values()) <= 0:
            continue
        dominant = max(candidates, key=lambda key: candidates[key])
        if prev_type is not None and dominant != prev_type:
            context_switches += 1
        prev_type = dominant

    return {
        "peak_block": peak_block,
        "morning_score": morning_score,
        "afternoon_score": afternoon_score,
        "evening_score": evening_score,
        "focus_blocks": focus_blocks,
        "context_switches": context_switches,
    }


def _safe_accuracy(predicted: float, actual: float) -> float:
    denominator = max(abs(predicted), abs(actual), 1.0)
    score = 1.0 - (abs(predicted - actual) / denominator)
    return round(max(0.0, min(1.0, score)), 3)


def _actual_focus_hours(today_data: dict) -> float:
    timeline = today_data.get("timeline", {})
    hourly = timeline.get("hourly", {}) if isinstance(timeline, dict) else {}
    active_hours = 0
    for hour in range(24):
        row = hourly.get(hour, {}) if isinstance(hourly, dict) else {}
        if int(row.get("total", 0) or 0) > 0:
            active_hours += 1
    return round(float(active_hours), 2)


def _compare_with_predictions(today_data: dict, yesterday_prediction_file: str) -> dict | None:
    prediction_path = Path(yesterday_prediction_file)
    if not prediction_path.exists():
        return None
    try:
        payload = json.loads(prediction_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    predictions = payload.get("predictions", {}) if isinstance(payload, dict) else {}
    if not isinstance(predictions, dict):
        return None

    actual_commits = int(today_data.get("sections", {}).get("git", {}).get("total_commits", 0) or 0)
    actual_focus_hours = _actual_focus_hours(today_data)
    actual_peak_hour = today_data.get("timeline", {}).get("peak_hour")
    actual_peak_str = f"{int(actual_peak_hour):02d}" if actual_peak_hour is not None else None

    metrics: list[dict[str, Any]] = []
    accuracy_values: list[float] = []

    pred_commits = float(predictions.get("commits", 0) or 0)
    commits_accuracy = _safe_accuracy(pred_commits, float(actual_commits))
    metrics.append(
        {
            "metric": "commits",
            "predicted": int(round(pred_commits)),
            "actual": actual_commits,
            "accuracy": commits_accuracy,
        }
    )
    accuracy_values.append(commits_accuracy)

    pred_focus = float(predictions.get("focus_hours", 0.0) or 0.0)
    focus_accuracy = _safe_accuracy(pred_focus, actual_focus_hours)
    metrics.append(
        {
            "metric": "focus_hours",
            "predicted": round(pred_focus, 2),
            "actual": actual_focus_hours,
            "accuracy": focus_accuracy,
        }
    )
    accuracy_values.append(focus_accuracy)

    pred_peak_hour = str(predictions.get("peak_hour", "")).zfill(2)[:2]
    peak_accuracy = 1.0 if (actual_peak_str and pred_peak_hour == actual_peak_str) else 0.0
    metrics.append(
        {
            "metric": "peak_hour",
            "predicted": pred_peak_hour,
            "actual": actual_peak_str,
            "accuracy": peak_accuracy,
        }
    )
    accuracy_values.append(peak_accuracy)

    overall = round(sum(accuracy_values) / len(accuracy_values), 3) if accuracy_values else 0.0
    return {
        "available": True,
        "predictions_vs_actual": metrics,
        "overall_accuracy": overall,
    }


def _command_to_language(command: str) -> str:
    cmd = (command or "").strip().lower()
    if cmd in {"python", "python3", "pytest", "pip"}:
        return "Python"
    if cmd in {"node", "npm", "npx", "yarn", "ts-node", "tsc"}:
        return "JavaScript/TypeScript"
    if cmd in {"go"}:
        return "Go"
    if cmd in {"cargo", "rustc"}:
        return "Rust"
    if cmd in {"java", "mvn", "gradle"}:
        return "Java"
    return "Unknown"


def _save_tomorrow_prediction(today_data: dict) -> None:
    try:
        now = datetime.now()
        today_key = now.strftime("%Y-%m-%d")
        tomorrow_key = (now + timedelta(days=1)).strftime("%Y-%m-%d")

        weekly_result = run(
            {"mode": "weekly", "scan_all_repos": today_data.get("meta", {}).get("scan_all_repos", False)},
            {},
        )
        weekly_report = weekly_result.get("report", {}) if isinstance(weekly_result, dict) else {}
        weekly_timeline = weekly_report.get("timeline", {}) if isinstance(weekly_report, dict) else {}
        weekly_hourly = weekly_timeline.get("hourly", {}) if isinstance(weekly_timeline, dict) else {}
        weekly_git = weekly_report.get("sections", {}).get("git", {}) if isinstance(weekly_report, dict) else {}
        weekly_shell = weekly_report.get("sections", {}).get("shell", {}) if isinstance(weekly_report, dict) else {}

        weekly_commits = int(weekly_git.get("total_commits", 0) or 0)
        predicted_commits = int(round(weekly_commits / 7))

        active_hour_count = 0
        for hour in range(24):
            row = weekly_hourly.get(hour, {}) if isinstance(weekly_hourly, dict) else {}
            if int(row.get("total", 0) or 0) > 0:
                active_hour_count += 1
        predicted_focus_hours = round(active_hour_count / 7.0, 2)

        peak_hour = weekly_timeline.get("peak_hour")
        peak_hour_text = f"{int(peak_hour):02d}" if peak_hour is not None else "09"

        top_commands = weekly_shell.get("top_commands", []) if isinstance(weekly_shell, dict) else []
        primary_language = "Unknown"
        if top_commands:
            top_command = str(top_commands[0].get("command", ""))
            primary_language = _command_to_language(top_command)

        row = {
            "generated_at": datetime.now().isoformat(),
            "based_on_date": today_key,
            "predictions": {
                "commits": predicted_commits,
                "focus_hours": predicted_focus_hours,
                "peak_hour": peak_hour_text,
                "primary_language": primary_language,
            },
        }

        target_dir = Path("logs") / "predictions"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / f"{tomorrow_key}.json"
        target_file.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def _summarize_weekly_feedback(days_back: int = 7) -> dict[str, Any]:
    path = Path("logs") / "user_feedback.jsonl"
    if not path.exists():
        return {
            "total_feedback": 0,
            "positive_ratio": 0.0,
            "top_categories": [],
            "learning_notes": [],
        }
    cutoff_ts = (datetime.now() - timedelta(days=days_back)).timestamp()
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            ts = parsed.get("ts", "")
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.timestamp() >= cutoff_ts:
                rows.append(parsed)
    except Exception:
        rows = []

    if not rows:
        return {
            "total_feedback": 0,
            "positive_ratio": 0.0,
            "top_categories": [],
            "learning_notes": [],
        }

    category_counter: Counter[str] = Counter()
    positive_count = 0
    negative_counter: Counter[str] = Counter()
    for row in rows:
        category = str(row.get("category", "general")).strip() or "general"
        category_counter[category] += 1
        tags = row.get("auto_tags", [])
        if isinstance(tags, list):
            lowered = {str(tag).lower() for tag in tags}
            if "positive" in lowered:
                positive_count += 1
            if "negative" in lowered:
                negative_counter[category] += 1

    learning_notes: list[str] = []
    if negative_counter.get("time_prediction", 0) >= 2:
        learning_notes.append("집중 시간 예측 정확도를 높이기 위해 예측 로직 재보정이 필요합니다.")
    if negative_counter.get("productivity_advice", 0) >= 2:
        learning_notes.append("생산성 제안의 개인화 수준을 강화할 필요가 있습니다.")
    if positive_count >= max(1, len(rows) // 2):
        learning_notes.append("대체로 제안 품질 만족도가 높아 현재 추천 전략을 유지할 수 있습니다.")
    if not learning_notes:
        learning_notes.append("피드백 표본이 충분하지 않아 다음 주 데이터 누적이 필요합니다.")

    return {
        "total_feedback": len(rows),
        "positive_ratio": round(positive_count / len(rows), 3),
        "top_categories": [name for name, _ in category_counter.most_common(3)],
        "learning_notes": learning_notes,
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
