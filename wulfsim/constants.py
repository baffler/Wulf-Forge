"""Physics constants read directly out of wulfram2.exe (Ghidra project W2VULK).

Each value below was read from the binary's .data section at the listed address; do
not "tidy" them -- they are load-bearing for matching the client integration.
"""

# 0x00564e28 -> double 0.5 : the 1/2 in  x += v*dt + 1/2*a*dt^2
HALF = 0.5

# 0x00564f10 -> double 1000.0 : EntityPhysics_RunWorldTick computes dt = elapsed_ms / 1000.0
# i.e. the world tick is fed an integer millisecond delta and integrates in seconds.
TICK_DENOM_MS = 1000.0

# 0x00564fc0 -> float -1.0 : the lower clamp on every normalized control coefficient
# (VehicleTuningSlot_GetScaledValue / VehicleTuning_ComputeControlScalars). Range [-1.0, 1.0].
CONTROL_CLAMP_MIN = -1.0
CONTROL_CLAMP_MAX = 1.0

# 0x005738b8 -> gravity acceleration. Statically 0.0 in the image; written at runtime by
# Net_HandleBehavior from the BEHAVIOR(0x24) header `gravity_accel`. packets.toml default = 100.0.
# Used as a pure downward acceleration in EntityPhysics_PitchDown (accel.z -= gravity * s).
DEFAULT_GRAVITY = 100.0
