import tempfile
import unittest
from pathlib import Path

from core.entity_manager import EntityManager
from core.map_loader import (
    REPAIR_PAD_UNIT_TYPE,
    ensure_team_repair_pads,
    resolve_repair_pad,
)
from network.packets.base import Packet
from network.packets.packet_config import PacketConfig
from network.packets.player import (
    AddToRosterPacket,
    UpdateStatsPacket,
    parse_reincarnate_request,
)
from network.streams import PacketWriter


def read_u16(data: bytes, offset: int) -> tuple[int, int]:
    return int.from_bytes(data[offset : offset + 2], "big"), offset + 2


def read_u32(data: bytes, offset: int) -> tuple[int, int]:
    return int.from_bytes(data[offset : offset + 4], "big"), offset + 4


def read_string(data: bytes, offset: int) -> tuple[str, int]:
    length, offset = read_u16(data, offset)
    raw = data[offset : offset + length]
    offset += length
    if raw.endswith(b"\x00"):
        raw = raw[:-1]
    return raw.decode("ascii"), offset


class WorldEntryProtocolTests(unittest.TestCase):
    def test_add_to_roster_matches_client_read_order(self):
        payload = AddToRosterPacket(
            account_id=7,
            team=2,
            name="Pilot",
            nametag="TAG",
        ).serialize()

        self.assertEqual(payload[0], 0x1A)
        offset = 1
        player_id, offset = read_u32(payload, offset)
        unknown, offset = read_u32(payload, offset)
        team_id, offset = read_u16(payload, offset)
        _stat_b, offset = read_u16(payload, offset)
        name, offset = read_string(payload, offset)
        callsign, offset = read_string(payload, offset)

        self.assertEqual(player_id, 7)
        self.assertEqual(unknown, 0)
        self.assertEqual(team_id, 2)
        self.assertEqual(name, "Pilot")
        self.assertEqual(callsign, "TAG")

    def test_update_stats_writes_team_as_first_short(self):
        payload = UpdateStatsPacket(player_id=7, team_id=1).serialize()

        self.assertEqual(payload[0], 0x1C)
        player_id, offset = read_u32(payload, 1)
        unknown, offset = read_u32(payload, offset)
        team_id, _offset = read_u16(payload, offset)

        self.assertEqual(player_id, 7)
        self.assertEqual(unknown, 6)
        self.assertEqual(team_id, 1)

    def test_reincarnate_spawn_request_matches_client_order(self):
        writer = PacketWriter()
        writer.write_byte(0x25)
        writer.write_int16(0x1234)
        writer.write_int16(0x0011)
        writer.write_byte(0)
        writer.write_int32(5)
        writer.write_int32(99)
        writer.write_int32(111)
        writer.write_int32(222)

        request = parse_reincarnate_request(writer.get_bytes())

        self.assertFalse(request.is_team_switch)
        self.assertEqual(request.sequence, 0x1234)
        self.assertEqual(request.unit_id, 5)
        self.assertEqual(request.repair_pad_id, 99)
        self.assertEqual(request.extra_x, 111)
        self.assertEqual(request.extra_y, 222)

    def test_reincarnate_team_request_matches_client_order(self):
        writer = PacketWriter()
        writer.write_byte(0x25)
        writer.write_int16(0x1234)
        writer.write_int16(0x0009)
        writer.write_byte(1)
        writer.write_int32(2)
        writer.write_int32(0)

        request = parse_reincarnate_request(writer.get_bytes())

        self.assertTrue(request.is_team_switch)
        self.assertEqual(request.team_id, 2)


class MapBootstrapTests(unittest.TestCase):
    def test_ensure_team_repair_pads_uses_land_height_for_empty_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            map_dir = Path(tmp)
            (map_dir / "land").write_text(
                "2x2\n"
                "1000x800\n"
                "0 10\n"
                "0 20\n"
                "0 30\n"
                "0 40\n",
                encoding="ascii",
            )
            entities = EntityManager()

            created = ensure_team_repair_pads(entities, map_dir)

            pads = [
                e for e in entities.get_all()
                if e.unit_type == REPAIR_PAD_UNIT_TYPE
            ]
            self.assertEqual(created, 2)
            self.assertEqual({pad.team_id for pad in pads}, {1, 2})
            self.assertTrue(all(pad.pos[2] > 40.0 for pad in pads))

    def test_zero_repair_pad_id_resolves_to_team_pad(self):
        entities = EntityManager()
        team_one_pad = entities.create_entity(
            unit_type=REPAIR_PAD_UNIT_TYPE,
            team_id=1,
            pos=(100.0, 100.0, 50.0),
        )
        entities.create_entity(
            unit_type=REPAIR_PAD_UNIT_TYPE,
            team_id=2,
            pos=(200.0, 200.0, 50.0),
        )

        self.assertIs(resolve_repair_pad(entities, 0, 1), team_one_pad)

    def test_explicit_repair_pad_id_must_match_selected_team(self):
        entities = EntityManager()
        wrong_team_pad = entities.create_entity(
            unit_type=REPAIR_PAD_UNIT_TYPE,
            team_id=2,
            pos=(200.0, 200.0, 50.0),
        )

        self.assertIsNone(resolve_repair_pad(entities, wrong_team_pad.net_id, 1))


class SpawnHandlerTests(unittest.TestCase):
    def _make_spawn_context(self):
        import main

        server = type("Server", (), {})()
        server.entities = EntityManager()
        server.packet_cfg = PacketConfig.load("packets.toml")
        server.sessions = []
        server.cfg = type(
            "Cfg",
            (),
            {
                "debug": type("Debug", (), {"show_ascii": False})(),
            },
        )()

        session = type("Session", (), {})()
        session.player_id = 1
        session.team = 1
        session.entity = None
        session.is_logged_in = True
        session.name = "Pilot"
        session.udp_context = None
        session.tcp_sock = None
        server.sessions.append(session)

        class FakeUdpContext:
            def __init__(self):
                self.server = server
                self.session = session
                self.sent = []
                self.acks = []

            def send(self, packet):
                if isinstance(packet, Packet):
                    packet = packet.serialize()
                self.sent.append(packet)

            def send_ack(self, packet_id, seq_num, subcmd=1):
                self.acks.append((packet_id, seq_num, subcmd))

        ctx = FakeUdpContext()
        session.udp_context = ctx
        return main, server, session, ctx

    def test_spawn_with_implicit_pad_sends_success_and_player_birth_notice(self):
        main, server, session, ctx = self._make_spawn_context()

        pad = server.entities.create_entity(
            unit_type=REPAIR_PAD_UNIT_TYPE,
            team_id=1,
            pos=(100.0, 100.0, 75.0),
        )
        pad.is_manned = False

        writer = PacketWriter()
        writer.write_byte(0x25)
        writer.write_int16(2)
        writer.write_int16(17)
        writer.write_byte(0)
        writer.write_int32(28)
        writer.write_int32(0)
        writer.write_int32(2000)
        writer.write_int32(700)

        main.on_reincarnate(ctx, writer.get_bytes())

        opcodes = [payload[0] for payload in ctx.sent]
        self.assertIn(0x18, opcodes)
        self.assertIn(0x25, opcodes)
        self.assertIn(0x1E, opcodes)

        reincarnate = next(payload for payload in ctx.sent if payload[0] == 0x25)
        self.assertEqual(reincarnate[1], 0)

        birth_notice = next(payload for payload in ctx.sent if payload[0] == 0x1E)
        player_id, _offset = read_u32(birth_notice, 1)
        self.assertEqual(player_id, session.player_id)

    def test_spawn_request_uses_selected_entry_id_and_default_playable_unit_type(self):
        main, server, session, ctx = self._make_spawn_context()

        first_pad = server.entities.create_entity(
            unit_type=REPAIR_PAD_UNIT_TYPE,
            team_id=1,
            pos=(100.0, 100.0, 75.0),
            override_net_id=28,
        )
        first_pad.is_manned = False
        selected_pad = server.entities.create_entity(
            unit_type=REPAIR_PAD_UNIT_TYPE,
            team_id=1,
            pos=(400.0, 500.0, 90.0),
            override_net_id=56,
        )
        selected_pad.is_manned = False

        writer = PacketWriter()
        writer.write_byte(0x25)
        writer.write_int16(3)
        writer.write_int16(17)
        writer.write_byte(0)
        writer.write_int32(selected_pad.net_id)
        writer.write_int32(0)
        writer.write_int32(2000)
        writer.write_int32(700)

        main.on_reincarnate(ctx, writer.get_bytes())

        self.assertIsNotNone(session.entity)
        self.assertEqual(session.entity.pos, selected_pad.pos)
        self.assertEqual(session.entity.unit_type, server.packet_cfg.tank.unit_type)


if __name__ == "__main__":
    unittest.main()
