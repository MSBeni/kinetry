"""Brand kit: extraction from a website, contrast-safe tokens, fallbacks.

The branding *agent* (agents.py) reads the signals extracted here and picks
tokens with judgment. Everything an LLM could get wrong is then enforced in
code: WCAG contrast, font availability, and sane fallbacks.
"""

from __future__ import annotations

import colorsys
import re
from collections import Counter
from collections.abc import Callable
from urllib.parse import urljoin

from pydantic import BaseModel, Field, field_validator

HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
RGB = re.compile(r"rgba?\(\s*(\d{1,3})[\s,]+(\d{1,3})[\s,]+(\d{1,3})")
FONT_DECL = re.compile(r"font-family\s*:\s*([^;}{]+)", re.I)
VAR_DECL = re.compile(r"(--[\w-]+)\s*:\s*([^;}{]+)")


# ---------------------------------------------------------------- color math
def norm_hex(c: str) -> str:
    c = c.strip().lower()
    m = RGB.match(c)
    if m:
        return "#" + "".join(f"{min(255, int(v)):02x}" for v in m.groups())
    if not c.startswith("#"):
        c = "#" + c
    if len(c) == 4:
        c = "#" + "".join(ch * 2 for ch in c[1:])
    return c


HEX6 = re.compile(r"#[0-9a-f]{6}")


def safe_hex(c: str) -> str:
    """Canonical '#rrggbb' or ValueError. Colors come from websites and models and end up in CSS."""
    out = norm_hex(str(c))
    if not HEX6.fullmatch(out):
        raise ValueError(f"not a color: {str(c)[:40]!r}")
    return out


def rgb(c: str) -> tuple[float, float, float]:
    c = norm_hex(c)
    return tuple(int(c[i : i + 2], 16) / 255 for i in (1, 3, 5))  # type: ignore[return-value]


def to_hex(r: float, g: float, b: float) -> str:
    return "#" + "".join(f"{round(max(0, min(1, v)) * 255):02x}" for v in (r, g, b))


def luminance(c: str) -> float:
    def ch(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = rgb(c)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a: str, b: str, t: float) -> str:
    ra, rb = rgb(a), rgb(b)
    return to_hex(*(x + (y - x) * t for x, y in zip(ra, rb, strict=True)))


def hls(c: str) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*rgb(c))


def ensure_contrast(fg: str, bg: str, minimum: float) -> str:
    """Move fg's lightness away from bg until the ratio passes, keeping hue."""
    if contrast(fg, bg) >= minimum:
        return norm_hex(fg)
    h, lum, s = hls(fg)
    darker = luminance(bg) > 0.4
    for _ in range(60):
        lum = max(0.0, lum - 0.02) if darker else min(1.0, lum + 0.02)
        cand = to_hex(*colorsys.hls_to_rgb(h, lum, s))
        if contrast(cand, bg) >= minimum:
            return cand
    return "#000000" if darker else "#ffffff"


# ---------------------------------------------------------------- brand kit
class BrandKit(BaseModel):
    name: str = Field(..., max_length=60)
    background: str = Field(..., description="Page background, hex. Videos read best on light, low-saturation grounds.")
    surface: str = Field(..., description="Card background, hex")
    ink: str = Field(..., description="Primary text color, hex")
    muted: str = Field(..., description="Secondary text color, hex")
    line: str = Field(..., description="Hairline/border color, hex")
    accent: str = Field(..., description="Primary brand color for eyebrows, bars, highlights, hex")
    accent2: str = Field(..., description="Secondary brand color for decoration, hex")
    display_font: str = Field(..., description="Headline font family (Google/Fontsource family name)")
    body_font: str = Field(..., description="Body/UI font family")
    display_weight: int = Field(
        400, description="Headline weight: 400 for elegant serifs, 600-700 for bold sans brands"
    )
    gradient: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="Brand gradient stops (hex), if the site uses a signature gradient; else empty",
    )
    radius: int = Field(24, ge=0, le=40, description="Corner radius in px for cards")
    tone: str = Field("calm", description="One or two words: calm, warm, bold, playful, corporate...")
    rationale: str = Field("", max_length=600)

    accent_ink: str = "#ffffff"  # computed: text color on accent fills
    accent_fill: str = ""  # computed: vivid brand color for shapes (non-text, needs 3:1)

    @field_validator("background", "surface", "ink", "muted", "line", "accent", "accent2", "accent_ink")
    @classmethod
    def _color(cls, v: str) -> str:
        return safe_hex(v)

    @field_validator("accent_fill")
    @classmethod
    def _fill(cls, v: str) -> str:
        return safe_hex(v) if v else v

    @field_validator("gradient")
    @classmethod
    def _stops(cls, v: list[str]) -> list[str]:
        return [safe_hex(c) for c in v]

    @field_validator("display_font", "body_font")
    @classmethod
    def _family(cls, v: str) -> str:  # family names end up in file names and CSS
        v = v.strip()
        if not re.fullmatch(r"[A-Za-z0-9 _.+&'-]{1,60}", v):
            raise ValueError(f"not a font family name: {v[:40]!r}")
        return v


def enforce(kit: BrandKit) -> tuple[BrandKit, list[str]]:
    """Make any kit legible on video. Returns the fixed kit and a change log."""
    log: list[str] = []
    k = kit.model_copy()
    for f in ("background", "surface", "ink", "muted", "line", "accent", "accent2"):
        setattr(k, f, norm_hex(getattr(k, f)))
    k.gradient = [norm_hex(c) for c in k.gradient]
    # Shapes (bars, dots, circles) keep the vivid brand color if it reaches the
    # 3:1 non-text minimum; text uses the contrast-fixed accent below.
    k.accent_fill = k.accent if contrast(k.accent, k.background) >= 3.0 else ""
    if luminance(k.background) < 0.6:
        log.append(f"background {k.background} too dark for the light templates -> tinted near-white")
        k.background = mix("#ffffff", k.accent, 0.04)
    if contrast(k.surface, k.ink) < 7:
        k.surface = "#ffffff"
    # The templates darken the background toward ink by up to 8% at the bottom
    # edge (vignette); text must pass against that darkest point too.
    k_bg_low = mix(k.background, k.ink, 0.08)
    rules = [
        ("ink", "background", 9.0),
        ("muted", "background", 4.8),
        ("accent", "background", 4.6),
        ("accent", "surface", 4.5),
        ("accent2", "background", 3.0),
    ]
    for fg, bg, minimum in rules:
        before = getattr(k, fg)
        ref = k_bg_low if bg == "background" else getattr(k, bg)
        after = ensure_contrast(before, ref, minimum)
        if after != before:
            log.append(f"{fg} {before} -> {after} (contrast vs {bg} >= {minimum})")
            setattr(k, fg, after)
    if contrast(k.line, k.background) > 1.6 or contrast(k.line, k.background) < 1.08:
        k.line = mix(k.background, k.ink, 0.12)
    if not k.accent_fill:
        k.accent_fill = k.accent
    k.accent_ink = "#ffffff" if contrast("#ffffff", k.accent_fill) >= contrast(k.ink, k.accent_fill) else k.ink
    if k.display_weight not in (400, 500, 600, 700):
        k.display_weight = 400
    return k, log


def signals_from_probe(probe: dict) -> dict:
    """Convert a browser probe (js/brand_probe.js) into the signals shape the
    brand agent and the heuristic fallback use."""
    weights: Counter = Counter()
    for c, n in probe.get("text_colors", []):
        weights[norm_hex(c)] += n
    for c, n in probe.get("background_colors", []):
        weights[norm_hex(c)] += n
    for name, v in probe.get("css_variables", {}).items():
        if name.startswith("--wp--"):
            continue  # WordPress palette presets, not brand
        try:
            weights[norm_hex(v)] += 200
        except Exception:
            pass
    for b in probe.get("roles", {}).get("buttons", []):
        for c in RGB.findall(b.get("gradient") or ""):
            weights[norm_hex("rgb({},{},{})".format(*c))] += 300
    brandish = [(c, n) for c, n in weights.most_common(40) if not _is_neutral(c)]
    neutrals = [(c, n) for c, n in weights.most_common(40) if _is_neutral(c)]
    return {
        "source": probe.get("url", ""),
        "site_name": probe.get("site_name", ""),
        "images": [u for u in probe.get("images", []) if isinstance(u, str) and u.startswith(("https://", "http://"))][
            :6
        ],
        "theme_color": norm_hex(probe["theme_color"]) if probe.get("theme_color") else None,
        "css_variables": {k: v for k, v in probe.get("css_variables", {}).items() if not k.startswith("--wp--")},
        "brand_colors": brandish[:12],
        "neutral_colors": neutrals[:10],
        "fonts": probe.get("fonts", []),
        "heading_fonts": probe.get("heading_fonts", []),
        "google_fonts": [],
        "roles": probe.get("roles", {}),
        "logo": {k: v for k, v in (probe.get("logos") or [{}])[0].items() if k not in ("svg", "dataUrl")}
        if probe.get("logos")
        else None,
        "stylesheets_read": ["(computed styles via browser probe)"],
    }


def logo_is_legible(svg: str, background: str) -> bool:
    """True if the logo's darkest fill stands out on the video background."""
    fills = [norm_hex(f) for f in re.findall(r'fill="(#[0-9a-fA-F]{3,6}|rgb\([^)]*\))"', svg)]
    if not fills:
        return True  # unknown (e.g. currentColor / CSS classes): let QA frames show it
    return max(contrast(f, background) for f in fills) >= 3.0


# ---------------------------------------------------------------- extraction
Fetcher = Callable[[str], str]


def http_fetcher(timeout: float = 20.0, public_only: bool = False) -> Fetcher:
    """GET pages and stylesheets. `public_only` re-checks every request, redirect hops included."""
    from .netguard import client as make_client
    from .netguard import get_capped, text_of

    client = make_client(
        public_only,
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (kinetry brand extractor)"},
    )

    def get(url: str) -> str:
        body, r = get_capped(client, url, 1_500_000)  # read no more than we keep
        return text_of(body, r)

    return get


def _is_neutral(c: str) -> bool:
    _, lum, s = hls(c)
    return s < 0.18 or lum > 0.94 or lum < 0.16  # very dark "colors" are text inks, not accents


def extract_signals(url_or_html: str, fetch: Fetcher | None = None, base_url: str = "") -> dict:
    """Pull brand evidence out of a page and its stylesheets.

    `url_or_html` is a URL (fetched) or raw HTML (with `base_url` for links).
    """
    fetch = fetch or http_fetcher()
    if url_or_html.lstrip().startswith("<"):
        html, base = url_or_html, base_url
    else:
        html, base = fetch(url_or_html), url_or_html

    css_parts = re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I)
    inline_styles = re.findall(r'style="([^"]+)"', html)
    sheets = re.findall(r'<link[^>]+rel=["\']?stylesheet["\']?[^>]*>', html, re.I)
    sheet_urls = []
    for tag in sheets:
        m = re.search(r'href=["\']([^"\']+)', tag)
        if m and "fonts.googleapis" not in m.group(1):
            sheet_urls.append(urljoin(base, m.group(1)))
    fetched = []
    for u in sheet_urls[:6]:
        try:
            css_parts.append(fetch(u))
            fetched.append(u)
        except Exception:
            pass
    css = "\n".join(css_parts + inline_styles)

    colors = Counter(norm_hex(c) for c in HEX.findall(css) + [f"rgb({a},{b},{c})" for a, b, c in RGB.findall(css)])
    brandish = [(c, n) for c, n in colors.most_common(60) if not _is_neutral(c)]
    neutrals = [(c, n) for c, n in colors.most_common(40) if _is_neutral(c)]

    variables = {}
    for name, val in VAR_DECL.findall(css):
        val = val.strip()
        if HEX.fullmatch(val) or RGB.match(val):
            variables[name] = norm_hex(val)

    fonts = Counter()
    for decl in FONT_DECL.findall(css):
        first = decl.split(",")[0].strip().strip("'\"")
        if (
            first
            and not first.startswith("var(")
            and first.lower() not in {"inherit", "initial", "sans-serif", "serif"}
        ):
            fonts[first] += 1
    gfonts = re.findall(r"fonts\.googleapis\.com/css2?\?family=([^\"'&]+)", html)
    google_families = sorted({f.split(":")[0].replace("+", " ") for g in gfonts for f in g.split("&family=")})

    theme = re.search(r'<meta[^>]+name=["\']theme-color["\'][^>]+content=["\']([^"\']+)', html, re.I)
    site = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', html, re.I)
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    images = []
    for tag in re.findall(r"<meta\b[^>]*>", html, re.I):
        key = re.search(r'(?:property|name)=["\']((?:og|twitter):image(?::secure_url|:src)?)["\']', tag, re.I)
        val = re.search(r'content=["\']([^"\']+)["\']', tag, re.I)
        if key and val:
            u = urljoin(base, val.group(1).strip()) if base else val.group(1).strip()
            if u.startswith(("https://", "http://")) and u not in images:
                images.append(u)
    return {
        "source": base or "inline-html",
        "images": images[:6],
        "site_name": (site.group(1) if site else (title.group(1).strip() if title else ""))[:80],
        "theme_color": norm_hex(theme.group(1))
        if theme and (HEX.match(theme.group(1)) or RGB.match(theme.group(1)))
        else None,
        "css_variables": dict(list(variables.items())[:40]),
        "brand_colors": brandish[:12],
        "neutral_colors": neutrals[:10],
        "fonts": fonts.most_common(8),
        "google_fonts": google_families,
        "stylesheets_read": fetched,
    }


def heuristic_kit(signals: dict) -> BrandKit:
    """No-LLM fallback: most-used saturated colors become the accents."""
    cands = [c for c, _ in signals["brand_colors"]]
    if signals.get("theme_color") and not _is_neutral(signals["theme_color"]):
        cands.insert(0, signals["theme_color"])
    accent = cands[0] if cands else "#3c6ee5"
    accent2 = next((c for c in cands[1:] if abs(hls(c)[0] - hls(accent)[0]) > 0.08), mix(accent, "#ffffff", 0.35))
    darks = [c for c, _ in signals["neutral_colors"] if luminance(c) < 0.08]
    ink = darks[0] if darks else "#18212f"
    fonts = [f for f, _ in signals["fonts"]] + signals.get("google_fonts", [])
    body = fonts[0] if fonts else "Inter"
    return BrandKit(
        name=signals.get("site_name") or "Brand",
        background=mix("#ffffff", accent, 0.035),
        surface="#ffffff",
        ink=ink,
        muted=mix(ink, "#ffffff", 0.35),
        line=mix(ink, "#ffffff", 0.86),
        accent=accent,
        accent2=accent2,
        display_font=body,
        body_font=body,
        rationale="heuristic: most frequent saturated colors and fonts on the site",
    )
