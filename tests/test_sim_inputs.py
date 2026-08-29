import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.sim.inputs import controls_from_actions, ACTION_TURN, ACTION_THROTTLE, ACTION_STRAFE


class InputMappingTests(unittest.TestCase):
    def test_maps_action_axes_to_inputs(self):
        actions = {ACTION_TURN: 1.0, ACTION_THROTTLE: -0.5, ACTION_STRAFE: 0.25}
        inp = controls_from_actions(actions)
        self.assertAlmostEqual(inp.turn, 1.0)
        self.assertAlmostEqual(inp.throttle, -0.5)
        self.assertAlmostEqual(inp.strafe, 0.25)

    def test_missing_actions_default_zero(self):
        inp = controls_from_actions({})
        self.assertEqual((inp.throttle, inp.strafe, inp.turn, inp.vertical), (0.0, 0.0, 0.0, 0.0))

    def test_clamps_to_unit_range(self):
        inp = controls_from_actions({ACTION_THROTTLE: 5.0, ACTION_TURN: -9.0})
        self.assertAlmostEqual(inp.throttle, 1.0)
        self.assertAlmostEqual(inp.turn, -1.0)


if __name__ == "__main__":
    unittest.main()
