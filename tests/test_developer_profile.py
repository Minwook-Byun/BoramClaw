from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from developer_profile import run


@patch("developer_profile._collect_git_data")
@patch("developer_profile._load_shell_entries")
def test_developer_profile_basic(mock_shell_entries, mock_git_data) -> None:
    now = datetime.now().timestamp()
    mock_shell_entries.return_value = [
        {"timestamp": now - 1000, "command": "python3 app.py"},
        {"timestamp": now - 900, "command": "pytest -q"},
        {"timestamp": now - 800, "command": "pip install requests"},
        {"timestamp": now - 700, "command": "git status"},
    ]
    mock_git_data.return_value = {
        "repo_count": 1,
        "commits": [{"date": "2026-02-20T10:00:00"}],
        "changed_files": ["api/user.py", "models/user_model.py"],
    }

    with tempfile.TemporaryDirectory(dir=str(Path.cwd() / "logs")) as td:
        case_root = Path(td)
        original_cwd = Path.cwd()
        os.chdir(case_root)
        try:
            result = run({"days_back": 30, "scan_all_repos": False}, {})
            assert result["ok"] is True
            assert result["profile"]["primary_language"] == "Python"
            assert len(result["role_insights"]) >= 1

            snapshot_path = case_root / "logs" / "developer_profiles" / f"{datetime.now().date().isoformat()}.json"
            assert snapshot_path.exists()
        finally:
            os.chdir(original_cwd)


@patch("developer_profile._collect_git_data")
@patch("developer_profile._load_shell_entries")
def test_developer_profile_growth(mock_shell_entries, mock_git_data) -> None:
    today = datetime.now().date()
    compare_date = today - timedelta(days=30)
    now = datetime.now().timestamp()
    mock_shell_entries.return_value = [
        {"timestamp": now - 1000, "command": "python3 app.py"},
        {"timestamp": now - 900, "command": "python3 manage.py"},
        {"timestamp": now - 800, "command": "pytest -q"},
        {"timestamp": now - 700, "command": "pytest tests"},
        {"timestamp": now - 600, "command": "docker build ."},
    ]
    mock_git_data.return_value = {
        "repo_count": 1,
        "commits": [{"date": "2026-02-20T10:00:00"}],
        "changed_files": ["service/api.py"],
    }

    with tempfile.TemporaryDirectory(dir=str(Path.cwd() / "logs")) as td:
        case_root = Path(td)
        original_cwd = Path.cwd()
        os.chdir(case_root)
        try:
            profile_dir = case_root / "logs" / "developer_profiles"
            profile_dir.mkdir(parents=True, exist_ok=True)
            compare_path = profile_dir / f"{compare_date.isoformat()}.json"
            compare_path.write_text(
                json.dumps(
                    {
                        "date": compare_date.isoformat(),
                        "profile": {"language_breakdown": {"Python": 0.40}},
                        "tool_usage": {"python3": 5, "pytest": 1},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run({"days_back": 30, "scan_all_repos": False}, {})
            growth = result["growth"]
            assert result["ok"] is True
            assert "new_tools" in growth
            assert "increased_usage" in growth
            assert "docker" in growth["new_tools"] or isinstance(growth["new_tools"], list)
        finally:
            os.chdir(original_cwd)
