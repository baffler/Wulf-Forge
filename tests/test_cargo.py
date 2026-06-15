"""Tests for server-authoritative cargo pickup / carry / deploy.

Protocol facts are reverse-engineered from wulfram2.exe (Ghidra W2VULK); see
docs/superpowers/specs/2026-06-15-cargo-pickup-deploy-design.md.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.packets.gameplay import CarryingInfoPacket  # noqa: E402
from network.streams import PacketWriter, PacketReader  # noqa: E402
from network.packets.update_array import EntitySerializer  # noqa: E402
from core.entity import GameEntity, UpdateMask  # noqa: E402
from network.translation_config import (  # noqa: E402
    ID_BITS_UNIT,
    ID_BITS_TEAM,
    ID_BITS_UNIT_CARGO,
    BANK_SELECTOR_BITS,
)


from network.packets.packet_config import PacketConfig  # noqa: E402


class ConfigWiringTests(unittest.TestCase):
    def test_max_speed_height_pickup_path(self):
        # main.py wires CargoSystem's pickup gate from this exact path; it lives
        # on active_vehicle_physics, not on `tank`. Lock it so the wiring can't
        # silently break again.
        cfg = PacketConfig()
        self.assertAlmostEqual(
            cfg.behavior.active_vehicle_physics.max_speed_height_pickup, 3.5
        )
        self.assertFalse(hasattr(cfg.tank, "max_speed_height_pickup"))

    def test_cargo_tunable_defaults(self):
        cfg = PacketConfig()
        self.assertAlmostEqual(cfg.cargo.pickup_radius, 15.0)
        self.assertAlmostEqual(cfg.cargo.max_pickup_altitude, 10.0)
        self.assertAlmostEqual(cfg.cargo.ground_z, 0.0)

    def test_cargo_tunables_load_from_toml(self):
        import tempfile

        toml = (
            "[cargo]\n"
            "pickup_radius = 22.5\n"
            "max_pickup_altitude = 4.0\n"
            "ground_z = -1.0\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(toml)
            path = fh.name
        cfg = PacketConfig.load(path)
        self.assertAlmostEqual(cfg.cargo.pickup_radius, 22.5)
        self.assertAlmostEqual(cfg.cargo.max_pickup_altitude, 4.0)
        self.assertAlmostEqual(cfg.cargo.ground_z, -1.0)


class CarryingInfoLayoutTests(unittest.TestCase):
    def test_byte_layout_matches_client(self):
        # Net_HandleCarryingInfo @ 0x0046e190 reads, in order:
        #   int32 entityId, byte hasCargo, byte cargoType, byte unk_v2
        pkt = CarryingInfoPacket(
            player_id=0x01020304,
            has_cargo=True,
            cargo_type=25,
            variant=2,
        )
        data = pkt.serialize()

        self.assertEqual(data[0], 0x29, "opcode")
        self.assertEqual(data[1:5], bytes([0x01, 0x02, 0x03, 0x04]), "entityId int32 BE")
        self.assertEqual(data[5], 1, "hasCargo")
        self.assertEqual(data[6], 25, "cargoType (carried unit type)")
        self.assertEqual(data[7], 2, "unk_v2 (team/colour variant)")
        self.assertEqual(len(data), 8)

    def test_not_carrying_sets_flag_zero(self):
        pkt = CarryingInfoPacket(player_id=7, has_cargo=False, cargo_type=0, variant=0)
        data = pkt.serialize()
        self.assertEqual(data[5], 0, "hasCargo cleared")


class CargoBoxDefinitionTests(unittest.TestCase):
    def test_definition_writes_contained_unit_type(self):
        # A cargo box is unit_type 19; the contained unit type rides in the
        # DEFINITION block (ID_BITS_UNIT_CARGO) and must come from the entity,
        # not a hardcoded constant.
        ent = GameEntity(net_id=5, unit_type=19, team_id=1)
        ent.cargo_contained_type = 30  # not the legacy hardcoded 25

        writer = PacketWriter()
        EntitySerializer(writer).serialize(
            ent, force_definition=True, forced_mask=UpdateMask.DEFINITION
        )

        reader = PacketReader(writer.get_bytes())
        self.assertEqual(reader.read_int32(), 5, "net_id")
        reader.read_bits(1)  # is_manned
        mask = reader.read_bits(10)
        self.assertTrue(mask & UpdateMask.DEFINITION)
        reader.read_bits(BANK_SELECTOR_BITS)
        self.assertEqual(reader.read_bits(ID_BITS_UNIT), 19, "unit_type")
        reader.read_bits(ID_BITS_TEAM)
        reader.read_bits(ID_BITS_TEAM)
        self.assertEqual(
            reader.read_bits(ID_BITS_UNIT_CARGO), 30, "contained type from entity"
        )


from core.entity_manager import EntityManager  # noqa: E402
from core.cargo import CargoSystem  # noqa: E402
from network.packets.gameplay import DeleteObjectPacket  # noqa: E402


def _carrier(mgr, pos=(0.0, 0.0, 1.0), vel=(0.0, 0.0, 0.0), team=1):
    ent = mgr.create_entity(unit_type=1, team_id=team, pos=pos)
    ent.vel = vel
    ent.is_manned = True
    return ent


def _box(mgr, pos, contained=30, team=1):
    box = mgr.create_entity(unit_type=19, team_id=team, pos=pos)
    box.cargo_contained_type = contained
    box.is_manned = False
    return box


class PickupEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.mgr = EntityManager()
        self.cargo = CargoSystem(self.mgr, max_pickup_speed=3.5, max_pickup_altitude=10.0)

    def test_slow_low_uncarried_is_eligible(self):
        carrier = _carrier(self.mgr, pos=(0, 0, 2.0), vel=(1.0, 1.0, 0.0))
        self.assertTrue(self.cargo.is_eligible(carrier))

    def test_already_carrying_is_ineligible(self):
        carrier = _carrier(self.mgr, vel=(0.0, 0.0, 0.0))
        carrier.carried_cargo_type = 25
        self.assertFalse(self.cargo.is_eligible(carrier))

    def test_too_fast_is_ineligible(self):
        carrier = _carrier(self.mgr, vel=(5.0, 0.0, 0.0))
        self.assertFalse(self.cargo.is_eligible(carrier))

    def test_too_high_is_ineligible(self):
        carrier = _carrier(self.mgr, pos=(0, 0, 50.0), vel=(0.0, 0.0, 0.0))
        self.assertFalse(self.cargo.is_eligible(carrier))


class PickupTargetingTests(unittest.TestCase):
    def setUp(self):
        self.mgr = EntityManager()
        self.cargo = CargoSystem(self.mgr, pickup_radius=15.0)

    def test_finds_nearest_box_in_radius(self):
        carrier = _carrier(self.mgr, pos=(0, 0, 1.0))
        far = _box(self.mgr, pos=(10, 0, 1.0))
        near = _box(self.mgr, pos=(3, 0, 1.0))
        self.assertIs(self.cargo.find_nearest_box(carrier), near)
        self.assertIsNotNone(far)

    def test_no_box_outside_radius(self):
        carrier = _carrier(self.mgr, pos=(0, 0, 1.0))
        _box(self.mgr, pos=(100, 0, 1.0))
        self.assertIsNone(self.cargo.find_nearest_box(carrier))


class PickupAttachTests(unittest.TestCase):
    def setUp(self):
        self.mgr = EntityManager()
        self.cargo = CargoSystem(self.mgr)

    def test_pickup_attaches_and_emits_carrying_info(self):
        carrier = _carrier(self.mgr, pos=(0, 0, 1.0), vel=(0.5, 0.0, 0.0), team=2)
        box = _box(self.mgr, pos=(2, 0, 1.0), contained=27)

        packets = self.cargo.try_pickup(carrier, carrier_id=99)

        self.assertEqual(carrier.carried_cargo_type, 27)
        self.assertEqual(carrier.carried_variant, 2)
        self.assertIsNone(self.mgr.get_entity(box.net_id), "box removed from world")

        infos = [p for p in packets if isinstance(p, CarryingInfoPacket)]
        dels = [p for p in packets if isinstance(p, DeleteObjectPacket)]
        self.assertEqual(len(infos), 1)
        self.assertTrue(infos[0].has_cargo)
        self.assertEqual(infos[0].cargo_type, 27)
        self.assertEqual(infos[0].player_id, 99)
        self.assertEqual(len(dels), 1)
        self.assertEqual(dels[0].net_id, box.net_id)

    def test_ineligible_carrier_picks_up_nothing(self):
        carrier = _carrier(self.mgr, vel=(20.0, 0.0, 0.0))
        _box(self.mgr, pos=(1, 0, 1.0))
        self.assertEqual(self.cargo.try_pickup(carrier, carrier_id=1), [])
        self.assertIsNone(carrier.carried_cargo_type)


class DeployDropTests(unittest.TestCase):
    def setUp(self):
        self.mgr = EntityManager()
        self.cargo = CargoSystem(self.mgr)

    def test_deploy_spawns_unmanned_unit_of_contained_type(self):
        carrier = _carrier(self.mgr, pos=(5, 6, 3.0), team=2)
        carrier.carried_cargo_type = 30
        carrier.carried_variant = 2

        packets = self.cargo.handle_drop_request(carrier, carrier_id=7, deploy=True)

        deployed = [e for e in self.mgr.get_all() if e.unit_type == 30]
        self.assertEqual(len(deployed), 1)
        self.assertFalse(deployed[0].is_manned, "deployed unit is static/anchored")
        self.assertEqual(deployed[0].team_id, 2)
        self.assertIsNone(carrier.carried_cargo_type, "carry cleared")

        infos = [p for p in packets if isinstance(p, CarryingInfoPacket)]
        self.assertEqual(len(infos), 1)
        self.assertFalse(infos[0].has_cargo)

    def test_drop_spawns_loose_box_with_contained_type(self):
        carrier = _carrier(self.mgr, pos=(5, 6, 3.0), team=1)
        carrier.carried_cargo_type = 30

        self.cargo.handle_drop_request(carrier, carrier_id=7, deploy=False)

        boxes = [e for e in self.mgr.get_all() if e.unit_type == 19]
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0].cargo_contained_type, 30)
        self.assertFalse(boxes[0].is_manned)
        self.assertIsNone(carrier.carried_cargo_type)

    def test_deploy_without_cargo_is_noop(self):
        carrier = _carrier(self.mgr)
        before = len(self.mgr.get_all())
        self.assertEqual(self.cargo.handle_drop_request(carrier, carrier_id=7, deploy=True), [])
        self.assertEqual(len(self.mgr.get_all()), before)


class PickupTickTests(unittest.TestCase):
    def test_tick_collects_pickups_independent_of_sync_mode(self):
        # Regression: the pickup scan used to be gated behind
        # should_run_server_simulation, so it never ran in client_state_relay
        # mode. cargo_pickup_tick must work for any server regardless of mode.
        import main
        from types import SimpleNamespace

        mgr = EntityManager()
        cargo = CargoSystem(mgr)
        carrier = _carrier(mgr, pos=(0, 0, 1.0), vel=(0.0, 0.0, 0.0))
        _box(mgr, pos=(2, 0, 1.0), contained=25)
        session = SimpleNamespace(entity=carrier, player_id=5, is_logged_in=True)
        server = SimpleNamespace(sessions=[session], cargo=cargo)

        packets = main.cargo_pickup_tick(server)

        infos = [p for p in packets if isinstance(p, CarryingInfoPacket)]
        self.assertEqual(len(infos), 1)
        self.assertTrue(infos[0].has_cargo)
        self.assertEqual(carrier.carried_cargo_type, 25)


class DescribePickupTests(unittest.TestCase):
    def test_reports_eligibility_and_nearest_distance(self):
        mgr = EntityManager()
        cargo = CargoSystem(
            mgr, max_pickup_speed=3.5, max_pickup_altitude=10.0, pickup_radius=15.0
        )
        carrier = _carrier(mgr, pos=(0, 0, 2.0), vel=(1.0, 0.0, 0.0))
        _box(mgr, pos=(3, 0, 2.0))

        d = cargo.describe_pickup(carrier)
        self.assertTrue(d["eligible"])
        self.assertFalse(d["carrying"])
        self.assertAlmostEqual(d["speed"], 1.0)
        self.assertAlmostEqual(d["altitude"], 2.0)
        self.assertAlmostEqual(d["nearest_dist"], 3.0)

    def test_reports_ineligible_when_too_high(self):
        mgr = EntityManager()
        cargo = CargoSystem(mgr, max_pickup_altitude=10.0)
        carrier = _carrier(mgr, pos=(0, 0, 50.0))
        d = cargo.describe_pickup(carrier)
        self.assertFalse(d["eligible"])
        self.assertGreater(d["altitude"], 10.0)


if __name__ == "__main__":
    unittest.main()
