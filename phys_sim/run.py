"""phys_sim entry point.

    python run.py                         # standalone sandbox + REST API + sliders
    python run.py --no-api                # without the REST server
    python run.py --attach --entity-ptr 0x6XXXXX,0x0   # attach to a running wulfram2.exe

Starts the REST server on a background thread (shares the live Tunables/SimWorld) and then
runs the ursina window on the main thread.
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# Physics now lives in the top-level `wulfsim` package (re-exported by sim shims).
sys.path.insert(0, os.path.dirname(HERE))

from tunables import Tunables          # noqa: E402
from world import SimWorld             # noqa: E402


def _parse_chain(text: str) -> tuple[int, ...]:
    return tuple(int(x.strip(), 16) for x in text.split(",") if x.strip())


def main() -> None:
    ap = argparse.ArgumentParser(description="Wulfram II vehicle physics sandbox")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8077)
    ap.add_argument("--no-api", action="store_true", help="don't start the REST server")
    ap.add_argument("--attach", action="store_true", help="attach to a running wulfram2.exe")
    ap.add_argument("--entity-ptr", default="",
                    help="comma-separated hex pointer chain to the player entity, e.g. 0x678abc,0x0")
    ap.add_argument("--config", default="packets.toml", help="tunable overrides file")
    args = ap.parse_args()

    tun = Tunables()
    tun.load_overrides(os.path.join(HERE, args.config))
    world = SimWorld(tun)

    attach_state = {"report": None}
    tracker = None
    if args.attach:
        from live.attach import GameAttach, AttachConfig
        from live.drift import DriftTracker
        cfg = AttachConfig(entity_ptr_chain=_parse_chain(args.entity_ptr))
        ga = GameAttach(cfg)
        try:
            ga.open()
            print(f"[attach] connected to {cfg.process_name}")
            if not cfg.entity_ptr_chain:
                print("[attach] no --entity-ptr given; drift inert until you supply the chain")
        except Exception as e:  # noqa: BLE001
            print(f"[attach] failed: {e}")
        tracker = DriftTracker(attach=ga)

    if not args.no_api:
        from api import server as api_server
        api_server.serve(world, host=args.host, port=args.port, attach_state=attach_state)
        print(f"[rest] http://{args.host}:{args.port}/  (try /tunables, /state, /drift)")

    from render.app import run_app
    run_app(world, tracker=tracker, attach_state=attach_state, port=args.port)


if __name__ == "__main__":
    main()
