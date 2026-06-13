import unittest

from network.packets.behavior import BehaviorPacket
from network.packets.packet_config import BehaviorConfig, PacketConfig


def read_fixed1616(data: bytes, offset: int) -> float:
    raw = int.from_bytes(data[offset : offset + 4], "big", signed=True)
    return raw / 65536.0


def read_u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def skip_jet_reaction_surfaces(data: bytes, offset: int, surface_count: int = 4) -> int:
    for _ in range(surface_count):
        count = read_u32(data, offset)
        offset += 4
        offset += count * ((6 * 4) + 4)
        offset += 4
    return offset


class BehaviorConfigTests(unittest.TestCase):
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

    def test_default_packet_config_triples_tank_hover_height(self):
        cfg = PacketConfig.load("packets.toml")

        self.assertEqual(cfg.behavior.active_vehicle_physics.tank_hover_height, 9.75)

    def test_jet_reaction_surfaces_use_four_corner_samples_for_autolevel(self):
        cfg = BehaviorConfig(
            weapons_units_count=0,
            unit_count=0,
            vehicle_physics_count=0,
            active_vehicles_count=0,
        )

        payload = BehaviorPacket(cfg).serialize()

        offset = 1 + 95
        for _ in range(4):
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
                    (-2.0, -2.0, -0.5),
                    (2.0, -2.0, -0.5),
                    (-2.0, 2.0, -0.5),
                    (2.0, 2.0, -0.5),
                },
            )
            self.assertEqual(set(normals), {(0.0, 0.0, -0.75)})
            self.assertEqual(read_fixed1616(payload, offset), 5.0)
            offset += 4


if __name__ == "__main__":
    unittest.main()
