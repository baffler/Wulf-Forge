"""Real map terrain heightmap for the server-side tank sim.

Loads a Wulfram `land` file (ASCII): line 1 = "GWxGH" grid dims, line 2 =
"WWxWH" world dims, then GW*GH lines of "<col> <height>" in row-major order
(the first column is ignored; the height is the world-unit ground Z at that
grid node). Provides bilinear `height_at(x, y)` over world coords [0, WW]x[0, WH]
so the sim's suspension/ground-clamp track the real terrain instead of a flat
plane (mirrors the client's Terrain_GetHeightAtPoint @ 0x004fa340).

Orientation (row-major vs transposed) can't be confirmed statically; `transpose`
flips it if hills land on the wrong axis in-game.
"""
from __future__ import annotations

import os
from typing import List, Optional


class MapHeightMap:
    def __init__(self, grid_w: int, grid_h: int, world_w: float, world_h: float,
                 heights: List[float], *, transpose: bool = False):
        self.gw = grid_w
        self.gh = grid_h
        self.world_w = world_w
        self.world_h = world_h
        self.sx = world_w / (grid_w - 1)
        self.sy = world_h / (grid_h - 1)
        self.h = heights
        self.transpose = transpose

    def _node(self, ix: int, iy: int) -> float:
        idx = ix * self.gh + iy if self.transpose else iy * self.gw + ix
        return self.h[idx]

    def height_at(self, x: float, y: float) -> float:
        """Bilinearly interpolated ground height at world (x, y); edge-clamped."""
        gx = x / self.sx
        gy = y / self.sy
        ix = min(max(int(gx), 0), self.gw - 2)
        iy = min(max(int(gy), 0), self.gh - 2)
        tx = min(max(gx - ix, 0.0), 1.0)
        ty = min(max(gy - iy, 0.0), 1.0)
        h00 = self._node(ix, iy)
        h10 = self._node(ix + 1, iy)
        h01 = self._node(ix, iy + 1)
        h11 = self._node(ix + 1, iy + 1)
        h0 = h00 * (1 - tx) + h10 * tx
        h1 = h01 * (1 - tx) + h11 * tx
        return h0 * (1 - ty) + h1 * ty

    @classmethod
    def from_land_file(cls, path: str, *, transpose: bool = False) -> "MapHeightMap":
        with open(path, "r", encoding="ascii", errors="replace") as f:
            lines = f.read().splitlines()
        gw, gh = (int(v) for v in lines[0].split("x"))
        ww, wh = (float(v) for v in lines[1].split("x"))
        heights: List[float] = []
        for line in lines[2:2 + gw * gh]:
            parts = line.split()
            heights.append(float(parts[1]) if len(parts) >= 2 else 0.0)
        if len(heights) < gw * gh:  # pad a short/truncated file
            heights.extend([0.0] * (gw * gh - len(heights)))
        return cls(gw, gh, ww, wh, heights, transpose=transpose)


def load_map_heightmap(map_name: str, maps_root: str = "shared/data/maps",
                       *, transpose: bool = False) -> Optional[MapHeightMap]:
    """Load the `land` heightmap for a map, or None if absent."""
    if not map_name:
        return None
    path = os.path.join(maps_root, map_name, "land")
    if not os.path.exists(path):
        return None
    try:
        return MapHeightMap.from_land_file(path, transpose=transpose)
    except (OSError, ValueError, IndexError):
        return None
