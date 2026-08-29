"""Heightmap terrain with interpolated height sampling.

Analogue of Terrain_GetHeightAtPoint @ 0x004fa340, which locates the grid cell + triangle
under a world XY point and returns the interpolated ground height. Here we back it with an
editable procedural heightmap (rolling hills) and bilinear sampling so suspension can track
slopes. The client also uses this for ground-penetration tests (Collision_CheckObjectGroundHeight
@ 0x00500f60) and a ceiling query (Collision_CheckEntityAgainstCeiling @ 0x004fb050).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List


@dataclass(slots=True)
class HeightMap:
    size: int = 64            # grid cells per side
    spacing: float = 8.0      # world units between grid samples
    amplitude: float = 18.0   # hill height
    base: float = 0.0         # ground plane Z
    _h: List[List[float]] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        n = self.size + 1
        self._h = [[self._procedural(ix, iy) for iy in range(n)] for ix in range(n)]

    def _procedural(self, ix: int, iy: int) -> float:
        # Smooth rolling hills; deterministic so REST/sliders see a stable world.
        fx = ix / self.size * math.pi * 2.0
        fy = iy / self.size * math.pi * 2.0
        h = (math.sin(fx * 1.3) * math.cos(fy * 1.1)
             + 0.5 * math.sin(fx * 2.7 + 1.0) * math.cos(fy * 2.3))
        return self.base + h * self.amplitude * 0.5

    @property
    def extent(self) -> float:
        return self.size * self.spacing

    def height_at(self, x: float, y: float) -> float:
        """Bilinearly interpolated terrain height at world (x, y)."""
        half = self.extent * 0.5
        gx = (x + half) / self.spacing
        gy = (y + half) / self.spacing
        n = self.size
        if gx < 0 or gy < 0 or gx >= n or gy >= n:
            return self.base
        ix, iy = int(gx), int(gy)
        tx, ty = gx - ix, gy - iy
        h00 = self._h[ix][iy]
        h10 = self._h[ix + 1][iy]
        h01 = self._h[ix][iy + 1]
        h11 = self._h[ix + 1][iy + 1]
        h0 = h00 * (1 - tx) + h10 * tx
        h1 = h01 * (1 - tx) + h11 * tx
        return h0 * (1 - ty) + h1 * ty
