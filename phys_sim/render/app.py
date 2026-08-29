"""ursina render shell: terrain + controllable vehicle + HUD + tuning sliders.

Pure-physics lives in sim/ and is renderer-agnostic; this module only visualizes SimWorld and
maps input. Client physics is Z-up; ursina is Y-up, so the mapping is:
    ursina_pos = (sim.x, sim.z, sim.y)   yaw(sim z) -> ursina rotation_y
"""
from __future__ import annotations

import math

from sim.vehicle import Inputs


def _build_terrain_mesh(terrain):
    from ursina import Mesh, Entity, color

    n = terrain.size + 1
    half = terrain.extent * 0.5
    verts, tris, cols = [], [], []
    for ix in range(n):
        for iy in range(n):
            x = ix * terrain.spacing - half
            y = iy * terrain.spacing - half
            h = terrain._h[ix][iy]
            verts.append((x, h, y))  # ursina Y-up
            t = (h - terrain.base) / max(terrain.amplitude, 1e-3) * 0.5 + 0.5
            cols.append(color.rgb(60 + 120 * t, 110 + 80 * t, 70 + 60 * t))
    for ix in range(terrain.size):
        for iy in range(terrain.size):
            a = ix * n + iy
            b = (ix + 1) * n + iy
            c = (ix + 1) * n + (iy + 1)
            d = ix * n + (iy + 1)
            tris += [(a, b, c), (a, c, d)]
    mesh = Mesh(vertices=verts, triangles=tris, colors=cols, mode="triangle")
    return Entity(model=mesh, double_sided=True)


def run_app(world, tracker=None, attach_state=None, port=8077):
    from ursina import (Ursina, Entity, EditorCamera, camera, color, held_keys, Text,
                        Vec3 as UVec3, window)

    app = Ursina(title="phys_sim — Wulfram II vehicle physics", borderless=False)
    window.color = color.rgb(20, 24, 34)

    _build_terrain_mesh(world.terrain)

    # Vehicle: hull + a small barrel so heading is visible.
    hull = Entity(model="cube", color=color.olive, scale=(3, 1.2, 4))
    barrel = Entity(parent=hull, model="cube", color=color.gray, scale=(0.18, 0.18, 1.2),
                    z=0.7, y=0.4)

    from ui.sliders import build_sliders
    build_sliders(world.tunables)

    hud = Text(text="", parent=camera.ui, x=0.30, y=0.46, scale=0.7, color=color.white)
    help_txt = Text(
        text="W/S throttle  A/D strafe  Q/E turn  Space/Ctrl up/down  |  1 Tank 2 Scout 3 Bomber  R reset",
        parent=camera.ui, x=-0.5, y=-0.46, scale=0.65, color=color.light_gray)

    state = {"third_person": True}

    def update():
        from ursina import time as _t
        inp = Inputs(
            throttle=float(held_keys["w"]) - float(held_keys["s"]),
            strafe=float(held_keys["a"]) - float(held_keys["d"]),
            turn=float(held_keys["q"]) - float(held_keys["e"]),
            vertical=float(held_keys["space"]) - float(held_keys["control"]),
        )
        world.advance(_t.dt, inp)
        s = world.state()

        # Sync mesh: sim Z-up -> ursina Y-up.
        px, py, pz = s["pos"]
        hull.position = UVec3(px, pz, py)
        hull.rotation_y = -math.degrees(s["yaw"])

        # Chase camera behind the hull.
        cam_back = 18.0
        yaw = s["yaw"]
        camera.position = UVec3(px - math.cos(yaw) * cam_back, pz + 8.0,
                                py - math.sin(yaw) * cam_back)
        camera.look_at(hull.position)

        drift_line = ""
        if tracker is not None:
            rep = tracker.update(_t.dt)
            if attach_state is not None:
                attach_state["report"] = rep
            if rep:
                drift_line = (f"\nDRIFT pos {rep['pos_err']:.4f} (max {rep['max_pos_err']:.4f})"
                              f"  vel {rep['vel_err']:.4f}")
            elif tracker.attach.attached:
                drift_line = "\nDRIFT: waiting for entity..."
            else:
                drift_line = "\nDRIFT: not attached"

        g = world.tunables.effective_gravity
        hud.text = (f"{s['kind'].upper()}\n"
                    f"pos  ({px:7.2f},{py:7.2f},{pz:7.2f})\n"
                    f"vel  ({s['vel'][0]:6.2f},{s['vel'][1]:6.2f},{s['vel'][2]:6.2f})\n"
                    f"speed {s['speed']:6.2f}  yaw {math.degrees(s['yaw']):6.1f}\n"
                    f"g_eff {g:6.2f}\n"
                    f"REST  http://127.0.0.1:{port}/state"
                    f"{drift_line}")

    def on_input(key):
        if key == "1":
            world.set_vehicle("tank")
        elif key == "2":
            world.set_vehicle("scout")
        elif key == "3":
            world.set_vehicle("bomber")
        elif key == "r":
            world.reset()

    # ursina calls update()/input(key) on every Entity each frame; bind ours to a controller.
    controller = Entity()
    controller.update = update
    controller.input = on_input

    app.run()
