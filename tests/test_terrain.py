import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.sim.terrain import MapHeightMap, load_map_heightmap  # noqa: E402


def _write_land(tmp, text):
    p = Path(tmp) / "land"
    p.write_text(text, encoding="ascii")
    return str(p)


class MapHeightMapTests(unittest.TestCase):
    # 2x2 grid over a 10x10 world; row-major heights: (ix,iy)->idx iy*2+ix
    #   (0,0)=0  (1,0)=10  (0,1)=20  (1,1)=30
    LAND = "2x2\n10.000000x10.000000\n0 0\n1 10\n0 20\n1 30\n"

    def test_corner_nodes_exact(self):
        hm = MapHeightMap.from_land_file(_write_land(tempfile.mkdtemp(), self.LAND))
        self.assertAlmostEqual(hm.height_at(0.0, 0.0), 0.0)
        self.assertAlmostEqual(hm.height_at(10.0, 0.0), 10.0)   # ix=1,iy=0
        self.assertAlmostEqual(hm.height_at(0.0, 10.0), 20.0)   # ix=0,iy=1
        self.assertAlmostEqual(hm.height_at(10.0, 10.0), 30.0)  # ix=1,iy=1

    def test_bilinear_midpoint(self):
        hm = MapHeightMap.from_land_file(_write_land(tempfile.mkdtemp(), self.LAND))
        # center of the cell = average of the four corners = (0+10+20+30)/4 = 15
        self.assertAlmostEqual(hm.height_at(5.0, 5.0), 15.0)

    def test_off_map_edge_clamped(self):
        hm = MapHeightMap.from_land_file(_write_land(tempfile.mkdtemp(), self.LAND))
        self.assertAlmostEqual(hm.height_at(-50.0, -50.0), 0.0)    # clamps to (0,0)
        self.assertAlmostEqual(hm.height_at(999.0, 999.0), 30.0)   # clamps to (1,1)

    def test_missing_map_returns_none(self):
        self.assertIsNone(load_map_heightmap("does_not_exist", maps_root=tempfile.mkdtemp()))

    def test_real_crossroads_land_loads(self):
        hm = load_map_heightmap("crossroads")
        if hm is None:
            self.skipTest("crossroads land file not present")
        self.assertEqual((hm.gw, hm.gh), (129, 129))
        self.assertAlmostEqual(hm.world_w, 5600.0)
        # in-bounds sample returns a finite world-unit height
        z = hm.height_at(2578.0, 3040.0)
        self.assertGreater(z, 0.0)
        self.assertLess(z, 300.0)


if __name__ == "__main__":
    unittest.main()
