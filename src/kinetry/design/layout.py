"""Pick a layout for every scene that doesn't name one.

Plain code, no model: seeded so the same plan always gets the same layouts (and `design.seed`
reshuffles them), restricted to layouts that support the format, nudged toward the style's
preferred layouts, and never repeating the layout a scene type used last time.
"""

from __future__ import annotations

import hashlib
import random

from .catalog import Catalog, load_catalog
from .plan import VideoPlan2


def pick_layouts(plan: VideoPlan2, catalog: Catalog | None = None) -> VideoPlan2:
    cat = catalog or load_catalog()
    fmt = plan.design.resolved_format()
    style = cat.styles.get(plan.design.style or "")
    prefs = style.tokens.get("layout_prefs", {}) if style else {}
    key = f"{plan.design.seed}|{plan.title}|{'/'.join(s.type for s in plan.scenes)}"
    rng = random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:12], 16))
    last: dict[str, str] = {}
    for sc in plan.scenes:
        comp = cat.components.get(sc.type)
        if comp is None:
            continue
        options = comp.layouts_for(fmt) or list(comp.layouts)
        if sc.layout in options:
            last[sc.type] = sc.layout
            continue
        fresh = [o for o in options if o != last.get(sc.type)] or options
        pref = prefs.get(sc.type)
        if pref in fresh and (sc.type not in last or rng.random() < 0.75):
            choice = pref
        else:
            choice = fresh[rng.randrange(len(fresh))]
        sc.layout = choice
        last[sc.type] = choice
    return plan
