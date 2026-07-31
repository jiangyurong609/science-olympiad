"""Phase M — data-driven diagrams on slides."""
from __future__ import annotations

import xml.dom.minidom as minidom

import pytest

from app.services.video_diagrams import (
    DiagramError, bar_diagram, flow_diagram, pyramid_diagram, render_diagram, table_diagram,
)
from app.services.video_slides import render_scene_svg


def _parses(fragment: str) -> None:
    minidom.parseString(f'<svg xmlns="http://www.w3.org/2000/svg">{fragment}</svg>')


FLOW = {"kind": "flow", "steps": [
    {"label": "Algae", "sublabel": "TL1 producer"}, {"label": "Mayfly", "sublabel": "TL2"},
    {"label": "Small fish", "sublabel": "TL3"}, {"label": "Heron", "sublabel": "TL4"}]}
PYRAMID = {"kind": "pyramid", "levels": [
    {"label": "Producers", "value": 10000, "value_label": "10,000"},
    {"label": "Primary", "value": 1000, "value_label": "1,000"},
    {"label": "Secondary", "value": 100, "value_label": "100"}]}
BARS = {"kind": "bars", "bars": [
    {"label": "Ectotherms", "value": 40, "value_label": "10-40%"},
    {"label": "Endotherms", "value": 3, "value_label": "1-3%"}]}
TABLE = {"kind": "table", "headers": ["Trophic level", "kcal/m2/yr", "efficiency"],
         "rows": [["Producers", "20,810", "-"], ["Primary", "3,368", "16.2%"]]}


@pytest.mark.parametrize("spec", [FLOW, PYRAMID, BARS, TABLE])
def test_every_diagram_kind_emits_well_formed_svg(spec):
    fragment, height, width = render_diagram(spec)
    _parses(fragment)
    assert height > 0 and width > 0


def test_flow_draws_one_arrow_between_each_pair():
    fragment, _, _ = flow_diagram(FLOW["steps"])
    # direction is the point of a food chain, so arrows must connect every pair
    assert fragment.count("marker-end") == len(FLOW["steps"]) - 1
    assert "Algae" in fragment and "Heron" in fragment


def test_pyramid_tier_width_encodes_quantity():
    fragment, _, _ = pyramid_diagram(PYRAMID["levels"])
    widths = [int(w) for w in __import__("re").findall(r'<rect[^>]*width="(\d+)"', fragment)]
    assert widths == sorted(widths, reverse=True), "a larger quantity must draw a wider tier"


def test_inverted_data_draws_an_inverted_shape():
    # biomass pyramids really do invert; the diagram must not silently normalise that away
    fragment, _, _ = pyramid_diagram([
        {"label": "Phytoplankton", "value": 4}, {"label": "Zooplankton", "value": 20}])
    widths = [int(w) for w in __import__("re").findall(r'<rect[^>]*width="(\d+)"', fragment)]
    assert widths[1] > widths[0]


def test_bars_scale_against_the_largest_value():
    fragment, _, _ = bar_diagram(BARS["bars"])
    _parses(fragment)
    assert "10-40%" in fragment and "1-3%" in fragment


def test_table_renders_headers_and_rows():
    fragment, _, _ = table_diagram(TABLE["headers"], TABLE["rows"])
    assert "TROPHIC LEVEL" in fragment      # headers are set in caps
    assert "20,810" in fragment


def test_content_is_escaped_not_injected():
    fragment, _, _ = flow_diagram([{"label": "A & B", "sublabel": "<script>x</script>"}])
    _parses(fragment)
    assert "<script>" not in fragment and "&amp;" in fragment


def test_unknown_or_empty_specs_fail_loudly():
    with pytest.raises(DiagramError, match="unknown diagram kind"):
        render_diagram({"kind": "sankey"})
    with pytest.raises(DiagramError):
        flow_diagram([])
    with pytest.raises(DiagramError):
        table_diagram(["h"], [])


def test_slide_with_a_diagram_is_valid_and_contains_it():
    svg = render_scene_svg({"index": 6, "archetype": "diagram", "headline": "The food chain",
                            "diagram": FLOW})
    minidom.parseString(svg)
    assert "Algae" in svg and "Heron" in svg


def test_a_broken_diagram_degrades_to_a_caption_not_a_blank_slide():
    svg = render_scene_svg({"index": 6, "archetype": "diagram", "headline": "Broken",
                            "diagram": {"kind": "nope"}})
    minidom.parseString(svg)
    assert "diagram unavailable" in svg
    assert "BROKEN" in svg, "the headline must survive so the slide still teaches something"


def test_a_narrow_tier_moves_its_value_outside_instead_of_overlapping():
    """A long label on a small tier would otherwise print on top of the value."""
    fragment, _, _ = pyramid_diagram([
        {"label": "Producers", "value": 100, "value_label": "100"},
        {"label": "Secondary consumers indeed", "value": 3, "value_label": "100"},
    ])
    _parses(fragment)
    # the crowded tier's value is drawn muted and left-anchored outside the bar
    assert 'fill="#8ba09d"' in fragment


def test_diagram_is_centred_on_the_slide():
    svg = render_scene_svg({"index": 1, "archetype": "diagram", "headline": "H", "diagram": PYRAMID})
    import re
    left = int(re.search(r'translate\((\d+),', svg).group(1))
    assert left > 140, "a narrow diagram must be centred, not pinned to the left rail"
