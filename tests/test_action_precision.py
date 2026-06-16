"""Control-axis (action channel) quantization precision.

The client adopts the quantization params the server sends in the TRANSLATION
packet (records, by channel id) and uses them for BOTH decode and its own
outgoing encode (Net_DecodeQuantizedFloat / SyncAction_WriteChannelValue in
wulfram2.exe). So the server's GLOBAL_CONFIGS defines the precision. The analog
control axes (ids 1/2/3/6/7 via config 11, id 5 via config 10) are normalized
to [-1, 1], so those records must use max=1.0 / range=2.0 for full-precision
round-trip -- not the SCALAR_DEFAULT (max=1000) placeholder.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.translation_config import get_config_by_index  # noqa: E402


class ActionPrecisionTests(unittest.TestCase):
    def test_control_axis_configs_are_normalized(self):
        for idx in (10, 11):
            c = get_config_by_index(idx)
            self.assertAlmostEqual(c.max_value, 1.0, msg=f"cfg[{idx}] max")
            self.assertAlmostEqual(c.range, 2.0, msg=f"cfg[{idx}] range")

    def test_control_axis_round_trips_at_full_precision(self):
        c = get_config_by_index(11)
        for v in (0.0, 0.25, -0.25, 0.5, -0.5, 1.0, -1.0, 0.123, -0.876):
            _, raw, _bits = c.compress(v)
            back = c.decompress(0, raw)
            self.assertAlmostEqual(back, v, places=3, msg=f"round-trip {v} -> {back}")


if __name__ == "__main__":
    unittest.main()
