#!/usr/bin/env python3
"""
dashboard.py
BoramClaw 웹 대시보드 - 실시간 활동 시각화

실시간 차트, 리포트 히스토리, 규칙 관리 UI 제공
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from flask import Flask, render_template_string, jsonify, request
import sys

# Context Engine import
sys.path.insert(0, str(Path(__file__).parent))
from context_engine import ContextEngine
from rules_engine import RulesEngine

logger = logging.getLogger(__name__)

app = Flask(__name__)

# HTML 템플릿
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BoramClaw Dashboard 📊</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 {
            text-align: center;
            color: white;
            margin-bottom: 30px;
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            transition: transform 0.3s ease;
        }
        .card:hover { transform: translateY(-5px); }
        .card h2 {
            margin-bottom: 20px;
            color: #667eea;
            font-size: 1.5em;
            border-bottom: 2px solid #f0f0f0;
            padding-bottom: 10px;
        }
        .stat {
            display: flex;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid #f5f5f5;
        }
        .stat:last-child { border-bottom: none; }
        .stat-label { color: #666; font-weight: 500; }
        .stat-value { color: #333; font-weight: bold; font-size: 1.1em; }
        .badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
        }
        .badge-success { background: #d4edda; color: #155724; }
        .badge-warning { background: #fff3cd; color: #856404; }
        .badge-danger { background: #f8d7da; color: #721c24; }
        .badge-info { background: #d1ecf1; color: #0c5460; }
        canvas { max-height: 300px; }
        .refresh-btn {
            background: white;
            color: #667eea;
            border: none;
            padding: 12px 30px;
            border-radius: 25px;
            font-size: 1em;
            font-weight: 600;
            cursor: pointer;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            transition: all 0.3s ease;
            margin: 20px auto;
            display: block;
        }
        .refresh-btn:hover {
            background: #667eea;
            color: white;
            transform: scale(1.05);
        }
        .timestamp {
            text-align: center;
            color: white;
            margin-top: 20px;
            font-size: 0.9em;
            opacity: 0.8;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #999;
            font-size: 1.2em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 BoramClaw Dashboard</h1>

        <div class="grid">
            <!-- 현재 컨텍스트 -->
            <div class="card">
                <h2>📍 Current Context</h2>
                <div id="context-stats"></div>
            </div>

            <!-- 세션 정보 -->
            <div class="card">
                <h2>⏱️ Work Session</h2>
                <div id="session-stats"></div>
            </div>

            <!-- Git 활동 -->
            <div class="card">
                <h2>📝 Git Activity</h2>
                <div id="git-stats"></div>
            </div>
        </div>

        <!-- 활동 차트 -->
        <div class="grid">
            <div class="card">
                <h2>💻 Shell Commands (Top 10)</h2>
                <canvas id="shellChart"></canvas>
            </div>

            <div class="card">
                <h2>🌐 Browser Activity</h2>
                <canvas id="browserChart"></canvas>
            </div>
        </div>

        <!-- Rules Engine 상태 -->
        <div class="card">
            <h2>⚙️ Rules Engine Status</h2>
            <div id="rules-stats"></div>
        </div>

        <button class="refresh-btn" onclick="refreshDashboard()">🔄 Refresh</button>
        <div class="timestamp" id="timestamp"></div>
    </div>

    <script>
        let shellChart, browserChart;

        async function fetchData() {
            const response = await fetch('/api/dashboard');
            return response.json();
        }

        function updateContextStats(context) {
            const html = `
                <div class="stat">
                    <span class="stat-label">Primary Activity</span>
                    <span class="stat-value">
                        <span class="badge badge-${context.activity_badge}">${context.primary_activity}</span>
                    </span>
                </div>
                <div class="stat">
                    <span class="stat-label">Confidence</span>
                    <span class="stat-value">${context.confidence}%</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Lookback</span>
                    <span class="stat-value">${context.lookback_minutes} min</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Active</span>
                    <span class="stat-value">
                        <span class="badge badge-${context.is_active ? 'success' : 'danger'}">
                            ${context.is_active ? 'Yes ✓' : 'No ✗'}
                        </span>
                    </span>
                </div>
            `;
            document.getElementById('context-stats').innerHTML = html;
        }

        function updateSessionStats(session) {
            const html = `
                <div class="stat">
                    <span class="stat-label">Session Active</span>
                    <span class="stat-value">
                        <span class="badge badge-${session.is_active ? 'success' : 'warning'}">
                            ${session.is_active ? 'Active' : 'Inactive'}
                        </span>
                    </span>
                </div>
                <div class="stat">
                    <span class="stat-label">Duration</span>
                    <span class="stat-value">${session.duration_minutes} min</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Start Time</span>
                    <span class="stat-value">${session.start_time || 'N/A'}</span>
                </div>
            `;
            document.getElementById('session-stats').innerHTML = html;
        }

        function updateGitStats(git) {
            const html = `
                <div class="stat">
                    <span class="stat-label">Recent Commits</span>
                    <span class="stat-value">${git.recent_commits}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Files Changed</span>
                    <span class="stat-value">${git.files_changed}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Lines Added</span>
                    <span class="stat-value" style="color: #28a745;">+${git.lines_added}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Lines Deleted</span>
                    <span class="stat-value" style="color: #dc3545;">-${git.lines_deleted}</span>
                </div>
            `;
            document.getElementById('git-stats').innerHTML = html;
        }

        function updateShellChart(shell) {
            const ctx = document.getElementById('shellChart').getContext('2d');

            if (shellChart) shellChart.destroy();

            shellChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: shell.commands,
                    datasets: [{
                        label: 'Executions',
                        data: shell.counts,
                        backgroundColor: 'rgba(102, 126, 234, 0.8)',
                        borderColor: 'rgba(102, 126, 234, 1)',
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        y: { beginAtZero: true }
                    }
                }
            });
        }

        function updateBrowserChart(browser) {
            const ctx = document.getElementById('browserChart').getContext('2d');

            if (browserChart) browserChart.destroy();

            browserChart = new Chart(ctx, {
                type: 'pie',
                data: {
                    labels: browser.domains,
                    datasets: [{
                        data: browser.visits,
                        backgroundColor: [
                            'rgba(255, 99, 132, 0.8)',
                            'rgba(54, 162, 235, 0.8)',
                            'rgba(255, 206, 86, 0.8)',
                            'rgba(75, 192, 192, 0.8)',
                            'rgba(153, 102, 255, 0.8)',
                            'rgba(255, 159, 64, 0.8)',
                        ],
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        legend: { position: 'bottom' }
                    }
                }
            });
        }

        function updateRulesStats(rules) {
            const html = `
                <div class="stat">
                    <span class="stat-label">Rules Loaded</span>
                    <span class="stat-value">${rules.total_rules}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Enabled</span>
                    <span class="stat-value">${rules.enabled_rules}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Last Evaluated</span>
                    <span class="stat-value">${rules.last_evaluated || 'Never'}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Actions Executed</span>
                    <span class="stat-value">${rules.actions_executed}</span>
                </div>
            `;
            document.getElementById('rules-stats').innerHTML = html;
        }

        async function refreshDashboard() {
            try {
                const data = await fetchData();

                updateContextStats(data.context);
                updateSessionStats(data.session);
                updateGitStats(data.git);
                updateShellChart(data.shell);
                updateBrowserChart(data.browser);
                updateRulesStats(data.rules);

                document.getElementById('timestamp').textContent =
                    `Last updated: ${new Date().toLocaleString('ko-KR')}`;
            } catch (error) {
                console.error('Failed to refresh dashboard:', error);
                alert('Failed to refresh dashboard. Check console for details.');
            }
        }

        // 초기 로드
        refreshDashboard();

        // 30초마다 자동 갱신
        setInterval(refreshDashboard, 30000);
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    """대시보드 메인 페이지"""
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/dashboard")
def api_dashboard():
    """대시보드 데이터 API"""
    try:
        # Context Engine 초기화
        context_engine = ContextEngine(lookback_minutes=30)

        # 현재 컨텍스트 조회
        context = context_engine.get_current_context(repo_path=".")
        session = context_engine.detect_work_session(repo_path=".")

        # Git 통계
        git_activity = context.get("activities", {}).get("git", {})
        git_stats = {
            "recent_commits": git_activity.get("recent_commit_count", 0),
            "files_changed": git_activity.get("files_changed", 0),
            "lines_added": git_activity.get("insertions", 0),
            "lines_deleted": git_activity.get("deletions", 0),
        }

        # Shell 통계
        shell_activity = context.get("activities", {}).get("shell", {})
        top_commands = shell_activity.get("top_commands", [])[:10]
        shell_stats = {
            "commands": [cmd.get("command", "unknown") for cmd in top_commands],
            "counts": [cmd.get("count", 0) for cmd in top_commands],
        }

        # Browser 통계
        browser_activity = context.get("activities", {}).get("browser", {})
        top_domains = browser_activity.get("top_domains", [])[:6]
        browser_stats = {
            "domains": [d.get("domain", "unknown") for d in top_domains],
            "visits": [d.get("count", 0) for d in top_domains],
        }

        # Rules Engine 상태
        rules_file = Path("config/rules.yaml")
        rules_stats = {"total_rules": 0, "enabled_rules": 0, "last_evaluated": None, "actions_executed": 0}
        if rules_file.exists():
            try:
                rules_engine = RulesEngine(str(rules_file))
                if rules_engine.load_rules():
                    rules_stats["total_rules"] = len(rules_engine.rules)
                    rules_stats["enabled_rules"] = sum(1 for r in rules_engine.rules if r.get("enabled", True))
            except Exception as e:
                logger.error(f"Rules Engine 로드 실패: {e}")

        # Context 요약
        summary = context.get("summary", {})
        context_stats = {
            "primary_activity": summary.get("primary_activity", "unknown"),
            "confidence": int(summary.get("confidence", 0) * 100),
            "lookback_minutes": context.get("lookback_minutes", 30),
            "is_active": summary.get("is_active", False),
            "activity_badge": "success" if summary.get("primary_activity") == "coding" else "info",
        }

        # Session 정보
        session_stats = {
            "is_active": session.get("is_session_active", False),
            "duration_minutes": session.get("session_duration_minutes", 0),
            "start_time": session.get("session_start_time", "N/A"),
        }

        return jsonify({
            "context": context_stats,
            "session": session_stats,
            "git": git_stats,
            "shell": shell_stats,
            "browser": browser_stats,
            "rules": rules_stats,
            "timestamp": datetime.now().isoformat(),
        })

    except Exception as e:
        logger.error(f"Dashboard API 오류: {e}")
        return jsonify({"error": str(e)}), 500


def start_dashboard(port: int = 8092, host: str = "127.0.0.1"):
    """대시보드 서버 시작"""
    print(f"\n🎉 BoramClaw Dashboard 시작!")
    print(f"📊 URL: http://{host}:{port}")
    print(f"🔄 30초마다 자동 갱신")
    print(f"\n종료: Ctrl+C\n")

    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start_dashboard(port=8092)
