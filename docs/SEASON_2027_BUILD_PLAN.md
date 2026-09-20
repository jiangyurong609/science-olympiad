# Season 2027 — build plan for the missing subjects

Written 2026-09-19. Every claim about source availability below was checked by fetching the
page and measuring the extracted text, not by assuming a `.gov` domain is usable. Several
obvious-looking sources turned out to be JavaScript shells that yield nothing to a crawler, and
that finding is what separates the tiers.

## Where Division B stands

26 events on the 2027 roster. 14 have a real course, 4 are thin, 8 have nothing.

| State | Events |
|---|---|
| Ready (6+ lessons) | Boomilever, Circuit Lab, Codebusters, Crime Busters, Disease Detectives, **Dynamic Planet (21)**, Experimental Design, Heredity, Hovercraft, Remote Sensing, Rocks and Minerals (16), **Roller Coaster (11)**, Scrambler, Write It Do It |
| Thin (1 lesson) | Elastic Launched Glider, Food Science, Ping Pong Parachute, Protein Builders *(trial)* |
| Empty | Botany, Thermodynamics, Code Craze *(trial)*, Hydraulics *(trial)* |
| Not offered — topic rotated, no correct-topic course | **Anatomy & Physiology, Meteorology, Solar System, Water Quality** |

The last row is the priority: these are real 2027 events with nothing behind them, because their
only courses teach the topic that rotated out.

## What the corpus already holds

**No usable past test exists for any of the four.** All 19 papers we hold for those subjects are
the wrong rotation year — 10 Anatomy papers on other body systems, 4 Water Quality on freshwater
macroinvertebrates, 4 Meteorology on everyday weather and climate, 1 Solar System survey. This is
the same position Dynamic Planet was in, and the same conclusion applies: **past tests give
format, not content.** The formats are already captured in `scripts/build_season_exam.py`.

## scioly.org

Not reachable by automation. The site runs Anubis and returns a hard `Access Denied` to both
`WebFetch` and a real browser session; this is an explicit refusal and was not worked around.
Two things are known from public search results and are worth a human visit:

- The Test Exchange serves files directly, e.g.
  `scioly.org/tests/files/waterquality_2020_c_user-svph300_key2.pdf`, so a logged-in human can
  download papers and drop them into `docs/science_olympiad_tests/_extracted/`, after which the
  existing import path handles them with no special casing.
- `scioly.org/wiki/Water_Quality/Marine_and_Estuary_Macroorganism_List` exists and is exactly the
  organism list the 2027 Water Quality course needs.

**Ask:** download (a) any 2027-topic papers for the four subjects, and (b) that organism list.
Everything else below proceeds without them.

## Source feasibility, measured

Extracted text length after stripping scripts and navigation. "Shell" means the page returns
HTML but the content is rendered client-side, so a crawler stores nothing useful.

| Subject | Source | Text | Verdict |
|---|---|---|---|
| Solar System | NASA Enceladus | 12,085 | usable |
| Solar System | NASA Europa | 8,722 | usable |
| Solar System | NASA astrobiology, JUICE, Europa Clipper, TRAPPIST-1 catalog | 200 OK | usable |
| A&P | NIAID immune system overview | 12,225 | usable |
| A&P | NIDDK digestive system | 10,771 | usable |
| A&P | NHLBI lungs | 1,580 | **shell** |
| Water Quality | EPA coral reefs | 6,229 | usable |
| Water Quality | EPA estuaries | 5,497 | usable |
| Water Quality | NPS coral reefs | 5,093 | usable |
| Water Quality | NOAA estuaries tutorial | 4,001 | usable |
| Water Quality | NOAA CoRIS | 2,569 | usable |
| Water Quality | `oceanservice.noaa.gov/facts/*` | 330 | **shell** |
| Meteorology | NWS glossary | 77,613 | usable |
| Meteorology | NOAA JetStream (tstorms, radar, skew-T, METAR) | 3,828 | **shell** |
| Meteorology | SPC tornado FAQ | 41 | **shell** |

Two traps found while measuring, both of which would have inflated a source count:

1. `oceanservice.noaa.gov/facts/coral-reef.html`, `coralbleaching.html` and
   `why-care-about-corals.html` return **byte-identical** responses — one page counted three
   times. `ensure_sources` should dedupe on content hash, not URL.
2. `weather.gov/jetstream/*` returns **403 to our user agent** and 200 to a browser one, then
   serves the same shell for every path. A 403 that becomes a 200 is not the same as a page that
   becomes useful.

## The plan, in dependency order

### Tier 1 — buildable now, no new infrastructure

**Solar System (habitability)** and **Anatomy & Physiology (respiratory, digestive, immune)**.

Both follow the route Dynamic Planet proved, which took one grounding pass and one authoring run:

1. Add a domain to `scripts/open_sources.py` (`astrobiology`, `anatomy_2027`) with verified URLs,
   and register the rotation in `EVENT_DOMAIN_BY_SEASON`.
2. Write `data/courses/<event>-2027.json` from the scope manifest's topic list — the manifest
   already names every required object and system, including the 16 spacecraft Solar System may
   be examined on and the specific disorders A&P lists per body system.
3. `ground_event --apply` → extract passages per snapshot → `author_course_from_blueprint`.
4. `exam_agent --rounds 3` for the papers.

Two gaps to close first: A&P needs a respiratory source to replace the NHLBI shell (MedlinePlus
and NCBI Bookshelf are the candidates), and Solar System needs per-object pages for Ganymede,
Makemake, Bennu and 67P alongside the ones already verified.

### Tier 2 — buildable after source assembly

**Water Quality (marine, estuary, coral reef).** Five solid federal sources exist, but the event
is 30% organism identification against a named list of 25 taxa, so it needs a per-organism source
set the way Rocks needs one per specimen. Build that list from Wikipedia taxon pages, verified
individually, exactly as the 72 Rocks specimen pages were. The scioly.org organism list above
would confirm the roster.

### Tier 3 — blocked on infrastructure

**Meteorology (severe weather and storms).** This is the hardest of the four and the most
valuable, because at least half the 2027 exam is interpreting radar, hodographs, Stüve diagrams
and METAR — and every good federal teaching resource for exactly that (JetStream, SPC) is a
JavaScript shell. The NWS glossary alone cannot carry a course.

The unblock is a **browser-rendered snapshot path**: the shared browser service already runs a
real Chromium, so a `--render` mode for `ground_event` that loads a URL, waits for the page, and
snapshots the rendered text would make JetStream, the SPC FAQs and the NOAA facts pages
available. That single capability unlocks Meteorology and improves Water Quality.

It also needs figures. Radar imagery, hodographs and Stüve diagrams are the event, and a
text-only course cannot teach them.

### Tier 4 — new events with no prior art

**Botany, Thermodynamics** (both empty, both regular events) and the trials **Code Craze**,
**Hydraulics**, plus topping up the four thin build events. Botany and Thermodynamics are
ordinary knowledge/hybrid events with good open sources and should follow the Tier 1 route.
Code Craze is delegated to an annual CodeHS module and cannot be authored here — its scope lives
outside anything we may read. Hydraulics is a build event, so it wants the Roller Coaster
treatment: physics lessons plus a rules-comprehension quiz a coach writes from the manual.

## Cross-cutting work

- **Specimen and figure imagery.** Rocks needs images for 130 of 150 official specimens; Water
  Quality needs 25 organisms; Meteorology needs radar and sounding displays; the new Dynamic
  Planet and Roller Coaster courses have no images at all. This is a sourcing job with a
  licensing requirement, and it gates the identification-heavy events.
- **Content-hash dedupe in `ensure_sources`**, per the NOAA finding above.
- **The four rotated courses stay hidden** until their replacements exist. Their lessons and past
  tests remain on the archive surface.
- **Review capacity is the real bottleneck.** 59 Dynamic Planet questions already wait in the
  Content Review queue. Authoring four more subjects multiplies that queue, and no amount of
  machine verification substitutes for the human read that makes an exam `reviewed`.

## Suggested sequence

1. Human: download the scioly.org organism list and any 2027-topic papers.
2. Solar System and A&P through the Tier 1 route — two courses, proven path.
3. Water Quality organism source set, then the Tier 1 route.
4. Browser-rendered snapshot mode, then Meteorology.
5. Botany and Thermodynamics.
6. Imagery, continuously — it gates Rocks and Water Quality quality more than lesson count does.
