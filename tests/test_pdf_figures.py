"""Phase 7a — figures must survive import, and junk must not be mistaken for one.

Attaching a school crest to a question as "the figure" is worse than attaching nothing: the
item then looks answerable and gets scored. These tests pin both halves — real figures are
kept, furniture is rejected, and an attachment the extractor had to guess is marked as a
guess rather than presented as fact.
"""
from __future__ import annotations

import io

import pytest

from app.services.pdf_figures import (
    Figure, attach_figures_to_items, extract_figures, locate_items, page_offsets,
    page_of_offset,
)

PAGED_TEXT = """[Page 1]
1. Identify the mineral shown in the photograph.
2. What is its hardness on the Mohs scale?

[Page 2]
3. Which sample is a metamorphic rock?

[Page 3]
4. Name the depositional environment in the diagram.
"""


PAGE_TEXT_2 = """[Page 1]
1. Identify the mineral shown in the photograph.

[Page 2]
3. Which sample is shown in the diagram?
"""


def _figure(page: int, sequence: int = 1, digest: str = "d") -> Figure:
    return Figure(page=page, sequence=sequence, content=b"x", content_type="image/png",
                  width=400, height=300, sha256=digest, storage_key=f"k{page}{sequence}")


# ---------------------------------------------------------------- page anchoring

def test_page_markers_are_read_in_order():
    offsets = page_offsets(PAGED_TEXT)
    assert [page for _, page in offsets] == [1, 2, 3]
    assert [PAGED_TEXT.index(f"[Page {page}]") for _, page in offsets] == \
        [offset for offset, _ in offsets]


def test_an_offset_maps_to_the_page_it_falls_on():
    offsets = page_offsets(PAGED_TEXT)
    assert page_of_offset(offsets, PAGED_TEXT.index("Mohs")) == 1
    assert page_of_offset(offsets, PAGED_TEXT.index("metamorphic")) == 2
    assert page_of_offset(offsets, PAGED_TEXT.index("depositional")) == 3
    assert page_of_offset([], 5) is None


def test_items_are_located_by_their_own_text_not_by_the_models_word():
    items = [
        {"label": "1", "stem": "Identify the mineral shown in the photograph."},
        {"label": "3", "stem": "Which sample is a metamorphic rock?"},
        {"label": "4", "stem": "Name the depositional environment in the diagram."},
    ]
    assert locate_items(PAGED_TEXT, items) == [1, 2, 3]


def test_an_item_that_cannot_be_found_gets_no_page_rather_than_a_guess():
    items = [{"label": "9", "stem": "A question that appears nowhere in the source text."}]
    assert locate_items(PAGED_TEXT, items) == [None]


def test_text_without_page_markers_yields_no_pages():
    items = [{"label": "1", "stem": "Identify the mineral shown in the photograph."}]
    assert locate_items("no markers here at all", items) == [None]


# ---------------------------------------------------------------- attachment

def test_a_lone_figure_with_a_lone_figure_referencing_question_is_paired():
    items = [{"label": "3", "stem": "Which sample is shown in the diagram?",
              "image_dependent": True}]
    stats = attach_figures_to_items(PAGE_TEXT_2, items, [_figure(2)])
    assert items[0]["page"] == 2
    assert items[0]["figure_match"] == "sole_on_page"
    assert len(items[0]["figures"]) == 1
    assert stats["image_dependent_resolved"] == 1


def test_an_item_that_never_mentions_a_figure_is_given_none():
    """Attaching a figure because it shares a page is how a text question ends up
    illustrated by its neighbour's diagram."""
    items = [{"label": "3", "stem": "Which of these minerals is hardest?"}]
    stats = attach_figures_to_items(PAGE_TEXT_2, items, [_figure(2)])
    assert items[0]["figure_match"] == "no_figure_reference"
    assert stats["no_figure_reference"] == 1
    assert stats["image_dependent_resolved"] == 0


def test_a_printed_label_is_a_stronger_anchor_than_adjacency():
    """When the document itself ties question to picture, say so — and distinguish it from
    a pairing that was merely inferred from sharing a page."""
    text = "[Page 1]\n1. Identify the mineral in Figure 3.\n\nFigure 3. Specimen tray.\n"
    items = [{"label": "1", "stem": "Identify the mineral in Figure 3.",
              "image_dependent": True}]
    stats = attach_figures_to_items(text, items, [_figure(1)])
    assert items[0]["figure_match"] == "label_matched"
    assert items[0]["figure_label"] == "3"
    assert stats["label_matched"] == 1


def test_two_questions_on_one_page_make_the_attachment_ambiguous():
    """Both items get the candidate, but neither may claim it is theirs."""
    items = [
        {"label": "1", "stem": "Identify the mineral shown in the photograph."},
        {"label": "2", "stem": "What does the diagram above show?"},
    ]
    attach_figures_to_items(PAGED_TEXT, items, [_figure(1)])
    assert [i["figure_match"] for i in items] == ["ambiguous", "ambiguous"]


def test_an_unlocated_item_receives_no_figures():
    items = [{"label": "9", "stem": "Nowhere to be found in this document at all."}]
    stats = attach_figures_to_items(PAGED_TEXT, items, [_figure(1), _figure(2)])
    assert items[0]["figures"] == []
    assert items[0]["figure_match"] == "unlocated"
    assert stats["unlocated"] == 1


def test_a_page_with_no_figure_is_reported_as_none_not_ambiguous():
    items = [{"label": "4", "stem": "Name the depositional environment in the diagram."}]
    attach_figures_to_items(PAGED_TEXT, items, [_figure(1)])
    assert items[0]["figure_match"] == "none"
    assert items[0]["figures"] == []


# ---------------------------------------------------------------- rejection rules

def _minimal_pdf(pages: list[list[tuple[int, int]]], *, flat: bool = False,
                 uniform: bool = False) -> bytes:
    """Build a PDF carrying raw-RGB image XObjects of the given sizes.

    Written by hand rather than with a PDF library: the extraction rules are the thing under
    test, and pulling in a document generator just to exercise them would add a dependency
    the application itself does not need.
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)          # 1-indexed object number

    kids, page_objects = [], []
    for page_specs in pages:
        xobjects, resources = [], []
        for index, (width, height) in enumerate(page_specs):
            if uniform:
                pixel = lambda x, y: 200                      # one colour everywhere
            elif flat:
                pixel = lambda x, y: 0 if (x // 20) % 2 else 255   # two-tone line drawing
            else:
                pixel = lambda x, y: (x * 7 + y * 13 + index * 29) % 256
            raw = bytes(pixel(x, y)
                        for y in range(height) for x in range(width) for _ in range(3))
            number = add(
                b"<< /Type /XObject /Subtype /Image /Width " + str(width).encode()
                + b" /Height " + str(height).encode()
                + b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length "
                + str(len(raw)).encode() + b" >>\nstream\n" + raw + b"\nendstream"
            )
            name = f"/Im{index}".encode()
            xobjects.append(number)
            resources.append(name + b" " + str(number).encode() + b" 0 R")
        content = add(b"<< /Length 0 >>\nstream\n\nendstream")
        page_objects.append((resources, content))

    pages_number = len(objects) + len(page_objects) + 1
    for resources, content in page_objects:
        number = add(
            b"<< /Type /Page /Parent " + str(pages_number).encode()
            + b" 0 R /MediaBox [0 0 612 792] /Resources << /XObject << "
            + b" ".join(resources) + b" >> >> /Contents "
            + str(content).encode() + b" 0 R >>"
        )
        kids.append(number)
    add(b"<< /Type /Pages /Kids [" + b" ".join(str(k).encode() + b" 0 R" for k in kids)
        + b"] /Count " + str(len(kids)).encode() + b" >>")
    catalog = add(b"<< /Type /Catalog /Pages " + str(pages_number).encode() + b" 0 R >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root "
            + str(catalog).encode() + b" 0 R >>\nstartxref\n"
            + str(xref_at).encode() + b"\n%%EOF\n")
    return bytes(out)


def test_tiny_rasters_are_not_figures():
    report = extract_figures(_minimal_pdf([[(40, 40)]]))
    assert report.figures == []
    assert report.rejected.get("too_small") == 1


def test_a_short_bar_is_caught_by_the_size_floor():
    report = extract_figures(_minimal_pdf([[(1500, 80)]]))
    assert report.figures == []
    assert report.rejected.get("too_small") == 1


def test_a_tall_enough_but_very_wide_bar_is_caught_by_aspect():
    """Dimensions alone would pass this letterhead rule: it clears the height floor and is
    only rejected because it is 14x wider than it is tall."""
    report = extract_figures(_minimal_pdf([[(1800, 130)]]))
    assert report.figures == []
    assert report.rejected.get("rule_or_divider") == 1


def test_a_flat_line_drawing_is_kept_not_dropped_for_compressing_well():
    """Encoded size was once used as a content proxy; a two-tone diagram compresses to a
    couple of kilobytes and was dropped by it. Dimensions decide, not the encoder."""
    report = extract_figures(_minimal_pdf([[(200, 160)]], flat=True))
    assert len(report.figures) == 1, report.rejected


def test_a_uniform_block_is_not_a_figure():
    report = extract_figures(_minimal_pdf([[(200, 160)]], uniform=True))
    assert report.figures == []
    assert report.rejected.get("uniform_block") == 1


def test_a_real_figure_survives_extraction():
    report = extract_figures(_minimal_pdf([[(200, 160)]]))
    assert len(report.figures) == 1
    figure = report.figures[0]
    assert figure.page == 1
    assert figure.width == 200 and figure.height == 160
    assert figure.sha256


def test_a_logo_repeated_on_every_page_is_furniture_not_a_figure():
    """The same raster on several pages is a header, and attaching it to a question would
    make an unanswerable item look answerable."""
    # identical dimensions and identical pixel data on all three pages
    report = extract_figures(_minimal_pdf([[(200, 160)], [(200, 160)], [(200, 160)]]))
    assert report.figures == [], "a header logo must never be offered as a figure"
    assert report.rejected.get("repeated_across_pages") == 1


def test_two_distinct_figures_on_one_page_are_both_kept():
    report = extract_figures(_minimal_pdf([[(200, 160), (240, 180)]]))
    assert len(report.figures) == 2
    assert {fig.page for fig in report.figures} == {1}
    assert len({fig.sha256 for fig in report.figures}) == 2


def test_a_malformed_pdf_raises_rather_than_returning_silence():
    with pytest.raises(Exception):
        extract_figures(b"not a pdf at all")


def test_a_label_inside_question_prose_is_not_treated_as_a_caption():
    """"Image 1 shows Enceladus…" identifies nothing; it refers to something identified
    elsewhere. Counting it would let a question anchor to whichever figure happened to sit on
    the page its own text was printed on."""
    from app.services.pdf_figures import page_figure_labels
    text = ("[Page 1]\n"
            "4b. Image 1 shows Enceladus. Around which planet does it orbit?\n"
            "[Page 2]\n"
            "Image 1. Enceladus, imaged by Cassini.\n")
    labels = page_figure_labels(text)
    assert 1 not in labels, "the prose reference must not register as a caption"
    assert labels.get(2) == {"1"}, "the caption on page 2 must"


def test_a_prose_reference_cannot_anchor_a_figure_by_coincidence():
    text = ("[Page 1]\n"
            "4b. Image 1 shows Enceladus. Around which planet does it orbit?\n")
    items = [{"label": "4b", "stem": "Image 1 shows Enceladus. Around which planet?",
              "image_dependent": True}]
    stats = attach_figures_to_items(text, items, [_figure(1)])
    assert items[0]["figure_match"] != "label_matched"
    assert stats["label_matched"] == 0
