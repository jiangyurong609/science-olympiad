"""Audit what the catalog teaches against what this season's rules actually test.

A season rotates topics without renaming events. "Meteorology" is on the roster every year,
but 2027 tests severe weather and storms while the course in the catalog was written for
everyday weather and climate — same name, different body of material, and nothing in the data
model notices. This reads a season scope manifest (docs/season_<year>/division_<div>_scope.json,
the factual syllabus derived from the official rules manual) and reports, per event, whether the
content a student is actually served covers it.

The strongest signal is `named_entities`: when the rules require Europa, Enceladus and
TRAPPIST-1 by name, a course that never says those words is not teaching the event, however
good it is. Topic keywords are a weaker second signal, so both are reported separately rather
than blended into one number.

This is a read-only report. Usage:
  python scripts/audit_season_alignment.py [--season 2027] [--division B] [--json out.json]
    [--event "Meteorology"] [--min-coverage 0.5]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from sqlalchemy import text

from app.core.database import SessionLocal

REPO = Path(__file__).resolve().parent.parent


def _manifest(season: int, division: str) -> dict:
    path = REPO / f"docs/season_{season}/division_{division.lower()}_scope.json"
    if not path.exists():
        raise SystemExit(
            f"no scope manifest at {path.relative_to(REPO)} — a season audit needs the "
            f"syllabus for that division before it can claim anything about coverage"
        )
    return json.loads(path.read_text())


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


# Names the catalog and the rules manual spell differently for the same event.
ALIAS = {
    "elastic launch glider": "elastic launched glider",
    "protein modeling": "protein builders",
}


def _key(name: str) -> str:
    n = _norm(name)
    return ALIAS.get(n, n)


def _serving_events(db, season: int, division: str) -> dict[str, list[dict]]:
    """Events a student in this division can actually reach, keyed by normalized name.

    Deliberately not filtered to `season == season`: the catalog serves the prior season's
    courses as the foundational library, and those are exactly the rows whose topic may have
    rotated out from under them. An audit that only looked at current-season rows would report
    every rotated event as "no content" and miss the real defect, which is stale content being
    served under a current name.
    """
    rows = db.execute(text("""
        select e.id, e.name, e.division, e.season, e.season_status, e.topic_focus,
          coalesce((select count(*) from lessons l
                    where l.event_id = e.id and l.status = 'published'), 0) lessons,
          coalesce((select count(*) from exams x
                    where x.event_id = e.id and x.published), 0) exams,
          coalesce((select count(*) from practice_sets p where p.event_id = e.id), 0) labs
        from events e
        where e.active
          and e.season_status not in ('superseded', 'archived_superseded')
          and (e.division = :div or e.division = 'B/C')
        order by e.season desc
    """), {"div": division}).fetchall()
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(_key(r.name), []).append(dict(r._mapping))
    return out


def _content_blob(db, event_id: int) -> str:
    """Every word a student reads in this event's published lessons, lowercased."""
    rows = db.execute(text("""
        select v.content from lessons l
        join lesson_versions v on v.lesson_id = l.id and v.version = l.current_version
        where l.event_id = :e and l.status = 'published'
    """), {"e": event_id}).fetchall()
    return " ".join(json.dumps(r.content) for r in rows).lower()


STOP = {
    "and", "the", "of", "for", "with", "from", "their", "its", "limited", "into", "also",
    "including", "include", "includes", "such", "state", "nationals", "only", "other",
    "types", "type", "using", "used", "between", "versus", "based", "these", "those", "when",
    "which", "what", "role", "roles", "basic", "general", "common", "effects", "effect",
    "properties", "property", "concepts", "concept", "understand", "identify", "identifying",
    "analysis", "analyze", "questions", "data", "given", "form", "forms", "level", "levels",
    "system", "systems", "than", "over", "across", "within", "about", "each", "both", "more",
    "less", "plus", "plot", "plots", "scale", "scales", "size", "value", "values", "term",
    "terms", "point", "points", "part", "parts", "where", "while", "under", "above",
}


def _topic_covered(topic: str, blob: str) -> bool:
    """Whether a course's text plausibly teaches this topic.

    Single distinctive words are too weak on their own. "channel", "sediment" and "discharge"
    all appear in an oceanography course, so matching any one of them scored the 2027 freshwater
    Dynamic Planet scope as fully covered by a course on tides and seawater. A two-word phrase
    from the topic ("drainage basin", "stream order", "rolling resistance") is specific enough
    to mean something, so a topic counts as covered when a phrase lands, or when most of its
    distinctive words do.
    """
    text = re.sub(r"\[[^\]]*\]", " ", topic.lower())
    text = re.sub(r"[^a-z0-9 \-]", " ", text)
    tokens = [w for w in text.split() if len(w) > 3]
    content = [w for w in tokens if len(w) > 4 and w not in STOP]
    for first, second in zip(tokens, tokens[1:]):
        if (first not in STOP or second not in STOP) and f"{first} {second}" in blob:
            return True
    if not content:
        return False
    hits = sum(1 for w in set(content) if w in blob)
    return hits >= max(2, round(len(set(content)) * 0.6))


def audit(season: int, division: str, only: str, min_cov: float) -> dict:
    manifest = _manifest(season, division)
    db = SessionLocal()
    serving = _serving_events(db, season, division)
    report = {"season": season, "division": division, "events": []}
    for spec in manifest["events"]:
        if only and only.lower() not in spec["event"].lower():
            continue
        key = _key(spec["event"])
        candidates = serving.get(key, [])
        entry = {
            "event": spec["event"],
            "topic_focus_2027": spec.get("topic_focus", ""),
            "rotating_subtitle": spec.get("rotating_subtitle"),
            "event_type": spec.get("event_type"),
            "is_trial": spec.get("is_trial", False),
            "catalog": [],
        }
        if not candidates:
            entry["verdict"] = "MISSING"
            entry["detail"] = "no event a student can reach serves this subject"
            report["events"].append(entry)
            continue
        best = None
        for ev in candidates:
            blob = _content_blob(db, ev["id"])
            named = spec.get("named_entities") or []
            named_hits = [n for n in named if n.lower() in blob]
            topics = spec.get("topics") or []
            topic_hits = [t for t in topics if _topic_covered(t, blob)]
            row = {
                "event_id": ev["id"], "name": ev["name"], "season": ev["season"],
                "season_status": ev["season_status"], "topic_focus": ev["topic_focus"] or "",
                "lessons": ev["lessons"], "exams": ev["exams"], "labs": ev["labs"],
                "named_required": len(named), "named_covered": len(named_hits),
                "named_missing": [n for n in named if n.lower() not in blob][:25],
                "topics_required": len(topics), "topics_covered": len(topic_hits),
                "topics_missing": [t for t in topics if t not in topic_hits][:25],
            }
            row["named_coverage"] = (len(named_hits) / len(named)) if named else None
            row["topic_coverage"] = (len(topic_hits) / len(topics)) if topics else None
            entry["catalog"].append(row)
            score = row["named_coverage"] if row["named_coverage"] is not None else row["topic_coverage"]
            if best is None or (score or 0) > (best[0] or 0):
                best = ((score or 0), row)
        score, row = best
        # Which signal decides. When the rules name eight or more specific things, whether the
        # course says them is a far better test of "is this even the right subject" than keyword
        # overlap on prose: Rocks and Minerals scored 20% on keywords and was called a topic
        # mismatch, which is the label for a course teaching something else entirely. Only when
        # the rules name almost nothing does topic coverage have to lead.
        named_leads = (row["named_required"] or 0) >= 8
        lead = row["named_coverage"] if named_leads else row["topic_coverage"]
        lead = 0.0 if lead is None else lead
        # Broad topical coverage vetoes the mismatch label however few names land. Disease
        # Detectives covers 23 of 24 topics and names 1 of 9 required references: it is
        # unmistakably the right subject that has not been taught PulseNet or Bradford Hill,
        # which is a gap to fill, not a course to rewrite.
        if (row["topic_coverage"] or 0) >= 0.7:
            lead = max(lead, min_cov * 0.4)
        counts = (f"{row['topics_covered']}/{row['topics_required']} topics and "
                  f"{row['named_covered']}/{row['named_required']} required names")
        entry["decided_by"] = "named_entities" if named_leads else "topic_keywords"
        if row["lessons"] == 0:
            entry["verdict"] = "NO_CONTENT"
            entry["detail"] = "event exists in the catalog but serves no published lesson"
        elif row["lessons"] < 3:
            # A one-lesson stub cannot cover a season, whatever it happens to match.
            entry["verdict"] = "NO_CONTENT"
            entry["detail"] = (f"only {row['lessons']} published lesson(s) — a stub, not a course "
                               f"({counts})")
        elif lead < min_cov * 0.4:
            entry["verdict"] = "TOPIC_MISMATCH"
            entry["detail"] = (f"{row['lessons']} lessons cover {counts} — this course teaches a "
                               f"different body of material")
        elif lead < 0.8:
            entry["verdict"] = "GAPS"
            entry["detail"] = f"right subject, {row['lessons']} lessons cover {counts}"
        else:
            entry["verdict"] = "ALIGNED"
            entry["detail"] = f"content covers the tested scope ({counts})"
        report["events"].append(entry)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2027)
    ap.add_argument("--division", default="B")
    ap.add_argument("--event", default="")
    ap.add_argument("--min-coverage", type=float, default=0.5)
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    report = audit(args.season, args.division, args.event, args.min_coverage)

    order = {"MISSING": 0, "NO_CONTENT": 1, "TOPIC_MISMATCH": 2, "GAPS": 3, "ALIGNED": 4}
    rows = sorted(report["events"], key=lambda e: (order.get(e["verdict"], 9), e["event"]))
    counts: dict[str, int] = {}
    print(f"\n=== Division {report['division']} · {report['season']} season alignment ===\n")
    for e in rows:
        counts[e["verdict"]] = counts.get(e["verdict"], 0) + 1
        trial = " [trial]" if e["is_trial"] else ""
        print(f"{e['verdict']:15} {e['event']}{trial}")
        print(f"                tests: {e['topic_focus_2027']}")
        print(f"                {e['detail']}")
        for c in e["catalog"]:
            nc = "n/a" if c["named_coverage"] is None else f"{c['named_coverage']:.0%}"
            tc = "n/a" if c["topic_coverage"] is None else f"{c['topic_coverage']:.0%}"
            print(f"                 · [{c['event_id']}] {c['name']} {c['season']}"
                  f" ({c['season_status']}) lessons={c['lessons']} exams={c['exams']}"
                  f" topics={tc} names={nc}")
            if c["named_missing"]:
                print(f"                   missing names: {', '.join(c['named_missing'][:12])}")
            # With no required names the topic list is the only evidence there is, so show it:
            # for a rotated event the uncovered topics are the new season's whole subject.
            if c["topics_missing"] and not c["named_required"]:
                for t in c["topics_missing"][:8]:
                    print(f"                   uncovered: {t[:96]}")
        print()
    print("summary: " + " · ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1))
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
