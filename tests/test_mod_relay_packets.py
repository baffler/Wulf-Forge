import sys
import time
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import ModRelayConfig  # noqa: E402
from core.entity import GameEntity, UpdateMask  # noqa: E402
from mod_relay.packets import (  # noqa: E402
    CLIENT_STATE_V1_STRUCT,
    MAGIC,
    TYPE_CLIENT_STATE,
    VERSION_V1,
    parse_client_state_v1,
)
from mod_relay.session_mapper import map_mod_packet_to_session, resolve_mod_packet_session  # noqa: E402
from mod_relay.state_apply import apply_mod_client_state  # noqa: E402


def _packet(
    *,
    magic=MAGIC,
    version=VERSION_V1,
    packet_type=TYPE_CLIENT_STATE,
    sequence=7,
    player_id=42,
):
    return CLIENT_STATE_V1_STRUCT.pack(
        magic,
        version,
        packet_type,
        sequence,
        1234,
        player_id,
        0xABCDEF,
        1.0,
        2.0,
        3.0,
        4.0,
        5.0,
        6.0,
        0.1,
        0.2,
        0.3,
        0.4,
        0.5,
        0.6,
        0,
    )


class ModRelayPacketTests(unittest.TestCase):
    def test_valid_client_state_packet_decodes(self):
        state = parse_client_state_v1(_packet())

        self.assertIsNotNone(state)
        self.assertEqual(state.sequence, 7)
        self.assertEqual(state.client_tick_ms, 1234)
        self.assertEqual(state.player_id, 42)
        self.assertEqual(state.local_entity, 0xABCDEF)
        self.assertEqual(state.pos, (1.0, 2.0, 3.0))
        self.assertEqual(state.vel, (4.0, 5.0, 6.0))
        self.assertAlmostEqual(state.rot[0], 0.1)
        self.assertAlmostEqual(state.rot[1], 0.2)
        self.assertAlmostEqual(state.rot[2], 0.3)
        self.assertAlmostEqual(state.angvel[0], 0.4)
        self.assertAlmostEqual(state.angvel[1], 0.5)
        self.assertAlmostEqual(state.angvel[2], 0.6)

    def test_rejects_bad_size(self):
        self.assertIsNone(parse_client_state_v1(_packet()[:-1]))

    def test_rejects_bad_magic(self):
        self.assertIsNone(parse_client_state_v1(_packet(magic=0xBAD)))

    def test_rejects_bad_version(self):
        self.assertIsNone(parse_client_state_v1(_packet(version=2)))

    def test_packet_size_is_76_bytes(self):
        self.assertEqual(CLIENT_STATE_V1_STRUCT.size, 76)


class ModRelaySessionMappingTests(unittest.TestCase):
    def test_maps_nonzero_player_id_to_session_player_id(self):
        state = parse_client_state_v1(_packet(player_id=42))
        session = SimpleNamespace(player_id=42, entity=GameEntity(net_id=99), is_logged_in=True)
        server = SimpleNamespace(sessions=[session])

        self.assertIs(map_mod_packet_to_session(server, ("127.0.0.1", 5000), state), session)

    def test_maps_nonzero_player_id_to_entity_net_id(self):
        state = parse_client_state_v1(_packet(player_id=99))
        session = SimpleNamespace(player_id=42, entity=GameEntity(net_id=99), is_logged_in=True)
        server = SimpleNamespace(sessions=[session])

        self.assertIs(map_mod_packet_to_session(server, ("127.0.0.1", 5000), state), session)

    def test_maps_zero_player_id_by_unique_source_ip(self):
        state = parse_client_state_v1(_packet(player_id=0))
        session = SimpleNamespace(
            player_id=42,
            entity=GameEntity(net_id=99),
            is_logged_in=True,
            address=("127.0.0.1", 1111),
            udp_addr=None,
        )
        server = SimpleNamespace(sessions=[session])

        self.assertIs(map_mod_packet_to_session(server, ("127.0.0.1", 5000), state), session)

    def test_rejects_ambiguous_source_ip(self):
        state = parse_client_state_v1(_packet(player_id=0))
        sessions = [
            SimpleNamespace(player_id=1, entity=GameEntity(net_id=10), is_logged_in=True, address=("127.0.0.1", 1), udp_addr=None),
            SimpleNamespace(player_id=2, entity=GameEntity(net_id=20), is_logged_in=True, address=("127.0.0.1", 2), udp_addr=None),
        ]
        server = SimpleNamespace(sessions=sessions)

        result = resolve_mod_packet_session(server, ("127.0.0.1", 5000), state)
        self.assertIsNone(result.session)
        self.assertIn("ambiguous", result.reason)

    def test_reuses_existing_debug_binding_for_unknown_player_id(self):
        state = parse_client_state_v1(_packet(player_id=777))
        session = SimpleNamespace(
            player_id=42,
            entity=GameEntity(net_id=99),
            is_logged_in=True,
            address=("127.0.0.1", 1111),
            udp_addr=None,
            mod_relay_addr=("127.0.0.1", 5000),
        )
        server = SimpleNamespace(sessions=[session])

        result = resolve_mod_packet_session(server, ("127.0.0.1", 5000), state)

        self.assertIs(result.session, session)
        self.assertEqual(result.reason, "existing_debug_binding")

    def test_auto_binds_unknown_player_id_to_recent_unbound_same_ip_spawn(self):
        state = parse_client_state_v1(_packet(player_id=777))
        older = SimpleNamespace(
            player_id=1,
            entity=GameEntity(net_id=10),
            is_logged_in=True,
            address=("127.0.0.1", 1000),
            udp_addr=None,
            mod_relay_addr=None,
            mod_relay_last_spawned_at=1.0,
        )
        newer = SimpleNamespace(
            player_id=2,
            entity=GameEntity(net_id=20),
            is_logged_in=True,
            address=("127.0.0.1", 2000),
            udp_addr=None,
            mod_relay_addr=None,
            mod_relay_last_spawned_at=2.0,
        )
        server = SimpleNamespace(
            sessions=[older, newer],
            cfg=SimpleNamespace(mod_relay=ModRelayConfig(debug_mapping=True, auto_bind=True)),
        )

        result = resolve_mod_packet_session(server, ("127.0.0.1", 5000), state)

        self.assertIs(result.session, newer)
        self.assertEqual(result.reason, "auto_bound_recent_spawn_same_ip")
        self.assertEqual(newer.mod_relay_addr, ("127.0.0.1", 5000))
        self.assertEqual(newer.mod_relay_packet_player_id, 777)

    def test_auto_bind_can_be_disabled(self):
        state = parse_client_state_v1(_packet(player_id=777))
        session = SimpleNamespace(
            player_id=1,
            entity=GameEntity(net_id=10),
            is_logged_in=True,
            address=("127.0.0.1", 1000),
            udp_addr=None,
            mod_relay_addr=None,
        )
        server = SimpleNamespace(
            sessions=[session],
            cfg=SimpleNamespace(mod_relay=ModRelayConfig(debug_mapping=True, auto_bind=False)),
        )

        result = resolve_mod_packet_session(server, ("127.0.0.1", 5000), state)

        self.assertIsNone(result.session)
        self.assertIn("unknown player_id", result.reason)


class ModRelayStateApplyTests(unittest.TestCase):
    def test_apply_mutates_default_safe_fields_and_marks_dirty(self):
        state = parse_client_state_v1(_packet())
        entity = GameEntity(net_id=99)
        session = SimpleNamespace(entity=entity)

        applied = apply_mod_client_state(SimpleNamespace(), session, state)

        self.assertTrue(applied)
        self.assertEqual(entity.pos, state.pos)
        self.assertEqual(entity.vel, state.vel)
        self.assertEqual(entity.rot, state.rot)
        self.assertEqual(entity.spin, (0.0, 0.0, 0.0))
        self.assertTrue(entity.pending_mask & UpdateMask.POS)
        self.assertTrue(entity.pending_mask & UpdateMask.VEL)
        self.assertTrue(entity.pending_mask & UpdateMask.ROT)
        self.assertFalse(entity.pending_mask & UpdateMask.SPIN)
        self.assertTrue(entity.pending_mask & UpdateMask.HARD_SYNC)

    def test_apply_respects_server_mod_relay_field_switches(self):
        state = parse_client_state_v1(_packet())
        entity = GameEntity(net_id=99)
        session = SimpleNamespace(entity=entity)
        server = SimpleNamespace(
            cfg=SimpleNamespace(
                mod_relay=ModRelayConfig(
                    hard_sync=False,
                    adaptive_hard_sync=False,
                    apply_velocity=False,
                    apply_rotation=True,
                    apply_spin=True,
                )
            )
        )

        applied = apply_mod_client_state(server, session, state)

        self.assertTrue(applied)
        self.assertEqual(entity.pos, state.pos)
        self.assertEqual(entity.vel, (0.0, 0.0, 0.0))
        self.assertEqual(entity.rot, state.rot)
        self.assertEqual(entity.spin, state.angvel)
        self.assertTrue(entity.pending_mask & UpdateMask.POS)
        self.assertFalse(entity.pending_mask & UpdateMask.VEL)
        self.assertTrue(entity.pending_mask & UpdateMask.ROT)
        self.assertTrue(entity.pending_mask & UpdateMask.SPIN)
        self.assertFalse(entity.pending_mask & UpdateMask.HARD_SYNC)

    def test_adaptive_hard_sync_skips_normal_driving_after_initial_packets(self):
        state = parse_client_state_v1(_packet())
        entity = GameEntity(net_id=99)
        session = SimpleNamespace(entity=entity)
        server = SimpleNamespace(
            mod_relay_entity_updates={
                99: {
                    "apply_count": 3,
                    "monotonic": time.monotonic(),
                }
            },
            cfg=SimpleNamespace(
                mod_relay=ModRelayConfig(
                    hard_sync=False,
                    adaptive_hard_sync=True,
                    hard_sync_initial_packets=3,
                    hard_sync_stale_ms=500,
                    hard_sync_teleport_distance=250.0,
                )
            ),
        )

        applied = apply_mod_client_state(server, session, state)

        self.assertTrue(applied)
        self.assertFalse(entity.pending_mask & UpdateMask.HARD_SYNC)
        self.assertEqual(session.mod_relay_last_hard_sync_reason, "")

    def test_adaptive_hard_sync_marks_initial_packets(self):
        state = parse_client_state_v1(_packet())
        entity = GameEntity(net_id=99)
        session = SimpleNamespace(entity=entity)
        server = SimpleNamespace(
            mod_relay_entity_updates={},
            cfg=SimpleNamespace(
                mod_relay=ModRelayConfig(
                    hard_sync=False,
                    adaptive_hard_sync=True,
                    hard_sync_initial_packets=3,
                )
            ),
        )

        applied = apply_mod_client_state(server, session, state)

        self.assertTrue(applied)
        self.assertTrue(entity.pending_mask & UpdateMask.HARD_SYNC)
        self.assertEqual(session.mod_relay_last_hard_sync_reason, "initial")

    def test_adaptive_hard_sync_marks_stale_stream(self):
        state = parse_client_state_v1(_packet())
        entity = GameEntity(net_id=99)
        session = SimpleNamespace(entity=entity)
        server = SimpleNamespace(
            mod_relay_entity_updates={
                99: {
                    "apply_count": 3,
                    "monotonic": time.monotonic() - 1.0,
                }
            },
            cfg=SimpleNamespace(
                mod_relay=ModRelayConfig(
                    hard_sync=False,
                    adaptive_hard_sync=True,
                    hard_sync_initial_packets=3,
                    hard_sync_stale_ms=500,
                )
            ),
        )

        applied = apply_mod_client_state(server, session, state)

        self.assertTrue(applied)
        self.assertTrue(entity.pending_mask & UpdateMask.HARD_SYNC)
        self.assertEqual(session.mod_relay_last_hard_sync_reason, "stale")

    def test_adaptive_hard_sync_marks_large_position_delta(self):
        state = parse_client_state_v1(_packet())
        assert state is not None
        state.pos = (1000.0, 0.0, 0.0)
        entity = GameEntity(net_id=99)
        session = SimpleNamespace(entity=entity)
        server = SimpleNamespace(
            mod_relay_entity_updates={
                99: {
                    "apply_count": 3,
                    "monotonic": time.monotonic(),
                }
            },
            cfg=SimpleNamespace(
                mod_relay=ModRelayConfig(
                    hard_sync=False,
                    adaptive_hard_sync=True,
                    hard_sync_initial_packets=3,
                    hard_sync_teleport_distance=250.0,
                )
            ),
        )

        applied = apply_mod_client_state(server, session, state)

        self.assertTrue(applied)
        self.assertTrue(entity.pending_mask & UpdateMask.HARD_SYNC)
        self.assertEqual(session.mod_relay_last_hard_sync_reason, "teleport")

    def test_apply_rejects_invalid_position(self):
        state = parse_client_state_v1(_packet())
        assert state is not None
        state.pos = (float("nan"), 2.0, 3.0)
        entity = GameEntity(net_id=99)
        session = SimpleNamespace(entity=entity)

        applied = apply_mod_client_state(SimpleNamespace(), session, state)

        self.assertFalse(applied)
        self.assertEqual(entity.pending_mask, 0)

    def test_apply_rejects_invalid_required_rotation(self):
        state = parse_client_state_v1(_packet())
        assert state is not None
        state.rot = (float("inf"), 0.0, 0.0)
        entity = GameEntity(net_id=99)
        session = SimpleNamespace(entity=entity)

        applied = apply_mod_client_state(SimpleNamespace(), session, state)

        self.assertFalse(applied)
        self.assertEqual(entity.pending_mask, 0)


if __name__ == "__main__":
    unittest.main()
