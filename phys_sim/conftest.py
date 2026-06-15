"""Make the repo root importable so the `sim` shims can re-export `wulfsim`.

The physics modules now live in the top-level `wulfsim` package; `phys_sim/sim`
is a thin compatibility shim that re-exports from it. When pytest runs from
inside `phys_sim/`, the repo root is not on sys.path, so add it here.
"""
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
