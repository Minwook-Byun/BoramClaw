from __future__ import annotations

import json
from pathlib import Path
import unittest


class TestComfyUIAssets(unittest.TestCase):
    def test_workflow_json_is_valid(self) -> None:
        path = Path("comfyui/workflows/boramclaw_architecture_api.json")
        self.assertTrue(path.exists())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(payload, dict)
        for node_id in ["1", "2", "3", "4", "5", "6", "7"]:
            self.assertIn(node_id, payload)
        self.assertEqual(payload["1"]["class_type"], "CheckpointLoaderSimple")
        self.assertEqual(payload["7"]["class_type"], "SaveImage")

    def test_prompt_file_exists(self) -> None:
        path = Path("comfyui/prompts/boramclaw_architecture_prompt_ko.txt")
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("BoramClaw", text)
        self.assertIn("ReAct", text)


if __name__ == "__main__":
    unittest.main()

