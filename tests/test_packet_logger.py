import contextlib
import io
import unittest

from main import unknown_packet
from network.packets.packet_logger import PACKET_NAMES, PacketLogger, packet_name


class PacketOpcodeLabelTests(unittest.TestCase):
    def test_every_opcode_previously_logged_as_unknown_is_labeled(self):
        observed_unknowns = {
            0x04: "D_SET_START",
            0x15: "DELETE_OBJECT",
            0x16: "WORLD_STATS",
            0x17: "PLAYER",
            0x18: "TANK",
            0x1A: "ADD_TO_ROSTER",
            0x1B: "REMOVE_FROM_ROSTER",
            0x1C: "UPDATE_STATS",
            0x1E: "BIRTH_NOTICE",
            0x22: "LOGIN_STATUS",
            0x23: "MOTD",
            0x25: "REINCARNATE",
            0x26: "RETARGET",
            0x28: "TEAM_INFO",
            0x2F: "GAME_CLOCK",
            0x32: "TRANSLATION",
            0x39: "WANT_UPDATES",
            0x54: "GENERIC",
        }

        self.assertEqual(
            {opcode: packet_name(opcode) for opcode in observed_unknowns},
            observed_unknowns,
        )

    def test_logger_uses_canonical_label(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            PacketLogger().log_packet(
                "UDP-RECV", bytes([0x26, 0, 0, 0, 0]), include_tcp_len_prefix=False
            )

        self.assertIn("RETARGET", output.getvalue())
        self.assertNotIn("UNKNOWN", output.getvalue())

    def test_unimplemented_known_packet_is_reported_as_unhandled(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            unknown_packet(None, bytes([0x54, 0]))

        self.assertIn("Unhandled GENERIC (0x54", output.getvalue())
        self.assertNotIn("Unknown opcode", output.getvalue())

    def test_unknown_opcode_remains_distinguishable(self):
        self.assertNotIn(0xFF, PACKET_NAMES)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            unknown_packet(None, bytes([0xFF]))

        self.assertIn("Unknown opcode 0xFF", output.getvalue())


if __name__ == "__main__":
    unittest.main()
