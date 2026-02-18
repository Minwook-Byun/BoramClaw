from __future__ import annotations

from pathlib import Path
import shutil
import unittest

from setup_wizard import run_setup_wizard


class TestSetupWizard(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_root = Path.cwd().resolve() / "logs" / "test_runtime_setup_wizard"
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)
        cls.runtime_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)

    def test_non_interactive_writes_env(self) -> None:
        env_path = self.runtime_root / f"{self._testMethodName}.env"
        result = run_setup_wizard(
            env_path=str(env_path),
            non_interactive=True,
            updates={"ANTHROPIC_API_KEY": "sk-ant-test", "CLAUDE_MODEL": "claude-sonnet-4-5-20250929"},
        )
        self.assertTrue(result.get("ok"))
        text = env_path.read_text(encoding="utf-8")
        self.assertIn("ANTHROPIC_API_KEY=sk-ant-test", text)
        self.assertIn("CLAUDE_MODEL=claude-sonnet-4-5-20250929", text)
        self.assertIn("TOOL_WORKDIR=.", text)


if __name__ == "__main__":
    unittest.main()
