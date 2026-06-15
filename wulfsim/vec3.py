"""Minimal mutable 3-vector for the pure physics core (no external deps).

Client convention: +Z is up (gravity acts on z). The render layer maps to ursina's
Y-up at its own boundary; the core never deals with the renderer's axes.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(slots=True)
class Vec3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def copy(self) -> "Vec3":
        return Vec3(self.x, self.y, self.z)

    def set(self, x: float, y: float, z: float) -> None:
        self.x, self.y, self.z = x, y, z

    def zero(self) -> None:
        self.x = self.y = self.z = 0.0

    def length(self) -> float:
        # Mirrors Math_ClassifyAndCheckResult used as a vector magnitude in the thrust path.
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)
