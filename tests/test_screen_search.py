"""screen_search 도구 테스트."""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.screen_search import TOOL_SPEC, run, _format_results, _health_check


class TestToolSpec(unittest.TestCase):
    """TOOL_SPEC 규약 검증."""

    def test_has_required_fields(self):
        for key in ("name", "description", "version", "input_schema"):
            self.assertIn(key, TOOL_SPEC)

    def test_name(self):
        self.assertEqual(TOOL_SPEC["name"], "screen_search")

    def test_input_schema_requires_query(self):
        self.assertIn("query", TOOL_SPEC["input_schema"]["required"])


class TestFormatResults(unittest.TestCase):
    """응답 가공 로직 테스트."""

    def test_empty_data(self):
        result = _format_results({"data": []})
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 0)

    def test_ocr_item(self):
        raw = {
            "data": [{
                "type": "OCR",
                "content": {
                    "timestamp": "2026-02-18T10:00:00Z",
                    "app_name": "Chrome",
                    "window_name": "GitHub",
                    "text": "Hello World" * 100,
                },
            }],
            "pagination": {"total": 1},
        }
        result = _format_results(raw)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["app_name"], "Chrome")
        # text는 500자로 잘림
        self.assertLessEqual(len(result["results"][0]["text"]), 500)

    def test_audio_item(self):
        raw = {
            "data": [{
                "type": "Audio",
                "content": {
                    "timestamp": "2026-02-18T10:00:00Z",
                    "transcription": "회의 내용입니다",
                    "device_name": "MacBook Pro Mic",
                },
            }],
        }
        result = _format_results(raw)
        self.assertEqual(result["results"][0]["transcription"], "회의 내용입니다")


class TestRunFunction(unittest.TestCase):
    """run() 함수 테스트."""

    def test_empty_query_returns_error(self):
        with patch("tools.screen_search._health_check", return_value={"status": "healthy"}):
            result = run({"query": ""}, {})
            self.assertFalse(result["ok"])
            self.assertIn("비어", result["error"])

    def test_screenpipe_not_running(self):
        with patch("tools.screen_search._health_check",
                    return_value={"status": "unreachable", "error": "refused"}):
            result = run({"query": "test"}, {})
            self.assertFalse(result["ok"])
            self.assertIn("실행 중이 아닙니다", result["error"])

    def test_successful_search(self):
        mock_response = {"data": [], "pagination": {"total": 0}}
        with patch("tools.screen_search._health_check", return_value={"status": "healthy"}), \
             patch("tools.screen_search._search", return_value=mock_response):
            result = run({"query": "test", "hours_back": 1}, {})
            self.assertTrue(result["ok"])
            self.assertEqual(result["count"], 0)


class TestCLI(unittest.TestCase):
    """CLI 인터페이스 테스트."""

    def test_tool_spec_json_via_main(self):
        """main() 함수를 직접 호출하여 STRICT_WORKDIR_ONLY 우회."""
        from io import StringIO
        from tools.screen_search import main
        with patch("sys.argv", ["screen_search.py", "--tool-spec-json"]), \
             patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            ret = main()
        self.assertEqual(ret, 0)
        spec = json.loads(mock_stdout.getvalue())
        self.assertEqual(spec["name"], "screen_search")


if __name__ == "__main__":
    unittest.main()
