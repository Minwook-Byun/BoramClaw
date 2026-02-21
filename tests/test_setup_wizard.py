from __future__ import annotations

from pathlib import Path
import shutil
import unittest

from setup_wizard import run_setup_wizard, run_vc_setup_wizard


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

    def test_vc_setup_central_non_interactive(self) -> None:
        runtime = self.runtime_root / self._testMethodName
        runtime.mkdir(parents=True, exist_ok=True)
        result = run_vc_setup_wizard(
            workdir=str(runtime),
            mode="central",
            non_interactive=True,
            updates={
                "startup_id": "acme",
                "display_name": "Acme AI",
                "gateway_url": "http://127.0.0.1:8742",
                "folder_alias": "desktop_common",
                "gateway_secret": "secret",
                "email_recipients": "ops@vc.test",
            },
        )
        self.assertTrue(result.get("ok"))
        tenant_path = runtime / "config" / "vc_tenants.json"
        self.assertTrue(tenant_path.exists())
        text = tenant_path.read_text(encoding="utf-8")
        self.assertIn("\"startup_id\": \"acme\"", text)
        env_text = (runtime / ".env").read_text(encoding="utf-8")
        self.assertIn("TOOL_WORKDIR=", env_text)
        self.assertIn("/vc onboard acme 7d", str(result.get("validation_command", "")))

    def test_vc_setup_gateway_non_interactive(self) -> None:
        runtime = self.runtime_root / self._testMethodName
        runtime.mkdir(parents=True, exist_ok=True)
        shared = runtime / "shared-common"
        result = run_vc_setup_wizard(
            workdir=str(runtime),
            mode="gateway",
            non_interactive=True,
            updates={
                "startup_id": "acme",
                "gateway_secret": "secret",
                "folder_alias": "desktop_common",
                "gateway_folder_path": str(shared),
            },
        )
        self.assertTrue(result.get("ok"))
        gateway_path = runtime / "config" / "vc_gateway.json"
        self.assertTrue(gateway_path.exists())
        payload = gateway_path.read_text(encoding="utf-8")
        self.assertIn("\"startup_id\": \"acme\"", payload)
        start_script = runtime / "scripts" / "windows" / "start_gateway.bat"
        install_script = runtime / "scripts" / "windows" / "install_gateway_service.bat"
        uninstall_script = runtime / "scripts" / "windows" / "uninstall_gateway_service.bat"
        self.assertTrue(start_script.exists())
        self.assertTrue(install_script.exists())
        self.assertTrue(uninstall_script.exists())
        start_text = start_script.read_text(encoding="utf-8")
        self.assertIn("py -3.10 -V", start_text)
        self.assertIn("py -3 vc_gateway_agent.py", start_text)
        self.assertIn("if defined BORAMCLAW_PYTHON_BIN", start_text)
        self.assertIn("config\\vc_gateway.json not found", start_text)
        self.assertIn("vc_gateway_agent.py", str(result.get("validation_command", "")))


if __name__ == "__main__":
    unittest.main()
