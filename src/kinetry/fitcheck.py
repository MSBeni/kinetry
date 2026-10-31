"""Text-fit gate and deterministic repair.

`measure()` loads the composed page in Chrome and reports line counts,
widows and overflow per field. `plan_repairs()` decides, per problem field,
whether shrinking the type one step is enough or the copy must be rewritten
(handed to the LLM repair agent).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import PKG_DIR, Settings
from .design.render import SCALES


@dataclass
class Problem:
    field: str
    issue: str  # too_many_lines | widow | overflow_x | stage_overflow
    detail: str
    text: str = ""


def measure(index_html: Path, settings: Settings, out_json: Path, size: tuple[int, int] = (1920, 1080)) -> dict:
    env = settings.hf_env()
    res = subprocess.run(
        [
            "node",
            str(PKG_DIR / "js" / "measure.mjs"),
            str(index_html),
            settings.resolve_browser(),
            str(out_json),
            str(size[0]),
            str(size[1]),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    if res.returncode != 0:
        raise RuntimeError(f"measure failed: {res.stderr[-600:]}")
    return json.loads(out_json.read_text())


def find_problems(report: dict) -> list[Problem]:
    probs: list[Problem] = []
    by_scene: dict[int, list[dict]] = {}
    for f in report["fields"]:
        if f["field"].startswith("scenes."):
            by_scene.setdefault(int(f["field"].split(".")[1]), []).append(f)
        if f["lines"] > f["maxLines"]:
            probs.append(Problem(f["field"], "too_many_lines", f"{f['lines']} lines > max {f['maxLines']}", f["text"]))
        elif f["widow"]:
            probs.append(Problem(f["field"], "widow", "single word alone on the last line", f["text"]))
        if f["overflowX"] > 2:
            probs.append(Problem(f["field"], "overflow_x", f"{f['overflowX']}px past its container", f["text"]))
    for st in report["stages"]:
        if max(st["overflowY"], st.get("overflowTop", 0), st.get("overflowX", 0)) > 2:
            # blame the largest text in that scene
            fs = sorted(by_scene.get(st["scene"], []), key=lambda x: -x["fontSize"])
            if fs:
                probs.append(
                    Problem(
                        fs[0]["field"],
                        "stage_overflow",
                        f"scene content runs {max(st['overflowY'], st.get('overflowTop', 0), st.get('overflowX', 0))}px "
                        "outside the safe area",
                        fs[0]["text"],
                    )
                )
    # one problem per field (most severe first)
    order = {"stage_overflow": 0, "overflow_x": 1, "too_many_lines": 2, "widow": 3}
    seen, out = set(), []
    for p in sorted(probs, key=lambda p: order[p.issue]):
        if p.field not in seen:
            seen.add(p.field)
            out.append(p)
    return out


def plan_repairs(
    problems: list[Problem], fit: dict[str, int], widow_floor: int = 2
) -> tuple[dict[str, int], list[Problem]]:
    """Shrink type where there is room; return fields that need a copy rewrite."""
    new_fit = dict(fit)
    rewrite: list[Problem] = []
    for p in problems:
        if not p.field.startswith("scenes."):  # chrome labels have no fit levels: only shorter copy helps
            rewrite.append(p)
            continue
        if p.issue == "stage_overflow":
            # the whole scene is too tall: shrink all its type a step; past the smallest step, shorten the biggest text
            key = ".".join(p.field.split(".")[:2])  # "scenes.N"
            lvl = new_fit.get(key, 0)
            if lvl < len(SCALES) - 1:
                new_fit[key] = lvl + 1
            else:
                rewrite.append(p)
            continue
        lvl = new_fit.get(p.field, 0)
        limit = widow_floor if p.issue == "widow" else len(SCALES) - 1  # widows shouldn't shrink far
        if lvl < limit:
            new_fit[p.field] = lvl + 1
        else:
            rewrite.append(p)
    return new_fit, rewrite


def _step(cur, part: str):
    if part.isdigit() and isinstance(cur, list):
        return cur[int(part)]
    return cur[part] if isinstance(cur, dict) else getattr(cur, part)


def get_path(obj, path: str):
    """'scenes.2.data.items.0.title' through models, dicts and lists."""
    cur = obj
    for part in path.split("."):
        cur = _step(cur, part)
    return cur


def set_path(obj, path: str, value: str) -> None:
    parts = path.split(".")
    cur = obj
    for part in parts[:-1]:
        cur = _step(cur, part)
    last = parts[-1]
    if last.isdigit() and isinstance(cur, list):
        cur[int(last)] = value
    elif isinstance(cur, dict):
        cur[last] = value
    else:
        setattr(cur, last, value)
