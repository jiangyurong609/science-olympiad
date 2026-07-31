"""Phase M — data-driven diagrams for slides and lessons.

Bulleted text is the weakest way to teach a relationship. A food chain is a sequence, an
energy budget is a set of proportions, a trophic pyramid is a shape — each of those reads
faster as a picture than as a sentence, which matters most for the students least likely to
read the sentence.

These render to SVG from plain data, so the same diagram can appear on a video slide and in
a lesson without a diagram library, and colour keeps its meaning: amber energy, ember loss,
green production, cyan data, violet recycling.
"""
from __future__ import annotations

from xml.sax.saxutils import escape

INK = "#e9f4f1"
MUTED = "#8ba09d"
PANEL = "#16262a"
RULE = "#2a4046"
BODY_FONT = "'DejaVu Sans', 'Liberation Sans', Arial, Helvetica, sans-serif"
MONO_FONT = "'DejaVu Sans Mono', 'Liberation Mono', 'Courier New', monospace"

ACCENTS = {
    "energy": "#f2a83a", "loss": "#e0522c", "production": "#34c98a",
    "data": "#46b3d6", "recycle": "#a97fd6",
}
# A pyramid/flow reads as a gradient from production at the base to loss at the top.
LEVEL_COLOURS = ["#34c98a", "#7bbf63", "#c9b23f", "#f2a83a", "#e0522c"]


class DiagramError(ValueError):
    pass


def _t(x, y, text, *, size, fill=INK, weight=400, anchor="start", family=BODY_FONT):
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">'
            f'{escape(str(text))}</text>')


def _accent(name: str) -> str:
    return ACCENTS.get(name or "", ACCENTS["energy"])


def _ellipsis(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def flow_diagram(steps: list[dict], *, width=1640, accent="energy"):
    """A left-to-right chain: food chain, process, energy path.

    Each step is {label, sublabel?}. Arrows carry the direction of flow, which is the whole
    point of the diagram — energy moves from the eaten to the eater.
    """
    if not steps:
        raise DiagramError("flow diagram needs at least one step")
    steps = steps[:5]
    colour = _accent(accent)
    gap, height = 46, 132
    box_w = int((width - gap * (len(steps) - 1)) / len(steps))
    parts = [
        f'<defs><marker id="fa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        f'markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0 0 L10 5 L0 10 z" fill="{MUTED}"/></marker></defs>'
    ]
    for index, step in enumerate(steps):
        x = index * (box_w + gap)
        parts.append(
            f'<rect x="{x}" y="0" width="{box_w}" height="{height}" rx="8" fill="{PANEL}" '
            f'stroke="{colour}" stroke-width="2"/>'
        )
        cx = x + box_w // 2
        parts.append(_t(cx, 60, _ellipsis(step.get("label", ""), 22), size=32, weight=700, anchor="middle"))
        if step.get("sublabel"):
            parts.append(_t(cx, 96, _ellipsis(step["sublabel"], 26), size=22, fill=MUTED,
                            anchor="middle", family=MONO_FONT))
        if index < len(steps) - 1:
            ax = x + box_w + 6
            parts.append(f'<path d="M{ax} {height // 2} L{ax + gap - 14} {height // 2}" '
                         f'stroke="{MUTED}" stroke-width="3" marker-end="url(#fa)"/>')
    return f'<g transform="translate(0,0)">{"".join(parts)}</g>', height, width


def pyramid_diagram(levels: list[dict], *, width=1200):
    """A trophic pyramid. Tier width encodes the quantity, so the shape itself is the lesson —
    and an inverted one is visibly wrong."""
    if not levels:
        raise DiagramError("pyramid needs at least one level")
    levels = levels[:5]
    values = [float(l.get("value", 0) or 0) for l in levels]
    peak = max(values) or 1.0
    row_h, gap = 74, 10
    parts = []
    for index, level in enumerate(levels):
        share = (float(level.get("value", 0) or 0) / peak) if peak else 0
        w = max(220, int(width * (0.32 + 0.68 * share)))
        x = (width - w) // 2
        y = index * (row_h + gap)
        colour = LEVEL_COLOURS[min(index, len(LEVEL_COLOURS) - 1)]
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{row_h}" rx="6" fill="{colour}"/>')
        label = _ellipsis(level.get("label", ""), 30)
        parts.append(_t(x + 24, y + 46, label, size=28, weight=700, fill="#08120f"))
        value = level.get("value_label")
        if value:
            # Approximate advance widths; a narrow tier cannot hold both, so the value moves
            # outside rather than printing on top of the label.
            needed = len(label) * 15.5 + len(str(value)) * 14 + 70
            if needed <= w:
                parts.append(_t(x + w - 24, y + 46, value, size=24, fill="#08120f",
                                anchor="end", family=MONO_FONT))
            else:
                parts.append(_t(x + w + 20, y + 46, value, size=24, fill=MUTED,
                                anchor="start", family=MONO_FONT))
    return "".join(parts), len(levels) * (row_h + gap), width


def bar_diagram(bars: list[dict], *, width=1500, accent="data"):
    """Horizontal comparison: efficiencies, productivity by biome, transfer percentages."""
    if not bars:
        raise DiagramError("bar diagram needs at least one bar")
    bars = bars[:6]
    colour = _accent(accent)
    peak = max((float(b.get("value", 0) or 0) for b in bars), default=1.0) or 1.0
    label_w, value_w, row_h, gap = 520, 200, 56, 20
    track_w = width - label_w - value_w
    parts = []
    for index, bar in enumerate(bars):
        y = index * (row_h + gap)
        parts.append(_t(0, y + 38, _ellipsis(bar.get("label", ""), 34), size=28, fill=INK))
        parts.append(f'<rect x="{label_w}" y="{y + 14}" width="{track_w}" height="28" rx="6" fill="#0d171a"/>')
        filled = max(6, int(track_w * (float(bar.get("value", 0) or 0) / peak)))
        parts.append(f'<rect x="{label_w}" y="{y + 14}" width="{filled}" height="28" rx="6" fill="{colour}"/>')
        if bar.get("value_label"):
            parts.append(_t(label_w + track_w + 24, y + 38, bar["value_label"], size=26,
                            fill=colour, family=MONO_FONT))
    return "".join(parts), len(bars) * (row_h + gap), width


def table_diagram(headers: list[str], rows: list[list], *, width=1640):
    """A real dataset — the thing that turns a claim into evidence."""
    if not headers or not rows:
        raise DiagramError("table needs headers and at least one row")
    rows = rows[:6]
    cols = len(headers)
    col_w = width // cols
    row_h = 58
    parts = []
    for index, header in enumerate(headers):
        anchor, x = ("start", index * col_w) if index == 0 else ("end", (index + 1) * col_w - 20)
        parts.append(_t(x, 34, str(header).upper(), size=22, fill=MUTED, family=MONO_FONT, anchor=anchor))
    parts.append(f'<rect x="0" y="52" width="{width}" height="2" fill="{RULE}"/>')
    for r, row in enumerate(rows):
        y = 54 + (r + 1) * row_h
        for c, cell in enumerate(row[:cols]):
            first = c == 0
            anchor, x = ("start", c * col_w) if first else ("end", (c + 1) * col_w - 20)
            parts.append(_t(x, y, _ellipsis(cell, 26), size=28,
                            fill=INK if first else ACCENTS["energy"],
                            anchor=anchor, family=BODY_FONT if first else MONO_FONT))
    return "".join(parts), 54 + (len(rows) + 1) * row_h, width


RENDERERS = {
    "flow": flow_diagram,
    "pyramid": pyramid_diagram,
    "bars": bar_diagram,
    "table": table_diagram,
}


def render_diagram(spec: dict) -> tuple[str, int, int]:
    """Render a diagram spec to (svg fragment, height, natural width). Unknown kinds fail
    loudly rather than silently producing an empty slide."""
    kind = (spec or {}).get("kind")
    if kind not in RENDERERS:
        raise DiagramError(f"unknown diagram kind {kind!r}; expected one of {sorted(RENDERERS)}")
    if kind == "flow":
        return flow_diagram(spec.get("steps") or [], accent=spec.get("accent", "energy"))
    if kind == "pyramid":
        return pyramid_diagram(spec.get("levels") or [])
    if kind == "bars":
        return bar_diagram(spec.get("bars") or [], accent=spec.get("accent", "data"))
    return table_diagram(spec.get("headers") or [], spec.get("rows") or [])
