from __future__ import annotations

from pathlib import Path
import os
import shutil
import unittest
from unittest.mock import patch

import config


class TestConfigApiKey(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_root = Path.cwd().resolve() / "logs" / "test_runtime_config"
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)
        cls.runtime_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)

    def test_resolve_api_key_priority(self) -> None:
        key, source = config._resolve_api_key(
            env_key="sk-ant-env",
            keychain_key="sk-ant-keychain",
            dotenv_key="sk-ant-dotenv",
            allow_plaintext_api_key=True,
        )
        self.assertEqual(key, "sk-ant-env")
        self.assertEqual(source, "env")

        key, source = config._resolve_api_key(
            env_key="",
            keychain_key="sk-ant-keychain",
            dotenv_key="sk-ant-dotenv",
            allow_plaintext_api_key=True,
        )
        self.assertEqual(key, "sk-ant-keychain")
        self.assertEqual(source, "keychain")

        key, source = config._resolve_api_key(
            env_key="",
            keychain_key="",
            dotenv_key="sk-ant-dotenv",
            allow_plaintext_api_key=False,
        )
        self.assertEqual(key, "")
        self.assertEqual(source, "missing")

    def test_load_dotenv_exclude_api_key(self) -> None:
        case = self.runtime_root / "dotenv_exclude"
        case.mkdir(parents=True, exist_ok=True)
        dotenv = case / ".env"
        dotenv.write_text("ANTHROPIC_API_KEY=sk-ant-dotenv\nFOO=bar\n", encoding="utf-8")

        old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        old_foo = os.environ.pop("FOO", None)
        try:
            config.load_dotenv(str(dotenv), exclude_keys={"ANTHROPIC_API_KEY"})
            self.assertEqual(os.getenv("FOO"), "bar")
            self.assertIsNone(os.getenv("ANTHROPIC_API_KEY"))
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("FOO", None)
            if old_key is not None:
                os.environ["ANTHROPIC_API_KEY"] = old_key
            if old_foo is not None:
                os.environ["FOO"] = old_foo

    def test_from_env_prefers_keychain_when_plaintext_disabled(self) -> None:
        case = self.runtime_root / "from_env"
        case.mkdir(parents=True, exist_ok=True)
        dotenv = case / ".env"
        dotenv.write_text(
            "ANTHROPIC_API_KEY=sk-ant-dotenv\n"
            "CLAUDE_MODEL=claude-sonnet-4-5-20250929\n"
            "TOOL_WORKDIR=.\n"
            "CUSTOM_TOOL_DIR=tools\n",
            encoding="utf-8",
        )
        (case / "tools").mkdir(parents=True, exist_ok=True)

        old_cwd = Path.cwd()
        old_env = dict(os.environ)
        try:
            os.chdir(case)
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ["ALLOW_PLAINTEXT_API_KEY"] = "0"
            with patch("config._load_key_from_keychain", return_value="sk-ant-keychain"):
                cfg = config.BoramClawConfig.from_env()
            self.assertEqual(cfg.anthropic_api_key, "sk-ant-keychain")
            self.assertEqual(cfg.api_key_source, "keychain")
        finally:
            os.chdir(old_cwd)
            os.environ.clear()
            os.environ.update(old_env)

