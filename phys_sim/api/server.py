"""REST API for live tuning + state inspection.

Runs Flask on a background thread so it shares the same Tunables / SimWorld instance the
renderer uses -- edits land on the next physics tick. Endpoints:

    GET  /tunables                 -> full registry (name, value, lo, hi, group, kind, info)
    GET  /tunables/<name>          -> single value
    POST /tunables    {name:value} -> bulk live patch (clamped to each tunable's range)
    GET  /state                    -> live vehicle state + effective gravity
    POST /reset                    -> reset vehicle to spawn
    POST /vehicle/<tank|scout|bomber> -> switch active vehicle
    GET  /drift                    -> live-vs-sim drift report (if attached to a game)
"""
from __future__ import annotations

import threading

from flask import Flask, jsonify, request


def create_app(world, attach_state=None) -> Flask:
    app = Flask("phys_sim")
    t = world.tunables

    @app.get("/")
    def index():
        return jsonify({
            "service": "phys_sim",
            "endpoints": ["/tunables", "/tunables/<name>", "/state", "/reset",
                          "/vehicle/<kind>", "/drift"],
        })

    @app.get("/tunables")
    def get_tunables():
        return jsonify(t.describe())

    @app.get("/tunables/<name>")
    def get_tunable(name):
        if not t.has(name):
            return jsonify({"error": f"unknown tunable '{name}'"}), 404
        return jsonify({"name": name, "value": t.get(name)})

    @app.post("/tunables")
    def set_tunables():
        data = request.get_json(force=True, silent=True) or {}
        applied, unknown = {}, []
        for name, value in data.items():
            if t.has(name):
                applied[name] = t.set(name, value).value
            else:
                unknown.append(name)
        return jsonify({"applied": applied, "unknown": unknown})

    @app.get("/state")
    def get_state():
        s = world.state()
        s["effective_gravity"] = t.effective_gravity
        return jsonify(s)

    @app.post("/reset")
    def reset():
        world.reset()
        return jsonify({"ok": True})

    @app.post("/vehicle/<kind>")
    def set_vehicle(kind):
        if world.set_vehicle(kind):
            return jsonify({"ok": True, "kind": kind})
        return jsonify({"error": f"unknown vehicle '{kind}'"}), 400

    @app.get("/drift")
    def drift():
        if attach_state is None or not attach_state.get("report"):
            return jsonify({"attached": False, "report": None})
        return jsonify({"attached": True, "report": attach_state["report"]})

    return app


def serve(world, host="127.0.0.1", port=8077, attach_state=None) -> threading.Thread:
    app = create_app(world, attach_state=attach_state)

    def _run():
        app.run(host=host, port=port, threaded=True, use_reloader=False, debug=False)

    th = threading.Thread(target=_run, name="phys_sim-rest", daemon=True)
    th.start()
    return th
