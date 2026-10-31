"""Brand kit × style pack × format -> CSS custom properties.

The brand decides colors, fonts and logo; the style decides how they're used: which ground
(the brand's own, a tint, warm paper, white, or dark), the type scale, radius, shadows and
which font plays which role. Every text color is re-checked against the ground it will sit
on (WCAG AA for text, 3:1 for shapes), including dark grounds and inverted scenes where the
brand color becomes the background.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..brand import BrandKit, contrast, ensure_contrast, luminance, mix

ROLES = ("display", "h2", "h3", "lead", "body", "item", "label", "eyebrow", "small", "stat", "quote", "caption")
DEFAULT_TYPE = {
    "display": 150,
    "h2": 96,
    "h3": 50,
    "lead": 40,
    "body": 34,
    "item": 40,
    "label": 24,
    "eyebrow": 24,
    "small": 24,
    "stat": 260,
    "quote": 92,
    "caption": 42,
}
# format scale and safe area (left/right padding, top, bottom with and without captions)
FORMAT = {
    "16:9": {"k": 1.0, "px": 140, "pt": 170, "pb": 150, "pb_caps": 230, "w": 1920, "h": 1080},
    "9:16": {"k": 1.0, "px": 80, "pt": 250, "pb": 260, "pb_caps": 470, "w": 1080, "h": 1920},
    "1:1": {"k": 0.76, "px": 84, "pt": 150, "pb": 130, "pb_caps": 230, "w": 1080, "h": 1080},
}
SHADOWS = {
    "none": "none",
    "soft": "0 18px 48px rgba(10, 20, 40, 0.10)",
    "lift": "0 30px 60px rgba(10, 20, 40, 0.16)",
    "hard": "8px 10px 0 var(--ink)",
}


@dataclass
class Palette:
    bg: str
    surface: str
    surface2: str
    ink: str
    muted: str
    line: str
    accent: str  # text-safe brand color
    fill: str  # vivid brand color for shapes
    on_fill: str
    accent2: str
    fill2: str
    soft: str
    dark: bool
    good: str = "#1a8f5a"
    bad: str = "#d23f3f"

    def vars(self, prefix: str = "") -> dict[str, str]:
        return {
            "--bg": self.bg,
            "--surface": self.surface,
            "--surface2": self.surface2,
            "--ink": self.ink,
            "--muted": self.muted,
            "--line": self.line,
            "--accent": self.accent,
            "--fill": self.fill,
            "--on-fill": self.on_fill,
            "--accent2": self.accent2,
            "--fill2": self.fill2,
            "--soft": self.soft,
            "--good": self.good,
            "--bad": self.bad,
        }


def _best_text(bg: str, *candidates: str) -> str:
    return max(candidates, key=lambda c: contrast(c, bg))


def palette(kit: BrandKit, ground: str) -> Palette:
    fill0 = kit.accent_fill or kit.accent
    if ground == "dark":
        base = mix(kit.ink, "#000000", 0.45)
        if contrast(base, "#000000") > 1.6:  # ink was too light to be a ground
            base = "#0c1220"
        bg = mix(base, fill0, 0.06)
        surface, surface2 = mix(bg, "#ffffff", 0.06), mix(bg, "#ffffff", 0.11)
        ink = "#eef1f6"
        line = mix(bg, "#ffffff", 0.16)
    else:
        if ground == "paper":
            bg = mix("#faf3e7", kit.background, 0.25)
            surface = "#fffdf8"
        elif ground == "white":
            bg, surface = "#ffffff", mix("#ffffff", kit.background, 0.6)
        elif ground == "tint":
            bg = mix(kit.background, fill0, 0.05)
            surface = kit.surface
        else:  # brand
            bg, surface = kit.background, kit.surface
        surface2 = mix(surface, kit.ink, 0.04)
        ink = ensure_contrast(kit.ink, bg, 9.0)
        line = kit.line if ground in ("brand", "tint") else mix(bg, kit.ink, 0.13)
    muted = ensure_contrast(mix(ink, bg, 0.36) if ground == "dark" else kit.muted, bg, 4.8)
    muted = ensure_contrast(muted, surface, 4.6)
    accent = ensure_contrast(kit.accent, bg, 4.6)
    fill = ensure_contrast(fill0, bg, 3.0)
    on_fill = _best_text(fill, "#ffffff", "#0b0f17", ink)
    if contrast(on_fill, fill) < 4.5:  # brand color too mid-tone for any text: deepen it for fills
        fill = ensure_contrast(fill, on_fill, 4.5)
    accent2 = ensure_contrast(kit.accent2, bg, 3.0)
    fill2 = accent2
    soft = mix(surface, fill, 0.12 if ground != "dark" else 0.18)
    good = ensure_contrast("#2fbf7f" if ground == "dark" else "#1a8f5a", bg, 4.5)
    bad = ensure_contrast("#ff6b6b" if ground == "dark" else "#d23f3f", bg, 4.5)
    return Palette(
        bg,
        surface,
        surface2,
        ink,
        muted,
        line,
        accent,
        fill,
        on_fill,
        accent2,
        fill2,
        soft,
        ground == "dark",
        good,
        bad,
    )


def inverse(p: Palette) -> Palette:
    """Palette for scenes set on the brand color (full-bleed quotes, bold titles)."""
    bg, ink = p.fill, p.on_fill
    muted = ensure_contrast(mix(ink, bg, 0.22), bg, 4.5)
    # keep the brand's second color for highlights when it reads on the fill
    # (text sits on top of highlights, so the ink must still read on it)
    if contrast(p.fill2, bg) >= 1.25 and contrast(ink, p.fill2) >= 3:
        fill2 = p.fill2
    else:
        fill2 = mix(bg, "#000000" if luminance(ink) > 0.5 else "#ffffff", 0.4)
    return Palette(
        bg=bg,
        surface=mix(bg, ink, 0.1),
        surface2=mix(bg, ink, 0.16),
        ink=ink,
        muted=muted,
        line=mix(bg, ink, 0.3),
        accent=ink,
        fill=ink,
        on_fill=bg,
        accent2=fill2,
        fill2=fill2,
        soft=mix(bg, ink, 0.12),
        dark=contrast(ink, "#ffffff") < 2,
        good=ink,
        bad=ink,
    )


def build_tokens(kit: BrandKit, style: dict, fmt: str, captions: bool) -> dict:
    """Everything the renderer needs: css vars for :root and .inv, plus a few raw values."""
    p = palette(kit, style.get("ground", "brand"))
    inv = inverse(p)
    f = FORMAT[fmt]
    k = f["k"] * style.get("format_scale", {}).get(fmt, 1.0)
    sizes = {**DEFAULT_TYPE, **style.get("type", {})}
    radius = kit.radius if style.get("radius", "brand") == "brand" else int(style["radius"])
    grad_stops = kit.gradient if len(kit.gradient) >= 2 else [p.fill, p.fill2]
    dw = kit.display_weight if style.get("display_weight", "brand") == "brand" else style["display_weight"]
    fonts = style.get("fonts", {})
    v = {
        **p.vars(),
        "--grad": f"linear-gradient(90deg, {', '.join(grad_stops)})",
        "--r": f"{radius}px",
        "--r-sm": f"{max(4, radius // 2)}px",
        "--shadow": SHADOWS.get(style.get("shadow", "soft"), "none"),
        "--bw": f"{style.get('border', 2)}px",
        "--dw": str(dw),
        "--tracking": style.get("tracking", "-0.02em"),
        "--head-case": style.get("head_case", "none"),
        "--f-display": '"TF Display", Georgia, serif',
        "--f-body": '"TF Body", ui-sans-serif, system-ui, sans-serif',
        "--f-accent": '"TF Accent", "TF Body", ui-sans-serif, sans-serif',
        "--f-mono": '"TF Mono", ui-monospace, "DejaVu Sans Mono", monospace',
        "--f-head": _font_var(fonts.get("head", "display")),
        "--f-label": _font_var(fonts.get("label", "body")),
        "--f-quote": _font_var(fonts.get("quote", "display")),
        "--f-num": _font_var(fonts.get("num", "display")),
        "--k": f"{k:.3f}",
        "--px": f"{f['px']}px",
        "--pt": f"{f['pt']}px",
        "--pb": f"{f['pb_caps'] if captions else f['pb']}px",
        "--W": f"{f['w']}px",
        "--H": f"{f['h']}px",
    }
    for role in ROLES:
        v[f"--fs-{role}"] = f"{round(sizes[role] * k)}px"
    return {"root": v, "inverse": inv.vars(), "palette": p, "inverse_palette": inv, "size": (f["w"], f["h"])}


def _font_var(role: str) -> str:
    return {"display": "var(--f-display)", "body": "var(--f-body)", "accent": "var(--f-accent)"}.get(role, role)


def css_block(selector: str, values: dict[str, str]) -> str:
    return selector + " {\n" + "\n".join(f"  {k}: {v};" for k, v in values.items()) + "\n}"
