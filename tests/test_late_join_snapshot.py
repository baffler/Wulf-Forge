import contextlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from core.entity import GameEntity, UpdateMask  # noqa: E402
from network.packets import BirthNoticePacket  # noqa: E402


class FakeEntityBuilder:
    def __init__(self):
        self.calls = []

    def build_forced_update_packet(
        self,
        entities,
        sequence_num,
        is_view_update,
        forced_mask,
        local_stats=None,
        force_spawn=True,
    ):
        self.calls.append(
            {
                "entities": list(entities),
                "sequence_num": sequence_num,
                "is_view_update": is_view_update,
                "forced_mask": forced_mask,
                "local_stats": local_stats,
                "force_spawn": force_spawn,
            }
        )
        return b"forced"


class LateJoinSnapshotTests(unittest.TestCase):
    def test_skips_when_no_other_spawned_players_exist(self):
        sent = []
        own_entity = GameEntity(net_id=10)
        session = SimpleNamespace(
            player_id=1,
            entity=own_entity,
            udp_context=None,
        )
        server = SimpleNamespace(
            sessions=[session],
            entities=FakeEntityBuilder(),
        )
        ctx = SimpleNamespace(session=session, server=server, send=sent.append)

        with contextlib.redirect_stdout(io.StringIO()):
            did_send = main.send_existing_player_entity_definitions(ctx, "test")

        self.assertFalse(did_send)
        self.assertEqual(sent, [])
        self.assertEqual(server.entities.calls, [])

    def test_sends_existing_player_births_and_forced_definitions_to_udp_context(self):
        tcp_sent = []
        udp_sent = []
        own_entity = GameEntity(net_id=10)
        own_entity.health = 0.75
        own_entity.energy = 0.5
        other_entity = GameEntity(net_id=20)
        stale_dirty_entity = GameEntity(net_id=30)
        stale_dirty_entity.is_manned = False

        udp_context = SimpleNamespace(send=udp_sent.append)
        session = SimpleNamespace(
            player_id=1,
            entity=own_entity,
            udp_context=udp_context,
        )
        other_session = SimpleNamespace(
            player_id=2,
            entity=other_entity,
            is_logged_in=True,
        )
        unmanned_session = SimpleNamespace(
            player_id=3,
            entity=stale_dirty_entity,
            is_logged_in=True,
        )
        server = SimpleNamespace(
            sessions=[session, other_session, unmanned_session],
            entities=FakeEntityBuilder(),
        )
        ctx = SimpleNamespace(session=session, server=server, send=tcp_sent.append)

        with contextlib.redirect_stdout(io.StringIO()):
            did_send = main.send_existing_player_entity_definitions(ctx, "test")

        self.assertTrue(did_send)
        self.assertEqual(tcp_sent, [])
        self.assertEqual(len(udp_sent), 2)
        self.assertIsInstance(udp_sent[0], BirthNoticePacket)
        self.assertEqual(udp_sent[0].player_id, 20)
        self.assertEqual(udp_sent[1], b"\x0Eforced")

        call = server.entities.calls[0]
        self.assertEqual([entity.net_id for entity in call["entities"]], [20])
        self.assertFalse(call["is_view_update"])
        self.assertTrue(call["force_spawn"])
        self.assertEqual(call["local_stats"], (0.75, 0.5))
        self.assertTrue(call["forced_mask"] & UpdateMask.DEFINITION)
        self.assertTrue(call["forced_mask"] & UpdateMask.POS)
        self.assertTrue(call["forced_mask"] & UpdateMask.VEL)
        self.assertTrue(call["forced_mask"] & UpdateMask.ROT)
        self.assertTrue(call["forced_mask"] & UpdateMask.HEALTH)


if __name__ == "__main__":
    unittest.main()
