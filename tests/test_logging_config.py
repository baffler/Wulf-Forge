import io
import sys
import tempfile
import unittest
from pathlib import Path

from core.logging_config import setup_logging


class LoggingConfigTests(unittest.TestCase):
    def test_setup_logging_creates_unique_log_files_and_captures_stdout(self):
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()

        sys.stdout = captured_stdout
        sys.stderr = captured_stderr
        try:
            with tempfile.TemporaryDirectory() as tmp:
                first = setup_logging(log_dir=tmp)
                print("first boot line")
                first.restore()

                second = setup_logging(log_dir=tmp)
                print("second boot line")
                second.restore()

                self.assertNotEqual(first.log_file, second.log_file)
                self.assertTrue(first.log_file.exists())
                self.assertTrue(second.log_file.exists())
                self.assertIn("first boot line", first.log_file.read_text(encoding="utf-8"))
                self.assertIn("second boot line", second.log_file.read_text(encoding="utf-8"))
                self.assertIn("first boot line", captured_stdout.getvalue())
                self.assertIn("second boot line", captured_stdout.getvalue())
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr

        self.assertIs(sys.stdout, original_stdout)
        self.assertIs(sys.stderr, original_stderr)

    def test_setup_logging_uses_logs_directory_by_default(self):
        runtime = setup_logging(install_stream_redirect=False)
        log_file = runtime.log_file
        try:
            self.assertEqual(log_file.parent, Path("logs").resolve())
            self.assertTrue(log_file.name.startswith("wulf-forge-"))
        finally:
            runtime.restore()
            log_file.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
