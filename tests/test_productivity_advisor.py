from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from productivity_advisor import run


@patch("productivity_advisor.workday_run")
def test_productivity_advisor_json_has_insights(mock_workday) -> None:
    mock_workday.return_value = {
        "status": "success",
        "report": {
            "sections": {
                "git": {
                    "total_commits": 2,
                    "commits": [
                        {"date": "2026-02-16T10:00:00"},
                        {"date": "2026-02-18T11:00:00"},
                        {"date": "2026-02-19T11:00:00"},
                        {"date": "2026-02-20T11:00:00"},
                    ],
                },
                "shell": {"total_commands": 260},
            },
            "timeline": {
                "hourly": {
                    **{h: {"total": 1 if h in {10, 11, 12} else 0} for h in range(24)},
                    22: {"total": 15},
                    23: {"total": 12},
                }
            },
            "productivity_analysis": {
                "peak_block": {"start": "10", "end": "12", "total": 25},
                "context_switches": 50,
            },
        },
    }

    result = run({"days_back": 7, "output_format": "json"}, {})
    assert result["ok"] is True
    assert len(result["insights"]) >= 1
    categories = {item["category"] for item in result["insights"]}
    assert "peak_time" in categories
    assert "late_night" in categories
    assert "context_switch" in categories


@patch("productivity_advisor.workday_run")
def test_productivity_advisor_text_mode(mock_workday) -> None:
    mock_workday.return_value = {
        "status": "success",
        "report": {
            "sections": {"git": {"total_commits": 10, "commits": []}, "shell": {"total_commands": 40}},
            "timeline": {"hourly": {h: {"total": 1 if h in {9, 10} else 0} for h in range(24)}},
            "productivity_analysis": {
                "peak_block": {"start": "09", "end": "11", "total": 10},
                "context_switches": 4,
            },
        },
    }

    result = run({"days_back": 7, "output_format": "text"}, {})
    assert result["ok"] is True
    assert "text" in result
    assert "생산성 리포트" in result["text"]
