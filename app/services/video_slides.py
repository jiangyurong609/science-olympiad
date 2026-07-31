"""Phase V — render storyboard scenes to slide images.

Slides are emitted as SVG rather than rasterised here: the render worker draws them in
Chromium, which handles SVG natively, so we avoid a rasterisation dependency and keep text
crisp at any output resolution.

The visual language matches the approved storyboard — a dark instrument panel where colour
carries meaning rather than decoration: amber is energy, ember is loss, green is production,
cyan is data, violet is recycling. A student learns to read the palette itself.
"""
from __future__ import annotations

from xml.sax.saxutils import escape

W, H = 1920, 1080
GROUND = "#0b1417"
PANEL = "#16262a"
INK = "#e9f4f1"
MUTED = "#8ba09d"
RULE = "#2a4046"
ACCENTS = {
    "energy": "#f2a83a", "loss": "#e0522c", "production": "#34c98a",
    "data": "#46b3d6", "recycle": "#a97fd6",
}
DEFAULT_ACCENT = ACCENTS["energy"]

# Font stacks must name faces present in the render container (Debian/Chromium). A stack of
# macOS-only names silently degrades to monospace in the rendered video.
DISPLAY_FONT = ("'Liberation Sans Narrow', 'DejaVu Sans Condensed', 'Arial Narrow', "
                "'Helvetica Neue', Helvetica, Arial, sans-serif")
BODY_FONT = "'DejaVu Sans', 'Liberation Sans', Arial, Helvetica, sans-serif"
MONO_FONT = "'DejaVu Sans Mono', 'Liberation Mono', 'Courier New', monospace"

# Slide archetypes; a scene's block type maps onto one of these.
ARCHETYPES = {
    "opening": "title",
    "property_cards": "points",
    "steps": "points",
    "worked_example": "steps",
    "image_gallery": "figure",
    "summary": "recap",
    "checkpoint": "check",
}


def archetype_for(block_type: str) -> str:
    return ARCHETYPES.get(block_type or "", "points")


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = str(text).split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _text(x: int, y: int, content: str, *, size: int, fill: str = INK,
          weight: int = 400, family: str = BODY_FONT,
          anchor: str = "start", spacing: float = 0) -> str:
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{ls}>'
            f"{escape(str(content))}</text>")


def _headline(text: str, accent: str, y: int = 250) -> str:
    lines = _wrap(text, 34)[:3]
    out = []
    for i, line in enumerate(lines):
        out.append(_text(140, y + i * 92, line.upper(), size=76, weight=700,
                         family=DISPLAY_FONT,
                         spacing=0.5))
    out.append(f'<rect x="140" y="{y + len(lines) * 92 - 46}" width="150" height="7" fill="{accent}" rx="3"/>')
    return "".join(out)


def _frame(body: str, *, slug: str, accent: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
        f'<defs><linearGradient id="glow" x1="1" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{accent}" stop-opacity="0.16"/>'
        f'<stop offset="60%" stop-color="{accent}" stop-opacity="0"/></linearGradient></defs>'
        f'<rect width="{W}" height="{H}" fill="{GROUND}"/>'
        f'<rect width="{W}" height="{H}" fill="url(#glow)"/>'
        f'<rect x="0" y="0" width="14" height="{H}" fill="{accent}"/>'
        + _text(W - 80, 84, slug, size=26, fill=MUTED, family=MONO_FONT,
                anchor="end", spacing=3)
        + body + "</svg>"
    )


def _points(items: list[str], accent: str, top: int = 470) -> str:
    out = []
    y = top
    for item in items[:5]:
        lines = _wrap(item, 62)[:2]
        out.append(f'<rect x="140" y="{y - 44}" width="10" height="{28 + 52 * len(lines)}" rx="5" fill="{accent}"/>')
        for i, line in enumerate(lines):
            out.append(_text(190, y + i * 52, line, size=40, fill=INK))
        y += 52 * len(lines) + 44
    return "".join(out)


def _numbered(items: list[str], accent: str, top: int = 470) -> str:
    out, y = [], top
    for index, item in enumerate(items[:5], start=1):
        out.append(_text(140, y, f"{index:02d}", size=38, fill=accent,
                         family=MONO_FONT, weight=700))
        for i, line in enumerate(_wrap(item, 56)[:2]):
            out.append(_text(240, y + i * 50, line, size=40, fill=INK))
        y += 96
    return "".join(out)


def render_scene_svg(scene: dict) -> str:
    """One storyboard scene → one slide."""
    accent = ACCENTS.get(scene.get("accent", ""), DEFAULT_ACCENT)
    kind = scene.get("archetype") or archetype_for(scene.get("block_type", ""))
    index = scene.get("index", 1)
    slug = f"{index:02d} · {kind.upper()}"
    headline = scene.get("headline", "")
    points = [p for p in (scene.get("points") or []) if str(p).strip()]

    if kind == "title":
        body = (
            _text(140, 300, str(scene.get("eyebrow", "Science Olympiad")).upper(), size=30,
                  fill=accent, family=MONO_FONT, spacing=6)
            + _headline(headline, accent, y=430)
            + (_text(140, 700, scene.get("subtitle", ""), size=42, fill=MUTED)
               if scene.get("subtitle") else "")
        )
    elif kind == "recap":
        body = _headline(headline, accent, y=230) + _numbered(points, accent, top=470)
    elif kind == "steps":
        body = _headline(headline, accent, y=230) + _numbered(points, accent, top=470)
    elif kind == "check":
        body = (
            _headline(headline, accent, y=230)
            + f'<rect x="140" y="430" width="{W - 280}" height="8" fill="{RULE}"/>'
            + _points(points, accent, top=530)
        )
    elif kind == "figure":
        body = (
            _headline(headline, accent, y=230)
            + f'<rect x="140" y="410" width="{W - 280}" height="480" rx="12" fill="{PANEL}" stroke="{RULE}" stroke-width="2"/>'
            + _text(W // 2, 660, scene.get("figure_caption", "figure"), size=36, fill=MUTED, anchor="middle")
        )
    else:  # points
        body = _headline(headline, accent, y=230) + _points(points, accent, top=470)

    return _frame(body, slug=slug, accent=accent)


def render_storyboard(scenes: list[dict]) -> list[str]:
    return [render_scene_svg({**scene, "index": scene.get("index", i + 1)})
            for i, scene in enumerate(scenes)]
