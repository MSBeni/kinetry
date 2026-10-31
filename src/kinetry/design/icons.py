"""Icons for any topic: Lucide (ISC license, ~1,900 icons), drawn as strokes so they can draw themselves on.

`kinetry setup` installs the pinned `lucide-static` npm package next to HyperFrames. The planner
names an icon ('coffee', 'shield-check') or a plain word ('security'); the resolver maps words to the
closest icon through Lucide's tag list. Without the package (unit tests, minimal installs) a small
built-in set keeps rendering working.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from html import escape
from pathlib import Path

LUCIDE_VERSION = "1.51.0"

# Lucide shapes (ISC, see licenses/lucide-ISC.txt) for a minimal offline set
BUILTIN = {
    "check": [["path", {"d": "M20 6 9 17l-5-5"}]],
    "circle": [["circle", {"cx": "12", "cy": "12", "r": "10"}]],
    "star": [
        [
            "path",
            {
                "d": "M11.5 2.6a.5.5 0 0 1 1 0l2.3 4.7 5.2.8a.5.5 0 0 1 .3.9l-3.8 3.7.9 5.2a.5.5 0 0 1-.7.5L12 16l-4.7 2.5a.5.5 0 0 1-.7-.5l.9-5.2L3.7 9a.5.5 0 0 1 .3-.9l5.2-.8z"
            },
        ]
    ],
    "lightbulb": [
        [
            "path",
            {
                "d": "M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"
            },
        ],
        ["path", {"d": "M9 18h6"}],
        ["path", {"d": "M10 22h4"}],
    ],
    "arrow-right": [["path", {"d": "M5 12h14"}], ["path", {"d": "m12 5 7 7-7 7"}]],
    "message-circle": [["path", {"d": "M7.9 20A9 9 0 1 0 4 16.1L2 22Z"}]],
    "target": [
        ["circle", {"cx": "12", "cy": "12", "r": "10"}],
        ["circle", {"cx": "12", "cy": "12", "r": "6"}],
        ["circle", {"cx": "12", "cy": "12", "r": "2"}],
    ],
    "users": [
        ["path", {"d": "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"}],
        ["circle", {"cx": "9", "cy": "7", "r": "4"}],
        ["path", {"d": "M22 21v-2a4 4 0 0 0-3-3.87"}],
        ["path", {"d": "M16 3.13a4 4 0 0 1 0 7.75"}],
    ],
    "sparkles": [
        [
            "path",
            {
                "d": "M9.9 15.5A2 2 0 0 0 8.5 14.1l-6.1-1.6a.5.5 0 0 1 0-1l6.1-1.6A2 2 0 0 0 9.9 8.5l1.6-6.1a.5.5 0 0 1 1 0l1.6 6.1a2 2 0 0 0 1.4 1.4l6.1 1.6a.5.5 0 0 1 0 1l-6.1 1.6a2 2 0 0 0-1.4 1.4l-1.6 6.1a.5.5 0 0 1-1 0z"
            },
        ]
    ],
}


class Icons:
    def __init__(self, tool_dir: Path | None = None):
        self.nodes: dict[str, list] = dict(BUILTIN)
        self.tags: dict[str, list[str]] = {}
        pkg = tool_dir / "node_modules" / "lucide-static" if tool_dir else None
        if pkg and (pkg / "icon-nodes.json").exists():
            self.nodes.update(json.loads((pkg / "icon-nodes.json").read_text()))
            if (pkg / "tags.json").exists():
                self.tags = json.loads((pkg / "tags.json").read_text())
        self.full = len(self.nodes) > len(BUILTIN)

    def resolve(self, name: str | None) -> str | None:
        if not name:
            return None
        n = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if n in self.nodes:
            return n
        return self._search(n)

    @lru_cache(maxsize=512)  # noqa: B019 - one Icons per process
    def _search(self, n: str) -> str:
        words = set(n.split("-"))
        best, score = None, 0.0
        for icon, tags in self.tags.items():
            if icon not in self.nodes:
                continue
            parts = set(icon.split("-"))
            s = 3 * len(words & parts) + sum(1 for t in tags if t in words or t == n.replace("-", " "))
            s -= 0.02 * len(parts)  # prefer simpler icons
            if s > score:
                best, score = icon, s
        return best or ("circle" if "circle" in self.nodes else next(iter(self.nodes)))

    def svg(self, name: str | None, cls: str = "") -> str:
        icon = self.resolve(name) or "circle"
        parts = []
        for tag, attrs in self.nodes[icon]:
            a = " ".join(f'{k}="{escape(str(v))}"' for k, v in attrs.items() if k != "key")
            parts.append(f"<{tag} {a}/>")
        return (
            f'<svg class="icon {cls}" data-icon="{icon}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{"".join(parts)}</svg>'
        )
