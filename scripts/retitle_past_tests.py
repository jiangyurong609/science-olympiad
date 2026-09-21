"""Title each imported past paper by the tournament it came from, not by its filename.

Exam titles were the PDF's filename: "A_u0026P EXAM PACKET" (an ampersand double-encoded by
the Drive walk), "Disease_Detectives_B_Test", and "Test", "Exam" or "Division B Exam" on
several papers each — so a student could not tell two papers in the same subject apart, or
say where either came from. The folder each paper was filed under names its source.

    DATABASE_URL=... python -m scripts.retitle_past_tests            # dry run
    DATABASE_URL=... python -m scripts.retitle_past_tests --apply
"""
from __future__ import annotations

import argparse
import re
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import AuditLog, Event, Exam, Source

IMPORTED = ("imported_practice", "unreviewed_practice")

# The first folder of each archive, and who ran it. Years come from the folder name or file.
ARCHIVES = [
    (r"^public-atx-inv-(\d{4})", "UT Austin Invitational"),
    (r"^public-atx-reg-(\d{4})", "UT Austin Regional"),
    (r"^public-atx-f\d+", "UT Austin"),
    (r"^public-rsoi-(\d{4})", "Rickards Invitational"),
    (r"^public-mit-", "MIT Invitational"),
    (r"^public-princeton-", "Princeton Invitational"),
    (r"^public-cornell", "Cornell Invitational"),
    (r"^public-uchicago", "UChicago Invitational"),
    (r"^public-ncso", "North Carolina Science Olympiad"),
    (r"^BullSO (\d{4})", "BullSO"),
    (r"^Division [BC] Tests and Answer Keys", "BullSO"),
    (r"^(\d{4}) GullSO", "GullSO"),
    (r"^\[Div [BC]\] (\d{4}) USC", "USC Invitational"),
    (r"^Div [BC]/", "Purdue Invitational"),
    (r"^(\d{4}) UW River Falls", "UW River Falls Border Battle"),
    (r"^Tests & Keys - Heights Invite (\d{4})", "Heights Invitational"),
    (r"^(\d{4}) GullSO", "GullSO"),
]
# Test exchange file names: <event>_<year>_<div>_<tournament>_<test|key>.pdf
EXCHANGE = re.compile(r"^[a-z0-9-]+_(\d{4})_(bc|b|c)_(.+?)_(?:test|exam)", re.I)
TOKEN_NAMES = {"uflorida": "University of Florida", "umich": "University of Michigan",
               "gopher": "Gopher", "kraemer": "Kraemer", "aviation": "Aviation",
               "ut": "UT Austin", "bvf": "BVF"}


def _year_from(text: str) -> str | None:
    m = re.search(r"(?<!\d)(20[12]\d)(?!\d)", text)
    if m:
        return m.group(1)
    m = re.search(r"(?<![\d])(?:SO|so|Sp|Invite)?\s?(2[0-9])(?![\d])", text)
    return f"20{m.group(1)}" if m and 17 <= int(m.group(1)) <= 29 else None


def tournament_label(relpath: str, text: str = "") -> str | None:
    head, _, rest = relpath.partition("/")
    name = relpath.rsplit("/", 1)[-1]
    if head == "public-scioly-exchange":
        m = EXCHANGE.match(name)
        if not m:
            return None
        year, _, token = m.groups()
        token = token.lower()
        if token.startswith(("ssss-", "captainstryouts-")):
            kind = "Test Exchange" if token.startswith("ssss-") else "Captains Tryout"
            who = token.split("-", 1)[1]
            return f"{kind} {year} ({who})"
        return f"{TOKEN_NAMES.get(token, token.replace('-', ' ').title())} {year}"
    for pattern, label in ARCHIVES:
        m = re.match(pattern, relpath)
        if not m:
            continue
        year = (m.group(1) if m.groups() else None) or _year_from(name) or _year_from(relpath)
        # Several UT Austin archive folders carry no year in their name. The paper's own
        # cover page almost always does ("2024 UT Invitational"), so read it from there
        # rather than infer it from the order the folders were listed in.
        if not year and text:
            m2 = re.search(r"(?<!\d)(20[12]\d)(?!\d)", text[:1500])
            year = m2.group(1) if m2 else None
        return f"{label} {year}" if year else label
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        planned: list[tuple[Exam, str]] = []
        unresolved = 0
        for exam in db.scalars(select(Exam).where(Exam.release_class.in_(IMPORTED))).all():
            source_id = (exam.blueprint or {}).get("exam_source_id")
            source = db.get(Source, source_id) if source_id else None
            relpath = (source.metadata_json or {}).get("relpath", "") if source else ""
            text = (source.extracted_text or "") if source else ""
            label = tournament_label(relpath, text) if relpath else None
            if not label:
                unresolved += 1
                continue
            event = db.get(Event, exam.event_id)
            division = "C" if "/Division C/" in relpath or re.search(r"_c_|Div C|\bC\b", relpath) else "B"
            planned.append((exam, f"{event.name} — Past Test: {label}, Division {division}"))
        # Two papers from the same tournament in one subject still need telling apart.
        seen: Counter[tuple[int, str]] = Counter()
        totals = Counter((e.event_id, t) for e, t in planned)
        changed = 0
        for exam, title in planned:
            key = (exam.event_id, title)
            seen[key] += 1
            final = f"{title} (paper {seen[key]})" if totals[key] > 1 else title
            if final != exam.title:
                changed += 1
                if changed <= 10:
                    print(f"  {exam.title[:58]!r:62s} -> {final!r}")
                if args.apply:
                    db.add(AuditLog(actor_user_id=None, action="exam.retitled",
                                    entity_type="exam", entity_id=str(exam.id),
                                    details={"from": exam.title, "to": final}))
                    exam.title = final
        if args.apply:
            db.commit()
        print(f"\n{'retitled' if args.apply else 'would retitle'} {changed}; "
              f"left {unresolved} whose source could not be placed (titles unchanged)")


if __name__ == "__main__":
    main()
