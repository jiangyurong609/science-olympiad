"""Phase 7a — recover the figures a PDF import currently throws away.

Import reads only `extract_text()`. Every diagram, specimen photo, chart and map in the
source PDF is discarded, so items that depend on one are flagged `image_dependent` and
excluded from scoring — roughly 224 of them. The question is not badly parsed; the thing it
refers to simply is not there.

Embedded images are recoverable from the same bytes the text came from. Two problems make a
naive extraction worse than useless, and both are handled here:

  * **decorative noise** — logos, rules, bullets and letterhead are embedded images too. A
    school crest attached to a question as "the figure" is a confident wrong answer, so
    anything too small, too thin, or too plain is dropped.
  * **repetition** — a header logo appears on all 12 pages. Images are hashed, and any image
    that recurs across pages is treated as furniture rather than a figure.

Figures are anchored to a **page**, not to an item: the page is what the extractor actually
knows. Matching a figure to the question that refers to it is `attach_figures_to_items`,
which uses the `[Page N]` markers both extractors already emit.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field

from pypdf import PdfReader

# below this a raster is an icon, a bullet, or a rule — never a specimen or a diagram
MIN_WIDTH = 120
MIN_HEIGHT = 120
MAX_ASPECT = 12.0          # letterhead bars and dividers are long and thin
MAX_FIGURES_PER_PAGE = 8

# Encoded byte size was tried as a proxy for "has real content" and removed. pypdf hands back
# a re-encoded PNG, and a line drawing or a flat-colour chart — precisely the figures these
# tests use — compresses to a couple of kilobytes, so the rule dropped real figures while
# keeping any noisy scan. Dimensions, aspect, uniformity, and cross-page repetition are all
# properties of the image itself and do not move with the encoder.
PAGE_MARKER = re.compile(r"\[Page (\d+)\]")


@dataclass
class Figure:
    page: int
    sequence: int
    content: bytes
    content_type: str
    width: int
    height: int
    sha256: str
    storage_key: str = ""

    @property
    def descriptor(self) -> dict:
        """The JSON form stored on `Question.assets`."""
        return {
            "kind": "figure", "page": self.page, "sequence": self.sequence,
            "storage_key": self.storage_key, "content_type": self.content_type,
            "width": self.width, "height": self.height, "sha256": self.sha256,
        }


@dataclass
class ExtractionReport:
    figures: list[Figure] = field(default_factory=list)
    pages: int = 0
    rejected: dict = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1


def _is_plausible_figure(width: int, height: int, pil_image, report: ExtractionReport) -> bool:
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        report.reject("too_small")
        return False
    longest, shortest = max(width, height), max(1, min(width, height))
    if longest / shortest > MAX_ASPECT:
        report.reject("rule_or_divider")
        return False
    # A single-colour raster is a background panel or a spacer. The threshold is exactly one
    # colour, not "few colours": a black-on-white line drawing has two, and rejecting those
    # would throw away the most common diagram in a printed test.
    if pil_image is not None:
        try:
            colours = pil_image.convert("RGB").getcolors(maxcolors=2)
        except Exception:
            colours = None
        if colours is not None and len(colours) <= 1:
            report.reject("uniform_block")
            return False
    return True


def extract_figures(pdf_bytes: bytes) -> ExtractionReport:
    """Pull plausible figures out of a PDF, page by page."""
    report = ExtractionReport()
    reader = PdfReader(io.BytesIO(pdf_bytes))
    if reader.is_encrypted:
        report.reject("encrypted")
        return report
    report.pages = len(reader.pages)

    by_hash: dict[str, list[Figure]] = {}
    for page_number, page in enumerate(reader.pages, start=1):
        kept_on_page = 0
        try:
            images = list(page.images)
        except Exception:
            # a malformed image stream must not abort the whole import
            report.reject("page_image_read_failed")
            continue
        for sequence, image in enumerate(images, start=1):
            if kept_on_page >= MAX_FIGURES_PER_PAGE:
                report.reject("page_figure_cap")
                break
            data = image.data or b""
            pil_image = getattr(image, "image", None)
            width = getattr(pil_image, "width", 0) or 0
            height = getattr(pil_image, "height", 0) or 0
            if not _is_plausible_figure(width, height, pil_image, report):
                continue
            digest = hashlib.sha256(data).hexdigest()
            figure = Figure(
                page=page_number, sequence=sequence, content=data,
                content_type=_content_type(image.name), width=width, height=height,
                sha256=digest,
            )
            by_hash.setdefault(digest, []).append(figure)
            kept_on_page += 1

    for digest, group in by_hash.items():
        # the same raster on more than one page is furniture: a logo, a header, a watermark
        if len({fig.page for fig in group}) > 1:
            report.reject("repeated_across_pages")
            continue
        report.figures.extend(group)
    report.figures.sort(key=lambda fig: (fig.page, fig.sequence))
    return report


def _content_type(name: str) -> str:
    lowered = (name or "").lower()
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith(".tiff"):
        return "image/tiff"
    return "application/octet-stream"


# "Figure 3", "Fig. 2b", "Diagram A", "Image 4" — the labels a printed test actually uses to
# tie a question to a picture. Matching on these is the only anchor the document itself
# provides; everything else is adjacency.
# The separator is `\s+`, not `\s*`, and the noun group carries its own case-insensitivity
# rather than the whole pattern. With `re.I` on the whole pattern `[A-Z]` matched lowercase,
# so "images", "figures" and "maps" all parsed as a label named "s" — page 2 of one real exam
# reported ten labels, most of them noise.
FIGURE_LABEL = re.compile(
    r"\b(?i:figure|fig\.?|diagram|image|photo|photograph|chart|graph|map)\s+"
    r"(\d{1,3}[a-z]?|[A-Z])\b")

# Which match kinds are strong enough to un-drop an image-dependent item. Adversarial review
# noted that one raster and one item sharing a page proves only that — not that the raster is
# the figure being referenced. `sole_on_page` is kept as resolving because the item must also
# explicitly reference a figure and be alone with it, but it is reported separately so its
# weaker basis stays visible rather than being folded into one "unique" number.
RESOLVING_MATCHES = {"label_matched", "sole_on_page"}


def figure_labels_in(text: str) -> set[str]:
    """The figure labels a piece of text names, normalised."""
    return {match.group(1).lower() for match in FIGURE_LABEL.finditer(text or "")}


def page_figure_labels(text: str) -> dict[int, set[str]]:
    """Which figure labels are *captioned* on each page.

    Only line-initial mentions count. "Image 1 shows Enceladus. Around which planet…" is a
    question referring to a figure, not a caption identifying one, and counting it would let a
    question anchor itself to whatever figure happened to sit on the page its own text was
    printed on — pairing by coincidence, dressed as the strongest anchor available.
    """
    offsets = page_offsets(text)
    if not offsets:
        return {}
    out: dict[int, set[str]] = {}
    for match in FIGURE_LABEL.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        if text[line_start:match.start()].strip():
            continue          # something precedes it on the line: a reference, not a caption
        page = page_of_offset(offsets, match.start())
        if page is not None:
            out.setdefault(page, set()).add(match.group(1).lower())
    return out


def references_figure(stem: str) -> bool:
    """Whether the stem points at a figure at all.

    Reuses the scorer's definition so "needs a figure" means one thing across the codebase;
    an item the scorer would not consider figure-dependent must not be handed a figure here.
    """
    from app.services.scoring import references_figure as _scorer_references_figure
    return _scorer_references_figure(stem)


def page_offsets(text: str) -> list[tuple[int, int]]:
    """Return (character_offset, page_number) for each `[Page N]` marker, in order."""
    return [(match.start(), int(match.group(1))) for match in PAGE_MARKER.finditer(text)]


def page_of_offset(offsets: list[tuple[int, int]], offset: int) -> int | None:
    """Which page a character offset falls on, or None when the text has no markers."""
    page = None
    for marker_offset, marker_page in offsets:
        if marker_offset <= offset:
            page = marker_page
        else:
            break
    return page


def locate_items(text: str, items: list[dict]) -> list[int | None]:
    """Find the page each parsed item came from.

    The page is derived from where the item's text actually appears rather than asked of the
    model. A parser that is already unsure enough to flag an item `image_dependent` is not
    the thing to trust for the page number, and a wrong page attaches the wrong figure —
    which is worse than attaching none.
    """
    offsets = page_offsets(text)
    if not offsets:
        return [None] * len(items)

    pages: list[int | None] = []
    cursor = 0
    for item in items:
        # The printed label is tried first because it is the one field the parser is told to
        # preserve verbatim ("preserve the printed numbering"), while the stem is explicitly
        # rewritten — the prompt asks for it to be expanded so it reads standalone. Matching
        # the stem first therefore failed on exactly the items that were expanded most, which
        # a backfill run measured directly: 11 of 43 could not be located at all.
        label = str(item.get("label") or "").strip()
        found = _find_label(text, label, cursor) if label else -1
        if found < 0 and label:
            found = _find_label(text, label, 0)
        if found < 0:
            stem = (item.get("stem") or "").strip()
            probe = _probe(stem)
            found = text.find(probe, cursor) if probe else -1
            if found < 0 and probe:
                found = text.find(probe)      # items may be reordered relative to the text
        if found < 0:
            pages.append(None)
            continue
        cursor = found
        pages.append(page_of_offset(offsets, found))
    return pages


def _probe(stem: str) -> str:
    """A distinctive slice of the stem, long enough not to match by accident."""
    cleaned = re.sub(r"\s+", " ", stem).strip()
    return cleaned[:60] if len(cleaned) >= 24 else ""


def _find_label(text: str, label: str, start: int) -> int:
    match = re.compile(rf"(?m)^\s*{re.escape(label)}[.)]\s").search(text, start)
    return match.start() if match else -1


def attach_figures_to_items(text: str, items: list[dict],
                            figures: list[Figure]) -> dict:
    """Give each item the figures printed on its own page.

    A page can hold several figures and several questions, so this is an association, not a
    claim about which figure a given question means. That ambiguity is recorded on the item
    (`figure_match` = `unique` or `ambiguous`) so review can see which attachments were
    guessed rather than determined, and so an ambiguous attachment never silently becomes
    evidence that the item is answerable.
    """
    by_page: dict[int, list[Figure]] = {}
    for figure in figures:
        by_page.setdefault(figure.page, []).append(figure)

    pages = locate_items(text, items)
    stats = {"located": 0, "unlocated": 0, "with_figures": 0,
             "label_matched": 0, "sole_on_page": 0, "ambiguous": 0,
             "no_figure_reference": 0, "image_dependent_resolved": 0}

    items_on_page: dict[int, int] = {}
    for page in pages:
        if page is not None:
            items_on_page[page] = items_on_page.get(page, 0) + 1
    labels_by_page = page_figure_labels(text)

    for item, page in zip(items, pages):
        item["page"] = page
        stem = str(item.get("stem") or "")

        # A named label anchors an item on its own, so this is tried before page location.
        # It has to be: a backfill run showed 11 of 43 items unlocatable, and their stems read
        # "Image 1 shows Enceladus…" — they named the figure explicitly while their rewritten
        # text matched nothing in the source. Requiring page location first meant the
        # strongest available anchor was never consulted for exactly the items that had one.
        named = figure_labels_in(stem)
        if named:
            pages_with_label = [p for p, labels in labels_by_page.items() if named & labels]
            if len(pages_with_label) == 1:
                anchor_page = pages_with_label[0]
                anchored = by_page.get(anchor_page, [])
                if len(anchored) == 1:
                    item["page"] = anchor_page
                    item["figures"] = [anchored[0].descriptor]
                    item["figure_match"] = "label_matched"
                    item["figure_label"] = sorted(named & labels_by_page[anchor_page])[0]
                    stats["located"] += 1
                    stats["with_figures"] += 1
                    stats["label_matched"] += 1
                    if item.get("image_dependent"):
                        stats["image_dependent_resolved"] += 1
                    continue

        if page is None:
            stats["unlocated"] += 1
            item["figures"] = []
            item["figure_match"] = "unlocated"
            continue
        stats["located"] += 1
        page_figures = by_page.get(page, [])
        item["figures"] = [fig.descriptor for fig in page_figures]
        if not page_figures:
            item["figure_match"] = "none"
            continue
        stats["with_figures"] += 1

        # An item that never mentions a figure has no figure to pair with. Attaching one
        # because it happened to share a page is how a text question ends up illustrated by
        # its neighbour's diagram.
        if not references_figure(stem):
            item["figure_match"] = "no_figure_reference"
            stats["no_figure_reference"] += 1
            continue

        # A label on the item's own page, where the global lookup above was inconclusive
        # because the label appears on more than one page.
        matched = named & labels_by_page.get(page, set())
        if matched and len(page_figures) == 1:
            item["figure_match"] = "label_matched"
            item["figure_label"] = sorted(matched)[0]
            stats["label_matched"] += 1
        elif len(page_figures) == 1 and items_on_page.get(page, 0) == 1:
            # One figure, one figure-referencing question, one page. Adjacency, not proof —
            # kept separate from `label_matched` so review can tell them apart.
            item["figure_match"] = "sole_on_page"
            stats["sole_on_page"] += 1
        else:
            item["figure_match"] = "ambiguous"
            stats["ambiguous"] += 1
        if item.get("image_dependent") and item["figure_match"] in RESOLVING_MATCHES:
            stats["image_dependent_resolved"] += 1
    return stats
