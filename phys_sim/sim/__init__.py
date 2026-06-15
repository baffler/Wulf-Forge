"""Compatibility shim: phys_sim.sim now re-exports the shared wulfsim package."""
from wulfsim import (  # noqa: F401
    vec3, constants, fixed, body, gravity, tuning,
    thrust, integrator, suspension, terrain, vehicle,
)
