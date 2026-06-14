import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from core.config import Config  # noqa: E402


def _server_with_mode(mode):
    return SimpleNamespace(cfg=SimpleNamespace(sync=SimpleNamespace(mode=mode)))


class SyncModeTests(unittest.TestCase):
    def test_default_config_uses_server_simulation(self):
        self.assertEqual(Config().sync.mode, main.SYNC_MODE_SERVER_SIMULATION)

    def test_config_loads_client_state_relay_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.toml"
            config_path.write_text(
                "[sync]\nmode = \"client_state_relay\"\n",
                encoding="utf-8",
            )

            cfg = Config.load(str(config_path))

        self.assertEqual(cfg.sync.mode, main.SYNC_MODE_CLIENT_STATE_RELAY)

    def test_server_simulation_policy(self):
        server = _server_with_mode("server_simulation")

        self.assertTrue(main.should_run_server_simulation(server))
        self.assertFalse(main.should_accept_client_state_relay(server))

    def test_client_state_relay_policy(self):
        server = _server_with_mode("client_state_relay")

        self.assertFalse(main.should_run_server_simulation(server))
        self.assertTrue(main.should_accept_client_state_relay(server))

    def test_invalid_or_missing_mode_falls_back_to_server_simulation(self):
        invalid = _server_with_mode("surprise_me")
        missing = SimpleNamespace(cfg=SimpleNamespace())

        self.assertEqual(main.get_sync_mode(invalid), main.SYNC_MODE_SERVER_SIMULATION)
        self.assertTrue(main.should_run_server_simulation(invalid))
        self.assertTrue(main.should_run_server_simulation(missing))


if __name__ == "__main__":
    unittest.main()
