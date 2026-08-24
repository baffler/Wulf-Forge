import unittest

from network.packets.behavior import (
    BehaviorPacket,
    SCOUT_BLUE_JET_POINTS,
    SCOUT_RED_JET_POINTS,
    TANK_BLUE_JET_POINTS,
    TANK_RED_JET_POINTS,
)
from network.packets.packet_config import BehaviorConfig, PacketConfig


def read_fixed1616(data: bytes, offset: int) -> float:
    raw = int.from_bytes(data[offset : offset + 4], "big", signed=True)
    return raw / 65536.0


def read_u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def quantize_fixed1616(value: float) -> float:
    return round(value * 65536.0) / 65536.0


def skip_jet_reaction_surfaces(data: bytes, offset: int, surface_count: int = 4) -> int:
    for _ in range(surface_count):
        count = read_u32(data, offset)
        offset += 4
        offset += count * ((6 * 4) + 4)
        offset += 4
    return offset


class BehaviorConfigTests(unittest.TestCase):
    def test_tank_and_scout_generic_vehicle_profiles_are_serialized_separately(self):
        cfg = BehaviorConfig(
            weapons_units_count=0,
            unit_count=0,
            vehicle_physics_count=2,
            active_vehicles_count=0,
        )

        payload = BehaviorPacket(cfg).serialize()
        offset = 1 + 95
        expected_profiles = (
            (20.0, 4.0, 700, 550, 0.8, 0.05, 1.3, 0, 33000),
            (20.0, 4.0, 700, 550, 0.8, 0.15, 1.1, 0, 13000),
        )

        for expected in expected_profiles:
            actual = (
                read_fixed1616(payload, offset),
                read_fixed1616(payload, offset + 4),
                read_u32(payload, offset + 8),
                read_u32(payload, offset + 12),
                read_fixed1616(payload, offset + 16),
                read_fixed1616(payload, offset + 20),
                read_fixed1616(payload, offset + 24),
                read_u32(payload, offset + 28),
                read_u32(payload, offset + 32),
            )
            self.assertEqual(actual, tuple(
                quantize_fixed1616(value) if isinstance(value, float) else value
                for value in expected
            ))
            offset += 36

    def test_tank_and_scout_active_vehicle_tuning_match_ghidra_defaults(self):
        cfg = BehaviorConfig(
            weapons_units_count=0,
            unit_count=0,
            vehicle_physics_count=0,
            active_vehicles_count=2,
        )

        payload = BehaviorPacket(cfg).serialize()
        offset = skip_jet_reaction_surfaces(payload, 1 + 95)

        tank_values = tuple(read_fixed1616(payload, offset + i * 4) for i in range(7))
        offset += 7 * 4
        scout_values = tuple(read_fixed1616(payload, offset + i * 4) for i in range(9))

        self.assertEqual(
            tank_values,
            tuple(quantize_fixed1616(value) for value in (4.5, 85.0, 69.7, 80.0, 2000.0, 3.25, 1.0)),
        )
        self.assertEqual(
            scout_values,
            tuple(quantize_fixed1616(value) for value in (4.5, 85.0, 38.0, 72.0, 85.0, 2000.0, 4.9, 3.5, 1.0)),
        )

    def test_tank_hover_height_is_serialized_from_config(self):
        cfg = BehaviorConfig(
            weapons_units_count=0,
            unit_count=0,
            vehicle_physics_count=0,
            active_vehicles_count=1,
        )
        cfg.active_vehicle_physics.hover_height = 12.5

        payload = BehaviorPacket(cfg).serialize()

        header_size = 95
        active_vehicle_start = skip_jet_reaction_surfaces(payload, 1 + header_size)
        tank_hover_height_offset = active_vehicle_start + (5 * 4)

        self.assertEqual(read_fixed1616(payload, tank_hover_height_offset), 12.5)

    def test_default_packet_config_uses_four_times_stock_tank_hover_height(self):
        cfg = PacketConfig.load("packets.toml")

        self.assertEqual(cfg.behavior.active_vehicle_physics.tank_hover_height, 13.0)

    def test_jet_reaction_surfaces_use_canonical_vehicle_geometry(self):
        cfg = BehaviorConfig(
            weapons_units_count=0,
            unit_count=0,
            vehicle_physics_count=0,
            active_vehicles_count=0,
        )

        payload = BehaviorPacket(cfg).serialize()

        offset = 1 + 95
        expected_surfaces = (
            TANK_RED_JET_POINTS,
            TANK_BLUE_JET_POINTS,
            SCOUT_RED_JET_POINTS,
            SCOUT_BLUE_JET_POINTS,
        )
        for expected_points in expected_surfaces:
            count = read_u32(payload, offset)
            offset += 4
            self.assertEqual(count, 4)

            positions = []
            normals = []
            for _sample in range(count):
                pos = tuple(read_fixed1616(payload, offset + i * 4) for i in range(3))
                offset += 12
                normal = tuple(read_fixed1616(payload, offset + i * 4) for i in range(3))
                offset += 12
                _flag = read_u32(payload, offset)
                offset += 4
                positions.append(pos)
                normals.append(normal)

            self.assertEqual(
                set(positions),
                {
                    tuple(quantize_fixed1616(value) for value in point[:3])
                    for point in expected_points
                },
            )
            self.assertEqual(set(normals), {(0.0, 0.0, -1.0)})
            self.assertEqual(read_fixed1616(payload, offset), 0.0)
            offset += 4


if __name__ == "__main__":
    unittest.main()
