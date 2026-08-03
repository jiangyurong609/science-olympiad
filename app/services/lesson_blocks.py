"""One reading of a lesson checkpoint, for every path that touches one.

Checkpoints are not written in a single shape. Hand-authored blocks use `question` and
`correct_index`; blocks produced by `split_lessons` use `prompt` and `answer_index`. Nothing
declared one canonical form, so each path picked a pair and silently ignored the other half of
the content — 41 of the pilot's 73 published checkpoints are the second shape, and every one
of them was broken in a different way depending on which path reached it:

  * the serve path stripped `correct_index` before sending a lesson to the browser, so the
    41 blocks keyed on `answer_index` **shipped their answer key to the student**;
  * the reader rendered `block.question`, so those 41 showed a heading and four choices with
    no question attached to them;
  * the grading path matched a checkpoint by `block["id"]` — which those blocks do not have —
    and compared the answer against `correct_index`, which for them is `None`. So the answer
    could not be submitted, and could not have been marked correct if it had been;
  * because a lesson completes only when every checkpoint is correct, no lesson containing one
    could ever complete, so no mastery evidence was ever recorded from lesson work at all.

The fix is not to pick a winner and rewrite the content — a schema migration would leave the
same class of bug waiting for the next generator. It is to read both shapes in one place, and
have every path use it.
"""
from __future__ import annotations

CHECKPOINT = "checkpoint"

# every key that can hold an answer key; the serve path must strip all of them
ANSWER_KEYS = ("correct_index", "answer_index")
_STEM_KEYS = ("question", "prompt")


def block_id(block: dict, index: int) -> str:
    """Stable id for a lesson block.

    Only some checkpoints are authored with an `id`; the rest get a deterministic position id
    so the reader can track completion for them too. Serve, validate and grade must all derive
    it the same way, or the client holds ids the server will not accept.
    """
    return str(block.get("id") or f"b{index}")


def checkpoint_stem(block: dict) -> str:
    for key in _STEM_KEYS:
        text = str(block.get(key) or "").strip()
        if text:
            return text
    return ""


def checkpoint_answer_index(block: dict) -> int | None:
    """The keyed choice, under whichever name this block uses.

    Returns `None` when the block has no usable key, which callers must treat as "cannot be
    graded" rather than as "index 0" — marking an unkeyed checkpoint wrong on every answer is
    exactly the behaviour this replaces.
    """
    for key in ANSWER_KEYS:
        value = block.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def is_gradeable(block: dict) -> bool:
    choices = [c for c in (block.get("choices") or []) if str(c).strip()]
    index = checkpoint_answer_index(block)
    return bool(checkpoint_stem(block)) and len(choices) >= 2 and index is not None \
        and 0 <= index < len(choices)


def checkpoint_ids(content: list) -> list[str]:
    """Ids of every checkpoint in a lesson, in order — all of them.

    An earlier version counted only *gradeable* checkpoints, reasoning that a malformed one
    would otherwise hold a lesson permanently incomplete. That is true, and the conclusion was
    still wrong: it let a lesson with one sound and one malformed checkpoint be completed, and
    mastery awarded, by answering half the required work. It measured completion against
    whatever happened to be answerable rather than against what the lesson asks.

    A lesson carrying an ungradeable checkpoint is a defective lesson. That is handled where
    defects belong — `ungradeable_checkpoints` keeps it away from students entirely — not by
    quietly shrinking what completion means.
    """
    return [block_id(block, index) for index, block in enumerate(content or [])
            if block.get("type") == CHECKPOINT]


def ungradeable_checkpoints(content: list) -> list[str]:
    """Ids of checkpoints a student could never answer correctly.

    No stem, fewer than two choices, or no answer key under any name. A lesson holding one
    cannot be finished, so it must not be served as if it could be.
    """
    return [block_id(block, index) for index, block in enumerate(content or [])
            if block.get("type") == CHECKPOINT and not is_gradeable(block)]


# What the reader actually renders, per block type. Everything else is authoring, review or
# provenance metadata and has no business in a browser.
_RENDERED_FIELDS: dict[str, set[str]] = {
    "opening": {"heading", "kicker", "body"},
    "property_cards": {"heading", "kicker", "body", "cards", "title", "items"},
    "worked_example": {"heading", "kicker", "prompt", "steps"},
    CHECKPOINT: {"heading", "kicker", "question", "choices"},
    "steps": {"heading", "kicker", "body", "steps", "items", "title", "cards"},
    "image_gallery": {"heading", "kicker", "body", "images"},
    "video": {"heading", "kicker", "body", "video_id"},
    "summary": {"heading", "kicker", "body", "points", "items", "title", "cards"},
}
# the fallback renderer draws these for a type nobody has written a renderer for yet
_FALLBACK_FIELDS = {"heading", "body"}


def student_safe(block: dict, index: int) -> dict:
    """A block as the browser may see it.

    This is an **allowlist**, and it is one because the denylist it replaced did not hold.
    Removing the four fields that obviously carry an answer missed every field added later:
    `solve_lesson_checkpoints` records a blind solver's verdict on each checkpoint, so
    `solver_check.chosen_index` — with `agreed: true` beside it — restated the key in plain
    JSON on **71 of the 73** published checkpoints, and `repair_dangling_checkpoints` keeps the
    pre-repair block under `superseded`, answer key, explanation and all, on 6 more.

    Neither was a mistake about those two fields; a denylist is wrong for this by construction.
    Every field a student may see has to be named, and anything an author, a script or a
    reviewer adds later is excluded until someone decides otherwise.
    """
    allowed = _RENDERED_FIELDS.get(str(block.get("type")), _FALLBACK_FIELDS)
    safe = {key: value for key, value in block.items() if key in allowed}
    safe["type"] = block.get("type")
    safe["id"] = block_id(block, index)
    if block.get("type") == CHECKPOINT:
        # the reader reads `question`; give it one whichever name the author used
        safe["question"] = checkpoint_stem(block)
    if block.get("type") in {"property_cards", "steps", "summary"}:
        safe["cards"] = normalised_cards(block)
    if not str(safe.get("heading") or "").strip():
        # some generators write `title` instead of `heading`, and the reader shows a generic
        # placeholder when it finds neither — content that exists, rendered as a stub
        safe["heading"] = str(block.get("title") or "").strip()
    return safe


# Every spelling a generator has used for the same three fields. The reader reads one shape;
# normalising here is what stopped 41 checkpoints shipping their stem under the wrong key, and
# this is the same defect in the card blocks: 79 lessons carry cards keyed
# `property`/`meaning`/`competition_implication`, so the reader found no `name`, fell back to a
# placeholder, and showed students the word "Concept" five times over real content.
_CARD_NAME = ("name", "title", "label", "property", "term", "heading")
_CARD_CUE = ("cue", "summary", "subtitle", "meaning", "definition")
_CARD_DETAIL = ("detail", "body", "description", "competition_implication", "note", "example")


def _first(card: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = card.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalised_cards(block: dict) -> list[dict]:
    """Cards in the one shape the reader knows, whichever shape they were written in."""
    raw = block.get("cards")
    if not isinstance(raw, list):
        raw = block.get("items")
    out = []
    for card in raw or []:
        if isinstance(card, str):
            out.append({"name": card.strip(), "cue": "", "detail": ""})
            continue
        if not isinstance(card, dict):
            continue
        name = _first(card, _CARD_NAME)
        cue = _first(card, _CARD_CUE)
        detail = _first(card, _CARD_DETAIL)
        if not (name or cue or detail):
            continue                      # nothing to show is better than a stub that lies
        out.append({"name": name or cue[:60], "cue": cue if name else "", "detail": detail})
    return out
