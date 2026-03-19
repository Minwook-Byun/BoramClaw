from __future__ import annotations

import unittest

from turn_feedback import classify_feedback_text, summarize_turn_feedback


class TestTurnFeedback(unittest.TestCase):
    def test_classify_feedback_text_distinguishes_outcomes(self) -> None:
        self.assertEqual(classify_feedback_text("아니 어제 기준으로 더 길게 써줘")["outcome"], "corrected")
        self.assertEqual(classify_feedback_text("너무 좋다. 이거 매시간 자동으로 해줘")["outcome"], "accepted")
        self.assertEqual(classify_feedback_text("이어서 진행해줘")["outcome"], "retried")
        self.assertEqual(classify_feedback_text("이번주 회고를 써줘")["outcome"], "ambiguous")

    def test_summarize_turn_feedback_collects_hints(self) -> None:
        rows = [
            {"session_id": "s1", "ts": "2026-03-13T09:00:00+09:00", "text": "오늘 투두를 짜줘"},
            {"session_id": "s1", "ts": "2026-03-13T09:10:00+09:00", "text": "아니 어제 기준으로 실제 구현된거랑 git도 보고 프롬프트 분석도 해줘"},
            {"session_id": "s1", "ts": "2026-03-13T09:20:00+09:00", "text": "존댓말써!"},
            {"session_id": "s1", "ts": "2026-03-13T09:30:00+09:00", "text": "너무 좋다. 이거 매시간 자동으로 해줘"},
        ]

        summary = summarize_turn_feedback(rows)

        self.assertEqual(summary["feedback_prompt_count"], 3)
        self.assertEqual(summary["feedback_counts"]["corrected"], 2)
        self.assertEqual(summary["feedback_counts"]["accepted"], 1)
        labels = [item["label"] for item in summary["top_correction_hints"]]
        self.assertIn("Git/로컬 근거 우선", labels)
        self.assertIn("프롬프트 흐름 분석 포함", labels)
        self.assertIn("존댓말 유지", labels)


if __name__ == "__main__":
    unittest.main()
