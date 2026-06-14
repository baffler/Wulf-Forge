import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LaunchScriptTests(unittest.TestCase):
    def test_powershell_launcher_starts_server_and_client_with_local_flags(self):
        script = ROOT / "launch-local.ps1"
        text = script.read_text(encoding="utf-8")

        self.assertIn("main.py", text)
        self.assertIn("wulfram2.exe", text)
        self.assertIn("-root", text)
        self.assertIn("-windowed", text)
        self.assertIn("Start-Process", text)

    def test_cmd_launcher_wraps_powershell_launcher(self):
        script = ROOT / "launch-local.cmd"
        text = script.read_text(encoding="utf-8")

        self.assertIn("launch-local.ps1", text)
        self.assertIn("-ExecutionPolicy", text)


if __name__ == "__main__":
    unittest.main()
