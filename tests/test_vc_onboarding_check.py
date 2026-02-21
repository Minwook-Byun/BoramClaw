from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import vc_onboarding_check
from vc_platform.service import get_registry


class TestVCOnboardingCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmpdir.name)
        (self.workdir / "config").mkdir(parents=True, exist_ok=True)
        (self.workdir / "data").mkdir(parents=True, exist_ok=True)
        (self.workdir / "vault").mkdir(parents=True, exist_ok=True)
        self.context = {"workdir": str(self.workdir)}

        registry = get_registry(self.context)
        registry.register("acme", "Acme AI")
        registry.bind_folder("acme", "http://127.0.0.1:8742", "desktop_common")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_onboarding_without_sample_collect(self) -> None:
        with patch.object(vc_onboarding_check, "request_json", return_value={"ok": True}):
            result = vc_onboarding_check.run(
                {"startup_id": "acme", "run_sample_collect": False},
                self.context,
            )
        self.assertTrue(result.get("success"), msg=str(result))
        self.assertGreaterEqual(len(result.get("checks", [])), 2)


if __name__ == "__main__":
    unittest.main()
