"""Opcode labeling for the packet logger.

Names are taken from the client's own NetDebug_PopulatePacketHistogram
@ 0x004865c9 in wulfram2.exe (the authoritative opcode->name source).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.packets.packet_logger import PacketLogger  # noqa: E402


class OpcodeNameTests(unittest.TestCase):
    def setUp(self):
        self.names = PacketLogger().packet_names

    def test_known_gameplay_opcodes(self):
        expected = {
            0x0E: "UPDATE_ARRAY",
            0x0F: "VIEW_UPDATE",
            0x15: "DELETE_OBJECT",
            0x24: "BEHAVIOR",
            0x25: "REINCARNATE",
            0x29: "CARRYING_INFO",
            0x2B: "DROP_REQUEST",
            0x2E: "WEAPON_DEMAND",
            0x38: "DOCKING",
            0x39: "WANT_UPDATES",
        }
        for opcode, name in expected.items():
            self.assertEqual(self.names.get(opcode), name, f"0x{opcode:02X}")

    def test_low_level_protocol_names_preserved(self):
        self.assertEqual(self.names.get(0x02), "D_ACK")
        self.assertEqual(self.names.get(0x03), "D_HANDSHAKE")

    def test_gameplay_range_fully_labeled(self):
        # Every opcode the client's histogram defines (0x08..0x3E) must resolve
        # to a real name so nothing logs as UNKNOWN.
        for opcode in range(0x08, 0x3F):
            self.assertIn(opcode, self.names, f"0x{opcode:02X} unlabeled")


class SpamFilterTests(unittest.TestCase):
    def _capture(self, logger, payload):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            logger.log_packet("TEST", payload, include_tcp_len_prefix=False)
        return buf.getvalue()

    def test_high_frequency_opcode_suppressed_by_default(self):
        logger = PacketLogger()
        out = self._capture(logger, bytes([0x0E, 0x00]))  # UPDATE_ARRAY
        self.assertEqual(out, "", "0x0E should be suppressed by default")

    def test_full_logging_when_spam_filter_cleared(self):
        logger = PacketLogger()
        logger.spam_opcodes = set()
        out = self._capture(logger, bytes([0x0E, 0x00]))
        self.assertIn("UPDATE_ARRAY", out)


class DebugConfigTests(unittest.TestCase):
    def test_log_all_opcodes_defaults_false(self):
        from core.config import DebugConfig

        self.assertFalse(DebugConfig().log_all_opcodes)


if __name__ == "__main__":
    unittest.main()
