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

    def test_external_velocity_write_is_honored(self):
        # Simulates a jump impulse written to the entity between ticks: the sim
        # must integrate from it, not clobber it back to the cached body's value.
        # First settle the tank (its cached body builds up state and parks at the
        # max_altitude ceiling, which equals hover_height here). Then, in a single
        # external write, reposition it below the ceiling AND apply an upward
        # impulse. If the sim honors the entity transform it integrates from z=2
        # with vel.z=100 (tank ends up near ~5, clearly below the ceiling); if it
        # clobbers the write it stays parked up near the ceiling (~9).
        ent = GameEntity(net_id=1, unit_type=0, team_id=1, pos=(0.0, 0.0, 10.0))
        for _ in range(20):
            self.sim.step(ent, dt=0.1)  # let it settle near the ceiling
        ent.pos = (ent.pos[0], ent.pos[1], 2.0)   # reposition below the ceiling
        ent.vel = (0.001, 0.001, 100.0)            # jump impulse
        self.sim.step(ent, dt=0.1)
        self.assertGreater(ent.pos[2], 2.0 + 1.0,
                           "jump impulse on ent.vel must raise the tank")
        self.assertLess(ent.pos[2], 8.0,
                        "external pos+vel write must be honored, not clobbered "
                        "back up to the cached body's settled ceiling height")

    def test_coasting_tank_brakes_hard_on_release(self):
        # RE: friction is thrust-gated -- k=0.1 thrusting, k=2.0 coasting. A tank
        # with horizontal velocity and NO input must brake hard (idle k=2.0),
        # not glide (the old continuous ground_friction=0.8 let it coast).
        ent = GameEntity(net_id=1, unit_type=0, team_id=1, pos=(0.0, 0.0, 2.0))
        ent.vel = (40.0, 0.0, 0.0)  # moving, no input
        for _ in range(10):
            self.sim.step(ent, dt=0.1)
        self.assertLess(abs(ent.vel[0]), 8.0,
                        f"coasting tank should brake hard, vx={ent.vel[0]}")

    def test_hover_settles_without_oscillation(self):
        # Regression: at the 10Hz server tick (dt=0.1) the stiff suspension PD
        # (spring=200) is numerically unstable under explicit Euler and locks into
        # a perpetual limit cycle (z bouncing, vz swinging +-20) -> the tank looked
        # "very wobbly" in-game. The fix sub-steps the integration so the PD settles.
        ent = GameEntity(net_id=1, unit_type=0, team_id=1, pos=(0.0, 0.0, 7.7))
        for _ in range(40):
            self.sim.step(ent, dt=0.1)
        self.assertLess(abs(ent.vel[2]), 0.5,
                        f"hover still oscillating: vz={ent.vel[2]}")
        z_before = ent.pos[2]
        self.sim.step(ent, dt=0.1)
        self.assertLess(abs(ent.pos[2] - z_before), 0.2,
                        f"z still jumping between ticks: {z_before} -> {ent.pos[2]}")

    def test_external_position_write_is_honored(self):
        # Simulates a teleport: writing ent.pos between ticks must move the sim there.
        ent = GameEntity(net_id=1, unit_type=0, team_id=1, pos=(0.0, 0.0, 10.0))
        self.sim.step(ent, dt=0.1)
        ent.pos = (500.0, 500.0, 50.0)  # teleport
        self.sim.step(ent, dt=0.1)
        self.assertAlmostEqual(ent.pos[0], 500.0, delta=5.0)
        self.assertAlmostEqual(ent.pos[1], 500.0, delta=5.0)


if __name__ == "__main__":
    unittest.main()
