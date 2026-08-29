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

    def test_calibrated_scales_pinned(self):
        # Calibrated via tools/fit_physics.py against the 2026-06-15 crossroads
        # capture, open-loop objective (drift mean 695u -> 141u -> 79u). Pin so
        # they can't silently regress; update both here and _MODEL_DEFAULTS after
        # a re-fit.
        self.assertAlmostEqual(self.t.get("thrust_scale"), 46.016, places=3)
        self.assertAlmostEqual(self.t.get("torque_scale"), 280.355, places=3)
        self.assertAlmostEqual(self.t.get("max_thrust"), 1317.781, places=3)
        self.assertAlmostEqual(self.t.get("control_divisor"), 372.336, places=3)
        self.assertAlmostEqual(self.t.get("angular_damp"), 2.824, places=3)

    def test_friction_constants_re_fixed(self):
        self.assertAlmostEqual(self.t.get("friction_thrust"), 0.1)
        self.assertAlmostEqual(self.t.get("friction_idle"), 2.0)


if __name__ == "__main__":
    unittest.main()
