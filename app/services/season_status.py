"""Which season statuses hide an event, in one place.

An exam published under an event no catalog view lists is findable by nobody. That happened
once already: the 2026 Meteorology paper imported cleanly, verified cleanly, published under a
`superseded` event, and no student could reach it. The importer grew a guard against that one
status, while the catalog kept its own separate set — so adding a third hidden status would
have re-opened the same hole silently, because the two lists are read by different modules and
nothing made them agree.

`HIDDEN_SEASON_STATUSES` is the shared answer to "can a student ever reach this event?", and
both the catalog filter and the past-test importer read it.
"""

# Retired duplicate twins, and events still being authored for a season. Neither may be served
# to a student, so neither may have content published under it.
HIDDEN_SEASON_STATUSES = frozenset({
    "archived_superseded",
    "superseded",
    "in_development",
})

# Reachable, but not presented as current-season competition coverage. These events keep their
# lessons and exams and carry a "Prior season" badge; they are listed on the archive surface.
ARCHIVED_SEASON_STATUSES = frozenset({
    "prior_season_practice",
    "archived_superseded",
})


def is_hidden(event) -> bool:
    """Whether this event is unreachable for every student, for any reason."""
    return (not getattr(event, "active", True)
            or getattr(event, "season_status", "") in HIDDEN_SEASON_STATUSES)
