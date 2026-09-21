# Gap analysis: Starter Pack vs our Rocks & Minerals B 2027 course

**What was compared:** the blueprint `data/courses/rocks-and-minerals-b-2027.json` (10 units, 31 lessons) and the **live published lesson text**. The live text was dumped read-only with `scripts/dump_course.py --event rocks-and-minerals-b-2027` on 2026-09-20: 32 lessons (the 31 blueprint lessons plus 1 video lesson). All 32 are `status=published`, `disposition=unreviewed_practice`.

Coverage is judged on the **live text**, because that is what students read. A blueprint objective that names a topic the live text never teaches still counts as a gap. Term hits were counted per lesson by regex over the dump, then read in context.

**Ratings:**
- **covered**: taught with correct content and at least one checkpoint.
- **thin**: mentioned, but incomplete, or only in a blueprint objective or a single passing line.
- **missing**: absent from all live text.

## 1. Pack topic → our lesson

### Mineral topics (rules 3.h)

| Pack topic (slides) | Rule | Our lesson(s) | Rating | What's missing |
|---|---|---|---|---|
| Definition of a mineral (6) | 3.h.i | `rocks-minerals-and-evidence`, `organic-gems-and-mineraloids` | **thin** | The live definition ("naturally occurring inorganic element or compound with orderly internal structure…") still omits **solid**, which the rules and slide 6 include. The expert review flagged this in `expert-2027`; it has not been fixed live. |
| Color (8) | 3.h.iii | `color-streak-and-luster` | covered | |
| Hardness / Mohs (9) | 3.h.iii | `hardness-and-mohs-scale`, `the-mohs-scale-in-order`, `field-hardness-tools` | covered, but see corrections | `field-hardness-tools` and `use-an-identification-flowchart` still give gypsum as 1.5–2 and use dioptase and chalcopyrite as reference values. They never give glass ≈5.5, which the pack's B-National Q30 uses, and they never give fingernail or copper values despite the lesson title. |
| Luster (10), streak (11) | 3.h.iii | `color-streak-and-luster` | covered | Streak plate: the pack says ~6.5, our course says ~7. |
| Cleavage/fracture (12) | 3.h.iii | `breakage-density-and-special-properties` | covered | |
| Density/SG/heft (13) | 3.h.iii | `breakage-density-and-special-properties` | covered | |
| **Diaphaneity** (14) | 3.h.iii | only incidentally in `quartz-varieties` | **thin** | The term *diaphaneity* and its transparent/translucent/opaque scale are never taught as a property. The pack tests this (B-National Q8). |
| **Tenacity** (15) | 3.h.iii | a few words in `sheet-and-ring-silicates` ("elastic") | **missing** | brittle / malleable / sectile / flexible / elastic (B-National Q9, Q66) |
| Reaction with acid (17) | 3.h.iv | `carbonates-and-borates`, `identify-an-unknown-specimen` | covered | |
| Fluorescence (18) | 3.h.iv | `isolated-silicates-and-garnets` (willemite), `use-an-identification-flowchart` | thin | Fluorite as the type example is absent from the property lessons. |
| Magnetism (19) | 3.h.iv | `breakage-density-and-special-properties`, `native-elements-and-oxides` | covered | |
| **Smell, taste** (20) | 3.h.iv | none | **missing** | Also the rules framing: tasting is never done, but described taste can be asked. |
| **Double refraction, piezoelectricity, radioactivity** (21) | 3.h.iv | none | **missing** | 0 hits for all three terms across 32 lessons |
| **Mineral habit, 21 listed** (22) | 3.h.v | scattered (`sheet-and-ring-silicates`, `isolated-silicates-and-garnets`) | **thin** | 0 hits for botryoidal, doubly terminated, druzy, hopper, micaceous, octahedral, pisolitic, rosette. The pack's exams test habit 7 times (B-Regional Q3; B-State Q3, 6, 7; B-National Q16–19). |
| **Formula and trace elements → color** (23) | 3.h.vi | formulas in family lessons; `quartz-varieties` (iron in amethyst) | **thin** | Chromium in emerald is absent. The chemistry→color principle is never stated as a rule. |
| **Polymorphs** (24) | 3.h.vii | the word appears once (`framework-and-chain-silicates`); calcite/aragonite in `carbonates-and-borates` | **thin** | Diamond/graphite are never called polymorphs, **andalusite has 0 hits**, and orthoclase/microcline are never called polymorphs. Tested 6 times in the pack. |
| Classification by families (57–58) | 3.h.viii | the 6 `mineral-families` lessons | covered | |
| Mineral groups (29) | 3.h.ix | `framework-and-chain-silicates`, `sheet-and-ring-silicates`, `isolated-silicates-and-garnets` | covered for feldspar/mica/garnet/amphibole; **thin** for pyroxene and tourmaline | **Augite has 0 hits.** Tourmaline has only 1 hit, although the lesson title promises "Beryl and Tourmaline". |
| **Methods of formation and environments** (30) | 3.h.x | evaporites in `chemical-and-biochemical-rocks` | **thin** | Hydrothermal: 0 hits in lesson text. Chemical weathering: 0 hits. |
| **Minerals of rock-forming environments** (30, 40) | 3.h.xi | none | **missing** | "Mafic minerals in oceanic crust" (B-State Q12, B-National Q27) |
| Bowen's Reaction Series (31) | 3.h.xii | `composition-and-bowen-series` | **thin** | Amphibole→biotite and K-feldspar→muscovite→quartz are not taught as a sequence. The weathering-stability corollary, tested in B-Regional Q27, B-State Q44 and B-National Q76, is absent. |
| **Uses of minerals** (33) | 3.h.xiii.1 | none | **missing** | 0 hits for ore of, geochronology, drywall/plaster, electronics. The pack tests this 10+ times. |
| Gem varieties (32) | 3.h.xiii.2 | `gem-varieties`, `organic-gems-and-mineraloids` | covered | |

### Rock topics (rules 3.i)

| Pack topic (slides) | Rule | Our lesson(s) | Rating | What's missing |
|---|---|---|---|---|
| Definition of a rock; mono-/polymineralic (35) | 3.i.i | `rocks-minerals-and-evidence` | **thin** | "Monomineralic" and "polymineralic" have 0 hits (B-National Q31). |
| Classification cues (36) | 3.i.iii | `sedimentary-evidence`, `metamorphic-evidence`, `cooling-history-and-texture` | covered | |
| Igneous textures (37) | 3.i.iv.1 | `cooling-history-and-texture`, `igneous-rocks-by-name` | **thin** | **Pyroclastic** and **pegmatitic** textures have 0 hits (B-National Q35–36). |
| Composition classes (38) | 3.i.iv.2 | `composition-and-bowen-series`, `igneous-rocks-by-name` | covered, with a labelling issue | Uses "silicic" in place of the rules' "felsic". Has no silica % ranges or ultramafic range in the Bowen lesson. |
| **Formations: batholith, lava flow, pyroclastic deposits** (39) | 3.i.iv.3 | none | **missing** | 0 hits for batholith, lava flow, pyroclastic |
| Texture ↔ cooling rate (39) | 3.i.iv.4 | `cooling-history-and-texture` | covered | |
| **Igneous rocks at plate boundaries** (40) | 3.i.iv.5 | none | **missing** | 0 hits for mid-ocean ridge and subduction |
| Sedimentary textures (41) | 3.i.v.1 | `sedimentary-evidence` | covered | |
| **Grain size ↔ energy/velocity; sorting; rounding** (42) | 3.i.v.3 | `clastic-rocks-by-grain-size` (naming only) | **thin** | "Energy" and "velocity" have 0 hits. Sorting and rounding are used to *name* rocks, never to infer environment energy. |
| **Environments of deposition, 10** (43) | 3.i.v.5 | one property card in `reason-through-rock-cycle-paths` | **thin** | Swamp, shelf and deep marine have 0 hits. There is no energy ranking. |
| **Primary sedimentary structures** (44) | 3.i.v.6 | none | **missing** | 0 hits for cross-bedding, ripple marks, mud cracks, graded bedding, plane bedding, tracks and trails |
| Metamorphic textures (45) | 3.i.vi.1 | `metamorphic-evidence`, `metamorphic-rocks-by-name` | **thin** | "Slaty cleavage" has 0 hits; "gneissic banding" has 0 hits. |
| Metamorphic minerals (30, 46) | 3.i.vi.3 | `metamorphic-grade-and-index-minerals`, `isolated-silicates-and-garnets` | covered | Andalusite is absent. |
| Protoliths (47) | 3.i.vi.4 | `metamorphic-evidence` | covered | All five pairs are in the opening. `metamorphic-rocks-by-name` covers only mudstone→slate/phyllite/schist and basalt→amphibolite. |
| Regional vs contact (48) | 3.i.vi.5 | `metamorphic-evidence`, `metamorphic-grade-and-index-minerals` | covered | |
| Grade and index minerals (46) | 3.i.vi.6 | `metamorphic-grade-and-index-minerals` | covered, **conflicts with the rules framing** | The lesson says muscovite "is not a single step" in the sequence. The rules list muscovite as one of the 7 index minerals, and the pack orders chlorite → muscovite → biotite. |
| Rock cycle (51) | 3.i.vii | `processes-that-change-rock`, `reason-through-rock-cycle-paths` | covered, thin on **uplift** | "Uplift" has 0 hits; the rules name "uplift, erosion & deposition". |
| **Economic uses of rocks** (52) | 3.i.viii | none | **missing** | building stone, ores, ornamental, agriculture, fossil fuels |
| Official List by category (56–58) | 3.c | the `mineral-families` and `rocks-by-name` units | covered for 122 of 129 leaf names | 7 leaf names absent; the plural heading "Potassium feldspars" is the 8th in the repo's count (see §2) |
| Cheat sheet / tips (60, 62) | – | `use-an-identification-flowchart`, `station-strategy-and-documentation` | covered | Do **not** import the two errors on slide 60. |
| Div C topics (25–28, 49–50, 53) | – | none | n/a (correctly absent) | |

**Summary:** of the 43 Div B pack topics above, **21 are covered, 13 thin, 9 missing.**

The missing topics:
- tenacity
- smell/taste
- double refraction/piezoelectricity/radioactivity
- minerals of rock-forming environments
- uses of minerals
- igneous formations (batholith, lava flow, pyroclastic deposits)
- igneous rocks at plate boundaries
- primary sedimentary structures
- economic uses of rocks

Diaphaneity, mineral habit, polymorphs, the Bowen sequence and depositional environments are the most exam-relevant **thin** topics.

## 2. The 8 specimens our course still doesn't name, and what the pack offers

Live-text hits are from the dump. The names are the ones listed in commit `2cf6e11`.

| Specimen (List family) | Live-course hits | Pack coverage | Can the pack supply identifying properties? |
|---|---|---|---|
| **Turquoise*** (phosphate) | 0 | Slide 57 (List). C-State Q25–26: phosphate class; "distinctive blue-green color and a massive habit" (Image 5 photo); primary use gemstone/ornamental. | Partly: class, color, habit, use. The Q25 photo is a usable visual. No hardness or streak. |
| **Celestite/Celestine** (sulfate) | 0 | Slide 57 (List); slide 25 (barite↔celestine "solid solution", Div C, overstated). | **No.** Family only. |
| **Potassium feldspars** (List heading) | "potassium feldspars" 0; "potassium feldspar" 19 in `framework-and-chain-silicates` | Slides 29, 58, 59 (pink/tan variety = Orthoclase/Microcline or "Potassium feldspar"); C-State Q12. | Yes, the naming rule. **Effectively covered already.** This is a counting artefact of the plural heading. |
| **Augite** (pyroxene group) | 0 | Slide 29 (pyroxene: single-chain, two cleavages near 90°); slide 31 (Bowen: "Pyroxene (Augite)"); slide 58; B-National Q23 ("common dark, rock-forming mineral … pyroxene group"); C-State Q37. | Partly: dark, rock-forming, 2 cleavages ≈90°, early on Bowen's series. |
| **Aventurine** (quartz variety) | 0 | Slide 58 (List) only. Slide 29's quartz row omits it. | **No.** Name only. |
| **Tuff Breccia*** (igneous; footnote 1, so data will be supplied) | 0 (tuff 1 hit) | Slide 56 (List); slide 37 pyroclastic texture; B-National Q35 (tuff = pyroclastic). | Generic only: pyroclastic texture. Nothing specific to tuff *breccia*. |
| **Fossil Limestone** (sedimentary) | 0 | Slide 41 (biochemical example); slide 56; B-Regional Q26 key, B-State Q43 key, C-Regional Q23. | Classification only (biochemical). No photo. |
| **Garnet Schist** (metamorphic) | 0 | Slide 56 (List); slide 45 (schistose = medium grade); slide 46 (garnet = medium-grade index mineral). | Only by combining: schistose texture plus garnet porphyroblasts. The pack never says this directly. |

**Conclusion:** the pack closes the gap only for **augite** and **turquoise**, and potassium feldspar is already closed. For **celestite, aventurine, tuff breccia and garnet schist**, the pack names the specimen but gives no properties. They still need an independent source, and they must not be filled from the pack.

## 3. What our course has that the pack lacks (no action needed)

- **Worked identification methods:**
  - the station evidence-profile routine
  - flowchart navigation
  - two-property verification
  - legal recovery moves at stations
  - (`observation-before-identification`, `use-an-identification-flowchart`, `identify-an-unknown-specimen`, `station-strategy-and-documentation`)
- **Field hardness tools and bracketing logic** (`field-hardness-tools`, `hardness-and-mohs-scale`).
- **Quantitative property data:**
  - specific-gravity ranges
  - cleavage angles (plagioclase 93–94°, hornblende 56/124°, pyroxene 87/93°)
  - hardness ranges for dozens of List minerals
- **Per-specimen identification cards for most of the List:**
  - carbonate, sulfide and apatite-group formulas
  - gypsum varieties by habit
  - mica, clay, zeolite and prehnite properties
  - labradorescence
  - microcline gridiron twinning
  - dioptase and rhodonite
  - kyanite's directional hardness
  - staurolite cruciform twins
- **Sedimentary naming thresholds:** arkose ≥25% feldspar, quartz arenite >90% quartz, greywacke matrix >15%, conglomerate vs breccia. Also chert/flint/diatomite, the banded iron formation definition, and bauxite composition.
- **Coal rank and coalification** (`coal-ranks`).
- **Quartz variety color causes** (smoky, rose, citrine heat-treatment) and a critique of the mineral definition for pearl, amber and opal.
- **Contact aureole and burial metamorphism.**
- **Off-list names** the course uses as vocabulary: siltstone, peat, hornfels, anorthite. These are harmless, but none of them is an identification answer on the 2027 List.

## 4. Observations outside the pack's evidence

These were noticed while reading the live text but are not supported or contradicted by the pack. They are **not** in `corrections.json`.

- `sheet-and-ring-silicates` and `isolated-silicates-and-garnets` still quote Miller-index notation ("hardness 2–2.5 parallel to {001}", "cleavage on [001]"). The expert review asked for that notation to be removed elsewhere.
- `carbonates-and-borates`: "Aragonite commonly occurs in red or white colors" and "Calcite and aragonite are both softer than 4 … in limestone" read oddly. They need a source check.
- `igneous-rocks-by-name`: "rhyolite is … generally glassy or fine-grained". Rhyolite is aphanitic; glassy rhyolitic rock is obsidian.
