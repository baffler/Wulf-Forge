import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.packets.packet_config import PacketConfig
from core.sim.tunables import ServerTunables


class ServerTunablesTests(unittest.TestCase):
    def setUp(self):
        self.t = ServerTunables(PacketConfig())

    def test_exact_values_come_from_behavior(self):
        avp = PacketConfig().behavior.active_vehicle_physics
        self.assertAlmostEqual(self.t.get("turn_adjust"), avp.turn_adjust)
        self.assertAlmostEqual(self.t.get("move_adjust"), avp.move_adjust)
        self.assertAlmostEqual(self.t.get("strafe_adjust"), avp.strafe_adjust)
        self.assertAlmostEqual(self.t.get("max_velocity"), avp.max_velocity)
        self.assertAlmostEqual(self.t.get("max_altitude"), avp.max_altitude)

    def test_effective_gravity_is_force_times_pct(self):
        b = PacketConfig().behavior
        expected = b.header.gravity_force * b.active_vehicle_physics.gravity_pct
        self.assertAlmostEqual(self.t.effective_gravity, expected)

    def test_model_knobs_have_defaults(self):
        for k in ("thrust_scale", "torque_scale", "max_thrust", "hover_spring",
                  "hover_damp", "angular_damp", "control_divisor"):
            self.assertGreater(self.t.get(k), 0.0)


if __name__ == "__main__":
    unittest.main()
