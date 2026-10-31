"""What stands on the 3D stage (see assets/fx/depth.mjs): the brand's own 3D models where it has shared some,
its logo mark on title and closing scenes, and abstract shapes in its colors everywhere else.

Nothing here is specific to a business or industry: models come from the brand's library (`kinetry.brand3d`),
and which one appears on which scene comes from the asset agent's tags matched against the plan's words, or
from `design.effects.depth_models` when the plan names them.
"""

from __future__ import annotations

import re


def logo_mark(mark: tuple[str, bytes] | None, logo: tuple[str, bytes] | None) -> str | None:
    """SVG text of the brand's mark for the 3D logo: the pack's mark, else a roughly square SVG logo."""
    for item, square_only in ((mark, False), (logo, True)):
        if not item or not item[0].lower().endswith(".svg") or len(item[1]) > 300_000:
            continue
        svg = item[1].decode("utf-8", errors="ignore")
        if "<path" not in svg:
            continue
        if square_only:
            vb = re.search(r'viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', svg)
            if not vb or not 0.7 <= float(vb.group(1)) / max(float(vb.group(2)), 1e-6) <= 1.4:
                continue
        return svg
    return None


def scene_models(plan, items, hero_scenes: set[int], has_mark: bool = False) -> tuple[dict[int, list[str]], list[str]]:
    """({scene index: ids of the brand models that may stand there, best first}, spare ids for scenes with room).
    `design.effects.depth_models`: "off" shows none, a mapping {scene number (1 = first): model id} places them
    as given (for the models the brand has), "auto" lets the asset agent choose."""
    from ..brand3d import pick_assets

    choice = plan.design.effects.depth_models
    if choice == "off" or not items:
        return {}, []
    have = {a.id for a in items}
    if isinstance(choice, dict):
        out = {}
        for k, v in choice.items():
            i = int(k) - 1 if str(k).strip().isdigit() else -1
            if 0 <= i < len(plan.scenes) and v in have:
                out[i] = [v]
        return out, []
    return pick_assets(plan, items, hero_scenes=hero_scenes, has_mark=has_mark)
