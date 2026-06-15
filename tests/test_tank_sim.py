import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.packets.packet_config import PacketConfig
from core.entity import GameEntity
from core.sim.tank import TankSim
from core.sim.inputs import ACTION_THROTTLE


class TankSimTests(unittest.TestCase):
    def setUp(self):
        self.sim = TankSim(PacketConfig())

    def test_idle_tank_does_not_drift_horizontally(self):
        ent = GameEntity(net_id=1, unit_type=0, team_id=1, pos=(0.0, 0.0, 10.0))
        for _ in range(20):
            self.sim.step(ent, dt=0.1)
        self.assertAlmostEqual(ent.pos[0], 0.0, places=3)
        self.assertAlmostEqual(ent.pos[1], 0.0, places=3)

    def test_throttle_moves_tank(self):
        ent = GameEntity(net_id=1, unit_type=0, team_id=1, pos=(0.0, 0.0, 10.0))
        ent.actions = {ACTION_THROTTLE: 1.0}
        start = ent.pos
        for _ in range(20):
            self.sim.step(ent, dt=0.1)
        moved = abs(ent.pos[0] - start[0]) + abs(ent.pos[1] - start[1])
        self.assertGreater(moved, 1.0, "throttle should move the tank")

    def test_writes_velocity_back_to_entity(self):
        ent = GameEntity(net_id=1, unit_type=0, team_id=1, pos=(0.0, 0.0, 10.0))
        ent.actions = {ACTION_THROTTLE: 1.0}
        self.sim.step(ent, dt=0.1)
        self.assertEqual(len(ent.vel), 3)


if __name__ == "__main__":
    unittest.main()
