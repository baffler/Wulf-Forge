import unittest

from core.entity import GameEntity, UpdateMask
from core.entity_manager import (
    EntityManager,
    MAX_UPDATE_ENTITIES,
    MAX_UPDATE_PACKET_BYTES,
    STATIC_ANCHOR_MASK,
)
from network.streams import PacketReader


def read_update_entity_count(payload: bytes) -> int:
    reader = PacketReader(payload[1:])
    if payload[0] == 0x0F:
        reader.read_int32()
    reader.read_int32()
    if reader.read_bits(1):
        reader.read_bits(5)
        reader.read_bits(10)
        reader.read_bits(10)
    return reader.read_bits(8)


class EntityManagerTests(unittest.TestCase):
    def test_static_anchor_packets_zero_unmanned_motion_without_dirtying_entities(self):
        entities = EntityManager()
        player = entities.create_entity(unit_type=0, team_id=1, pos=(10.0, 10.0, 10.0))
        player.is_manned = True
        player.clear_dirty()

        static_obj = entities.create_entity(unit_type=27, team_id=1, pos=(20.0, 20.0, 2.0))
        static_obj.is_manned = False
        static_obj.vel = (1.0, 2.0, 3.0)
        static_obj.spin = (4.0, 5.0, 6.0)
        static_obj.clear_dirty()

        payloads = entities.build_static_anchor_packets(
            sequence_num=1234,
            local_stats=(0.75, 0.5),
        )

        self.assertEqual(len(payloads), 1)
        payload = payloads[0]
        self.assertEqual(payload[0], 0x0E)
        reader = PacketReader(payload[1:])
        self.assertEqual(reader.read_int32(), 1234)
        self.assertEqual(reader.read_bits(1), 1)
        self.assertEqual(static_obj.vel, (0.0, 0.0, 0.0))
        self.assertEqual(static_obj.spin, (0.0, 0.0, 0.0))
        self.assertEqual(static_obj.pending_mask, 0)
        self.assertEqual(player.pending_mask, 0)
        self.assertEqual(STATIC_ANCHOR_MASK, UpdateMask.POS | UpdateMask.VEL | UpdateMask.ROT | UpdateMask.SPIN | UpdateMask.HARD_SYNC)

    def test_static_anchor_packets_are_split_below_the_udp_mtu(self):
        entities = EntityManager()
        for index in range(67):
            static_obj = entities.create_entity(
                unit_type=27,
                team_id=1,
                pos=(float(index), 20.0, 2.0),
            )
            static_obj.is_manned = False
            static_obj.clear_dirty()

        payloads = entities.build_static_anchor_packets(
            sequence_num=1234,
            local_stats=(1.0, 1.0),
        )

        self.assertGreater(len(payloads), 1)
        self.assertEqual(sum(read_update_entity_count(payload) for payload in payloads), 67)
        self.assertTrue(all(payload[0] == 0x0E for payload in payloads))
        self.assertTrue(all(len(payload) <= MAX_UPDATE_PACKET_BYTES for payload in payloads))

    def test_general_update_packets_split_by_encoded_byte_size(self):
        entities = EntityManager()
        full_update_mask = (
            UpdateMask.DEFINITION
            | UpdateMask.POS
            | UpdateMask.VEL
            | UpdateMask.ROT
            | UpdateMask.SPIN
            | UpdateMask.HEALTH
            | UpdateMask.ENERGY
            | UpdateMask.OWNER
            | UpdateMask.HARD_SYNC
        )
        updates = []
        for index in range(100):
            entity = GameEntity(
                net_id=index + 1,
                unit_type=27,
                team_id=1,
                pos=(float(index), 20.0, 2.0),
            )
            entity.pending_mask = full_update_mask
            updates.append(entity)

        payloads = entities.build_update_packets(
            updates,
            sequence_num=4321,
            is_view_update=False,
            local_stats=(0.75, 0.5),
        )

        self.assertGreater(len(payloads), 1)
        self.assertEqual(sum(read_update_entity_count(payload) for payload in payloads), 100)
        self.assertTrue(all(len(payload) <= MAX_UPDATE_PACKET_BYTES for payload in payloads))

    def test_general_update_packets_enforce_eight_bit_entity_count(self):
        updates = []
        for index in range(300):
            entity = GameEntity(net_id=index + 1, pos=(float(index), 0.0, 0.0))
            entity.pending_mask = UpdateMask.POS
            updates.append(entity)

        payloads = EntityManager().build_update_packets(
            updates,
            sequence_num=9876,
            is_view_update=False,
            max_packet_bytes=100_000,
        )

        counts = [read_update_entity_count(payload) for payload in payloads]
        self.assertEqual(MAX_UPDATE_ENTITIES, 255)
        self.assertEqual(counts, [255, 45])

    def test_general_update_packets_reject_an_impossible_single_record_budget(self):
        entity = GameEntity(net_id=1, pos=(1.0, 2.0, 3.0))
        entity.pending_mask = UpdateMask.POS

        with self.assertRaisesRegex(ValueError, "entity 1 update"):
            EntityManager().build_update_packets(
                [entity],
                sequence_num=1,
                is_view_update=False,
                max_packet_bytes=8,
            )


if __name__ == "__main__":
    unittest.main()
