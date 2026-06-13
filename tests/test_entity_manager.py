import unittest

from core.entity import UpdateMask
from core.entity_manager import EntityManager, STATIC_ANCHOR_MASK


class EntityManagerTests(unittest.TestCase):
    def test_static_anchor_packet_zeroes_unmanned_motion_without_dirtying_entities(self):
        entities = EntityManager()
        player = entities.create_entity(unit_type=0, team_id=1, pos=(10.0, 10.0, 10.0))
        player.is_manned = True
        player.clear_dirty()

        static_obj = entities.create_entity(unit_type=27, team_id=1, pos=(20.0, 20.0, 2.0))
        static_obj.is_manned = False
        static_obj.vel = (1.0, 2.0, 3.0)
        static_obj.spin = (4.0, 5.0, 6.0)
        static_obj.clear_dirty()

        payload = entities.build_static_anchor_packet(sequence_num=1234)

        self.assertIsNotNone(payload)
        self.assertEqual(payload[0], 0x0E)
        self.assertEqual(static_obj.vel, (0.0, 0.0, 0.0))
        self.assertEqual(static_obj.spin, (0.0, 0.0, 0.0))
        self.assertEqual(static_obj.pending_mask, 0)
        self.assertEqual(player.pending_mask, 0)
        self.assertEqual(STATIC_ANCHOR_MASK, UpdateMask.POS | UpdateMask.VEL | UpdateMask.ROT | UpdateMask.SPIN | UpdateMask.HARD_SYNC)


if __name__ == "__main__":
    unittest.main()
