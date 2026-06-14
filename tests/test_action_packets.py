import contextlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from network.streams import PacketWriter  # noqa: E402
from network.translation_config import get_config_by_index  # noqa: E402


def _fake_ctx(player_id=42):
    entity = SimpleNamespace(actions={})
    session = SimpleNamespace(player_id=player_id, entity=entity)
    return SimpleNamespace(session=session), entity


def _write_action_value(writer: PacketWriter, action_id: int, value: float):
    if action_id >= 8 or action_id == 4:
        writer.write_bits(1 if value != 0.0 else 0, 1)
        return

    cfg = get_config_by_index(10 if action_id == 5 else 11)
    _, raw_value, bit_count = cfg.compress(value)
    writer.write_bits(raw_value, bit_count)


def _action_update_packet(action_id: int, value: float) -> bytes:
    writer = PacketWriter()
    writer.write_byte(0x0A)
    writer.write_byte(1)
    writer.write_int32(1000)
    writer.write_int32(2000)
    writer.write_bits(action_id, get_config_by_index(15).precision_header_bits)
    _write_action_value(writer, action_id, value)
    return writer.get_bytes()


def _action_dump_packet(values: dict[int, float]) -> bytes:
    writer = PacketWriter()
    writer.write_byte(0x09)
    writer.write_int32(3000)
    writer.write_int32(4000)
    for action_id in range(1, 22):
        _write_action_value(writer, action_id, values.get(action_id, 0.0))
    return writer.get_bytes()


class ActionPacketReplayTests(unittest.TestCase):
    def test_action_update_stores_press_and_release_zero(self):
        ctx, entity = _fake_ctx()

        with contextlib.redirect_stdout(io.StringIO()):
            main.parse_action_packet(
                ctx,
                _action_update_packet(action_id=4, value=1.0),
                is_dump=False,
            )
            main.parse_action_packet(
                ctx,
                _action_update_packet(action_id=4, value=0.0),
                is_dump=False,
            )

        self.assertEqual(entity.actions[4], 0.0)

    def test_action_dump_uses_implicit_ids_and_clears_stale_values(self):
        ctx, entity = _fake_ctx()
        entity.actions[4] = 1.0

        with contextlib.redirect_stdout(io.StringIO()):
            decoded = main.parse_action_packet(
                ctx,
                _action_dump_packet({}),
                is_dump=True,
            )

        self.assertEqual(entity.actions[4], 0.0)
        self.assertEqual(len(decoded), 21)
        self.assertEqual(decoded[3][0], 4)
        self.assertEqual(decoded[3][1], 1.0)
        self.assertEqual(decoded[3][2], 0.0)


if __name__ == "__main__":
    unittest.main()
