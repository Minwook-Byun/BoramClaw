from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


def _load_module():
    tool_path = Path.cwd().resolve() / "tools" / "gmail_reply_recommender.py"
    spec = importlib.util.spec_from_file_location("gmail_reply_recommender_tool", tool_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestGmailFallback(unittest.TestCase):
    def test_fallback_used_when_gmail_api_fails(self) -> None:
        mod = _load_module()
        with patch.object(mod, "_build_gmail", side_effect=RuntimeError("api down")), patch.object(
            mod,
            "_run_imap_fallback",
            return_value=[
                {
                    "id": "1",
                    "thread_id": "",
                    "subject": "subject",
                    "from": "sender",
                    "snippet": "snippet",
                    "recommended_reply": "reply",
                    "source": "imap_fallback",
                }
            ],
        ):
            result = mod.run({"use_imap_fallback": True, "max_messages": 1}, {})
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("source"), "imap_fallback")
        self.assertEqual(result.get("count"), 1)

    def test_error_when_fallback_disabled(self) -> None:
        mod = _load_module()
        with patch.object(mod, "_build_gmail", side_effect=RuntimeError("api down")):
            result = mod.run({"use_imap_fallback": False}, {})
        self.assertFalse(result.get("ok"))
        self.assertIn("api down", str(result.get("error", "")))


if __name__ == "__main__":
    unittest.main()
