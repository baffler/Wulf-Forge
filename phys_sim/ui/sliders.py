"""On-screen tuning sliders bound to the shared Tunables registry.

Every slider edits the SAME Tunables object the physics tick and the REST API use, so changes
take effect on the next tick and are reflected in /tunables. Built dynamically from the
registry so new tunables appear automatically.
"""
from __future__ import annotations


def build_sliders(tunables, parent=None):
    """Create a column of labeled sliders (left edge of screen). Returns the list of widgets."""
    from ursina import Slider, Text, color, camera  # imported lazily (render-only dep)

    defs = tunables.describe()
    widgets = []

    # Group header + slider rows, top-to-bottom on the left.
    top = 0.46
    row_h = 0.038
    y = top
    last_group = None

    for d in defs:
        if d["group"] != last_group:
            Text(text=d["group"].upper(), parent=camera.ui, x=-0.86, y=y, scale=0.7,
                 color=color.azure)
            last_group = d["group"]
            y -= row_h

        name = d["name"]
        label = Text(text=name, parent=camera.ui, x=-0.86, y=y + 0.004, scale=0.6,
                     color=color.light_gray)
        val_text = Text(text=f"{d['value']:.3g}", parent=camera.ui, x=-0.40, y=y + 0.004,
                        scale=0.6, color=(color.lime if d["kind"] == "EXACT" else color.orange))

        s = Slider(min=d["lo"], max=d["hi"], default=d["value"], step=(d["hi"] - d["lo"]) / 200.0,
                   parent=camera.ui, x=-0.62, y=y, scale=0.5)

        def _make_cb(nm, slider, txt):
            def _cb():
                applied = tunables.set(nm, slider.value)
                txt.text = f"{applied.value:.3g}"
            return _cb

        s.on_value_changed = _make_cb(name, s, val_text)
        widgets.extend([label, val_text, s])
        y -= row_h

    return widgets
