from __future__ import annotations

from pathlib import Path
import tomllib
import unittest


class TestCliPackaging(unittest.TestCase):
    def test_pyproject_has_boramclaw_entrypoint(self) -> None:
        pyproject = Path.cwd() / "pyproject.toml"
        self.assertTrue(pyproject.exists())
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        scripts = data.get("project", {}).get("scripts", {})
        self.assertEqual(scripts.get("boramclaw"), "main:main")

