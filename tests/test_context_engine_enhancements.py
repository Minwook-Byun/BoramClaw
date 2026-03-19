from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from context_engine import ContextEngine


@patch("context_engine.browser_digest_run", return_value={"ok": True, "sessions": []})
@patch("context_engine.git_summary_run", return_value={"ok": True, "commits": []})
@patch("context_engine.shell_analyzer_run")
def test_get_current_context_has_alias_fields(mock_shell, mock_git, mock_browser) -> None:
    now_ts = datetime.now().timestamp()
    mock_shell.return_value = {
        "ok": True,
        "all_commands": [
            {"timestamp": now_ts - 3600, "command": "python3 app.py"},
            {"timestamp": now_ts - 1200, "command": "node server.js"},
        ],
    }

    engine = ContextEngine(lookback_minutes=30)
    context = engine.get_current_context()

    assert "last_activity_minutes_ago" in context
    assert "primary_activity" in context
    assert context["primary_activity"] == context["summary"]["primary_activity"]
    assert isinstance(context["last_activity_minutes_ago"], int)


@patch("context_engine.shell_analyzer_run")
def test_detect_work_session_break_and_consecutive_focus(mock_shell) -> None:
    now_ts = datetime.now().timestamp()
    # 30분+ 공백 존재: 두 번째와 세 번째 명령 사이
    mock_shell.return_value = {
        "ok": True,
        "all_commands": [
            {"timestamp": now_ts - 7200, "command": "python3 main.py"},
            {"timestamp": now_ts - 7000, "command": "git status"},
            {"timestamp": now_ts - 900, "command": "node app.js"},
            {"timestamp": now_ts - 600, "command": "npm test"},
        ],
    }

    engine = ContextEngine(lookback_minutes=30)
    session = engine.detect_work_session(min_duration_minutes=10)

    assert session["is_session_active"] is True
    assert session["duration_minutes"] >= 100
    assert session["last_break_minutes_ago"] is not None
    assert session["consecutive_focus_minutes"] == session["last_break_minutes_ago"]
    assert session["consecutive_focus_minutes"] >= 10
