from __future__ import annotations

import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from feedback_collector import run


def test_feedback_collector_saves_records() -> None:
    with tempfile.TemporaryDirectory(dir=str(Path.cwd() / "logs")) as td:
        case_root = Path(td)
        result = run(
            {
                "feedback": "오늘 집중 시간 예측 정확해, 커밋 리마인드도 좋아",
                "category": "time_prediction",
                "rating": 5,
            },
            {"workdir": str(case_root)},
        )

        assert result["ok"] is True
        assert "positive" in result["tags"]
        assert "time_management" in result["tags"]
        assert "coding_habit" in result["tags"]

        feedback_path = case_root / "logs" / "user_feedback.jsonl"
        assert feedback_path.exists()
        rows = [json.loads(line) for line in feedback_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(rows) == 1
        assert rows[0]["category"] == "time_prediction"

        reflexion_path = case_root / "logs" / "reflexion_cases.jsonl"
        assert reflexion_path.exists()
