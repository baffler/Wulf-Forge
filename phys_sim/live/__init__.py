"""Live game attachment + drift measurement.

Reads the running wulfram2.exe process memory at the known entity-physics offsets and the
gravity global, so the sandbox can be seeded from / compared against the real client and we
can measure exactly where the ported math drifts. This is the ground-truth instrument for
driving the sim to 1:1.
"""
