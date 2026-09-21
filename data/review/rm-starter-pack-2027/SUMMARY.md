# Rocks & Minerals 2027 Starter Pack: review summary

Source: `Rocks Minerals 2027 Starter Pack` (171-slide image-only deck, supplied by the program).
It is built from the 2027 **draft** rules and covers Divisions B and C, so this review treats it
as a secondary source. Every fact taken from it was checked against the 2027 rules and official
list, and Division C-only material is excluded.

## Counts
- 171 slides: 62 notes slides (58 with content) and 109 exam pages. Slides 153–171 are a
  pixel-identical copy of 105–123, so 90 exam pages are unique.
- Official List in the pack: 129 names (84 minerals, 45 rocks). None missing, none extra, none
  misspelled, and all 35 State/National asterisks match the manual.
- 5 sample papers (B Regional, State and National; C Regional and State). 240 questions: 172
  multiple choice, 23 multi-select, 45 short answer. 190 verified; 47 are Division C-only; 3
  Division B items have key or scope problems.
- 36 figure crops serving 41 figure references (`figures/`).

## Pack errors
1. Quick-ID cheat sheet (slide 60) calls alluvial fans low-energy and gneiss finely banded; the
   pack's own slide 43 and keys say the opposite.
2. Amber and pearl are described as "on the List"; they appear only among allowed gem varieties.
3. The "Full 2027" habit list (slide 22) shows 19 of 21 habits; twinning and tabular are missing.
4. Keys: B-National Q14 endorses tasting halite (rules forbid taste tests); B-National Q28 keys
   olivine as earlier than Ca-rich plagioclase (they begin together); B-State Q21 keys laccolith
   (outside Division B's batholith / lava flow / pyroclastic limit).
5. The Division C facies diagram numbers its fields 1–11 with no legend, so its questions cannot
   be answered from the figure.
6. Smaller problems: slide 29 upside down; slide 31's Bowen diagram mis-draws the last three
   minerals; slide 25 overstates two solid-solution series; slide 62 carries leftover Disease
   Detectives text; slide 3 omits the rule that nothing but the List may be removed from the
   binder during stations.

## Gaps in the live course (before this change)
1. Uses of minerals and rocks: no content, though the pack tests it 12+ times.
2. Sedimentary structures and depositional environments/energy: missing or thin.
3. Igneous formations and plate-boundary rocks: missing.
4. Other properties (smell, taste, double refraction, piezoelectricity, radioactivity),
   tenacity, diaphaneity, and 8 of the 21 habits: missing or thin.
5. Polymorphs and trace-element color: thin; andalusite never named.
6. Bowen's series incomplete; weathering link absent; "silicic" used where the rules say felsic.
7. Rule conflicts: mineral definition lacks "solid"; muscovite said not to be an index mineral;
   gypsum given as 1.5–2 and non-index minerals used as hardness references.

## What was applied
- `blueprint_changes.json`: 9 new lessons and 12 revised lessons merged into
  `data/courses/rocks-and-minerals-b-2027.json` (now 40 lessons).
- `corrections.json` plus the revised objectives: `corrections_apply.json`, run through
  `harden_course.sh --corrections`.
- Open sources added for the new topics in `scripts/open_sources.py` (geology domain).
- `exams.json`: four practice papers imported by `scripts/import_starter_pack_exams.py`, which
  also documents the dropped and reworded items.

## Decisions taken
- Opal: taught as a mineraloid, and students are told the List files it under quartz varieties.
- Streak plate: "about 6.5–7".
- Division C background (thin sections, facies diagrams, silicate-structure depth): excluded.
- Specimen photos labelled actinolite, zircon and turquoise are identified only by their
  question text; they are used only in those questions, not as identification items elsewhere.

## Still open
- Celestite, aventurine, tuff breccia and garnet schist: the pack names them without
  identifying properties; lessons draw on open sources for them.
- Specimen count: the repo says 150, 151 or 152 in different places; pick one definition.
- Sulfur's smell: slide 20's "rotten eggs" describes hydrogen sulfide; a mineralogist should
  confirm the wording used.
- The pack's figures are photographs of unknown licence; they ship as supplied by the program.
