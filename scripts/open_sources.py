import re
"""Curated public-domain / open-license science sources per scientific domain.

Every URL here is a U.S. government (public-domain) or clearly open educational
resource. These are the materials the platform is permitted to DOWNLOAD, retain,
and use for LLM fact-grounding — unlike the copyrighted official Science Olympiad
rules and past exams, which stay link-only.

Each event maps to one domain; the domain's source provides the factual grounding
for that event's generated course and exam.
"""

# Rights are declared per host rather than inferred at the call site. `ensure_sources` used to
# decide with `"wikipedia.org" in url` and default everything else to public domain, which is
# only correct while every non-Wikipedia entry is a federal work. Adding a CC-BY open textbook
# under that rule would have silently labelled it public domain — a rights error, and the kind
# that stays invisible until someone relies on it.
HOST_RIGHTS = {
    "en.wikipedia.org": {
        "rights_status": "fact_grounding_allowed",
        "license_name": "CC-BY-SA 4.0 (facts used with attribution)",
        "publisher": "Wikipedia contributors",
    },
    "www.usgs.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                     "publisher": "U.S. Geological Survey"},
    "www.nps.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                    "publisher": "U.S. National Park Service"},
    # Federal works, declared per host rather than inferred from ".gov" or from the domain's
    # default. The domain default is a single string describing a MIXED source set ("NASA and
    # Wikipedia"), so every NASA row would otherwise have carried a licence naming Wikipedia
    # as well — a rights error, and the kind nobody notices until someone relies on it.
    "science.nasa.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                         "publisher": "NASA"},
    "astrobiology.nasa.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                              "publisher": "NASA Astrobiology Program"},
    "nssdc.gsfc.nasa.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                            "publisher": "NASA Space Science Data Coordinated Archive"},
    "imagine.gsfc.nasa.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                              "publisher": "NASA Goddard Space Flight Center"},
    "www.nhc.noaa.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                         "publisher": "NOAA National Hurricane Center"},
    "www.spc.noaa.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                         "publisher": "NOAA Storm Prediction Center"},
    "www.epa.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                    "publisher": "U.S. Environmental Protection Agency"},
    "oceanservice.noaa.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                              "publisher": "NOAA National Ocean Service"},
    "www.pmel.noaa.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                          "publisher": "NOAA Pacific Marine Environmental Laboratory"},
    "www.nhlbi.nih.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                          "publisher": "National Heart, Lung, and Blood Institute"},
    "www.niddk.nih.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                          "publisher": "National Institute of Diabetes and Digestive and Kidney Diseases"},
    "www.niaid.nih.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                          "publisher": "National Institute of Allergy and Infectious Diseases"},
    "www.niams.nih.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                          "publisher": "National Institute of Arthritis and Musculoskeletal and Skin Diseases"},
    "medlineplus.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                        "publisher": "MedlinePlus, U.S. National Library of Medicine"},
    "www.cdc.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                    "publisher": "Centers for Disease Control and Prevention"},
    "www.cancer.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                       "publisher": "National Cancer Institute"},
    # The CDC's "Principles of Epidemiology in Public Health Practice" — the reference the
    # 2027 rules manual names for this event — is 404 on every live www.cdc.gov path. It
    # survives complete on the archive host, which is the same federal work at a different
    # address, not a third-party mirror.
    "archive.cdc.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                        "publisher": "Centers for Disease Control and Prevention (archive)"},
    "www.fda.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                    "publisher": "U.S. Food and Drug Administration"},
    "www.genome.gov": {"rights_status": "public_domain", "license_name": "public_domain",
                       "publisher": "National Human Genome Research Institute"},
}

# Hosts that refuse our crawler, recorded so the same URLs are not tried again. opentextbc.ca
# hosts an ideal CC-BY geology textbook and returns 403 to this user agent; using it would
# need permission or a different access route, not a retry.
# Hosts measured to refuse this crawler outright. Each entry records a finding, so nobody adds
# a fourteenth page from the same host expecting a different answer:
#   ninds.nih.gov    403 on every path tried, though sibling NIH institutes answer fine
#   organdonor.gov   403
# scioly.org is deliberately NOT here. It was recorded as blocked by an Anubis challenge, and a
# later fetch with this same client returned 48,515 characters of the page. It stays out of
# DOMAIN_SOURCES because it is neither a federal work nor Wikipedia, which is a rights decision
# and not a reachability one — the two are worth keeping distinct.
BLOCKED_HOSTS = {"opentextbc.ca", "www.ninds.nih.gov", "ninds.nih.gov",
                 "www.organdonor.gov", "organdonor.gov",
                 # measured 403 on every path tried, like weather.gov
                 "www.fsis.usda.gov", "www.nih.gov", "www.usda.gov", "www.ars.usda.gov"}


def rights_for(url: str, spec: dict) -> dict:
    """Rights for one URL: an explicit host rule, else the domain's declared default."""
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    if host in HOST_RIGHTS:
        return dict(HOST_RIGHTS[host])
    return {"rights_status": "public_domain", "license_name": spec["license"],
            "publisher": spec["publisher"]}


# A sentence is only a claim about a subject if it uses that subject's vocabulary, so the filter
# has to know which subject it is filtering for. `ground_event` carried one hardcoded regex of
# geology words, which meant grounding any other domain rejected nearly everything as "off_topic":
# a hydrology page explaining an aquifer, a recharge rate or a drainage divide contains none of
# `mineral|rock|crystal|igneous|...`. Rocks & Minerals is the only course this ever worked for, and
# the failure reported itself as "no verified claims" — indistinguishable from a bad source set.
DOMAIN_TERM_PATTERNS = {
    "geology": (r"mineral|rock|crystal|igneous|sediment|metamorph|magma|lava|quartz|feldspar|"
                r"mica|calcite|hardness|streak|luster|cleavage|fracture|silicate|carbonate|"
                r"oxide|sulfide|tecton|volcan|erupt|weather|erosion|deposit|strata|foliat|"
                r"grain|texture|density|element|chemical|formula|composition|pressure|"
                r"temperature|melt|cool|form"
                # The 2027 List includes coal ranks, organic gems and gem varieties; without these
                # terms "Lignite is the lowest rank of coal" was rejected as off-topic.
                r"|coal|lignite|bituminous|anthracite|peat|rank|resin|organic|gem|"
                r"gemstone|variety|chatoyan|pleochro|evaporite|ore|economic|jewel"),
    "hydrology": (r"water|stream|river|channel|creek|flow|discharge|runoff|precipitat|rain|"
                  r"snow|evaporat|transpir|infiltrat|percolat|aquifer|groundwater|water table|"
                  r"well|spring|recharge|watershed|drainage|basin|divide|tributar|sediment|"
                  r"erosion|deposit|meander|floodplain|flood|levee|delta|alluvial|karst|"
                  r"sinkhole|cave|limestone|dissolv|lake|reservoir|wetland|marsh|swamp|bog|"
                  r"porosity|permeab|hydraulic|gradient|velocity|storage|residence|budget|"
                  r"gauge|stage|hydrograph|bank|bed|gravel|silt|clay|sand|valley|slope"),
    "botany": (r"plant|leaf|leaves|root|stem|flower|seed|pollen|pollinat|photosynth|chloroplast|"
               r"chlorophyll|stomat|xylem|phloem|vascular|cuticle|transpir|meristem|cambium|"
               r"cotyledon|monocot|dicot|angiosperm|gymnosperm|bryophyte|fern|spore|gametophyte|"
               r"sporophyte|germinat|hormone|auxin|tropism|nutrient|nitrogen|cellulose|"
               r"cell wall|vacuole|respirat|stoma|petal|sepal|stamen|carpel|ovule|fruit|"
               r"taxonom|species|genus|evolution|fossil|pathogen|fungus|deficiency"),
    "severe_weather": (r"storm|thunderstorm|tornado|hurricane|cyclone|typhoon|supercell|"
                       r"mesocyclone|squall|derecho|downburst|microburst|gust|wind|shear|"
                       r"hodograph|radar|reflectiv|doppler|velocity|echo|sounding|radiosonde|"
                       r"skew-t|st[uü]ve|cape|cin|lcl|lifted|convect|instab|buoyan|updraft|"
                       r"downdraft|precipitat|rain|hail|snow|sleet|freezing|riming|bergeron|"
                       r"coalescen|cloud|cumulon|anvil|mammatus|lightning|charge|thunder|"
                       r"front|air mass|dryline|jet stream|atmospheric river|surge|flood|"
                       r"drought|heat wave|blizzard|nor'easter|ice storm|lake.effect|"
                       r"fujita|saffir|enso|el ni|warning|watch|metar|station model|asos|"
                       r"satellite|infrared|water vapor|pressure|temperature|dew point|humid"),
    "dairy_food_science": (r"independent variable|dependent variable|controlled variable|"
                           r"confound|hypothes|experiment|design|control|replicat|trial|"
                           r"significant figure|accuracy|precision|random error|"
                           r"systematic error|uncertaint|data table|measurement|"
                           r"milk|dairy|cream|butter|cheese|yogurt|yoghurt|curd|whey|"
                           r"casein|micelle|lactose|lactase|lactic|galactose|glucose|"
                           r"sugar|saccharid|carbohydrate|starch|glycosid|"
                           r"lipid|fat|triglycerid|fatty acid|saturated|unsaturated|trans|"
                           r"ester|hydrolys|saponif|hydrogenat|rancid|butterfat|globule|"
                           r"homogeni|emulsi|colloid|surfactant|micell|"
                           r"protein|amino acid|peptide|denatur|isoelectric|rennet|chymosin|"
                           r"coagulat|acid|ph\b|vinegar|acetic|citric|ferment|probiotic|"
                           r"lactobacil|streptococ|bifidobact|culture|"
                           r"pasteuriz|uht|steriliz|preserv|spoil|shelf life|refrigerat|"
                           r"freeze|frozen|evaporated|condensed|powdered|"
                           r"freezing point|colligative|molal|van 't hoff|eutectic|"
                           r"endotherm|enthalpy|fusion|supercool|churn|overrun|"
                           r"plant milk|soy|almond|oat|allerg|anaphyla|immunoglobulin|"
                           r"vitamin|riboflavin|calcium|phosphorus|potassium|mineral|"
                           r"dietary reference|daily value|rda|nutrition facts|label|serving|"
                           r"osteoporos|rickets|deficien|organic|certif|"
                           r"maillard|caramel|scald|raw milk|skim|buttermilk|kefir|"
                           r"titrat|specific heat|solub|solution|hydrogen bond|hydrophob|"
                           r"hydrophil|viscos|densit|mass|temperature"),
    "methodology_2027": (r"scientific method|hypothes|experiment|design|"
                         r"independent variable|dependent variable|controlled variable|"
                         r"constant|control|confound|randomi[sz]|replicat|trial|sample size|"
                         r"operational definition|reproducib|repeatab|observational|"
                         r"bias|blind|observer|"
                         r"measur|accuracy|precision|error|uncertaint|significant figure|"
                         r"unit|\bsi\b|metric|prefix|dimensional analysis|conversion|"
                         r"\bdata\b|qualitative|quantitative|table|chart|graph|plot|"
                         r"bar chart|line chart|scatter|histogram|axis|axes|"
                         r"coordinate|slope|regression|curve|fit|correlat|causation|"
                         r"extrapolat|interpolat|outlier|"
                         r"mean|median|mode|range|standard deviation|variance|average|"
                         r"descriptive statistic|dispersion|percent|ratio|proportion|"
                         r"scientific notation|"
                         r"claim|evidence|reasoning|argument|infer|deductive|inductive|"
                         r"falsifiab|theory|\blaw\b|peer review|notebook|conclusion|"
                         r"limitation|application|"
                         r"technical writing|communicat|instruction|procedur|specification|"
                         r"ambigu|plain language|readab|imperative|sequence|step|enumerat|"
                         r"abbreviat|acronym|"
                         r"spatial|orientation|rotat|translat|reflect|frame of reference|"
                         r"relative|direction|perpendicular|parallel|angle|degree|"
                         r"vertical|horizontal|symmetr|shape|cylinder|cube|sphere|"
                         r"rectangle|triangle|prism|length|diameter|radius|width|height|"
                         r"colou?r|adjacen|centroid|midpoint|position|above|below"),
    "remote_sensing_2027": (r"remote sensing|earth observation|satellite|sensor|imag|"
                            r"electromagnetic|spectrum|wavelength|frequenc|radiation|light|"
                            r"reflect|refract|snell|absor|scatter|rayleigh|\bmie\b|polariz|"
                            r"irradiance|radiance|inverse.square|wien|displacement|"
                            r"stefan|boltzmann|blackbody|black.body|planck|emissiv|"
                            r"infrared|thermal|ultraviolet|visible|near.infrared|shortwave|"
                            r"multispectral|hyperspectral|band|radiometer|scanner|imager|"
                            r"radar|backscatter|synthetic aperture|\bsar\b|insar|"
                            r"interferometr|altimet|elevation model|\bdem\b|lidar|"
                            r"orbit|low earth|medium earth|high earth|geostationary|"
                            r"geosynchronous|polar|sun.synchronous|kepler|period|altitude|"
                            r"resolution|spatial|temporal|radiometric|spectral|"
                            r"signal.to.noise|pixel|swath|revisit|"
                            r"landsat|thematic mapper|\betm\b|\boli\b|sentinel|terra|"
                            r"modis|aster|srtm|ecostress|goes|platform|mission|"
                            r"false colou?r|natural colou?r|grayscale|greyscale|composite|"
                            r"topographic|contour|scale|legend|orientation|marginal|"
                            r"aerial photograph|orthophoto|coordinate|latitude|longitude|"
                            r"slope|gradient|terrain|perimeter|area|distance|"
                            r"albedo|reflectance|aerosol|ndvi|vegetation index|"
                            r"land cover|land use|nlcd|classification|supervised|"
                            r"unsupervised|change|"
                            r"deforest|urban|habitat|wildfire|volcan|landslide|flood|"
                            r"subsidence|glacier|glacial|fluvial|stream|drainage|meander|"
                            r"surface temperature"),
    "cryptography_2027": (r"cipher|cryptogra|cryptanaly|crypt|encrypt|decrypt|encipher|"
                          r"plaintext|ciphertext|\bkey\b|keyword|alphabet|\bk1\b|\bk2\b|"
                          r"substitut|transposition|monoalphabet|polyalphabet|homophonic|"
                          r"aristocrat|patristocrat|xenocrypt|baconian|bacon|atbash|caesar|"
                          r"shift|rot13|affine|vigen|porta|tabula recta|nihilist|polybius|"
                          r"checkerboard|straddling|columnar|rail fence|adfgvx|playfair|"
                          r"bifid|trifid|morse|dot|dash|fractionat|cryptarithm|verbal "
                          r"arithmetic|"
                          r"frequenc|letter frequenc|bigram|trigram|digraph|index of "
                          r"coincidence|kasiski|crib|known.plaintext|ciphertext.only|"
                          r"brute.force|unicity|entropy|redundanc|"
                          r"modul|congruen|remainder|base 10|decimal|carry|addition|"
                          r"permutation|anagram|pattern|"
                          r"steganograph|null cipher|pigpen|scytale|enigma|bletchley|turing|"
                          r"al.kindi|babbage|kerckhoff|one.time pad|acaa?|american cryptogram"),
    "circuits_2027": (r"charge|coulomb|electric field|electrostatic|static|triboelectric|"
                      r"conductor|insulator|ground|earth|lightning|discharge|"
                      r"current|direct current|alternating current|\bdc\b|\bac\b|"
                      r"voltage|volt|potential difference|emf|electromotive|"
                      r"resist|resistivit|ohm|conductance|"
                      r"power|watt|energy|joule|kilowatt|ampere|amp|coulomb|"
                      r"resistor|colou?r code|tolerance|series|parallel|network|circuit|"
                      r"short circuit|open circuit|schematic|diagram|symbol|node|loop|"
                      r"kirchhoff|voltage divider|current divider|equivalent resistance|"
                      r"battery|cell|internal resistance|terminal|"
                      r"multimeter|ammeter|voltmeter|ohmmeter|measure|probe|breadboard|"
                      r"switch|spdt|spst|three.way|relay|fuse|breaker|gfci|residual.current|"
                      r"interrupt|safety|shock|hazard|"
                      r"semiconductor|silicon|doping|pn junction|p.n junction|diode|led|"
                      r"light.emitting|rectif|forward bias|reverse bias|"
                      r"logic gate|\band\b gate|\bor\b gate|\bnot\b gate|nand|nor|xor|"
                      r"truth table|boolean|de morgan|universal|functional complete|"
                      r"combinational|multiplexer|adder|karnaugh|binary|\bbit\b|"
                      r"ampere|volta|hertz|boole|"
                      r"usb|charger|ampere.hour|efficiency|joule heating|wire|gauge|"
                      r"potentiometer|troubleshoot"),
    "forensics_2027": (r"forensic|evidence|crime|scene|suspect|locard|custody|"
                       r"solubilit|dissolv|soluble|insoluble|precipitat|"
                       r"\bph\b|acid|base|alkal|indicator|litmus|neutraliz|"
                       r"densit|magnet|ferromagnet|attract|"
                       r"iodine|starch|amylose|tincture|lugol|blue.black|"
                       r"hydrochloric|hcl|effervesc|fizz|bubble|carbon dioxide|gas|"
                       r"sodium acetate|yeast|ascorbic|vitamin c|calcium carbonate|"
                       r"limestone|sodium chloride|table salt|sucrose|sugar|flour|"
                       r"gypsum|calcium sulfate|cornstarch|corn starch|baking soda|"
                       r"bicarbonate|gelatin|alka.seltzer|sand|silica|silicon dioxide|"
                       r"aluminium|aluminum|iron|zinc|magnesium|copper|\btin\b|metal|"
                       r"reactivity|displacement|corro|oxid|tarnish|"
                       r"lemon|isopropyl|rubbing alcohol|ammonia|water|vinegar|acetic|"
                       r"hydrogen peroxide|catalase|decompos|"
                       r"mixture|separat|filtrat|residue|"
                       r"polymer|plastic|resin|pete|hdpe|ldpe|polystyrene|polypropylene|"
                       r"polyvinyl|pvc|pmma|acrylic|thermoplast|monomer|burn test|"
                       r"hair|cuticle|medulla|cortex|keratin|follicle|"
                       r"fib(er|re)|natural fib|synthetic fib|wool|cotton|nylon|polyester|"
                       r"cellulose|weave|"
                       r"chromatograph|chromatogram|\brf\b|retardation factor|"
                       r"capillary|solvent|mobile phase|stationary phase|polarit|adsorp|"
                       r"\bink\b|\bdye\b|pigment|"
                       r"fingerprint|whorl|loop|arch|ridge|minutiae|latent|dermatoglyph|"
                       r"dna|profil|short tandem|electropherogram|electrophoresis|allele|"
                       r"pcr|codis|marker|peak|"
                       r"shoeprint|footwear|footprint|tread|tyre|tire|impression|"
                       r"gait|stride|direction|"
                       r"soil|texture|horizon|clay|silt|loam|sediment|mineral|grain|"
                       r"spatter|bloodstain|droplet|impact|velocity|viscos|surface tension|"
                       r"microscope|magnif|objective|comparison|"
                       r"physical propert|chemical propert|melting|boiling|crystal|"
                       r"hygroscop|deliquesc|odor|odour|colou?r|texture|"
                       r"goggles|apron|safety|hazard|waste"),
    "genetics_2027": (r"gene|allele|genotype|phenotype|dominan|recessiv|codominan|"
                      r"heterozyg|homozyg|zygot|mendel|punnett|hybrid|cross|pedigree|"
                      r"inherit|trait|autosom|sex.link|x.link|carrier|penetran|epistas|"
                      r"complementation|linkage|recombinat|crossover|centimorgan|map unit|"
                      r"probabilit|ratio|chi.squared|expected|observed|"
                      r"mitosis|meiosis|prophase|metaphase|anaphase|telophase|interphase|"
                      r"cytokinesis|spindle|centromere|kinetochore|chromatid|homolog|"
                      r"synapsis|chiasma|nondisjunction|aneuploid|ploidy|karyotype|trisomy|"
                      r"chromosom|dna|rna|nucleotide|nucleobase|base pair|purine|pyrimidine|"
                      r"adenine|thymine|guanine|cytosine|uracil|phosphodiester|deoxyribose|"
                      # 5' and 3' ends. NOT `5.|3.` — a dot matches any character, so that
                      # admits every sentence containing a number, which is most of them.
                      r"helix|antiparallel|5['\u2032]|3['\u2032]|chargaff|replicat|polymerase|okazaki|"
                      r"ligase|helicase|primase|primer|topoisomerase|proofread|semiconservat|"
                      r"telomere|plasmid|chromatin|euchromat|heterochromat|nucleosome|histone|"
                      r"mutation|point|frameshift|missense|nonsense|silent|insertion|deletion|"
                      r"substitution|translocation|inversion|duplication|ultraviolet|uva|uvb|"
                      r"dimer|excision repair|central dogma|transcription|translation|"
                      r"promoter|operator|operon|lac|trp|activator|repressor|inducer|"
                      # `cap` alone matches capacity, capture, capital, capillary.
                      r"splic|intron|exon|spliceosome|capping|5['\u2032] cap|polyadenyl|"
                      r"codon|anticodon|"
                      r"ribosome|trna|mrna|rrna|synthetase|peptide|amino acid|protein|"
                      r"hardy.weinberg|allele frequenc|equilibrium|genetic drift|founder|"
                      r"bottleneck|migration|gene flow|fitness|selection|polygen|additive|"
                      r"quantitative|heritab|population|pcr|denaturation|annealing|extension|"
                      r"thermal cycler|taq|thermus|electrophoresis|sanger|dideoxy|"
                      r"sequencing|restriction enzyme"),
    "astrobiology": (r"habitab|life|biosign|biolog|organic|amino|protein|nucleic|lipid|"
                     r"carbohydrate|extremophile|microb|metabol|chemolithoauto|tardigrade|"
                     r"ocean|water|ice|brine|clathrate|liquid|subsurface|plume|cryovolcan|"
                     r"tidal|heating|moon|satellite|planet|dwarf|asteroid|comet|kuiper|"
                     r"atmosphere|composition|spectr|albedo|flux|radiation|temperature|"
                     r"equilibrium|blackbody|stefan|wien|greenhouse|escape velocity|gravit|"
                     r"orbit|kepler|newton|eccentric|semi-major|energy|kinetic|potential|"
                     r"exoplanet|transit|radial velocity|microlensing|direct imaging|"
                     r"mission|spacecraft|instrument|telescope|orbiter|lander|rover|probe|"
                     r"doppler|wavelength|magnitude|density|mass|pressure|arrhenius|ideal gas"),
    "anatomy_2027": (r"respirat|lung|alveol|bronch|trache|pleura|diaphragm|airway|breath|"
                     r"ventilat|spiromet|spirogram|tidal volume|vital capacity|residual|"
                     r"gas exchange|oxygen|o2|carbon dioxide|hemoglobin|haemoglobin|"
                     r"dissociation|bohr|partial pressure|altitude|exercise|copd|asthma|"
                     r"emphysema|pneumonia|apnea|apnoea|cystic fibrosis|tuberculos|edema|"
                     r"pleurisy|fibrosis|pneumoconios|asbestos|digest|aliment|esophag|"
                     r"oesophag|stomach|gastric|intestin|duoden|jejun|ileum|colon|villi|"
                     r"villus|microvill|mucosa|submucosa|muscularis|serosa|epitheli|enzyme|"
                     r"pepsin|trypsin|amylase|lipase|bile|liver|hepat|pancrea|kupffer|"
                     r"peristal|absorpt|ulcer|gerd|reflux|colitis|crohn|celiac|coeliac|"
                     r"divertic|lactose|diarrh|appendic|obesity|immun|antigen|antibod|"
                     r"lymph|thymus|spleen|marrow|complement|toll-like|inflamm|macrophage|"
                     r"neutrophil|natural killer|dendritic|t cell|b cell|mhc|histocompat|"
                     r"allerg|hypersensitiv|anaphyla|urticaria|myasthenia|serum sickness|"
                     r"arthus|autoimmun|lupus|sclerod|psoria|multiple sclerosis|rheumatoid|"
                     r"hashimoto|graves|transplant|allograft|autograft|reject|car-t|"
                     r"immunotherap|vaccin|cytokine|interleukin|receptor|cell|tissue|organ"),
    "water_quality_marine": (r"water|marine|ocean|sea|estuar|coast|reef|coral|polyp|"
                            r"zooxanthell|symbio|algae|seagrass|mangrove|plankton|fish|"
                            r"invertebrate|urchin|lobster|shrimp|clam|sponge|snail|eel|"
                            r"grouper|parrotfish|snapper|wrasse|starfish|cucumber|"
                            r"salinity|saline|brackish|halocline|density|hydrometer|"
                            r"salinomet|dissolved oxygen|oxygen|turbid|secchi|nephelomet|"
                            r"ph\b|acid|alkalin|nitrate|nitrogen|phosphate|phosphorus|"
                            r"nutrient|coliform|bacteria|solids|biochemical oxygen|bod|"
                            r"aragonite|saturation|carbonate|calcif|temperature|thermocline|"
                            r"bleach|disease|indicator|bioindicat|monitor|sampl|parameter|"
                            r"pollut|runoff|sediment|siltat|nonpoint|eutroph|hypox|dead zone|"
                            r"bloom|red tide|debris|plastic|pfas|contaminant|treatment|"
                            r"potable|wastewater|sewage|watershed|drainage|basin|cycle|"
                            r"food web|trophic|predat|herbivor|graz|population|ecosystem|"
                            r"habitat|distribution|indo-pacific|atlantic|protected area"),
    # The `physics` pattern covers motion and force and barely touches heat: grounding
    # Thermodynamics against it rejects most of its best sentences as off_topic, because a page
    # on entropy, emissivity or the Carnot cycle contains almost none of its vocabulary.
    "thermodynamics": (r"thermodynam|thermal|heat|temperature|kelvin|celsius|fahrenheit|"
                       r"absolute zero|thermomet|triple point|entropy|enthalpy|internal energy|"
                       r"adiabat|isotherm|isochor|isobar|calor|joule|btu|boltzmann|"
                       r"specific heat|heat capacity|latent|sensible|fusion|vaporiz|"
                       r"phase|state of matter|melt|freez|boil|condens|sublim|"
                       r"ideal gas|pressure|volume|mole|kinetic theory|molecul|"
                       r"conduct|convect|radiat|emissiv|absorptan|absorb|reflect|albedo|"
                       r"blackbody|black-body|planck|stefan|wien|irradian|exitance|flux|"
                       r"insulat|r-value|aerogel|radiant barrier|thermal mass|greenhouse|"
                       r"vacuum flask|equilibrium|carnot|otto|brayton|engine|cycle|"
                       r"efficien|work|energy|power|watt|reservoir|inverse-square|"
                       r"significant figure|si unit|metric|conversion"),
    # Fourteen domains had no tuned vocabulary and silently fell back to the geology pattern.
    # `ground_event` prints a warning nobody was reading, and the cost is measurable: Disease
    # Detectives rejected 8,351 sentences as "off_topic" and kept 375 claims from 140 sources,
    # because a page about attack rates and odds ratios contains none of
    # `mineral|rock|crystal|igneous`. Meteorology, with a tuned pattern, keeps 2,077 from 83.
    "epidemiology": (r"epidemi|outbreak|epidemic|pandemic|endemic|cluster|surveillance|"
                     r"incidence|prevalence|attack rate|case fatality|mortality|morbidity|"
                     r"rate|ratio|proportion|odds|risk|relative risk|confidence interval|"
                     r"cohort|case-control|cross-sectional|ecological|randomi|trial|study|"
                     r"bias|confound|recall|selection|misclassif|association|causal|"
                     r"bradford hill|koch|postulate|exposure|outcome|case definition|"
                     r"transmission|vector|vehicle|reservoir|host|agent|pathogen|infect|"
                     r"bacteri|virus|viral|fungal|protozoa|prion|incubation|latent|carrier|"
                     r"quarantine|isolation|contact tracing|vaccin|immuni|herd immunity|"
                     r"prevention|screening|control measure|epidemic curve|line listing|"
                     r"histogram|median|mean|mode|standard deviation|percentile|"
                     r"pulsenet|pfge|serotype|whole genome|sequenc|specimen|laboratory"),
    "genetics": (r"gene|genetic|genom|allele|chromosom|chromatid|centromere|telomere|"
                 r"dna|rna|nucleotide|base pair|codon|anticodon|helix|strand|"
                 r"replicat|transcri|translat|ribosome|polymerase|primer|promoter|"
                 r"operon|repressor|activator|intron|exon|splic|mutation|missense|"
                 r"nonsense|frameshift|silent|deletion|insertion|substitution|"
                 r"dominan|recessive|codominan|epistas|heterozyg|homozyg|genotype|"
                 r"phenotype|punnett|cross|hybrid|segregat|independent assortment|"
                 r"pedigree|inherit|linkage|recombinat|crossing over|karyotype|"
                 r"nondisjunction|trisomy|monosomy|aneuploid|meiosis|mitosis|gamete|"
                 r"hardy|weinberg|allele frequency|drift|founder|bottleneck|fitness|"
                 r"probability|ratio|polygen|quantitative trait|heritab|pcr|sanger"),
    "remote_sensing": (r"remote sensing|satellite|sensor|orbit|imagery|image|band|"
                       r"wavelength|spectrum|spectral|infrared|thermal|visible|microwave|"
                       r"radar|lidar|radiometr|reflect|emiss|albedo|radiation|radiance|"
                       r"resolution|pixel|swath|landsat|modis|goes|nadir|"
                       r"electromagnetic|absorption|scatter|atmospher|aerosol|cloud|"
                       r"vegetation|ndvi|land cover|sea surface|temperature|ice|ocean|"
                       r"greenhouse|energy budget|climate|false colour|false color|"
                       r"composite|calibrat|ground truth|interpret"),
    "forensics": (r"forensic|evidence|crime|analys|identif|sample|unknown|test|"
                  r"chromatograph|spectroscop|flame test|precipitat|solubil|acid|base|"
                  r"ph\b|indicator|reagent|polymer|plastic|fiber|fibre|hair|"
                  r"fingerprint|dna|blood|spatter|glass|refractive|density|"
                  r"powder|crystal|metal|alloy|conductiv|magnet|"
                  r"microscop|observ|measur|mass|volume|density|reaction|chemical|"
                  r"physical propert|qualitative|quantitative|control|standard"),
    "cryptography": (r"cipher|cryptogra|crypt|encrypt|decrypt|plaintext|ciphertext|"
                     r"key|shift|caesar|substitut|transposit|vigen|affine|atbash|"
                     r"hill cipher|playfair|baconian|morse|nihilist|porta|"
                     r"frequency analys|letter frequency|cryptanaly|brute force|"
                     r"modular|modulo|inverse|alphabet|encode|decode|message|"
                     r"pattern|digraph|trigraph|keyword|rail fence|columnar"),
    "methodology": (r"experiment|hypothes|variable|independent|dependent|control|"
                    r"constant|procedure|method|data|measur|observ|record|"
                    r"analys|graph|table|chart|axis|trend|correlat|"
                    r"conclusion|evidence|claim|reason|error|uncertainty|precision|"
                    r"accuracy|replicat|trial|sample|randomi|bias|validity|"
                    r"qualitative|quantitative|unit|metric|significant figure"),
    "chemistry": (r"chemical|chemistry|element|compound|molecul|atom|ion|isotope|"
                  r"reaction|equation|stoichiometr|mole|molar|concentration|"
                  r"solution|solvent|solute|solubil|precipitat|acid|base|ph\b|"
                  r"titrat|indicator|buffer|oxidation|reduction|redox|electron|"
                  r"bond|covalent|ionic|periodic|valence|gas|pressure|volume|"
                  r"temperature|heat|energy|enthalp|equilibrium|rate|catalyst"),
    "metrology": (r"measur|unit|metric|si\b|meter|metre|gram|liter|litre|second|"
                  r"kelvin|mole|candela|ampere|prefix|kilo|centi|milli|micro|"
                  r"convert|conversion|dimension|significant figure|precision|"
                  r"accuracy|uncertainty|estimat|scale|balance|graduated|"
                  r"volume|mass|length|density|area|temperature|calibrat"),
    # The last six. These serve the archived 2026 events and Division C's Astronomy and
    # Entomology, which students can still pick, so "prior season" is not a reason to leave
    # them grounding against geology vocabulary.
    "anatomy": (r"anatom|physiolog|body|organ|tissue|cell|system|nerve|neuron|neural|"
                r"brain|spinal|cortex|synap|axon|dendrite|receptor|reflex|"
                r"endocrine|hormone|gland|pituitary|thyroid|adrenal|pancrea|insulin|"
                r"muscle|skelet|bone|joint|cartilage|tendon|ligament|contract|fiber|fibre|"
                r"blood|heart|vessel|artery|vein|circulat|respirat|lung|digest|"
                r"membrane|homeostas|regulat|stimulus|response|disease|disorder|"
                r"function|structure|secret|transmit|signal"),
    "astronomy": (r"star|stellar|sun|solar|planet|moon|satellite|orbit|galaxy|galactic|"
                  r"nebula|cluster|universe|cosmic|cosmolog|redshift|doppler|"
                  r"spectrum|spectral|magnitude|luminosity|flux|brightness|parallax|"
                  r"light year|parsec|telescope|observator|wavelength|infrared|"
                  r"ultraviolet|x-ray|radio|black hole|neutron star|white dwarf|"
                  r"supernova|main sequence|hertzsprung|russell|fusion|hydrogen|helium|"
                  r"mass|gravity|gravitat|kepler|newton|eclipse|transit|exoplanet|"
                  r"nuclear|temperature|radiation|blackbody|accretion|binary"),
    "entomology": (r"insect|arthropod|entomolog|order|family|genus|species|taxonom|"
                   r"classif|identif|specimen|key\b|morpholog|anatomy|"
                   r"head|thorax|abdomen|antenna|wing|elytra|leg|tarsus|mandible|"
                   r"proboscis|ovipositor|exoskeleton|cuticle|molt|moult|instar|"
                   r"metamorphos|larva|pupa|nymph|egg|complete metamorphosis|"
                   r"coleoptera|lepidoptera|diptera|hymenoptera|hemiptera|odonata|"
                   r"orthoptera|isoptera|habitat|ecolog|pollinat|predat|parasit|"
                   r"pest|beneficial|vector|feed|host plant"),
    "meteorology": (r"weather|atmospher|climate|air mass|front|pressure|barometr|"
                    r"temperature|humid|dew point|relative humidity|precipitat|rain|"
                    r"snow|cloud|cumul|stratus|cirrus|nimbus|fog|wind|jet stream|"
                    r"circulation|coriolis|convect|advect|adiabat|lapse rate|"
                    r"stability|inversion|condens|evaporat|saturation|"
                    r"storm|thunderstorm|hurricane|tornado|forecast|station model|"
                    r"isobar|isotherm|radiation|greenhouse|season|solstice|equinox"),
    "oceanography": (r"ocean|sea|marine|water|salin|saltwater|seawater|brackish|"
                     r"current|gyre|upwell|downwell|thermohaline|tide|tidal|wave|"
                     r"swell|crest|trough|wavelength|surf|coast|shore|beach|"
                     r"estuar|reef|coral|continental shelf|slope|abyssal|trench|"
                     r"ridge|seafloor|sediment|plankton|nekton|benthic|pelagic|"
                     r"thermocline|halocline|pycnocline|density|temperature|pressure|"
                     r"dissolved oxygen|nutrient|productivity|el ni|enso|circulation"),
    "water": (r"water|aquatic|freshwater|stream|river|lake|pond|wetland|watershed|"
              r"macroinvertebrate|invertebrate|benthic|taxa|taxon|indicator|"
              r"tolerance|pollut|contamin|runoff|nutrient|nitrate|phosphate|"
              r"dissolved oxygen|turbid|ph\b|temperature|conductiv|hardness|"
              r"alkalin|coliform|bacteria|sampling|monitor|quality|index|"
              r"habitat|riparian|erosion|sediment|ecosystem|food web|"
              r"eutroph|algae|bloom|treatment|filtration"),
    "physics": (r"energy|force|motion|velocity|speed|accelerat|momentum|inertia|mass|weight|"
                r"gravit|friction|roll|slide|torque|lever|pulley|wheel|axle|incline|machine|"
                r"mechanical advantage|work|power|potential|kinetic|rotat|angular|circular|"
                r"centripetal|loop|spring|pressure|current|voltage|resist|circuit|magnet|"
                r"capacit|wave|heat|temperature|thermal"),
}


def domain_terms_pattern(domain: str) -> str:
    """Subject vocabulary for a domain's claim filter.

    Falls back to the geology pattern, which is what every domain silently used before, so a
    domain without an entry behaves exactly as it did rather than changing meaning unnoticed —
    but `ground_event` says out loud that the filter is not tuned for it.
    """
    return DOMAIN_TERM_PATTERNS.get(domain, DOMAIN_TERM_PATTERNS["geology"])


# domain -> {publisher, license, urls[]}
DOMAIN_SOURCES = {
    "geology": {
        "publisher": "U.S. National Park Service / USGS",
        "license": "public_domain",
        # Chosen to span the Rocks & Minerals skill list: identification properties, crystal
        # chemistry, mineral groups, igneous processes and volcanism, tectonics, sedimentary
        # environments, and metamorphism. Federal works, so public domain.
        "urls": [
            "https://www.nps.gov/subjects/geology/minerals.htm",
            "https://www.nps.gov/subjects/geology/rocks.htm",
            "https://www.nps.gov/subjects/geology/igneous.htm",
            "https://www.nps.gov/subjects/geology/sedimentary.htm",
            "https://www.nps.gov/subjects/geology/metamorphic.htm",
            "https://www.nps.gov/subjects/geology/plate-tectonics.htm",
            "https://www.usgs.gov/faqs/what-are-igneous-rocks",
            "https://www.usgs.gov/faqs/what-are-sedimentary-rocks",
            "https://www.usgs.gov/faqs/what-are-metamorphic-rocks",
            "https://www.usgs.gov/faqs/what-difference-between-rock-and-mineral",
            "https://www.usgs.gov/programs/mineral-resources-program",
            "https://www.usgs.gov/programs/earthquake-hazards/science-earthquakes",
            "https://en.wikipedia.org/wiki/Bowen%27s_reaction_series",
            "https://en.wikipedia.org/wiki/Crystal_habit",
            "https://en.wikipedia.org/wiki/Metamorphic_facies",
            "https://en.wikipedia.org/wiki/Silicate_mineral",
            "https://en.wikipedia.org/wiki/Mohs_scale",
            "https://en.wikipedia.org/wiki/Cleavage_(crystal)",
            "https://en.wikipedia.org/wiki/Igneous_rock",
            "https://en.wikipedia.org/wiki/Sedimentary_rock",
            "https://en.wikipedia.org/wiki/Metamorphic_rock",
            "https://en.wikipedia.org/wiki/Mineral",
            "https://en.wikipedia.org/wiki/Rock_cycle",
            "https://en.wikipedia.org/wiki/Plate_tectonics",
            "https://en.wikipedia.org/wiki/Solid_solution",
            "https://en.wikipedia.org/wiki/Streak_(mineralogy)",
            # Added to close the eight recorded ContentGaps on rocks-and-minerals-b: the
            # originals are overview pages, and the ungrounded blocks teach specifics
            # (hazards, differentiation, depositional settings, facies) they never reach.
            "https://en.wikipedia.org/wiki/Mineralogy",
            "https://en.wikipedia.org/wiki/Lustre_(mineralogy)",
            "https://en.wikipedia.org/wiki/Crystal_system",
            "https://en.wikipedia.org/wiki/Specific_gravity",
            "https://en.wikipedia.org/wiki/Crystal_structure",
            "https://en.wikipedia.org/wiki/Polymorphism_(materials_science)",
            "https://en.wikipedia.org/wiki/Carbonate_mineral",
            "https://en.wikipedia.org/wiki/Sulfide_mineral",
            "https://en.wikipedia.org/wiki/Oxide_mineral",
            "https://en.wikipedia.org/wiki/Asbestos",
            "https://en.wikipedia.org/wiki/Fractional_crystallization_(geology)",
            "https://en.wikipedia.org/wiki/Igneous_differentiation",
            "https://en.wikipedia.org/wiki/Types_of_volcanic_eruptions",
            "https://en.wikipedia.org/wiki/Lava",
            "https://en.wikipedia.org/wiki/Subduction",
            "https://en.wikipedia.org/wiki/Mid-ocean_ridge",
            "https://en.wikipedia.org/wiki/Hotspot_(geology)",
            "https://en.wikipedia.org/wiki/Depositional_environment",
            "https://en.wikipedia.org/wiki/Clastic_rock",
            "https://en.wikipedia.org/wiki/Diagenesis",
            "https://en.wikipedia.org/wiki/Foliation_(geology)",
            "https://en.wikipedia.org/wiki/Contact_metamorphism",
            # Second targeted pass, against the nine blocks still unsupported after the first:
            # carbonate acid tests, UV fluorescence, Bowen chain minerals, coal rank, the
            # lever rule, and thin-section optics. Core Rocks & Minerals subject matter that
            # belonged in this set regardless of which block prompted it.
            "https://en.wikipedia.org/wiki/Dolomite_(mineral)",
            "https://en.wikipedia.org/wiki/Calcite",
            "https://en.wikipedia.org/wiki/Dolostone",
            "https://en.wikipedia.org/wiki/Chalk",
            "https://en.wikipedia.org/wiki/Barite",
            "https://en.wikipedia.org/wiki/Fluorescence",
            "https://en.wikipedia.org/wiki/Coal",
            "https://en.wikipedia.org/wiki/Anthracite",
            "https://en.wikipedia.org/wiki/Lever_rule",
            "https://en.wikipedia.org/wiki/Birefringence",
            "https://en.wikipedia.org/wiki/Petrographic_microscope",
            "https://en.wikipedia.org/wiki/Olivine",
            "https://en.wikipedia.org/wiki/Pyroxene",
            "https://en.wikipedia.org/wiki/Amphibole",
            "https://en.wikipedia.org/wiki/Augite",
            "https://en.wikipedia.org/wiki/Shield_volcano",
            # The official 2027 National Rocks and Minerals List names 150 specimens and
            # identification is 30-50% of event points, limited to that list. 76 of them
            # appeared in no lesson, exam or lab, so there was nothing to ground a lesson
            # about them on: whole groups (Amphibole, Pyroxene, Mica, Garnet), every quartz
            # and gem variety, the feldspars, and rocks from pegmatite to coquina. Each page
            # below was fetched and checked before being added.
            "https://en.wikipedia.org/wiki/Actinolite",
            "https://en.wikipedia.org/wiki/Alkali_feldspar",
            "https://en.wikipedia.org/wiki/Almandine",
            "https://en.wikipedia.org/wiki/Amazonite",
            "https://en.wikipedia.org/wiki/Amethyst",
            "https://en.wikipedia.org/wiki/Amphibolite",
            "https://en.wikipedia.org/wiki/Apatite",
            "https://en.wikipedia.org/wiki/Apophyllite",
            "https://en.wikipedia.org/wiki/Aquamarine_%28gem%29",
            "https://en.wikipedia.org/wiki/Aragonite",
            "https://en.wikipedia.org/wiki/Arkose",
            "https://en.wikipedia.org/wiki/Aventurine",
            "https://en.wikipedia.org/wiki/Banded_iron_formation",
            "https://en.wikipedia.org/wiki/Bornite",
            "https://en.wikipedia.org/wiki/Celestine_%28mineral%29",
            "https://en.wikipedia.org/wiki/Chalcedony",
            "https://en.wikipedia.org/wiki/Chalcopyrite",
            "https://en.wikipedia.org/wiki/Chrysocolla",
            "https://en.wikipedia.org/wiki/Citrine",
            "https://en.wikipedia.org/wiki/Coquina",
            "https://en.wikipedia.org/wiki/Diamond",
            "https://en.wikipedia.org/wiki/Diatomite",
            "https://en.wikipedia.org/wiki/Dioptase",
            "https://en.wikipedia.org/wiki/Emerald",
            "https://en.wikipedia.org/wiki/Fluorapatite",
            "https://en.wikipedia.org/wiki/Garnet",
            "https://en.wikipedia.org/wiki/Goethite",
            "https://en.wikipedia.org/wiki/Grossular",
            "https://en.wikipedia.org/wiki/Gypsum",
            "https://en.wikipedia.org/wiki/Hiddenite",
            "https://en.wikipedia.org/wiki/Hornblende",
            "https://en.wikipedia.org/wiki/Jasper",
            "https://en.wikipedia.org/wiki/Kaolinite",
            "https://en.wikipedia.org/wiki/Kunzite",
            "https://en.wikipedia.org/wiki/Labradorite",
            "https://en.wikipedia.org/wiki/Lepidolite",
            "https://en.wikipedia.org/wiki/Magnesite",
            "https://en.wikipedia.org/wiki/Mica",
            "https://en.wikipedia.org/wiki/Morganite",
            "https://en.wikipedia.org/wiki/Orthoclase",
            "https://en.wikipedia.org/wiki/Pegmatite",
            "https://en.wikipedia.org/wiki/Pyrolusite",
            "https://en.wikipedia.org/wiki/Pyromorphite",
            "https://en.wikipedia.org/wiki/Quartz",
            "https://en.wikipedia.org/wiki/Rhodochrosite",
            "https://en.wikipedia.org/wiki/Rhodonite",
            "https://en.wikipedia.org/wiki/Rose_Quartz",
            "https://en.wikipedia.org/wiki/Ruby",
            "https://en.wikipedia.org/wiki/Rutile",
            "https://en.wikipedia.org/wiki/Sapphire",
            "https://en.wikipedia.org/wiki/Selenite_%28mineral%29",
            "https://en.wikipedia.org/wiki/Siderite",
            "https://en.wikipedia.org/wiki/Smoky_Quartz",
            "https://en.wikipedia.org/wiki/Soapstone",
            "https://en.wikipedia.org/wiki/Sodalite",
            "https://en.wikipedia.org/wiki/Sphalerite",
            "https://en.wikipedia.org/wiki/Spodumene",
            "https://en.wikipedia.org/wiki/Staurolite",
            "https://en.wikipedia.org/wiki/Stibnite",
            "https://en.wikipedia.org/wiki/Stilbite",
            "https://en.wikipedia.org/wiki/Syenite",
            "https://en.wikipedia.org/wiki/Tiger%27s_eye",
            "https://en.wikipedia.org/wiki/Travertine",
            "https://en.wikipedia.org/wiki/Tremolite",
            "https://en.wikipedia.org/wiki/Tuff",
            "https://en.wikipedia.org/wiki/Turquoise",
            "https://en.wikipedia.org/wiki/Ulexite",
            "https://en.wikipedia.org/wiki/Vanadinite",
            "https://en.wikipedia.org/wiki/Willemite",
            "https://en.wikipedia.org/wiki/Wollastonite",
            "https://en.wikipedia.org/wiki/Zincite",
            "https://en.wikipedia.org/wiki/Zircon",
            # The 2027 National Rocks and Minerals List names 152 specimens and 46 of the
            # ones the course never mentioned had no page here at all — granite, basalt,
            # gabbro, obsidian, talc, topaz, corundum, every quartz variety, every
            # gemstone. A course cannot teach a specimen its corpus has no evidence about,
            # so the lesson for it recorded a content gap instead. Identification is 30-50%
            # of the event's points and is limited to that list.
            "https://en.wikipedia.org/wiki/Agate",
            "https://en.wikipedia.org/wiki/Alabaster",
            "https://en.wikipedia.org/wiki/Albite",
            "https://en.wikipedia.org/wiki/Amber",
            "https://en.wikipedia.org/wiki/Andesite",
            "https://en.wikipedia.org/wiki/Aquamarine_(gem)",
            "https://en.wikipedia.org/wiki/Azurite",
            "https://en.wikipedia.org/wiki/Basalt",
            "https://en.wikipedia.org/wiki/Bauxite",
            "https://en.wikipedia.org/wiki/Beryl",
            "https://en.wikipedia.org/wiki/Biotite",
            "https://en.wikipedia.org/wiki/Bituminous_coal",
            "https://en.wikipedia.org/wiki/Breccia",
            "https://en.wikipedia.org/wiki/Chert",
            "https://en.wikipedia.org/wiki/Citrine_(quartz)",
            "https://en.wikipedia.org/wiki/Corundum",
            "https://en.wikipedia.org/wiki/Diorite",
            "https://en.wikipedia.org/wiki/Dolomite_(rock)",
            "https://en.wikipedia.org/wiki/Epidote",
            "https://en.wikipedia.org/wiki/Evaporite",
            "https://en.wikipedia.org/wiki/Feldspar",
            "https://en.wikipedia.org/wiki/Flint",
            "https://en.wikipedia.org/wiki/Fracture_(mineralogy)",
            "https://en.wikipedia.org/wiki/Gabbro",
            "https://en.wikipedia.org/wiki/Granite",
            "https://en.wikipedia.org/wiki/Greywacke",
            "https://en.wikipedia.org/wiki/Index_mineral",
            "https://en.wikipedia.org/wiki/Kyanite",
            "https://en.wikipedia.org/wiki/Lignite",
            "https://en.wikipedia.org/wiki/Limestone",
            "https://en.wikipedia.org/wiki/Malachite",
            "https://en.wikipedia.org/wiki/Microcline",
            "https://en.wikipedia.org/wiki/Milky_quartz",
            "https://en.wikipedia.org/wiki/Mineral_group",
            "https://en.wikipedia.org/wiki/Mineraloid",
            "https://en.wikipedia.org/wiki/Muscovite",
            "https://en.wikipedia.org/wiki/Native_metal",
            "https://en.wikipedia.org/wiki/Obsidian",
            "https://en.wikipedia.org/wiki/Opal",
            "https://en.wikipedia.org/wiki/Ore",
            "https://en.wikipedia.org/wiki/Pearl",
            "https://en.wikipedia.org/wiki/Peridot",
            "https://en.wikipedia.org/wiki/Peridotite",
            "https://en.wikipedia.org/wiki/Plagioclase",
            "https://en.wikipedia.org/wiki/Prehnite",
            "https://en.wikipedia.org/wiki/Protolith",
            "https://en.wikipedia.org/wiki/Pumice",
            "https://en.wikipedia.org/wiki/Regional_metamorphism",
            "https://en.wikipedia.org/wiki/Rhyolite",
            "https://en.wikipedia.org/wiki/Rock_crystal",
            "https://en.wikipedia.org/wiki/Rose_quartz",
            "https://en.wikipedia.org/wiki/Schist",
            "https://en.wikipedia.org/wiki/Scoria",
            "https://en.wikipedia.org/wiki/Serpentinite",
            "https://en.wikipedia.org/wiki/Silver",
            "https://en.wikipedia.org/wiki/Smoky_quartz",
            "https://en.wikipedia.org/wiki/Talc",
            "https://en.wikipedia.org/wiki/Topaz",
            "https://en.wikipedia.org/wiki/Tourmaline",
        ],
    },
    "meteorology": {
        "publisher": "NOAA National Weather Service",
        "license": "public_domain",
        "urls": [
            "https://en.wikipedia.org/wiki/Weather_front",
            "https://en.wikipedia.org/wiki/Atmospheric_circulation",
            "https://en.wikipedia.org/wiki/Adiabatic_process",
            "https://en.wikipedia.org/wiki/Relative_humidity",
            "https://en.wikipedia.org/wiki/Meteorology",
            "https://en.wikipedia.org/wiki/Atmosphere_of_Earth",
            "https://en.wikipedia.org/wiki/Atmospheric_pressure",
            "https://en.wikipedia.org/wiki/Cloud",
            "https://en.wikipedia.org/wiki/Precipitation",
            "https://en.wikipedia.org/wiki/Thunderstorm",
            "https://en.wikipedia.org/wiki/Tornado",
            "https://en.wikipedia.org/wiki/Tropical_cyclone",
            "https://en.wikipedia.org/wiki/Jet_stream",
            "https://en.wikipedia.org/wiki/Weather_radar",
            "https://en.wikipedia.org/wiki/Coriolis_force",
            "https://en.wikipedia.org/wiki/Lapse_rate",
            "https://en.wikipedia.org/wiki/Dew_point",
            "https://en.wikipedia.org/wiki/Air_mass",
            "https://en.wikipedia.org/wiki/Station_model",
            "https://en.wikipedia.org/wiki/Weather_forecasting",
        ],
    },
    "oceanography": {
        "publisher": "NOAA Ocean Service",
        "license": "public_domain",
        "urls": [
            "https://oceanservice.noaa.gov/education/tutorial_currents/welcome.html",
            "https://oceanservice.noaa.gov/education/tutorial_tides/welcome.html",
            "https://oceanservice.noaa.gov/facts/thermohaline-circulation.html",
            "https://oceanservice.noaa.gov/facts/upwelling.html",
            "https://oceanservice.noaa.gov/facts/elnino.html",
            "https://oceanservice.noaa.gov/facts/acidification.html",
            "https://oceanservice.noaa.gov/facts/coriolis.html",
            "https://www.usgs.gov/programs/earthquake-hazards/science-earthquakes",
            "https://en.wikipedia.org/wiki/Ocean_current",
            "https://en.wikipedia.org/wiki/Thermocline",
            "https://en.wikipedia.org/wiki/Plate_tectonics",
            "https://en.wikipedia.org/wiki/Mid-ocean_ridge",
            "https://en.wikipedia.org/wiki/Ekman_transport",
            "https://en.wikipedia.org/wiki/Salinity",
            "https://en.wikipedia.org/wiki/Oceanography",
            "https://en.wikipedia.org/wiki/Tide",
        ],
    },
    "astronomy": {
        "publisher": "NASA",
        "license": "public_domain",
        "urls": [
            "https://science.nasa.gov/solar-system/",
            "https://science.nasa.gov/universe/stars/",
            "https://science.nasa.gov/universe/galaxies/",
            "https://science.nasa.gov/universe/black-holes/",
            "https://science.nasa.gov/sun/",
            "https://en.wikipedia.org/wiki/Stellar_evolution",
            "https://en.wikipedia.org/wiki/Hertzsprung%E2%80%93Russell_diagram",
            "https://en.wikipedia.org/wiki/Main_sequence",
            "https://en.wikipedia.org/wiki/Supernova",
            "https://en.wikipedia.org/wiki/White_dwarf",
            "https://en.wikipedia.org/wiki/Neutron_star",
            "https://en.wikipedia.org/wiki/Redshift",
            "https://en.wikipedia.org/wiki/Kepler%27s_laws_of_planetary_motion",
            "https://en.wikipedia.org/wiki/Light_curve",
        ],
    },
    "remote_sensing": {
        "publisher": "NASA Earthdata",
        "license": "public_domain",
        "urls": [
            "https://www.earthdata.nasa.gov/learn/backgrounders/remote-sensing",
            "https://landsat.gsfc.nasa.gov/satellites/landsat-8/",
            "https://www.usgs.gov/landsat-missions/landsat-satellite-missions",
            "https://en.wikipedia.org/wiki/Remote_sensing",
            "https://en.wikipedia.org/wiki/Electromagnetic_spectrum",
            "https://en.wikipedia.org/wiki/Normalized_difference_vegetation_index",
            "https://en.wikipedia.org/wiki/Blackbody_radiation",
            "https://en.wikipedia.org/wiki/Albedo",
            "https://en.wikipedia.org/wiki/Greenhouse_effect",
            "https://en.wikipedia.org/wiki/Radiative_forcing",
            "https://en.wikipedia.org/wiki/Wien%27s_displacement_law",
            "https://en.wikipedia.org/wiki/Stefan%E2%80%93Boltzmann_law",
            "https://www.earthdata.nasa.gov/learn/earth-observation-data-basics",
            "https://en.wikipedia.org/wiki/Multispectral_image",
        ],
    },
    "anatomy": {
        "publisher": "NIH National Library of Medicine (MedlinePlus)",
        "license": "public_domain",
        "urls": [
            "https://medlineplus.gov/hormones.html",
            "https://medlineplus.gov/bloodheartandcirculation.html",
            "https://medlineplus.gov/lungsandbreathing.html",
            "https://medlineplus.gov/digestivesystem.html",
            "https://medlineplus.gov/bonesjointsandmuscles.html",
            "https://medlineplus.gov/brainandnerves.html",
            "https://medlineplus.gov/kidneysandurinarysystem.html",
            "https://medlineplus.gov/immunesystemanddisorders.html",
            "https://en.wikipedia.org/wiki/Nervous_system",
            "https://en.wikipedia.org/wiki/Neuron",
            "https://en.wikipedia.org/wiki/Action_potential",
            "https://en.wikipedia.org/wiki/Central_nervous_system",
            "https://en.wikipedia.org/wiki/Endocrine_system",
            "https://en.wikipedia.org/wiki/Circulatory_system",
            "https://en.wikipedia.org/wiki/Respiratory_system",
            "https://en.wikipedia.org/wiki/Skeletal_muscle",
        ],
    },
    "genetics": {
        "publisher": "NIH National Human Genome Research Institute",
        "license": "public_domain",
        "urls": [
            "https://www.genome.gov/genetics-glossary",
            "https://www.genome.gov/about-genomics/fact-sheets/Deoxyribonucleic-Acid-Fact-Sheet",
            "https://www.genome.gov/genetics-glossary/Mitosis",
            "https://www.genome.gov/genetics-glossary/Meiosis",
            "https://www.genome.gov/genetics-glossary/Allele",
            "https://www.genome.gov/genetics-glossary/Genotype",
            "https://www.genome.gov/genetics-glossary/Phenotype",
            "https://www.genome.gov/genetics-glossary/Mutation",
            "https://medlineplus.gov/genetics/understanding/basics/gene/",
            "https://medlineplus.gov/genetics/understanding/inheritance/inheritancepatterns/",
            "https://en.wikipedia.org/wiki/Mendelian_inheritance",
            "https://en.wikipedia.org/wiki/Punnett_square",
            "https://en.wikipedia.org/wiki/Genetic_linkage",
            "https://en.wikipedia.org/wiki/Hardy%E2%80%93Weinberg_principle",
            "https://en.wikipedia.org/wiki/Pedigree_chart",
            "https://en.wikipedia.org/wiki/Epistasis",
            "https://www.genome.gov/about-genomics/introduction-to-genomics",
            "https://en.wikipedia.org/wiki/Genomics",
        ],
    },
    # 2027 Disease Detectives. 140 pages measured with `ground_event._fetch`, all distinct.
    #
    # The find that matters: the CDC's "Principles of Epidemiology in Public Health Practice"
    # (SS1978), which the rules manual names as the reference for this event, returns 404 on
    # every live `www.cdc.gov/csels/dsepd/ss1978/...` path. All 40 sections were probed. It is
    # complete on `archive.cdc.gov`, and one section alone — lesson 6 section 2 — is 102,306
    # characters working through all thirteen outbreak-investigation steps.
    #
    # Deliberately absent: who.int, which is CC BY-NC-SA 3.0 IGO and so neither a US federal
    # work nor compatible with the licences cleared here; and NCBI Bookshelf, whose
    # epidemiology-relevant open collection is StatPearls at CC BY-NC-ND, failing the same
    # test twice over.
    #
    # One scope item has no source in either pool and no lesson rests on it: Evan's
    # postulates. Zero matches across all 140 documents.
    "forensics_2027": {
        "publisher": "NIST / NIH / Wikipedia contributors",
        "license": "public_domain (federal) and CC-BY-SA 4.0 (Wikipedia, facts with attribution)",
        # Crime Busters 2027 names its evidence exhaustively, and half the score is the
        # qualitative analysis of it: thirteen named solids, six metals, six liquids, the
        # seven recyclable plastics, hair and fibre to the animal/vegetable/synthetic level,
        # paper chromatography with Rf, fingerprint patterns, DNA electropherograms,
        # shoeprints and tyre treads, soil, and spatter. Every named substance has a page
        # here, because an identification item is about THAT substance's properties.
        "urls": [
            "https://en.wikipedia.org/wiki/Acetic_acid",
            "https://en.wikipedia.org/wiki/Acid%E2%80%93base_reaction",
            "https://en.wikipedia.org/wiki/Adsorption",
            "https://en.wikipedia.org/wiki/Alka-Seltzer",
            "https://en.wikipedia.org/wiki/Aluminium",
            "https://en.wikipedia.org/wiki/Ammonia_solution",
            "https://en.wikipedia.org/wiki/Ascorbic_acid",
            "https://en.wikipedia.org/wiki/Automated_fingerprint_identification",
            "https://en.wikipedia.org/wiki/Blood_residue",
            "https://en.wikipedia.org/wiki/Bloodstain_pattern_analysis",
            "https://en.wikipedia.org/wiki/Boiling_point",
            "https://en.wikipedia.org/wiki/Calcium_carbonate",
            "https://en.wikipedia.org/wiki/Calcium_sulfate",
            "https://en.wikipedia.org/wiki/Capillary_action",
            "https://en.wikipedia.org/wiki/Carbon_dioxide",
            "https://en.wikipedia.org/wiki/Catalase",
            "https://en.wikipedia.org/wiki/Cellulose",
            "https://en.wikipedia.org/wiki/Chain_of_custody",
            "https://en.wikipedia.org/wiki/Chemical_property",
            "https://en.wikipedia.org/wiki/Chemical_test",
            "https://en.wikipedia.org/wiki/Chromatography",
            "https://en.wikipedia.org/wiki/Clay",
            "https://en.wikipedia.org/wiki/Combined_DNA_Index_System",
            "https://en.wikipedia.org/wiki/Comparison_microscope",
            "https://en.wikipedia.org/wiki/Copper",
            "https://en.wikipedia.org/wiki/Corn_starch",
            "https://en.wikipedia.org/wiki/Cotton",
            "https://en.wikipedia.org/wiki/Crime_scene",
            "https://en.wikipedia.org/wiki/Crystal",
            "https://en.wikipedia.org/wiki/Cuticle",
            "https://en.wikipedia.org/wiki/Deliquescence",
            "https://en.wikipedia.org/wiki/Density",
            "https://en.wikipedia.org/wiki/Dermatoglyphics",
            "https://en.wikipedia.org/wiki/DNA_profiling",
            "https://en.wikipedia.org/wiki/Dye",
            "https://en.wikipedia.org/wiki/Effervescence",
            "https://en.wikipedia.org/wiki/Electropherogram",
            "https://en.wikipedia.org/wiki/Ferromagnetism",
            "https://en.wikipedia.org/wiki/Fiber",
            "https://en.wikipedia.org/wiki/Filtration",
            "https://en.wikipedia.org/wiki/Fingerprint",
            "https://en.wikipedia.org/wiki/Flame_test",
            "https://en.wikipedia.org/wiki/Flour",
            "https://en.wikipedia.org/wiki/Footprint",
            "https://en.wikipedia.org/wiki/Forensic_footwear_evidence",
            "https://en.wikipedia.org/wiki/Forensic_geology",
            "https://en.wikipedia.org/wiki/Forensic_science",
            "https://en.wikipedia.org/wiki/Fur",
            "https://en.wikipedia.org/wiki/Gait",
            "https://en.wikipedia.org/wiki/Gel_electrophoresis",
            "https://en.wikipedia.org/wiki/Gelatin",
            "https://en.wikipedia.org/wiki/Gypsum",
            "https://en.wikipedia.org/wiki/Hair",
            "https://en.wikipedia.org/wiki/High-density_polyethylene",
            "https://en.wikipedia.org/wiki/Human_hair_color",
            "https://en.wikipedia.org/wiki/Hydrochloric_acid",
            "https://en.wikipedia.org/wiki/Hydrogen_peroxide",
            "https://en.wikipedia.org/wiki/Hygroscopy",
            "https://en.wikipedia.org/wiki/Ink",
            "https://en.wikipedia.org/wiki/Iodine",
            "https://en.wikipedia.org/wiki/Iodine_test",
            "https://en.wikipedia.org/wiki/Iron",
            "https://en.wikipedia.org/wiki/Isopropyl_alcohol",
            "https://en.wikipedia.org/wiki/Keratin",
            "https://en.wikipedia.org/wiki/Laboratory_safety",
            "https://en.wikipedia.org/wiki/Lemon_juice",
            "https://en.wikipedia.org/wiki/Limestone",
            "https://en.wikipedia.org/wiki/Litmus",
            "https://en.wikipedia.org/wiki/Live_scan",
            "https://en.wikipedia.org/wiki/Loam",
            "https://en.wikipedia.org/wiki/Locard%27s_exchange_principle",
            "https://en.wikipedia.org/wiki/Low-density_polyethylene",
            "https://en.wikipedia.org/wiki/Lugol%27s_iodine",
            "https://en.wikipedia.org/wiki/Magnesium",
            "https://en.wikipedia.org/wiki/Magnetism",
            "https://en.wikipedia.org/wiki/Melting_point",
            "https://en.wikipedia.org/wiki/Microscope",
            "https://en.wikipedia.org/wiki/Mixture",
            "https://en.wikipedia.org/wiki/Natural_fiber",
            "https://en.wikipedia.org/wiki/Neutralization_(chemistry)",
            "https://en.wikipedia.org/wiki/Nylon",
            "https://en.wikipedia.org/wiki/Optical_microscope",
            "https://en.wikipedia.org/wiki/Paper_chromatography",
            "https://en.wikipedia.org/wiki/Personal_protective_equipment",
            "https://en.wikipedia.org/wiki/PH",
            "https://en.wikipedia.org/wiki/PH_indicator",
            "https://en.wikipedia.org/wiki/Physical_property",
            "https://en.wikipedia.org/wiki/Plastic",
            "https://en.wikipedia.org/wiki/Polarity_(chemistry)",
            "https://en.wikipedia.org/wiki/Poly(methyl_methacrylate)",
            "https://en.wikipedia.org/wiki/Polyester",
            "https://en.wikipedia.org/wiki/Polyethylene_terephthalate",
            "https://en.wikipedia.org/wiki/Polymer",
            "https://en.wikipedia.org/wiki/Polymerase_chain_reaction",
            "https://en.wikipedia.org/wiki/Polypropylene",
            "https://en.wikipedia.org/wiki/Polystyrene",
            "https://en.wikipedia.org/wiki/Polyvinyl_chloride",
            "https://en.wikipedia.org/wiki/Qualitative_inorganic_analysis",
            "https://en.wikipedia.org/wiki/Reactivity_series",
            "https://en.wikipedia.org/wiki/Resin_identification_code",
            "https://en.wikipedia.org/wiki/Retardation_factor",
            "https://en.wikipedia.org/wiki/Safety_data_sheet",
            "https://en.wikipedia.org/wiki/Sand",
            "https://en.wikipedia.org/wiki/Separation_process",
            "https://en.wikipedia.org/wiki/Short_tandem_repeat",
            "https://en.wikipedia.org/wiki/Silicon_dioxide",
            "https://en.wikipedia.org/wiki/Silt",
            "https://en.wikipedia.org/wiki/Single_displacement_reaction",
            "https://en.wikipedia.org/wiki/Sodium_acetate",
            "https://en.wikipedia.org/wiki/Sodium_bicarbonate",
            "https://en.wikipedia.org/wiki/Sodium_chloride",
            "https://en.wikipedia.org/wiki/Soil",
            "https://en.wikipedia.org/wiki/Soil_horizon",
            "https://en.wikipedia.org/wiki/Soil_texture",
            "https://en.wikipedia.org/wiki/Solubility",
            "https://en.wikipedia.org/wiki/Solubility_chart",
            "https://en.wikipedia.org/wiki/Solvent",
            "https://en.wikipedia.org/wiki/Starch",
            "https://en.wikipedia.org/wiki/Sucrose",
            "https://en.wikipedia.org/wiki/Surface_tension",
            "https://en.wikipedia.org/wiki/Synthetic_fiber",
            "https://en.wikipedia.org/wiki/Thermoplastic",
            "https://en.wikipedia.org/wiki/Thin-layer_chromatography",
            "https://en.wikipedia.org/wiki/Tin",
            "https://en.wikipedia.org/wiki/Tire",
            "https://en.wikipedia.org/wiki/Trace_evidence",
            "https://en.wikipedia.org/wiki/Tread",
            "https://en.wikipedia.org/wiki/Vinegar",
            "https://en.wikipedia.org/wiki/Viscosity",
            "https://en.wikipedia.org/wiki/Vitamin_C",
            "https://en.wikipedia.org/wiki/Water",
            "https://en.wikipedia.org/wiki/Wool",
            "https://en.wikipedia.org/wiki/Yeast",
            "https://en.wikipedia.org/wiki/Zinc",
            "https://www.genome.gov/genetics-glossary/Polymerase-Chain-Reaction",
            "https://www.nist.gov/forensic-science",
            "https://www.nist.gov/forensic-science/dna-and-biological-evidence",
        ],
    },
    "genetics_2027": {
        "publisher": "NIH NHGRI / MedlinePlus / Wikipedia contributors",
        "license": "public_domain (federal) and CC-BY-SA 4.0 (Wikipedia, facts with attribution)",
        # Assembled against the 2027 Division B Heredity scope, which the manual calls
        # exhaustive: Mendelian genetics and pedigrees; mitosis and meiosis and karyotypes;
        # the molecular biology of DNA including replication, chromatin organisation, mutation
        # classes and nucleotide excision repair; the central dogma through transcription,
        # RNA maturation, translation and the lac and trp operons; Hardy-Weinberg and the
        # forces that violate it; and PCR and Sanger sequencing. The `genetics` domain that
        # `heredity` used to reach holds eighteen pages and grounded 350 claims for a
        # thirty-two lesson course.
        "urls": [
            "https://en.wikipedia.org/wiki/ABO_blood_group_system",
            "https://en.wikipedia.org/wiki/Activator_(genetics)",
            "https://en.wikipedia.org/wiki/Allele",
            "https://en.wikipedia.org/wiki/Allele_frequency",
            "https://en.wikipedia.org/wiki/Aminoacyl-tRNA_synthetase",
            "https://en.wikipedia.org/wiki/Anaphase",
            "https://en.wikipedia.org/wiki/Aneuploidy",
            "https://en.wikipedia.org/wiki/Anticodon",
            "https://en.wikipedia.org/wiki/Autosome",
            "https://en.wikipedia.org/wiki/Base_pair",
            "https://en.wikipedia.org/wiki/Binomial_distribution",
            "https://en.wikipedia.org/wiki/Cell_cycle",
            "https://en.wikipedia.org/wiki/Centimorgan",
            "https://en.wikipedia.org/wiki/Central_dogma_of_molecular_biology",
            "https://en.wikipedia.org/wiki/Centromere",
            "https://en.wikipedia.org/wiki/Chargaff%27s_rules",
            "https://en.wikipedia.org/wiki/Chi-squared_test",
            "https://en.wikipedia.org/wiki/Chiasma_(genetics)",
            "https://en.wikipedia.org/wiki/Chromatin",
            "https://en.wikipedia.org/wiki/Chromosomal_crossover",
            "https://en.wikipedia.org/wiki/Chromosomal_inversion",
            "https://en.wikipedia.org/wiki/Chromosomal_translocation",
            "https://en.wikipedia.org/wiki/Chromosome",
            "https://en.wikipedia.org/wiki/Codominance",
            "https://en.wikipedia.org/wiki/Complementation_(genetics)",
            "https://en.wikipedia.org/wiki/Cytokinesis",
            "https://en.wikipedia.org/wiki/Deletion_(genetics)",
            "https://en.wikipedia.org/wiki/Deoxyribose",
            "https://en.wikipedia.org/wiki/Dideoxynucleotide",
            "https://en.wikipedia.org/wiki/Dihybrid_cross",
            "https://en.wikipedia.org/wiki/Directionality_(molecular_biology)",
            "https://en.wikipedia.org/wiki/DNA",
            "https://en.wikipedia.org/wiki/DNA_ligase",
            "https://en.wikipedia.org/wiki/DNA_polymerase",
            "https://en.wikipedia.org/wiki/DNA_repair",
            "https://en.wikipedia.org/wiki/DNA_replication",
            "https://en.wikipedia.org/wiki/DNA_sequencing",
            "https://en.wikipedia.org/wiki/Dominance_(genetics)",
            "https://en.wikipedia.org/wiki/Down_syndrome",
            "https://en.wikipedia.org/wiki/Epistasis",
            "https://en.wikipedia.org/wiki/Euchromatin",
            "https://en.wikipedia.org/wiki/Exon",
            "https://en.wikipedia.org/wiki/Fitness_(biology)",
            "https://en.wikipedia.org/wiki/Five-prime_cap",
            "https://en.wikipedia.org/wiki/Founder_effect",
            "https://en.wikipedia.org/wiki/Frameshift_mutation",
            "https://en.wikipedia.org/wiki/Gel_electrophoresis",
            "https://en.wikipedia.org/wiki/Gene",
            "https://en.wikipedia.org/wiki/Gene_duplication",
            "https://en.wikipedia.org/wiki/Gene_flow",
            "https://en.wikipedia.org/wiki/Genetic_code",
            "https://en.wikipedia.org/wiki/Genetic_disorder",
            "https://en.wikipedia.org/wiki/Genetic_drift",
            "https://en.wikipedia.org/wiki/Genetic_linkage",
            "https://en.wikipedia.org/wiki/Genetic_recombination",
            "https://en.wikipedia.org/wiki/Genotype",
            "https://en.wikipedia.org/wiki/Gregor_Mendel",
            "https://en.wikipedia.org/wiki/Hardy%E2%80%93Weinberg_principle",
            "https://en.wikipedia.org/wiki/Helicase",
            "https://en.wikipedia.org/wiki/Heritability",
            "https://en.wikipedia.org/wiki/Heterochromatin",
            "https://en.wikipedia.org/wiki/Histone",
            "https://en.wikipedia.org/wiki/Homologous_chromosome",
            "https://en.wikipedia.org/wiki/Incomplete_dominance",
            "https://en.wikipedia.org/wiki/Insertion_(genetics)",
            "https://en.wikipedia.org/wiki/Interphase",
            "https://en.wikipedia.org/wiki/Intron",
            "https://en.wikipedia.org/wiki/Karyotype",
            "https://en.wikipedia.org/wiki/Kinetochore",
            "https://en.wikipedia.org/wiki/Klinefelter_syndrome",
            "https://en.wikipedia.org/wiki/Lac_operon",
            "https://en.wikipedia.org/wiki/Law_of_segregation",
            "https://en.wikipedia.org/wiki/Locus_(genetics)",
            "https://en.wikipedia.org/wiki/Meiosis",
            "https://en.wikipedia.org/wiki/Mendelian_inheritance",
            "https://en.wikipedia.org/wiki/Messenger_RNA",
            "https://en.wikipedia.org/wiki/Metaphase",
            "https://en.wikipedia.org/wiki/Missense_mutation",
            "https://en.wikipedia.org/wiki/Mitosis",
            "https://en.wikipedia.org/wiki/Monohybrid_cross",
            "https://en.wikipedia.org/wiki/Multiple_alleles",
            "https://en.wikipedia.org/wiki/Mutation",
            "https://en.wikipedia.org/wiki/Natural_selection",
            "https://en.wikipedia.org/wiki/Nondisjunction",
            "https://en.wikipedia.org/wiki/Nonsense_mutation",
            "https://en.wikipedia.org/wiki/Nucleic_acid_double_helix",
            "https://en.wikipedia.org/wiki/Nucleobase",
            "https://en.wikipedia.org/wiki/Nucleosome",
            "https://en.wikipedia.org/wiki/Nucleotide",
            "https://en.wikipedia.org/wiki/Nucleotide_excision_repair",
            "https://en.wikipedia.org/wiki/Okazaki_fragments",
            "https://en.wikipedia.org/wiki/Operon",
            "https://en.wikipedia.org/wiki/Pedigree_chart",
            "https://en.wikipedia.org/wiki/Peptide_bond",
            "https://en.wikipedia.org/wiki/Phenotype",
            "https://en.wikipedia.org/wiki/Phosphodiester_bond",
            "https://en.wikipedia.org/wiki/Plasmid",
            "https://en.wikipedia.org/wiki/Pleiotropy",
            "https://en.wikipedia.org/wiki/Ploidy",
            "https://en.wikipedia.org/wiki/Point_mutation",
            "https://en.wikipedia.org/wiki/Polyadenylation",
            "https://en.wikipedia.org/wiki/Polygene",
            "https://en.wikipedia.org/wiki/Polymerase_chain_reaction",
            "https://en.wikipedia.org/wiki/Population_bottleneck",
            "https://en.wikipedia.org/wiki/Population_genetics",
            "https://en.wikipedia.org/wiki/Primase",
            "https://en.wikipedia.org/wiki/Primer_(molecular_biology)",
            "https://en.wikipedia.org/wiki/Probability",
            "https://en.wikipedia.org/wiki/Product_rule",
            "https://en.wikipedia.org/wiki/Promoter_(genetics)",
            "https://en.wikipedia.org/wiki/Proofreading_(biology)",
            "https://en.wikipedia.org/wiki/Prophase",
            "https://en.wikipedia.org/wiki/Protein_primary_structure",
            "https://en.wikipedia.org/wiki/Punnett_square",
            "https://en.wikipedia.org/wiki/Pyrimidine_dimer",
            "https://en.wikipedia.org/wiki/Quantitative_trait_locus",
            "https://en.wikipedia.org/wiki/Replication_fork",
            "https://en.wikipedia.org/wiki/Repressor",
            "https://en.wikipedia.org/wiki/Restriction_enzyme",
            "https://en.wikipedia.org/wiki/Ribosomal_RNA",
            "https://en.wikipedia.org/wiki/Ribosome",
            "https://en.wikipedia.org/wiki/RNA_polymerase",
            "https://en.wikipedia.org/wiki/RNA_splicing",
            "https://en.wikipedia.org/wiki/Sanger_sequencing",
            "https://en.wikipedia.org/wiki/Semiconservative_replication",
            "https://en.wikipedia.org/wiki/Sex_linkage",
            "https://en.wikipedia.org/wiki/Silent_mutation",
            "https://en.wikipedia.org/wiki/Sister_chromatids",
            "https://en.wikipedia.org/wiki/Spindle_apparatus",
            "https://en.wikipedia.org/wiki/Start_codon",
            "https://en.wikipedia.org/wiki/Stop_codon",
            "https://en.wikipedia.org/wiki/Synapsis",
            "https://en.wikipedia.org/wiki/Taq_polymerase",
            "https://en.wikipedia.org/wiki/Telomere",
            "https://en.wikipedia.org/wiki/Telophase",
            "https://en.wikipedia.org/wiki/Test_cross",
            "https://en.wikipedia.org/wiki/Thermal_cycler",
            "https://en.wikipedia.org/wiki/Thermus_aquaticus",
            "https://en.wikipedia.org/wiki/Topoisomerase",
            "https://en.wikipedia.org/wiki/Transcription_(biology)",
            "https://en.wikipedia.org/wiki/Transcription_factor",
            "https://en.wikipedia.org/wiki/Transfer_RNA",
            "https://en.wikipedia.org/wiki/Translation_(biology)",
            "https://en.wikipedia.org/wiki/Trp_operon",
            "https://en.wikipedia.org/wiki/Turner_syndrome",
            "https://en.wikipedia.org/wiki/Ultraviolet",
            "https://en.wikipedia.org/wiki/X-linked_dominant_inheritance",
            "https://en.wikipedia.org/wiki/X-linked_recessive_inheritance",
            "https://en.wikipedia.org/wiki/Xeroderma_pigmentosum",
            "https://en.wikipedia.org/wiki/Y_linkage",
            "https://en.wikipedia.org/wiki/Zygosity",
            "https://medlineplus.gov/genetics/understanding/basics/chromosome/",
            "https://medlineplus.gov/genetics/understanding/basics/dna/",
            "https://medlineplus.gov/genetics/understanding/basics/gene/",
            "https://medlineplus.gov/genetics/understanding/basics/noncodingdna/",
            "https://medlineplus.gov/genetics/understanding/inheritance/inheritancepatterns/",
            "https://medlineplus.gov/genetics/understanding/inheritance/penetranceexpressivity/",
            "https://medlineplus.gov/genetics/understanding/mutationsanddisorders/genemutation/",
            "https://medlineplus.gov/genetics/understanding/mutationsanddisorders/possiblemutations/",
            "https://medlineplus.gov/genetics/understanding/traits/",
            "https://www.genome.gov/about-genomics/fact-sheets/Chromosomes-Fact-Sheet",
            "https://www.genome.gov/about-genomics/fact-sheets/Deoxyribonucleic-Acid-Fact-Sheet",
            "https://www.genome.gov/about-genomics/fact-sheets/DNA-Sequencing-Fact-Sheet",
            "https://www.genome.gov/about-genomics/fact-sheets/Genetic-Mapping-Fact-Sheet",
            "https://www.genome.gov/about-genomics/fact-sheets/Polymerase-Chain-Reaction-Fact-Sheet",
            "https://www.genome.gov/about-genomics/introduction-to-genomics",
            "https://www.genome.gov/genetics-glossary",
            "https://www.genome.gov/genetics-glossary/Allele",
            "https://www.genome.gov/genetics-glossary/Autosomal-Dominant",
            "https://www.genome.gov/genetics-glossary/Base-Pair",
            "https://www.genome.gov/genetics-glossary/Chromatin",
            "https://www.genome.gov/genetics-glossary/Chromosome",
            "https://www.genome.gov/genetics-glossary/Codon",
            "https://www.genome.gov/genetics-glossary/Deletion",
            "https://www.genome.gov/genetics-glossary/DNA-Replication",
            "https://www.genome.gov/genetics-glossary/DNA-Sequencing",
            "https://www.genome.gov/genetics-glossary/Dominant",
            "https://www.genome.gov/genetics-glossary/Double-Helix",
            "https://www.genome.gov/genetics-glossary/Exon",
            "https://www.genome.gov/genetics-glossary/Gene",
            "https://www.genome.gov/genetics-glossary/Genotype",
            "https://www.genome.gov/genetics-glossary/Heterozygous",
            "https://www.genome.gov/genetics-glossary/Histone",
            "https://www.genome.gov/genetics-glossary/Homozygous",
            "https://www.genome.gov/genetics-glossary/Insertion",
            "https://www.genome.gov/genetics-glossary/Intron",
            "https://www.genome.gov/genetics-glossary/Karyotype",
            "https://www.genome.gov/genetics-glossary/Meiosis",
            "https://www.genome.gov/genetics-glossary/Messenger-RNA-mRNA",
            "https://www.genome.gov/genetics-glossary/Mitosis",
            "https://www.genome.gov/genetics-glossary/Mutation",
            "https://www.genome.gov/genetics-glossary/Nucleotide",
            "https://www.genome.gov/genetics-glossary/Pedigree",
            "https://www.genome.gov/genetics-glossary/Phenotype",
            "https://www.genome.gov/genetics-glossary/Plasmid",
            "https://www.genome.gov/genetics-glossary/Polymerase-Chain-Reaction",
            "https://www.genome.gov/genetics-glossary/Recessive",
            "https://www.genome.gov/genetics-glossary/Ribosome",
            "https://www.genome.gov/genetics-glossary/Telomere",
            "https://www.genome.gov/genetics-glossary/Transcription",
            "https://www.genome.gov/genetics-glossary/Transfer-RNA",
            "https://www.genome.gov/genetics-glossary/Translation",
            "https://www.genome.gov/genetics-glossary/Translocation",
            "https://www.genome.gov/genetics-glossary/X-Linked",
        ],
    },
    "methodology_2027": {
        "publisher": "NIST / Wikipedia contributors",
        "license": "public_domain (federal) and CC-BY-SA 4.0 (Wikipedia, facts with attribution)",
        # Experimental Design and Write It Do It are the two events with NO written exam:
        # one is scored by a checklist against a report written on site, the other by a
        # rubric against an object somebody else built from your description. So this domain
        # is built from what those two instruments actually score — for Experimental Design,
        # every line of the official checklist (problem statement, hypothesis, the three
        # variable kinds, procedure, data table, graph, the statistics, claim/evidence/
        # reasoning, experimental error, limitations); for Write It Do It, the vocabulary a
        # description has to be precise in (orientation, relative position, reference frame,
        # shape, dimension, colour, sequence) and what makes technical prose unambiguous.
        "urls": [
            "https://en.wikipedia.org/wiki/Abbreviation",
            "https://en.wikipedia.org/wiki/Accuracy_and_precision",
            "https://en.wikipedia.org/wiki/Acronym",
            "https://en.wikipedia.org/wiki/Adjacency",
            "https://en.wikipedia.org/wiki/Ambiguity",
            "https://en.wikipedia.org/wiki/Angle",
            "https://en.wikipedia.org/wiki/Approximation_error",
            "https://en.wikipedia.org/wiki/Argument",
            "https://en.wikipedia.org/wiki/Arithmetic_mean",
            "https://en.wikipedia.org/wiki/Average",
            "https://en.wikipedia.org/wiki/Axis_(mathematics)",
            "https://en.wikipedia.org/wiki/Bar_chart",
            "https://en.wikipedia.org/wiki/Bias",
            "https://en.wikipedia.org/wiki/Blinded_experiment",
            "https://en.wikipedia.org/wiki/Cartesian_coordinate_system",
            "https://en.wikipedia.org/wiki/Centroid",
            "https://en.wikipedia.org/wiki/Chart",
            "https://en.wikipedia.org/wiki/Color_term",
            "https://en.wikipedia.org/wiki/Colour",
            "https://en.wikipedia.org/wiki/Confounding",
            "https://en.wikipedia.org/wiki/Controlling_for_a_variable",
            "https://en.wikipedia.org/wiki/Conversion_of_units",
            "https://en.wikipedia.org/wiki/Correlation",
            "https://en.wikipedia.org/wiki/Correlation_does_not_imply_causation",
            "https://en.wikipedia.org/wiki/Cube",
            "https://en.wikipedia.org/wiki/Curve_fitting",
            "https://en.wikipedia.org/wiki/Cylinder",
            "https://en.wikipedia.org/wiki/Data",
            "https://en.wikipedia.org/wiki/Deductive_reasoning",
            "https://en.wikipedia.org/wiki/Degree_(angle)",
            "https://en.wikipedia.org/wiki/Dependent_and_independent_variables",
            "https://en.wikipedia.org/wiki/Descriptive_statistics",
            "https://en.wikipedia.org/wiki/Design_of_experiments",
            "https://en.wikipedia.org/wiki/Diameter",
            "https://en.wikipedia.org/wiki/Dimensional_analysis",
            "https://en.wikipedia.org/wiki/Enumeration",
            "https://en.wikipedia.org/wiki/Evidence",
            "https://en.wikipedia.org/wiki/Experiment",
            "https://en.wikipedia.org/wiki/Extrapolation",
            "https://en.wikipedia.org/wiki/Falsifiability",
            "https://en.wikipedia.org/wiki/Frame_of_reference",
            "https://en.wikipedia.org/wiki/Geometric_shape",
            "https://en.wikipedia.org/wiki/Graph_of_a_function",
            "https://en.wikipedia.org/wiki/Histogram",
            "https://en.wikipedia.org/wiki/Hypothesis",
            "https://en.wikipedia.org/wiki/Imperative_mood",
            "https://en.wikipedia.org/wiki/Inductive_reasoning",
            "https://en.wikipedia.org/wiki/Inference",
            "https://en.wikipedia.org/wiki/Instruction_manual",
            "https://en.wikipedia.org/wiki/International_System_of_Units",
            "https://en.wikipedia.org/wiki/Interpolation",
            "https://en.wikipedia.org/wiki/Lab_notebook",
            "https://en.wikipedia.org/wiki/Length",
            "https://en.wikipedia.org/wiki/Level_of_measurement",
            "https://en.wikipedia.org/wiki/Line_chart",
            "https://en.wikipedia.org/wiki/Linear_regression",
            "https://en.wikipedia.org/wiki/Logical_reasoning",
            "https://en.wikipedia.org/wiki/Mean",
            "https://en.wikipedia.org/wiki/Measurement",
            "https://en.wikipedia.org/wiki/Median",
            "https://en.wikipedia.org/wiki/Metric_prefix",
            "https://en.wikipedia.org/wiki/Midpoint",
            "https://en.wikipedia.org/wiki/Mode_(statistics)",
            "https://en.wikipedia.org/wiki/Null_hypothesis",
            "https://en.wikipedia.org/wiki/Observational_error",
            "https://en.wikipedia.org/wiki/Observational_study",
            "https://en.wikipedia.org/wiki/Observer-expectancy_effect",
            "https://en.wikipedia.org/wiki/Operational_definition",
            "https://en.wikipedia.org/wiki/Orientation_(geometry)",
            "https://en.wikipedia.org/wiki/Outlier",
            "https://en.wikipedia.org/wiki/Parallel_(geometry)",
            "https://en.wikipedia.org/wiki/Peer_review",
            "https://en.wikipedia.org/wiki/Percentage",
            "https://en.wikipedia.org/wiki/Perpendicular",
            "https://en.wikipedia.org/wiki/Plain_language",
            "https://en.wikipedia.org/wiki/Prism_(geometry)",
            "https://en.wikipedia.org/wiki/Procedural_knowledge",
            "https://en.wikipedia.org/wiki/Propagation_of_uncertainty",
            "https://en.wikipedia.org/wiki/Proportionality_(mathematics)",
            "https://en.wikipedia.org/wiki/Qualitative_property",
            "https://en.wikipedia.org/wiki/Quantitative_research",
            "https://en.wikipedia.org/wiki/Radius",
            "https://en.wikipedia.org/wiki/Randomization",
            "https://en.wikipedia.org/wiki/Range_(statistics)",
            "https://en.wikipedia.org/wiki/Ratio",
            "https://en.wikipedia.org/wiki/Readability",
            "https://en.wikipedia.org/wiki/Rectangle",
            "https://en.wikipedia.org/wiki/Reflection_(mathematics)",
            "https://en.wikipedia.org/wiki/Relative_direction",
            "https://en.wikipedia.org/wiki/Repeatability",
            "https://en.wikipedia.org/wiki/Replication_(statistics)",
            "https://en.wikipedia.org/wiki/Reproducibility",
            "https://en.wikipedia.org/wiki/Rotation",
            "https://en.wikipedia.org/wiki/Sample_size_determination",
            "https://en.wikipedia.org/wiki/Scatter_plot",
            "https://en.wikipedia.org/wiki/Scientific_control",
            "https://en.wikipedia.org/wiki/Scientific_law",
            "https://en.wikipedia.org/wiki/Scientific_method",
            "https://en.wikipedia.org/wiki/Scientific_notation",
            "https://en.wikipedia.org/wiki/Scientific_theory",
            "https://en.wikipedia.org/wiki/Selection_bias",
            "https://en.wikipedia.org/wiki/Sequence",
            "https://en.wikipedia.org/wiki/Significant_figures",
            "https://en.wikipedia.org/wiki/Slope",
            "https://en.wikipedia.org/wiki/Spatial_relation",
            "https://en.wikipedia.org/wiki/Specification_(technical_standard)",
            "https://en.wikipedia.org/wiki/Sphere",
            "https://en.wikipedia.org/wiki/Standard_deviation",
            "https://en.wikipedia.org/wiki/Statistical_dispersion",
            "https://en.wikipedia.org/wiki/Symmetry",
            "https://en.wikipedia.org/wiki/Table_(information)",
            "https://en.wikipedia.org/wiki/Technical_communication",
            "https://en.wikipedia.org/wiki/Technical_writing",
            "https://en.wikipedia.org/wiki/Translation_(geometry)",
            "https://en.wikipedia.org/wiki/Triangle",
            "https://en.wikipedia.org/wiki/Units_of_measurement",
            "https://en.wikipedia.org/wiki/Variance",
            "https://en.wikipedia.org/wiki/Vertical_and_horizontal",
            "https://www.nist.gov/pml/owm/metric-si-prefixes",
            "https://www.nist.gov/pml/owm/metric-si/si-units",
        ],
    },
    "remote_sensing_2027": {
        "publisher": "USGS / NASA / NOAA / Wikipedia contributors",
        "license": "public_domain (federal) and CC-BY-SA 4.0 (Wikipedia, facts with attribution)",
        # Remote Sensing 2027 is "Observable Earth" and the manual bounds it tightly: the
        # five named equations (only Wien, the wave equation and radar altimetry range may
        # be tested quantitatively), the passive and active sensor types, the six orbit
        # classes, the four resolution kinds, and interpretation from a CLOSED list of
        # platforms — Landsat 5-9 with TM/ETM/OLI, Sentinel-1A/1B and 2A/2B, Terra's MODIS
        # and ASTER, SRTM, ECOSTRESS and GOES. Each of those has a page here; the old
        # `remote_sensing` domain held fourteen pages and named three of them.
        "urls": [
            "https://en.wikipedia.org/wiki/Absorption_(electromagnetic_radiation)",
            "https://en.wikipedia.org/wiki/Advanced_Spaceborne_Thermal_Emission_and_Reflection_Radiometer",
            "https://en.wikipedia.org/wiki/Aerial_photography",
            "https://en.wikipedia.org/wiki/Aerosol",
            "https://en.wikipedia.org/wiki/Albedo",
            "https://en.wikipedia.org/wiki/Altimeter",
            "https://en.wikipedia.org/wiki/Backscatter",
            "https://en.wikipedia.org/wiki/Black-body_radiation",
            "https://en.wikipedia.org/wiki/Cardinal_direction",
            "https://en.wikipedia.org/wiki/Contour_line",
            "https://en.wikipedia.org/wiki/Deforestation",
            "https://en.wikipedia.org/wiki/Digital_elevation_model",
            "https://en.wikipedia.org/wiki/Drainage_system_(geomorphology)",
            "https://en.wikipedia.org/wiki/Earth_observation_satellite",
            "https://en.wikipedia.org/wiki/ECOSTRESS",
            "https://en.wikipedia.org/wiki/Electromagnetic_radiation",
            "https://en.wikipedia.org/wiki/Electromagnetic_spectrum",
            "https://en.wikipedia.org/wiki/Elevation",
            "https://en.wikipedia.org/wiki/Emissivity",
            "https://en.wikipedia.org/wiki/Enhanced_Thematic_Mapper_Plus",
            "https://en.wikipedia.org/wiki/False_color",
            "https://en.wikipedia.org/wiki/Flood",
            "https://en.wikipedia.org/wiki/Fluvial_processes",
            "https://en.wikipedia.org/wiki/Frequency",
            "https://en.wikipedia.org/wiki/Geographic_coordinate_system",
            "https://en.wikipedia.org/wiki/Geostationary_Operational_Environmental_Satellite",
            "https://en.wikipedia.org/wiki/Geostationary_orbit",
            "https://en.wikipedia.org/wiki/Geosynchronous_orbit",
            "https://en.wikipedia.org/wiki/Glacial_motion",
            "https://en.wikipedia.org/wiki/Glacier",
            "https://en.wikipedia.org/wiki/GOES",
            "https://en.wikipedia.org/wiki/Grade_(slope)",
            "https://en.wikipedia.org/wiki/Grayscale",
            "https://en.wikipedia.org/wiki/Habitat_destruction",
            "https://en.wikipedia.org/wiki/High_Earth_orbit",
            "https://en.wikipedia.org/wiki/Hyperspectral_imaging",
            "https://en.wikipedia.org/wiki/Image_resolution",
            "https://en.wikipedia.org/wiki/Image_sensor",
            "https://en.wikipedia.org/wiki/Infrared",
            "https://en.wikipedia.org/wiki/Interferometric_synthetic-aperture_radar",
            "https://en.wikipedia.org/wiki/Inverse-square_law",
            "https://en.wikipedia.org/wiki/Irradiance",
            "https://en.wikipedia.org/wiki/Kepler%27s_laws_of_planetary_motion",
            "https://en.wikipedia.org/wiki/Land_cover",
            "https://en.wikipedia.org/wiki/Land_use",
            "https://en.wikipedia.org/wiki/Landsat_5",
            "https://en.wikipedia.org/wiki/Landsat_7",
            "https://en.wikipedia.org/wiki/Landsat_8",
            "https://en.wikipedia.org/wiki/Landsat_9",
            "https://en.wikipedia.org/wiki/Landsat_program",
            "https://en.wikipedia.org/wiki/Landslide",
            "https://en.wikipedia.org/wiki/Latitude",
            "https://en.wikipedia.org/wiki/Lidar",
            "https://en.wikipedia.org/wiki/Light",
            "https://en.wikipedia.org/wiki/Longitude",
            "https://en.wikipedia.org/wiki/Low_Earth_orbit",
            "https://en.wikipedia.org/wiki/Map_legend",
            "https://en.wikipedia.org/wiki/Meander",
            "https://en.wikipedia.org/wiki/Medium_Earth_orbit",
            "https://en.wikipedia.org/wiki/Mie_scattering",
            "https://en.wikipedia.org/wiki/Moderate_Resolution_Imaging_Spectroradiometer",
            "https://en.wikipedia.org/wiki/Multispectral_image",
            "https://en.wikipedia.org/wiki/Near-infrared_spectroscopy",
            "https://en.wikipedia.org/wiki/Normalized_difference_vegetation_index",
            "https://en.wikipedia.org/wiki/Operational_Land_Imager",
            "https://en.wikipedia.org/wiki/Orbit",
            "https://en.wikipedia.org/wiki/Orbital_period",
            "https://en.wikipedia.org/wiki/Orthophoto",
            "https://en.wikipedia.org/wiki/Pixel",
            "https://en.wikipedia.org/wiki/Planck%27s_law",
            "https://en.wikipedia.org/wiki/Polar_orbit",
            "https://en.wikipedia.org/wiki/Polarization_(waves)",
            "https://en.wikipedia.org/wiki/Push_broom_scanner",
            "https://en.wikipedia.org/wiki/Radar",
            "https://en.wikipedia.org/wiki/Radar_altimeter",
            "https://en.wikipedia.org/wiki/Radiance",
            "https://en.wikipedia.org/wiki/Radiometer",
            "https://en.wikipedia.org/wiki/Radiometric_resolution",
            "https://en.wikipedia.org/wiki/Rayleigh_scattering",
            "https://en.wikipedia.org/wiki/Reflectance",
            "https://en.wikipedia.org/wiki/Reflection_(physics)",
            "https://en.wikipedia.org/wiki/Refraction",
            "https://en.wikipedia.org/wiki/Remote_sensing",
            "https://en.wikipedia.org/wiki/RGB_color_model",
            "https://en.wikipedia.org/wiki/Satellite",
            "https://en.wikipedia.org/wiki/Scale_(map)",
            "https://en.wikipedia.org/wiki/Scattering",
            "https://en.wikipedia.org/wiki/Sentinel-1",
            "https://en.wikipedia.org/wiki/Sentinel-2",
            "https://en.wikipedia.org/wiki/Shuttle_Radar_Topography_Mission",
            "https://en.wikipedia.org/wiki/Signal-to-noise_ratio",
            "https://en.wikipedia.org/wiki/Snell%27s_law",
            "https://en.wikipedia.org/wiki/Spatial_resolution",
            "https://en.wikipedia.org/wiki/Spectral_resolution",
            "https://en.wikipedia.org/wiki/Speed_of_light",
            "https://en.wikipedia.org/wiki/Statistical_classification",
            "https://en.wikipedia.org/wiki/Stefan%E2%80%93Boltzmann_law",
            "https://en.wikipedia.org/wiki/Stream",
            "https://en.wikipedia.org/wiki/Subsidence",
            "https://en.wikipedia.org/wiki/Sun-synchronous_orbit",
            "https://en.wikipedia.org/wiki/Supervised_learning",
            "https://en.wikipedia.org/wiki/Surface_temperature",
            "https://en.wikipedia.org/wiki/Synthetic-aperture_radar",
            "https://en.wikipedia.org/wiki/Temporal_resolution",
            "https://en.wikipedia.org/wiki/Terra_(satellite)",
            "https://en.wikipedia.org/wiki/Terrain",
            "https://en.wikipedia.org/wiki/Thematic_Mapper",
            "https://en.wikipedia.org/wiki/Thermographic_camera",
            "https://en.wikipedia.org/wiki/Topographic_map",
            "https://en.wikipedia.org/wiki/Ultraviolet",
            "https://en.wikipedia.org/wiki/Unsupervised_learning",
            "https://en.wikipedia.org/wiki/Urbanization",
            "https://en.wikipedia.org/wiki/Visible_spectrum",
            "https://en.wikipedia.org/wiki/Volcano",
            "https://en.wikipedia.org/wiki/Wavelength",
            "https://en.wikipedia.org/wiki/Whisk_broom_scanner",
            "https://en.wikipedia.org/wiki/Wien%27s_displacement_law",
            "https://en.wikipedia.org/wiki/Wildfire",
            "https://oceanservice.noaa.gov/facts/remotesensing.html",
            "https://science.nasa.gov/earth/",
            "https://science.nasa.gov/mission/ecostress/",
            "https://science.nasa.gov/mission/terra/",
            "https://www.usgs.gov/centers/eros/science/national-land-cover-database",
            "https://www.usgs.gov/landsat-missions/landsat-collection-2",
            "https://www.usgs.gov/landsat-missions/landsat-normalized-difference-vegetation-index",
            "https://www.usgs.gov/landsat-missions/landsat-satellite-missions",
        ],
    },
    "cryptography_2027": {
        "publisher": "Wikipedia contributors",
        "license": "public_domain (federal) and CC-BY-SA 4.0 (Wikipedia, facts with attribution)",
        # Codebusters 2027 lists its cipher types exhaustively and the Division B regional
        # set is: Aristocrats and Patristocrats on K1 or random alphabets, Baconian,
        # Xenocrypt in Spanish, Fractionated Morse, cryptarithms, Porta, complete columnar
        # transposition, Nihilist, Atbash, Caesar, the 5x5 checkerboard and homophonic
        # substitution. The `cryptography` domain holds thirteen pages and names four of
        # them. Two of the manual's ciphers have no article of their own — Porta is covered
        # through della Porta and the tabula recta, Fractionated Morse through Morse code
        # and the fractionating ciphers that share its construction.
        "urls": [
            "https://en.wikipedia.org/wiki/Addition",
            "https://en.wikipedia.org/wiki/ADFGVX_cipher",
            "https://en.wikipedia.org/wiki/Affine_cipher",
            "https://en.wikipedia.org/wiki/Al-Kindi",
            "https://en.wikipedia.org/wiki/Alan_Turing",
            "https://en.wikipedia.org/wiki/Alberti_cipher",
            "https://en.wikipedia.org/wiki/Alphabet",
            "https://en.wikipedia.org/wiki/American_Cryptogram_Association",
            "https://en.wikipedia.org/wiki/Anagram",
            "https://en.wikipedia.org/wiki/Atbash",
            "https://en.wikipedia.org/wiki/Autokey_cipher",
            "https://en.wikipedia.org/wiki/Bacon%27s_cipher",
            "https://en.wikipedia.org/wiki/Beale_ciphers",
            "https://en.wikipedia.org/wiki/Bifid_cipher",
            "https://en.wikipedia.org/wiki/Bigram",
            "https://en.wikipedia.org/wiki/Bletchley_Park",
            "https://en.wikipedia.org/wiki/Book_cipher",
            "https://en.wikipedia.org/wiki/Brute-force_attack",
            "https://en.wikipedia.org/wiki/Caesar_cipher",
            "https://en.wikipedia.org/wiki/Carry_(arithmetic)",
            "https://en.wikipedia.org/wiki/Charles_Babbage",
            "https://en.wikipedia.org/wiki/Cipher",
            "https://en.wikipedia.org/wiki/Cipher_disk",
            "https://en.wikipedia.org/wiki/Ciphertext",
            "https://en.wikipedia.org/wiki/Ciphertext-only_attack",
            "https://en.wikipedia.org/wiki/Classical_cipher",
            "https://en.wikipedia.org/wiki/Columnar_transposition",
            "https://en.wikipedia.org/wiki/Combinatorics",
            "https://en.wikipedia.org/wiki/Confusion_and_diffusion",
            "https://en.wikipedia.org/wiki/Constraint_satisfaction_problem",
            "https://en.wikipedia.org/wiki/Crib_(cryptanalysis)",
            "https://en.wikipedia.org/wiki/Cryptanalysis",
            "https://en.wikipedia.org/wiki/Cryptanalysis_of_the_Enigma",
            "https://en.wikipedia.org/wiki/Cryptogram",
            "https://en.wikipedia.org/wiki/Cryptographic_key_types",
            "https://en.wikipedia.org/wiki/Cryptography",
            "https://en.wikipedia.org/wiki/Decimal",
            "https://en.wikipedia.org/wiki/Digraph_(orthography)",
            "https://en.wikipedia.org/wiki/Elementary_arithmetic",
            "https://en.wikipedia.org/wiki/Enigma_machine",
            "https://en.wikipedia.org/wiki/Entropy_(information_theory)",
            "https://en.wikipedia.org/wiki/Four-square_cipher",
            "https://en.wikipedia.org/wiki/Francis_Bacon",
            "https://en.wikipedia.org/wiki/Frequency_analysis",
            "https://en.wikipedia.org/wiki/Giovanni_Battista_della_Porta",
            "https://en.wikipedia.org/wiki/Great_Cipher",
            "https://en.wikipedia.org/wiki/Greatest_common_divisor",
            "https://en.wikipedia.org/wiki/Grille_(cryptography)",
            "https://en.wikipedia.org/wiki/Hill_cipher",
            "https://en.wikipedia.org/wiki/History_of_cryptography",
            "https://en.wikipedia.org/wiki/Homophonic_substitution_cipher",
            "https://en.wikipedia.org/wiki/Index_of_coincidence",
            "https://en.wikipedia.org/wiki/Kasiski_examination",
            "https://en.wikipedia.org/wiki/Kerckhoffs%27s_principle",
            "https://en.wikipedia.org/wiki/Key_(cryptography)",
            "https://en.wikipedia.org/wiki/Keyword_cipher",
            "https://en.wikipedia.org/wiki/Known-plaintext_attack",
            "https://en.wikipedia.org/wiki/Letter_frequency",
            "https://en.wikipedia.org/wiki/Modular_arithmetic",
            "https://en.wikipedia.org/wiki/Modulo",
            "https://en.wikipedia.org/wiki/Morse_code",
            "https://en.wikipedia.org/wiki/Nihilist_cipher",
            "https://en.wikipedia.org/wiki/Nomenclator_cipher",
            "https://en.wikipedia.org/wiki/Null_cipher",
            "https://en.wikipedia.org/wiki/Number_base",
            "https://en.wikipedia.org/wiki/One-time_pad",
            "https://en.wikipedia.org/wiki/Permutation",
            "https://en.wikipedia.org/wiki/Pigeonhole_principle",
            "https://en.wikipedia.org/wiki/Pigpen_cipher",
            "https://en.wikipedia.org/wiki/Plaintext",
            "https://en.wikipedia.org/wiki/Playfair_cipher",
            "https://en.wikipedia.org/wiki/Polyalphabetic_cipher",
            "https://en.wikipedia.org/wiki/Polybius_square",
            "https://en.wikipedia.org/wiki/Positional_notation",
            "https://en.wikipedia.org/wiki/Prosigns_for_Morse_code",
            "https://en.wikipedia.org/wiki/Puzzle",
            "https://en.wikipedia.org/wiki/Rail_fence_cipher",
            "https://en.wikipedia.org/wiki/Redundancy_(information_theory)",
            "https://en.wikipedia.org/wiki/ROT13",
            "https://en.wikipedia.org/wiki/Running_key_cipher",
            "https://en.wikipedia.org/wiki/Samuel_Morse",
            "https://en.wikipedia.org/wiki/Scytale",
            "https://en.wikipedia.org/wiki/Spanish_language",
            "https://en.wikipedia.org/wiki/Spanish_orthography",
            "https://en.wikipedia.org/wiki/Steganography",
            "https://en.wikipedia.org/wiki/Straddling_checkerboard",
            "https://en.wikipedia.org/wiki/Substitution_cipher",
            "https://en.wikipedia.org/wiki/Substitution%E2%80%93permutation_network",
            "https://en.wikipedia.org/wiki/Tabula_recta",
            "https://en.wikipedia.org/wiki/Telegraphy",
            "https://en.wikipedia.org/wiki/Transposition_cipher",
            "https://en.wikipedia.org/wiki/Trifid_cipher",
            "https://en.wikipedia.org/wiki/Trigram",
            "https://en.wikipedia.org/wiki/Two-square_cipher",
            "https://en.wikipedia.org/wiki/Unicity_distance",
            "https://en.wikipedia.org/wiki/Verbal_arithmetic",
            "https://en.wikipedia.org/wiki/Vigen%C3%A8re_cipher",
            "https://en.wikipedia.org/wiki/Zodiac_Killer",
            "https://www.nist.gov/cryptography",
        ],
    },
    "circuits_2027": {
        "publisher": "Wikipedia contributors",
        "license": "public_domain (federal) and CC-BY-SA 4.0 (Wikipedia, facts with attribution)",
        # Circuit Lab 2027 names both what is in scope and what is OUT: no AC circuit
        # theory, no capacitance or inductance, no Thevenin or Norton, no sequential logic,
        # no oscilloscopes, and no trigonometry, complex numbers, matrices or calculus. What
        # is in: charge and Coulomb's law, DC circuits and Ohm's law, power and energy,
        # series and parallel, control devices, silicon PN junctions and LEDs, and
        # combinational logic through De Morgan and adders. The seven named historical
        # figures each have a page here because the manual asks for them by name.
        "urls": [
            "https://en.wikipedia.org/wiki/Adder_(electronics)",
            "https://en.wikipedia.org/wiki/Alessandro_Volta",
            "https://en.wikipedia.org/wiki/Alternating_current",
            "https://en.wikipedia.org/wiki/Ammeter",
            "https://en.wikipedia.org/wiki/Ampere",
            "https://en.wikipedia.org/wiki/Ampere_hour",
            "https://en.wikipedia.org/wiki/AND_gate",
            "https://en.wikipedia.org/wiki/Andr%C3%A9-Marie_Amp%C3%A8re",
            "https://en.wikipedia.org/wiki/Battery_charger",
            "https://en.wikipedia.org/wiki/Binary_arithmetic",
            "https://en.wikipedia.org/wiki/Binary_number",
            "https://en.wikipedia.org/wiki/Bit",
            "https://en.wikipedia.org/wiki/Boolean_algebra",
            "https://en.wikipedia.org/wiki/Breadboard",
            "https://en.wikipedia.org/wiki/Charles-Augustin_de_Coulomb",
            "https://en.wikipedia.org/wiki/Circuit_breaker",
            "https://en.wikipedia.org/wiki/Circuit_diagram",
            "https://en.wikipedia.org/wiki/Combinational_logic",
            "https://en.wikipedia.org/wiki/Coulomb",
            "https://en.wikipedia.org/wiki/Coulomb%27s_law",
            "https://en.wikipedia.org/wiki/Current_divider",
            "https://en.wikipedia.org/wiki/De_Morgan%27s_laws",
            "https://en.wikipedia.org/wiki/Diode",
            "https://en.wikipedia.org/wiki/Direct_current",
            "https://en.wikipedia.org/wiki/Doping_(semiconductor)",
            "https://en.wikipedia.org/wiki/Efficiency",
            "https://en.wikipedia.org/wiki/Electric_battery",
            "https://en.wikipedia.org/wiki/Electric_charge",
            "https://en.wikipedia.org/wiki/Electric_current",
            "https://en.wikipedia.org/wiki/Electric_field",
            "https://en.wikipedia.org/wiki/Electric_power",
            "https://en.wikipedia.org/wiki/Electrical_conductor",
            "https://en.wikipedia.org/wiki/Electrical_injury",
            "https://en.wikipedia.org/wiki/Electrical_network",
            "https://en.wikipedia.org/wiki/Electrical_resistance_and_conductance",
            "https://en.wikipedia.org/wiki/Electrical_safety",
            "https://en.wikipedia.org/wiki/Electromotive_force",
            "https://en.wikipedia.org/wiki/Electronic_color_code",
            "https://en.wikipedia.org/wiki/Electronic_symbol",
            "https://en.wikipedia.org/wiki/Electrostatic_discharge",
            "https://en.wikipedia.org/wiki/Forward_bias",
            "https://en.wikipedia.org/wiki/Functional_completeness",
            "https://en.wikipedia.org/wiki/Fuse_(electrical)",
            "https://en.wikipedia.org/wiki/Georg_Ohm",
            "https://en.wikipedia.org/wiki/George_Boole",
            "https://en.wikipedia.org/wiki/Gustav_Kirchhoff",
            "https://en.wikipedia.org/wiki/Half_adder",
            "https://en.wikipedia.org/wiki/Heinrich_Hertz",
            "https://en.wikipedia.org/wiki/Insulator_(electricity)",
            "https://en.wikipedia.org/wiki/Internal_resistance",
            "https://en.wikipedia.org/wiki/Joule",
            "https://en.wikipedia.org/wiki/Joule_heating",
            "https://en.wikipedia.org/wiki/Karnaugh_map",
            "https://en.wikipedia.org/wiki/Kilowatt-hour",
            "https://en.wikipedia.org/wiki/Kirchhoff%27s_circuit_laws",
            "https://en.wikipedia.org/wiki/Light-emitting_diode",
            "https://en.wikipedia.org/wiki/Lightning",
            "https://en.wikipedia.org/wiki/Logic_gate",
            "https://en.wikipedia.org/wiki/Multimeter",
            "https://en.wikipedia.org/wiki/Multiplexer",
            "https://en.wikipedia.org/wiki/Multiway_switching",
            "https://en.wikipedia.org/wiki/NAND_gate",
            "https://en.wikipedia.org/wiki/NOR_gate",
            "https://en.wikipedia.org/wiki/NOT_gate",
            "https://en.wikipedia.org/wiki/Ohm",
            "https://en.wikipedia.org/wiki/Ohm%27s_law",
            "https://en.wikipedia.org/wiki/Ohmmeter",
            "https://en.wikipedia.org/wiki/Open-circuit_voltage",
            "https://en.wikipedia.org/wiki/OR_gate",
            "https://en.wikipedia.org/wiki/P%E2%80%93n_junction",
            "https://en.wikipedia.org/wiki/Potentiometer",
            "https://en.wikipedia.org/wiki/Rectifier",
            "https://en.wikipedia.org/wiki/Relay",
            "https://en.wikipedia.org/wiki/Residual-current_device",
            "https://en.wikipedia.org/wiki/Resistivity",
            "https://en.wikipedia.org/wiki/Resistor",
            "https://en.wikipedia.org/wiki/Semiconductor",
            "https://en.wikipedia.org/wiki/Series_and_parallel_circuits",
            "https://en.wikipedia.org/wiki/Short_circuit",
            "https://en.wikipedia.org/wiki/Silicon",
            "https://en.wikipedia.org/wiki/Static_electricity",
            "https://en.wikipedia.org/wiki/Switch",
            "https://en.wikipedia.org/wiki/Triboelectric_effect",
            "https://en.wikipedia.org/wiki/Troubleshooting",
            "https://en.wikipedia.org/wiki/Truth_table",
            "https://en.wikipedia.org/wiki/USB",
            "https://en.wikipedia.org/wiki/USB_hardware",
            "https://en.wikipedia.org/wiki/Volt",
            "https://en.wikipedia.org/wiki/Voltage",
            "https://en.wikipedia.org/wiki/Voltage_divider",
            "https://en.wikipedia.org/wiki/Voltaic_pile",
            "https://en.wikipedia.org/wiki/Voltmeter",
            "https://en.wikipedia.org/wiki/Watt",
            "https://en.wikipedia.org/wiki/Wire_gauge",
            "https://en.wikipedia.org/wiki/XOR_gate",
        ],
    },
    "dairy_food_science": {
        "publisher": "FDA / MedlinePlus / Wikipedia contributors",
        "license": "public_domain (federal) and CC-BY-SA 4.0 (Wikipedia, facts with attribution)",
        # Food Science 2027 is a dairy event, and its written exam is scoped by the manual to
        # dairy topics only: the lipids, carbohydrates and proteins of milk; casein and whey;
        # emulsification and the fat globule; esterification and saturated versus unsaturated
        # fats; pasteurization, preservation and probiotics; lactose intolerance and lactose
        # free milk; non-dairy "milks"; allergens; labeling regulation and RDA; and the
        # freezing point depression that makes the ice cream task work. Nothing here is about
        # food science in general, because the exam is not.
        "urls": [
            "https://en.wikipedia.org/wiki/Acetic_acid",
            "https://en.wikipedia.org/wiki/Acid",
            "https://en.wikipedia.org/wiki/Almond_milk",
            "https://en.wikipedia.org/wiki/Amino_acid",
            "https://en.wikipedia.org/wiki/Bifidobacterium",
            "https://en.wikipedia.org/wiki/Butter",
            "https://en.wikipedia.org/wiki/Butterfat",
            "https://en.wikipedia.org/wiki/Buttermilk",
            "https://en.wikipedia.org/wiki/Calcium",
            "https://en.wikipedia.org/wiki/Caramelization",
            "https://en.wikipedia.org/wiki/Carbohydrate",
            "https://en.wikipedia.org/wiki/Casein",
            "https://en.wikipedia.org/wiki/Cheddar_cheese",
            "https://en.wikipedia.org/wiki/Cheese",
            "https://en.wikipedia.org/wiki/Chymosin",
            "https://en.wikipedia.org/wiki/Citric_acid",
            "https://en.wikipedia.org/wiki/Coagulation",
            "https://en.wikipedia.org/wiki/Colligative_properties",
            "https://en.wikipedia.org/wiki/Colloid",
            "https://en.wikipedia.org/wiki/Condensed_milk",
            "https://en.wikipedia.org/wiki/Cottage_cheese",
            "https://en.wikipedia.org/wiki/Cream",
            "https://en.wikipedia.org/wiki/Curd",
            "https://en.wikipedia.org/wiki/Dairy_product",
            "https://en.wikipedia.org/wiki/Denaturation_(biochemistry)",
            "https://en.wikipedia.org/wiki/Density",
            "https://en.wikipedia.org/wiki/Dietary_Reference_Intake",
            "https://en.wikipedia.org/wiki/Disaccharide",
            "https://en.wikipedia.org/wiki/Emulsifier",
            "https://en.wikipedia.org/wiki/Emulsion",
            "https://en.wikipedia.org/wiki/Endothermic_process",
            "https://en.wikipedia.org/wiki/Enthalpy_of_fusion",
            "https://en.wikipedia.org/wiki/Essential_amino_acid",
            "https://en.wikipedia.org/wiki/Essential_fatty_acid",
            "https://en.wikipedia.org/wiki/Ester",
            "https://en.wikipedia.org/wiki/Esterification",
            "https://en.wikipedia.org/wiki/Eutectic_system",
            "https://en.wikipedia.org/wiki/Evaporated_milk",
            "https://en.wikipedia.org/wiki/Fatty_acid",
            "https://en.wikipedia.org/wiki/Fermentation",
            "https://en.wikipedia.org/wiki/Food_allergy",
            "https://en.wikipedia.org/wiki/Food_chemistry",
            "https://en.wikipedia.org/wiki/Food_preservation",
            "https://en.wikipedia.org/wiki/Food_science",
            "https://en.wikipedia.org/wiki/Food_spoilage",
            "https://en.wikipedia.org/wiki/Freeze-drying",
            "https://en.wikipedia.org/wiki/Freezing-point_depression",
            "https://en.wikipedia.org/wiki/Galactose",
            "https://en.wikipedia.org/wiki/Glucose",
            "https://en.wikipedia.org/wiki/Glycosidic_bond",
            "https://en.wikipedia.org/wiki/Homogenization_(chemistry)",
            "https://en.wikipedia.org/wiki/Hydrogen_bond",
            "https://en.wikipedia.org/wiki/Hydrogenation",
            "https://en.wikipedia.org/wiki/Hydrolysis",
            "https://en.wikipedia.org/wiki/Hydrophile",
            "https://en.wikipedia.org/wiki/Hydrophobe",
            "https://en.wikipedia.org/wiki/Ice_cream",
            "https://en.wikipedia.org/wiki/Ice_cream_maker",
            "https://en.wikipedia.org/wiki/Isoelectric_point",
            "https://en.wikipedia.org/wiki/Kefir",
            "https://en.wikipedia.org/wiki/Lactase",
            "https://en.wikipedia.org/wiki/Lactic_acid",
            "https://en.wikipedia.org/wiki/Lactic_acid_fermentation",
            "https://en.wikipedia.org/wiki/Lactobacillus",
            "https://en.wikipedia.org/wiki/Lactose",
            "https://en.wikipedia.org/wiki/Lactose_intolerance",
            "https://en.wikipedia.org/wiki/Lipid",
            "https://en.wikipedia.org/wiki/Maillard_reaction",
            "https://en.wikipedia.org/wiki/Micelle",
            "https://en.wikipedia.org/wiki/Milk",
            "https://en.wikipedia.org/wiki/Milk_allergy",
            "https://en.wikipedia.org/wiki/Milk_fat_globule_membrane",
            "https://en.wikipedia.org/wiki/Molality",
            "https://en.wikipedia.org/wiki/Monosaccharide",
            "https://en.wikipedia.org/wiki/Mozzarella",
            "https://en.wikipedia.org/wiki/Nutrition_facts_label",
            "https://en.wikipedia.org/wiki/Oat_milk",
            "https://en.wikipedia.org/wiki/Omega-3_fatty_acid",
            "https://en.wikipedia.org/wiki/Organic_certification",
            "https://en.wikipedia.org/wiki/Organic_food",
            "https://en.wikipedia.org/wiki/Osteoporosis",
            "https://en.wikipedia.org/wiki/Pasteurization",
            "https://en.wikipedia.org/wiki/Peptide_bond",
            "https://en.wikipedia.org/wiki/PH",
            "https://en.wikipedia.org/wiki/Phosphorus",
            "https://en.wikipedia.org/wiki/Plant_milk",
            "https://en.wikipedia.org/wiki/Polysaccharide",
            "https://en.wikipedia.org/wiki/Potassium",
            "https://en.wikipedia.org/wiki/Powdered_milk",
            "https://en.wikipedia.org/wiki/Probiotic",
            "https://en.wikipedia.org/wiki/Protein",
            "https://en.wikipedia.org/wiki/Protein_structure",
            "https://en.wikipedia.org/wiki/Rancidification",
            "https://en.wikipedia.org/wiki/Raw_milk",
            "https://en.wikipedia.org/wiki/Reference_Daily_Intake",
            "https://en.wikipedia.org/wiki/Refrigeration",
            "https://en.wikipedia.org/wiki/Rennet",
            "https://en.wikipedia.org/wiki/Riboflavin",
            "https://en.wikipedia.org/wiki/Rickets",
            "https://en.wikipedia.org/wiki/Ricotta",
            "https://en.wikipedia.org/wiki/Saponification",
            "https://en.wikipedia.org/wiki/Saturated_fat",
            "https://en.wikipedia.org/wiki/Scalded_milk",
            "https://en.wikipedia.org/wiki/Scurvy",
            "https://en.wikipedia.org/wiki/Shelf_life",
            "https://en.wikipedia.org/wiki/Skimmed_milk",
            "https://en.wikipedia.org/wiki/Solubility",
            "https://en.wikipedia.org/wiki/Solution_(chemistry)",
            "https://en.wikipedia.org/wiki/Soy_milk",
            "https://en.wikipedia.org/wiki/Specific_heat_capacity",
            "https://en.wikipedia.org/wiki/Starch",
            "https://en.wikipedia.org/wiki/Streptococcus_thermophilus",
            "https://en.wikipedia.org/wiki/Supercooling",
            "https://en.wikipedia.org/wiki/Surfactant",
            "https://en.wikipedia.org/wiki/Titration",
            "https://en.wikipedia.org/wiki/Trans_fat",
            "https://en.wikipedia.org/wiki/Triglyceride",
            "https://en.wikipedia.org/wiki/Ultra-high-temperature_processing",
            "https://en.wikipedia.org/wiki/Unsaturated_fat",
            "https://en.wikipedia.org/wiki/Van_%27t_Hoff_factor",
            "https://en.wikipedia.org/wiki/Viscosity",
            "https://en.wikipedia.org/wiki/Vitamin",
            "https://en.wikipedia.org/wiki/Vitamin_A",
            "https://en.wikipedia.org/wiki/Vitamin_B12",
            "https://en.wikipedia.org/wiki/Vitamin_D",
            "https://en.wikipedia.org/wiki/Whey",
            "https://en.wikipedia.org/wiki/Yogurt",
            "https://medlineplus.gov/calcium.html",
            "https://medlineplus.gov/carbohydrates.html",
            "https://medlineplus.gov/dietaryfats.html",
            "https://medlineplus.gov/dietaryproteins.html",
            "https://medlineplus.gov/foodallergy.html",
            "https://medlineplus.gov/foodsafety.html",
            "https://medlineplus.gov/lactoseintolerance.html",
            "https://medlineplus.gov/minerals.html",
            "https://medlineplus.gov/nutrition.html",
            "https://medlineplus.gov/osteoporosis.html",
            "https://medlineplus.gov/vitamind.html",
            "https://medlineplus.gov/vitamins.html",
            "https://www.fda.gov/food/buy-store-serve-safe-food/dangers-raw-milk-unpasteurized-milk-can-pose-serious-health-risk",
            "https://www.fda.gov/food/buy-store-serve-safe-food/raw-milk-misconceptions-and-danger-raw-milk-consumption",
            "https://www.fda.gov/food/nutrition-facts-label/added-sugars-nutrition-facts-label",
            "https://www.fda.gov/food/nutrition-facts-label/daily-value-nutrition-and-supplement-facts-labels",
            "https://www.fda.gov/food/nutrition-facts-label/how-understand-and-use-nutrition-facts-label",
            # The notebook is nine experiments graded before the tournament starts and each
            # must have exactly one independent variable, so the event examines experiment
            # design as well as dairy chemistry. A keyword audit found the design lessons
            # matching no passage at all: the dairy corpus has nothing about a controlled
            # variable or a systematic error.
            "https://en.wikipedia.org/wiki/Dependent_and_independent_variables",
            "https://en.wikipedia.org/wiki/Controlling_for_a_variable",
            "https://en.wikipedia.org/wiki/Scientific_control",
            "https://en.wikipedia.org/wiki/Confounding",
            "https://en.wikipedia.org/wiki/Design_of_experiments",
            "https://en.wikipedia.org/wiki/Significant_figures",
            "https://en.wikipedia.org/wiki/Observational_error",
            "https://en.wikipedia.org/wiki/Accuracy_and_precision",
            "https://en.wikipedia.org/wiki/Replication_(statistics)",
            "https://en.wikipedia.org/wiki/Table_(information)",
            "https://en.wikipedia.org/wiki/Hypothesis",
            "https://en.wikipedia.org/wiki/Measurement",
        ],
    },
    "epidemiology": {
        "publisher": "CDC / NIH / Wikipedia contributors",
        "license": "public_domain (federal) and CC-BY-SA 4.0 (Wikipedia, facts with attribution)",
        "urls": [
            # --- CDC Principles of Epidemiology (SS1978) - the manual's named reference, live only on archive.cdc.gov
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson1/section1.html",  # clinician vs epidemiologist
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson1/section2.html",  # history: Hippocrates, Graunt, Farr, Snow
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson1/section3.html",  # uses of epidemiology
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson1/section4.html",  # core functions, field investigation
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson1/section5.html",  # the epidemiologic approach, case definition
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson1/section6.html",  # descriptive epidemiology: time, place, person
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson1/section7.html",  # analytic epidemiology, comparison groups
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson1/section8.html",  # epidemiologic triad, component causes
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson1/section9.html",  # natural history and spectrum of disease
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson1/section10.html",  # chain of infection
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson1/section11.html",  # sporadic, endemic, hyperendemic, epidemic
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson2/section2.html",  # types of variables
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson2/section3.html",  # frequency distributions and tables
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson2/section4.html",  # properties of frequency distributions
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson2/section6.html",  # mean, median, mode
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson2/section7.html",  # range, interquartile range, standard deviation
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson2/section8.html",  # choosing the right summary measure
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson3/section1.html",  # ratio, proportion, rate, attack rate
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson3/section2.html",  # incidence and prevalence
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson3/section3.html",  # death rate, case fatality, YPLL
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson3/section5.html",  # risk ratio, rate ratio, odds ratio
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson3/section6.html",  # attributable risk
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson4/section1.html",  # displaying data
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson4/section2.html",  # one, two and three variable tables
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson4/section3.html",  # line graphs, histograms, epidemic curves
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson4/section4.html",  # bar charts, pie, spot and area maps
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson4/section5.html",  # choosing and constructing a display
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson5/section1.html",  # introduction to surveillance
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson5/section2.html",  # purpose and characteristics of surveillance
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson5/section3.html",  # identifying health problems for surveillance
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson5/section4.html",  # passive, active and sentinel data collection
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson5/section5.html",  # analysing and interpreting surveillance data
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson5/section6.html",  # disseminating data and interpretations
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson5/section7.html",  # evaluating surveillance, predictive value positive
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson6/section1.html",  # why outbreaks are investigated
            "https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson6/section2.html",  # all 13 outbreak investigation steps, worked
            # --- CDC Field Epidemiology Manual
            "https://www.cdc.gov/field-epi-manual/php/chapters/defining-field-epi.html",  # descriptive vs analytic field epidemiology
            "https://www.cdc.gov/field-epi-manual/php/chapters/initiating-operations.html",  # preparing for field work
            "https://www.cdc.gov/field-epi-manual/php/chapters/field-investigation.html",  # case definition, line listing, epi curve, spot map
            "https://www.cdc.gov/field-epi-manual/php/chapters/collecting-data.html",  # surveillance sources, PulseNet, syndromic surveillance
            "https://www.cdc.gov/field-epi-manual/php/chapters/data-collection-management.html",  # questionnaires, variables, data quality
            "https://www.cdc.gov/field-epi-manual/php/chapters/describing-epi-data.html",  # time, place, person; epi curves
            "https://www.cdc.gov/field-epi-manual/php/chapters/design-conduct-analyze-field-studies.html",  # cohort vs case-control, bias, sample size
            "https://www.cdc.gov/field-epi-manual/php/chapters/analyze-interpret-data.html",  # 2x2 tables, RR, OR, p-values, vaccine efficacy
            "https://www.cdc.gov/field-epi-manual/php/chapters/epi-lab-collaboration.html",  # molecular subtyping, PFGE, WGS, serotyping
            "https://www.cdc.gov/field-epi-manual/php/chapters/interventions.html",  # control measures, breaking transmission
            "https://www.cdc.gov/field-epi-manual/php/chapters/gis-data.html",  # cluster maps, choropleth, spatial analysis
            "https://www.cdc.gov/field-epi-manual/php/chapters/healthcare-settings.html",  # healthcare-associated outbreaks
            "https://www.cdc.gov/field-epi-manual/php/chapters/community-settings.html",  # community outbreak investigation
            "https://www.cdc.gov/field-epi-manual/php/chapters/environmental-origin.html",  # environmental and waterborne investigation
            "https://www.cdc.gov/field-epi-manual/php/chapters/acute-enteric-disease.html",  # foodborne and enteric outbreaks, attack rates
            "https://www.cdc.gov/field-epi-manual/php/chapters/biologic-toxic-agents.html",  # agent classes, toxic exposures
            # --- CDC programmes and agents
            "https://www.cdc.gov/mmwr/preview/mmwrhtml/rr5013a1.htm",  # surveillance system attributes, representativeness
            "https://www.cdc.gov/one-health/about/index.html",  # agent-host-environment, zoonotic spillover
            "https://www.cdc.gov/pulsenet/about/index.html",  # PulseNet
            "https://www.cdc.gov/nndss/about/index.html",  # nationally notifiable disease surveillance
            "https://www.cdc.gov/nchs/nvss/index.htm",  # vital statistics, death certificates
            "https://www.cdc.gov/nchs/nhanes/about/index.html",  # survey-based surveillance
            "https://www.cdc.gov/brfss/about/index.htm",  # behavioural risk factor surveillance
            "https://www.cdc.gov/vaccines/basics/index.html",  # immunization as primary prevention
            "https://www.cdc.gov/vaccines/glossary/",  # vaccine terminology, efficacy, herd immunity
            "https://www.cdc.gov/vaccines/basics/explaining-how-vaccines-work.html",  # immunity and vaccination
            "https://www.cdc.gov/flu-vaccines-work/php/effectiveness-studies/index.html",  # test-negative vaccine effectiveness design
            "https://www.cdc.gov/antimicrobial-resistance/about/index.html",  # agent factors, control strategy
            "https://www.cdc.gov/prions/about/index.html",  # prion disease
            "https://www.cdc.gov/mosquitoes/about/index.html",  # vector and vector control
            "https://www.cdc.gov/ticks/about/index.html",  # vector-borne transmission
            "https://www.cdc.gov/salmonella/about/index.html",  # enteric outbreak agent
            "https://www.cdc.gov/norovirus/about/index.html",  # propagated spread
            "https://www.cdc.gov/listeria/about/index.html",  # PulseNet clusters
            "https://www.cdc.gov/ecoli/about/index.html",  # serotype
            "https://www.fda.gov/food/consumers/what-you-need-know-about-foodborne-illnesses",  # foodborne illness, vehicle
            "https://medlineplus.gov/infectiousdiseases.html",  # infectious agent classes, plain language
            "https://www.niaid.nih.gov/diseases-conditions/infectious-diseases",  # infectious disease research areas
            "https://www.niaid.nih.gov/research/vaccines",  # vaccines and immunity
            # --- Wikipedia
            "https://en.wikipedia.org/wiki/Epidemiology",  # scope, definitions, measures
            "https://en.wikipedia.org/wiki/John_Snow",  # Broad Street, natural experiment
            "https://en.wikipedia.org/wiki/Public_health_surveillance",  # surveillance types
            "https://en.wikipedia.org/wiki/Notifiable_disease",  # notifiable and reportable systems
            "https://en.wikipedia.org/wiki/Sentinel_surveillance",  # sentinel surveillance
            "https://en.wikipedia.org/wiki/Outbreak",  # outbreak vs epidemic, common source vs propagated
            "https://en.wikipedia.org/wiki/Epidemic",  # epidemic, pandemic, thresholds
            "https://en.wikipedia.org/wiki/Endemic_(epidemiology)",  # endemic, hyperendemic, sporadic
            "https://en.wikipedia.org/wiki/Cluster_(epidemiology)",  # disease cluster investigation
            "https://en.wikipedia.org/wiki/Pathogen",  # agent classes, pathogenicity, virulence
            "https://en.wikipedia.org/wiki/Pathogenic_bacteria",  # bacterial causes
            "https://en.wikipedia.org/wiki/Viral_disease",  # viral causes
            "https://en.wikipedia.org/wiki/Mycosis",  # fungal causes
            "https://en.wikipedia.org/wiki/Protozoan_infection",  # protist causes
            "https://en.wikipedia.org/wiki/Prion",  # prion causes
            "https://en.wikipedia.org/wiki/Non-communicable_disease",  # noninfectious causes, risk factors
            "https://en.wikipedia.org/wiki/Natural_history_of_disease",  # natural history timeline
            "https://en.wikipedia.org/wiki/Subclinical_infection",  # spectrum of disease, carrier
            "https://en.wikipedia.org/wiki/Incubation_period",  # incubation and latent periods
            "https://en.wikipedia.org/wiki/Transmission_(medicine)",  # modes of transmission, vehicle, vector
            "https://en.wikipedia.org/wiki/Case%E2%80%93control_study",  # case-control design
            "https://en.wikipedia.org/wiki/Cohort_study",  # cohort design
            "https://en.wikipedia.org/wiki/Cross-sectional_study",  # cross-sectional design
            "https://en.wikipedia.org/wiki/Ecological_study",  # ecological design
            "https://en.wikipedia.org/wiki/Randomized_controlled_trial",  # experimental design, randomization, blinding
            "https://en.wikipedia.org/wiki/Case_definition",  # confirmed, probable, suspect
            "https://en.wikipedia.org/wiki/Epidemic_curve",  # epi curve shapes
            "https://en.wikipedia.org/wiki/Attack_rate",  # attack rate and secondary attack rate
            "https://en.wikipedia.org/wiki/Relative_risk",  # risk ratio
            "https://en.wikipedia.org/wiki/Odds_ratio",  # odds ratio, cross-product
            "https://en.wikipedia.org/wiki/Risk_difference",  # attributable risk
            "https://en.wikipedia.org/wiki/Contingency_table",  # 2x2 table structure
            "https://en.wikipedia.org/wiki/Incidence_(epidemiology)",  # incidence proportion and rate, person-time
            "https://en.wikipedia.org/wiki/Prevalence",  # point and period prevalence
            "https://en.wikipedia.org/wiki/Mortality_rate",  # crude, cause-specific, age-adjusted
            "https://en.wikipedia.org/wiki/Case_fatality_rate",  # case fatality
            "https://en.wikipedia.org/wiki/Confounding",  # confounding and its control
            "https://en.wikipedia.org/wiki/Selection_bias",  # selection bias
            "https://en.wikipedia.org/wiki/Information_bias_(epidemiology)",  # information bias, misclassification
            "https://en.wikipedia.org/wiki/Recall_bias",  # recall bias
            "https://en.wikipedia.org/wiki/Ecological_fallacy",  # ecological fallacy
            "https://en.wikipedia.org/wiki/Bradford_Hill_criteria",  # the nine Hill criteria
            "https://en.wikipedia.org/wiki/Koch%27s_postulates",  # Koch's postulates and their limits
            "https://en.wikipedia.org/wiki/Causal_pie_model",  # component, sufficient and necessary cause
            "https://en.wikipedia.org/wiki/Directed_acyclic_graph",  # DAG structure
            "https://en.wikipedia.org/wiki/Causal_graph",  # causal DAGs, backdoor paths
            "https://en.wikipedia.org/wiki/GRADE_approach",  # certainty of evidence
            "https://en.wikipedia.org/wiki/Herd_immunity",  # herd immunity threshold
            "https://en.wikipedia.org/wiki/Vaccine_efficacy",  # efficacy and effectiveness
            "https://en.wikipedia.org/wiki/Basic_reproduction_number",  # R0
            "https://en.wikipedia.org/wiki/Ring_vaccination",  # ring vaccination
            "https://en.wikipedia.org/wiki/Preventive_healthcare",  # primary, secondary, tertiary prevention
            "https://en.wikipedia.org/wiki/Screening_(medicine)",  # screening as secondary prevention
            "https://en.wikipedia.org/wiki/Quarantine",  # quarantine
            "https://en.wikipedia.org/wiki/Isolation_(health_care)",  # isolation and precautions
            "https://en.wikipedia.org/wiki/Contact_tracing",  # contact tracing
            "https://en.wikipedia.org/wiki/Infection_control",  # infection prevention and control
            "https://en.wikipedia.org/wiki/Pulsed-field_gel_electrophoresis",  # PFGE method
            "https://en.wikipedia.org/wiki/PulseNet",  # PulseNet pattern matching
            "https://en.wikipedia.org/wiki/Single-nucleotide_polymorphism",  # SNP typing
            "https://en.wikipedia.org/wiki/Whole_genome_sequencing",  # WGS for outbreak subtyping
            "https://en.wikipedia.org/wiki/Molecular_epidemiology",  # molecular epidemiology
            "https://en.wikipedia.org/wiki/Histogram",  # histogram, class intervals
            "https://en.wikipedia.org/wiki/Choropleth_map",  # choropleth and area maps
            "https://en.wikipedia.org/wiki/Sensitivity_and_specificity",  # sensitivity, specificity, predictive value
        ],
    },
    "entomology": {
        "publisher": "USDA Agricultural Research Service",
        "license": "public_domain",
        "urls": [
            "https://en.wikipedia.org/wiki/Insect_morphology",
            "https://en.wikipedia.org/wiki/Entomology",
            "https://en.wikipedia.org/wiki/Insect",
            "https://en.wikipedia.org/wiki/Holometabolism",
            "https://en.wikipedia.org/wiki/Insect_wing",
            "https://en.wikipedia.org/wiki/Coleoptera",
            "https://en.wikipedia.org/wiki/Lepidoptera",
            "https://en.wikipedia.org/wiki/Hymenoptera",
            "https://en.wikipedia.org/wiki/Diptera",
            "https://en.wikipedia.org/wiki/Hemiptera",
            "https://en.wikipedia.org/wiki/Orthoptera",
            "https://en.wikipedia.org/wiki/Odonata",
            "https://en.wikipedia.org/wiki/Metamorphosis",
            "https://en.wikipedia.org/wiki/Arthropod",
        ],
    },
    "chemistry": {
        "publisher": "NIST / NIH PubChem",
        "license": "public_domain",
        "urls": [
            "https://www.nist.gov/chemistry",
            "https://en.wikipedia.org/wiki/Chemical_reaction",
            "https://en.wikipedia.org/wiki/Periodic_table",
            "https://en.wikipedia.org/wiki/Stoichiometry",
            "https://en.wikipedia.org/wiki/Chemical_bond",
            "https://en.wikipedia.org/wiki/Acid%E2%80%93base_reaction",
            "https://en.wikipedia.org/wiki/PH",
            "https://en.wikipedia.org/wiki/Chemical_equilibrium",
            "https://en.wikipedia.org/wiki/Thermochemistry",
            "https://en.wikipedia.org/wiki/Ideal_gas_law",
            "https://en.wikipedia.org/wiki/Molarity",
            "https://en.wikipedia.org/wiki/Redox",
            "https://en.wikipedia.org/wiki/Reaction_rate",
            "https://en.wikipedia.org/wiki/Le_Chatelier%27s_principle",
        ],
    },
    "forensics": {
        "publisher": "NIST Forensic Science",
        "license": "public_domain",
        "urls": [
            "https://www.nist.gov/forensic-science",
            "https://en.wikipedia.org/wiki/Forensic_science",
            "https://en.wikipedia.org/wiki/Chromatography",
            "https://en.wikipedia.org/wiki/Fingerprint",
            "https://en.wikipedia.org/wiki/DNA_profiling",
            "https://en.wikipedia.org/wiki/Spectroscopy",
            "https://en.wikipedia.org/wiki/Flame_test",
            "https://en.wikipedia.org/wiki/Polymer",
            "https://en.wikipedia.org/wiki/Fiber",
            "https://en.wikipedia.org/wiki/Blood_residue",
            "https://en.wikipedia.org/wiki/Refractive_index",
            "https://en.wikipedia.org/wiki/Density",
            "https://en.wikipedia.org/wiki/Solubility",
        ],
    },
    "physics": {
        "publisher": "NASA Glenn Research Center",
        "license": "public_domain",
        "urls": [
            "https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/",
            "https://en.wikipedia.org/wiki/Simple_machine",
            "https://www.grc.nasa.gov/www/k-12/airplane/newton.html",
            "https://en.wikipedia.org/wiki/Newton%27s_laws_of_motion",
            "https://en.wikipedia.org/wiki/Mechanical_advantage",
            "https://en.wikipedia.org/wiki/Lever",
            "https://en.wikipedia.org/wiki/Pulley",
            "https://en.wikipedia.org/wiki/Inclined_plane",
            "https://en.wikipedia.org/wiki/Torque",
            "https://en.wikipedia.org/wiki/Work_(physics)",
            "https://en.wikipedia.org/wiki/Conservation_of_energy",
            "https://en.wikipedia.org/wiki/Ohm%27s_law",
            "https://en.wikipedia.org/wiki/Series_and_parallel_circuits",
            "https://en.wikipedia.org/wiki/Kirchhoff%27s_circuit_laws",
            "https://en.wikipedia.org/wiki/Electrical_resistance_and_conductance",
            "https://en.wikipedia.org/wiki/Capacitor",
            "https://en.wikipedia.org/wiki/Magnetism",
            "https://en.wikipedia.org/wiki/Center_of_mass",
            "https://en.wikipedia.org/wiki/Structural_load",
            "https://en.wikipedia.org/wiki/Truss",
            "https://en.wikipedia.org/wiki/Friction",
            # Added for Roller Coaster (2027 Division B): the event is scored on run time
            # against a target, on loop height and on elevator mechanisms, so a team reasons
            # about gravitational potential energy converting to translational *and*
            # rotational kinetic energy, about rolling resistance setting the achievable
            # time, and about the speed a loop needs at its top to keep the ball on track.
            "https://en.wikipedia.org/wiki/Potential_energy",
            "https://en.wikipedia.org/wiki/Kinetic_energy",
            "https://en.wikipedia.org/wiki/Rolling",
            "https://en.wikipedia.org/wiki/Rolling_resistance",
            "https://en.wikipedia.org/wiki/Moment_of_inertia",
            "https://en.wikipedia.org/wiki/Angular_momentum",
            "https://en.wikipedia.org/wiki/Circular_motion",
            "https://en.wikipedia.org/wiki/Centripetal_force",
            "https://en.wikipedia.org/wiki/Banked_turn",
            "https://en.wikipedia.org/wiki/Inertia",
            "https://en.wikipedia.org/wiki/Acceleration",
            "https://en.wikipedia.org/wiki/Terminal_velocity",
            "https://en.wikipedia.org/wiki/Archimedes%27_screw",
        ],
    },
    "metrology": {
        "publisher": "NIST Office of Weights and Measures",
        "license": "public_domain",
        "urls": [
            "https://www.nist.gov/pml/owm/metric-si/si-units",
            "https://en.wikipedia.org/wiki/International_System_of_Units",
            "https://en.wikipedia.org/wiki/Metrology",
            "https://en.wikipedia.org/wiki/SI_base_unit",
            "https://en.wikipedia.org/wiki/Significant_figures",
            "https://en.wikipedia.org/wiki/Measurement_uncertainty",
            "https://en.wikipedia.org/wiki/Metric_prefix",
            "https://en.wikipedia.org/wiki/Dimensional_analysis",
            "https://en.wikipedia.org/wiki/Calibration",
            "https://en.wikipedia.org/wiki/Litre",
            "https://en.wikipedia.org/wiki/Kilogram",
        ],
    },
    "cryptography": {
        "publisher": "NIST / public domain references",
        "license": "public_domain",
        "urls": [
            "https://en.wikipedia.org/wiki/Substitution_cipher",
            "https://en.wikipedia.org/wiki/Classical_cipher",
            "https://en.wikipedia.org/wiki/Cryptography",
            "https://en.wikipedia.org/wiki/Caesar_cipher",
            "https://en.wikipedia.org/wiki/Vigen%C3%A8re_cipher",
            "https://en.wikipedia.org/wiki/Transposition_cipher",
            "https://en.wikipedia.org/wiki/Frequency_analysis",
            "https://en.wikipedia.org/wiki/Affine_cipher",
            "https://en.wikipedia.org/wiki/Hill_cipher",
            "https://en.wikipedia.org/wiki/Baconian_cipher",
            "https://en.wikipedia.org/wiki/RSA_cryptosystem",
            "https://en.wikipedia.org/wiki/Morse_code",
            "https://en.wikipedia.org/wiki/Modular_arithmetic",
        ],
    },
    "methodology": {
        "publisher": "NIST / NASA education",
        "license": "public_domain",
        "urls": [
            "https://en.wikipedia.org/wiki/Design_of_experiments",
            "https://en.wikipedia.org/wiki/Engineering_design_process",
            "https://en.wikipedia.org/wiki/Scientific_method",
            "https://en.wikipedia.org/wiki/Dependent_and_independent_variables",
            "https://en.wikipedia.org/wiki/Control_variable",
            "https://en.wikipedia.org/wiki/Statistical_hypothesis_test",
            "https://en.wikipedia.org/wiki/Standard_deviation",
            "https://en.wikipedia.org/wiki/Mean",
            "https://en.wikipedia.org/wiki/Accuracy_and_precision",
            "https://en.wikipedia.org/wiki/Observational_error",
            "https://en.wikipedia.org/wiki/Technical_drawing",
            "https://en.wikipedia.org/wiki/Orthographic_projection",
            "https://en.wikipedia.org/wiki/Isometric_projection",
        ],
    },
    "water": {
        "publisher": "USGS Water Science School / EPA",
        "license": "public_domain",
        "urls": [
            "https://www.usgs.gov/special-topics/water-science-school/science/water-quality-information-topic",
            "https://en.wikipedia.org/wiki/Water_quality",
            "https://www.usgs.gov/special-topics/water-science-school/science/dissolved-oxygen-and-water",
            "https://www.usgs.gov/special-topics/water-science-school/science/ph-and-water",
            "https://www.usgs.gov/special-topics/water-science-school/science/turbidity-and-water",
            "https://www.usgs.gov/special-topics/water-science-school/science/nitrogen-and-water",
            "https://www.usgs.gov/special-topics/water-science-school/science/phosphorus-and-water",
            "https://www.usgs.gov/special-topics/water-science-school/science/hardness-water",
            "https://www.usgs.gov/special-topics/water-science-school/science/water-density",
            "https://www.epa.gov/nutrientpollution/problem",
            "https://www.epa.gov/wqc/national-recommended-water-quality-criteria-aquatic-life-criteria-table",
            "https://oceanservice.noaa.gov/facts/eutrophication.html",
            "https://en.wikipedia.org/wiki/Biochemical_oxygen_demand",
            "https://en.wikipedia.org/wiki/Trophic_state_index",
            "https://en.wikipedia.org/wiki/Macroinvertebrate",
            "https://en.wikipedia.org/wiki/Salinity",
        ],
    },
    # 2027 Dynamic Planet: Earth's fresh waters. Assembled against that season's scope —
    # hydrologic cycle and water budgets, climatic controls on freshwater distribution,
    # drainage basins and stream networks, fluvial sediment transport and channel form,
    # fluvial landforms, streamflow and floods, groundwater and karst. The USGS Water
    # Science School is a federal work and is the best single teaching source for this event.
    # 2027 Botany (Division B and C): plant structure, physiology, diversity and ecology.
    # Every page below was fetched and its extracted text measured before being added; the two
    # federal candidates tried (USDA hardiness map, NPS plants index) are shells and are absent.
    # Botany, a 2027 event with no course in either division. 102 pages measured with
    # `ground_event._fetch`, no two bodies identical — replacing a 30-URL set that covered
    # barely a third of the manual's topics.
    #
    # `www.usda.gov` returns 403 to this crawler, the way weather.gov does, so the main USDA
    # site is unusable; `fs.usda.gov` and `aphis.usda.gov` answer fine and carry the
    # ethnobotany, pollination, invasives and GMO-regulation material. `ars.usda.gov` returned
    # 502 on everything tried, which is why nutrient-deficiency symptoms rest on Wikipedia.
    #
    # Two NPS entries are lesson plans: real content on stomata, carbon movement and leaf
    # adaptation, interleaved with classroom procedure ("have groups switch plants"). They
    # pass the length bar honestly and will carry fewer claims than their size suggests.
    "botany": {
        "publisher": "Wikipedia contributors / USDA Forest Service / NPS / NASA / DOE",
        "license": "public_domain (federal) and CC-BY-SA 4.0 (Wikipedia, facts with attribution)",
        "urls": [
            # --- plant cell
            "https://en.wikipedia.org/wiki/Plant_cell",  # organelles, plastids, plasmodesmata
            "https://en.wikipedia.org/wiki/Cell_wall",  # primary and secondary wall, cellulose, lignin
            "https://en.wikipedia.org/wiki/Vacuole",  # central vacuole, turgor, tonoplast
            "https://en.wikipedia.org/wiki/Chloroplast",  # thylakoid and stroma, endosymbiosis
            # --- root stem leaf
            "https://en.wikipedia.org/wiki/Root",  # root cap, zones, taproot vs fibrous, mycorrhizae
            "https://en.wikipedia.org/wiki/Plant_stem",  # nodes, internodes, stem modifications
            "https://en.wikipedia.org/wiki/Leaf",  # blade and petiole, venation, mesophyll
            "https://en.wikipedia.org/wiki/Plant_anatomy",  # tissue systems
            "https://en.wikipedia.org/wiki/Plant_morphology",  # external form, growth habit
            "https://www.nps.gov/articles/the-advantages-of-having-green-stems-in-arid-environments.htm",  # stem photosynthesis, arid adaptation
            "https://www.fs.usda.gov/wildflowers/beauty/ferns/structure.shtml",  # frond, rhizome, pinnae
            # --- reproductive structures
            "https://en.wikipedia.org/wiki/Flower",  # sepal, petal, stamen, carpel
            "https://en.wikipedia.org/wiki/Sporangium",  # sporangia, sori
            "https://en.wikipedia.org/wiki/Plant_reproductive_morphology",  # flower and cone reproductive parts
            "https://en.wikipedia.org/wiki/Alternation_of_generations",  # sporophyte and gametophyte
            # --- growth
            "https://en.wikipedia.org/wiki/Meristem",  # apical and lateral meristems, primary vs secondary growth
            "https://en.wikipedia.org/wiki/Plant_hormone",  # auxin, gibberellin, cytokinin, ABA, ethylene
            "https://en.wikipedia.org/wiki/Auxin",  # polar transport, apical dominance
            "https://en.wikipedia.org/wiki/Tropism",  # photo, gravi and thigmotropism
            "https://en.wikipedia.org/wiki/Vascular_cambium",  # secondary xylem and phloem, growth rings
            "https://en.wikipedia.org/wiki/Germination",  # imbibition, dormancy, seedling emergence
            # --- transport
            "https://en.wikipedia.org/wiki/Xylem",  # tracheids, vessels, cohesion-tension
            "https://en.wikipedia.org/wiki/Phloem",  # sieve elements, companion cells, translocation
            "https://en.wikipedia.org/wiki/Vascular_tissue",  # vascular bundles
            "https://en.wikipedia.org/wiki/Transpiration",  # transpiration stream, rates and controls
            "https://en.wikipedia.org/wiki/Stoma",  # guard cells, gas exchange
            "https://en.wikipedia.org/wiki/Plant_physiology",  # water relations, nutrition, growth control
            "https://en.wikipedia.org/wiki/Plant_nutrition",  # macro and micronutrients, deficiency symptoms
            # --- diversity
            "https://en.wikipedia.org/wiki/Algae",  # algal groups, pigments, distinction from land plants
            "https://en.wikipedia.org/wiki/Embryophyte",  # land plant lineages
            "https://en.wikipedia.org/wiki/Woody_plant",  # wood formation, trees vs shrubs
            "https://en.wikipedia.org/wiki/Herbaceous_plant",  # annual, biennial, perennial
            "https://en.wikipedia.org/wiki/Wood",  # heartwood and sapwood, rings
            "https://www.fs.usda.gov/wildflowers/beauty/ferns/what.shtml",  # ferns vs seed plants, spores not seeds
            "https://en.wikipedia.org/wiki/Monocotyledon",  # monocot characters and families
            "https://en.wikipedia.org/wiki/Dicotyledon",  # dicot characters, eudicot split
            "https://en.wikipedia.org/wiki/Cryptogam",  # the historical cryptogam grouping
            "https://en.wikipedia.org/wiki/Plant_taxonomy",  # ranks, classification, APG
            "https://en.wikipedia.org/wiki/Bryophyte",  # mosses, liverworts, hornworts
            "https://en.wikipedia.org/wiki/Moss",  # moss structure and life cycle
            "https://en.wikipedia.org/wiki/Fern",  # fern life cycle, prothallus
            "https://en.wikipedia.org/wiki/Gymnosperm",  # naked seeds, four extant groups
            "https://en.wikipedia.org/wiki/Conifer",  # cones, needles, conifer wood
            "https://en.wikipedia.org/wiki/Flowering_plant",  # angiosperm traits, double fertilization
            # --- history
            "https://en.wikipedia.org/wiki/History_of_botany",  # Theophrastus to modern systematics
            "https://en.wikipedia.org/wiki/Botany",  # scope and subdisciplines
            # --- genetics and reproduction
            "https://en.wikipedia.org/wiki/Pollination",  # self and cross pollination, vectors
            "https://en.wikipedia.org/wiki/Pollen",  # pollen grain structure, palynology
            "https://en.wikipedia.org/wiki/Seed",  # seed coat, endosperm, embryo, dormancy
            "https://en.wikipedia.org/wiki/Seed_dispersal",  # wind, water, animal, ballistic
            "https://en.wikipedia.org/wiki/Mendelian_inheritance",  # segregation, independent assortment
            "https://en.wikipedia.org/wiki/Plant_breeding",  # hybridization and selection
            "https://www.fs.usda.gov/managing-land/wildflowers/pollinators/what-is-pollination",  # pollination mechanics
            "https://www.fs.usda.gov/managing-land/wildflowers/pollinators/syndromes",  # pollination syndromes
            "https://www.fs.usda.gov/wildflowers/pollinators/wind.shtml",  # wind and water pollination
            "https://www.fs.usda.gov/managing-land/wildflowers/pollinators/who-are-the-pollinators",  # pollinator taxa
            # --- photosynthesis
            "https://en.wikipedia.org/wiki/Photosynthesis",  # light and dark reactions, pigments
            "https://en.wikipedia.org/wiki/Calvin_cycle",  # carbon fixation, RuBisCO
            "https://en.wikipedia.org/wiki/C4_carbon_fixation",  # C4 anatomy and advantage
            "https://en.wikipedia.org/wiki/Crassulacean_acid_metabolism",  # CAM night fixation
            "https://en.wikipedia.org/wiki/Cellular_respiration",  # glycolysis, Krebs, ETC
            "https://www.energy.gov/science/doe-explainssolar-fuels",  # artificial vs natural photosynthesis
            "https://www.energy.gov/science/ber/articles/landmark-photosynthesis-gene-discovery-boosts-plant-growth-advances-crop",  # photosynthetic efficiency genetics
            "https://www.nps.gov/teachers/classrooms/matter-in-motion.htm",  # stomata, carbon movement (lesson plan)
            # --- evolution
            "https://en.wikipedia.org/wiki/Paleobotany",  # plant fossils and preservation
            "https://en.wikipedia.org/wiki/Evolutionary_history_of_plants",  # land colonization, vascular tissue, seeds, flowers
            # --- cycles
            "https://en.wikipedia.org/wiki/Carbon_cycle",  # fluxes, reservoirs, photosynthetic uptake
            "https://en.wikipedia.org/wiki/Nitrogen_cycle",  # fixation, nitrification, denitrification
            "https://en.wikipedia.org/wiki/Nitrogen_fixation",  # rhizobia, nodules, nitrogenase
            "https://en.wikipedia.org/wiki/Primary_production",  # GPP and NPP by biome
            "https://science.nasa.gov/earth/earth-observatory/the-carbon-cycle/",  # fast and slow carbon cycle
            "https://science.nasa.gov/earth/earth-observatory/measuring-vegetation-ndvi-evi/",  # NDVI, leaf reflectance
            "https://www.energy.gov/science/doe-explainsthe-carbon-cycle",  # carbon reservoirs and plant uptake
            "https://www.nps.gov/articles/000/plants-climateimpact.htm",  # plant responses to climate, phenology
            # --- human use
            "https://en.wikipedia.org/wiki/Ethnobotany",  # human plant use, methods
            "https://en.wikipedia.org/wiki/Fruit",  # fruit types and dispersal
            "https://www.fs.usda.gov/wildflowers/ethnobotany/food/index.shtml",  # native food plants
            "https://www.fs.usda.gov/wildflowers/ethnobotany/medicinal/index.shtml",  # medicinal plants and compounds
            "https://www.fs.usda.gov/wildflowers/ethnobotany/fibers.shtml",  # fiber plants, basketry, cordage
            "https://www.fs.usda.gov/managing-land/wildflowers/pollinators/importance",  # pollination and the food supply
            # --- ecology
            "https://en.wikipedia.org/wiki/Competition_(biology)",  # intra and interspecific competition
            "https://en.wikipedia.org/wiki/Plant_ecology",  # communities, limiting factors
            "https://en.wikipedia.org/wiki/Ecological_succession",  # primary and secondary succession
            "https://www.fs.usda.gov/wildflowers/invasives/index.shtml",  # invasive plants displacing natives
            "https://www.fs.usda.gov/wildflowers/beauty/index.shtml",  # wildflower adaptations to habitat
            "https://www.nps.gov/teachers/classrooms/plant-adaptations.htm",  # structure and function, desert leaves (lesson plan)
            # --- GMO and agriculture
            "https://en.wikipedia.org/wiki/Genetically_modified_crops",  # traits, Bt, herbicide tolerance
            "https://en.wikipedia.org/wiki/Genetically_modified_organism",  # techniques, regulation, debate
            "https://www.aphis.usda.gov/biotechnology",  # APHIS regulation of GE organisms
            "https://www.aphis.usda.gov/biotechnology/regulations",  # 7 CFR 340 and the agency split
            "https://www.aphis.usda.gov/biotechnology/about",  # Biotechnology Regulatory Services
            "https://en.wikipedia.org/wiki/Agriculture",  # crop production and systems
            "https://en.wikipedia.org/wiki/Cereal",  # grain crops, structure, yields
            "https://www.energy.gov/science/doe-explainsbioenergy-research",  # crops as feedstock
            "https://www.energy.gov/science/doe-explainsbiofuels",  # biomass to liquid fuel
            # --- disease
            "https://en.wikipedia.org/wiki/Plant_pathology",  # fungal, bacterial and viral pathogens
            "https://en.wikipedia.org/wiki/Plant_disease_resistance",  # PAMP and effector-triggered immunity
            "https://www.energy.gov/science/doe-explainsthe-plant-microbiome",  # root and leaf microbiome
            # --- station work
            "https://en.wikipedia.org/wiki/Herbarium",  # specimen preparation and curation
            "https://en.wikipedia.org/wiki/Optical_microscope",  # magnification, objectives, illumination
            "https://en.wikipedia.org/wiki/Microscope_slide",  # wet mounts and staining
            "https://www.fs.usda.gov/managing-land/wildflowers/kids/vocabulary",  # botany and ecology glossary
        ],
    },
    # Thermodynamics, a 2027 hybrid event with no course in either division. 125 pages
    # measured with `ground_event._fetch`, no two bodies identical.
    #
    # The physics is carried by Wikipedia and by NASA Glenn's Beginner's Guide; NIST covers
    # temperature and units genuinely well. The honest gap is the BUILD half: DOE's entire
    # consumer `energy.gov/energysaver/*` section — insulation, R-value, radiant barriers,
    # passive solar, the pages that would have taught the device — now returns 404 to this
    # crawler, every one of eleven paths tried. So insulation, absorptivity, surface colour
    # and thermal mass have no federal source at all and rest on Wikipedia.
    #
    # Fetch `grc.nasa.gov` SEQUENTIALLY. Eight parallel connections hang indefinitely; the
    # same URLs return in under a second one at a time.
    #
    # Two scope items have no source and none should be invented for them: the competition's
    # own rules (passive-only operation, banned materials, impound) and the specific
    # lamp-above-device temperature prediction. Both belong to a coach reading the manual.
    "thermodynamics": {
        "publisher": "Wikipedia contributors / NASA / NIST / NOAA / DOE",
        "license": "public_domain (federal) and CC-BY-SA 4.0 (Wikipedia, facts with attribution)",
        "urls": [
            # --- systems and properties
            "https://en.wikipedia.org/wiki/Thermodynamic_system",  # open, closed, isolated systems
            "https://en.wikipedia.org/wiki/Intensive_and_extensive_properties",  # intensive vs extensive
            "https://www.grc.nasa.gov/www/k-12/airplane/gasprop.html",  # gas property definitions
            "https://www.grc.nasa.gov/www/k-12/airplane/specvol.html",  # specific volume
            "https://www.grc.nasa.gov/www/k-12/airplane/spec.html",  # specific quantities per unit mass
            # --- temperature
            "https://en.wikipedia.org/wiki/Temperature",  # kinetic definition, scales, measurement
            "https://en.wikipedia.org/wiki/Zeroth_law_of_thermodynamics",  # transitivity of thermal equilibrium
            "https://en.wikipedia.org/wiki/Scale_of_temperature",  # empirical vs thermodynamic scales
            "https://en.wikipedia.org/wiki/Kelvin",  # kelvin, absolute scale
            "https://en.wikipedia.org/wiki/Celsius",  # Celsius and conversions
            "https://en.wikipedia.org/wiki/Fahrenheit",  # Fahrenheit and conversions
            "https://en.wikipedia.org/wiki/Absolute_zero",  # 0 K and the third law
            "https://en.wikipedia.org/wiki/Thermometer",  # thermometer types, calibration
            "https://en.wikipedia.org/wiki/Triple_point",  # triple point of water
            "https://www.nist.gov/si-redefinition/kelvin-introduction",  # what the kelvin is
            "https://www.nist.gov/si-redefinition/kelvin/kelvin-thermodynamic-temperature",  # thermodynamic temperature
            "https://www.nist.gov/si-redefinition/kelvin/kelvin-present-realization",  # realizing the kelvin
            "https://www.nist.gov/si-redefinition/kelvin/kelvin-its-90",  # ITS-90 fixed points
            "https://www.nist.gov/si-redefinition/kelvin/kelvin-future-realization",  # primary thermometry
            "https://www.nist.gov/pml/owm/si-units-temperature",  # SI temperature unit and conversions
            "https://www.nist.gov/pml/sensor-science/thermodynamic-metrology",  # thermodynamic measurement
            "https://www.grc.nasa.gov/www/k-12/airplane/temptr.html",  # temperature and molecular motion
            "https://www.grc.nasa.gov/www/k-12/airplane/thermo.html",  # the zeroth law
            # --- heat units
            "https://en.wikipedia.org/wiki/Heat",  # heat as energy in transit
            "https://en.wikipedia.org/wiki/Calorie",  # calorie and kilocalorie
            "https://en.wikipedia.org/wiki/British_thermal_unit",  # BTU and conversions
            "https://en.wikipedia.org/wiki/Joule",  # joule, mechanical equivalent of heat
            "https://en.wikipedia.org/wiki/Boltzmann_constant",  # energy per kelvin
            # --- phases
            "https://en.wikipedia.org/wiki/State_of_matter",  # solid, liquid, gas, plasma
            "https://en.wikipedia.org/wiki/Phase_transition",  # first-order transitions, critical point
            "https://en.wikipedia.org/wiki/Phase_diagram",  # P-T diagrams and phase boundaries
            "https://en.wikipedia.org/wiki/Latent_heat",  # latent heat of fusion and vaporization
            "https://en.wikipedia.org/wiki/Sensible_heat",  # sensible vs latent heat
            "https://en.wikipedia.org/wiki/Enthalpy_of_fusion",  # melting enthalpy
            # --- gas laws
            "https://en.wikipedia.org/wiki/Ideal_gas_law",  # PV=nRT and the combined gas laws
            "https://en.wikipedia.org/wiki/Ideal_gas",  # assumptions and deviations
            "https://www.grc.nasa.gov/www/k-12/airplane/eqstat.html",  # equation of state worked
            "https://www.grc.nasa.gov/www/k-12/airplane/kinth.html",  # kinetic theory of pressure
            # --- heat transfer
            "https://en.wikipedia.org/wiki/Heat_transfer",  # conduction, convection, radiation
            "https://en.wikipedia.org/wiki/Thermal_conduction",  # Fourier's law
            "https://en.wikipedia.org/wiki/Convection",  # natural vs forced convection
            "https://en.wikipedia.org/wiki/Thermal_radiation",  # emission spectra, radiative exchange
            "https://en.wikipedia.org/wiki/Thermal_conductivity_and_resistivity",  # k values and measurement
            "https://en.wikipedia.org/wiki/Newton%27s_law_of_cooling",  # cooling rate and delta-T
            "https://en.wikipedia.org/wiki/Thermal_contact_conductance",  # interface resistance
            "https://www.grc.nasa.gov/www/k-12/airplane/heat.html",  # heat capacity and direction of transfer
            "https://www.energy.gov/cmei/ito/process-heat-basics",  # delivering heat to a material
            # --- heat capacity
            "https://en.wikipedia.org/wiki/Heat_capacity",  # molar and volumetric heat capacity
            "https://en.wikipedia.org/wiki/Specific_heat_capacity",  # Q = mc dT and tabulated values
            "https://en.wikipedia.org/wiki/Calorimetry",  # calorimeter types
            "https://en.wikipedia.org/wiki/Properties_of_water",  # water's specific and latent heats
            "https://www.grc.nasa.gov/www/k-12/airplane/specheat.html",  # cp, cv and gamma
            # --- processes
            "https://en.wikipedia.org/wiki/Adiabatic_process",  # no heat exchange
            "https://en.wikipedia.org/wiki/Isothermal_process",  # constant temperature
            "https://en.wikipedia.org/wiki/Isochoric_process",  # constant volume
            "https://en.wikipedia.org/wiki/Isobaric_process",  # constant pressure
            "https://en.wikipedia.org/wiki/Work_(thermodynamics)",  # PV work and path dependence
            "https://en.wikipedia.org/wiki/Enthalpy",  # H = U + PV
            # --- cycles and engines
            "https://en.wikipedia.org/wiki/Thermodynamic_cycle",  # PV and TS diagrams
            "https://en.wikipedia.org/wiki/Heat_engine",  # reservoirs and work output
            "https://en.wikipedia.org/wiki/Carnot_cycle",  # Carnot cycle and maximum efficiency
            "https://en.wikipedia.org/wiki/Thermal_efficiency",  # efficiency and the Carnot limit
            "https://www.grc.nasa.gov/www/k-12/airplane/carnot.html",  # Carnot cycle worked
            "https://www.grc.nasa.gov/www/k-12/airplane/otto.html",  # Otto cycle, four strokes
            "https://www.grc.nasa.gov/www/k-12/airplane/brayton.html",  # Brayton cycle
            # --- laws
            "https://en.wikipedia.org/wiki/First_law_of_thermodynamics",  # energy conservation, dU = Q - W
            "https://en.wikipedia.org/wiki/Second_law_of_thermodynamics",  # Clausius and Kelvin statements
            "https://en.wikipedia.org/wiki/Entropy",  # entropy, statistical meaning
            "https://en.wikipedia.org/wiki/Internal_energy",  # U as a state function
            "https://en.wikipedia.org/wiki/Third_law_of_thermodynamics",  # entropy at absolute zero
            "https://www.grc.nasa.gov/www/k-12/airplane/thermo0.html",  # the laws overview
            "https://www.grc.nasa.gov/www/k-12/airplane/thermo1.html",  # the first law applied
            "https://www.grc.nasa.gov/www/k-12/airplane/thermo1f.html",  # energy conservation for a flow
            "https://www.grc.nasa.gov/www/k-12/airplane/entropy.html",  # entropy and the second law
            # --- history
            "https://en.wikipedia.org/wiki/History_of_thermodynamics",  # caloric to kinetic theory
            "https://en.wikipedia.org/wiki/William_Thomson,_1st_Baron_Kelvin",  # absolute scale, second law
            "https://en.wikipedia.org/wiki/Joseph_Black",  # latent and specific heat
            "https://en.wikipedia.org/wiki/James_Prescott_Joule",  # mechanical equivalent of heat
            "https://en.wikipedia.org/wiki/Nicolas_L%C3%A9onard_Sadi_Carnot",  # the ideal engine
            "https://en.wikipedia.org/wiki/Max_Planck",  # quantization, blackbody law
            "https://en.wikipedia.org/wiki/Rudolf_Clausius",  # entropy and the second law
            "https://en.wikipedia.org/wiki/Ludwig_Boltzmann",  # statistical entropy
            "https://en.wikipedia.org/wiki/James_Clerk_Maxwell",  # distribution and kinetic theory
            "https://www.nist.gov/si-redefinition/kelvin/kelvin-history",  # history of temperature standards
            # --- radiation
            "https://en.wikipedia.org/wiki/Black-body_radiation",  # ideal emitter, Wien displacement
            "https://en.wikipedia.org/wiki/Planck%27s_law",  # spectral radiance
            "https://en.wikipedia.org/wiki/Radiant_exitance",  # radiant exitance in W/m2
            "https://en.wikipedia.org/wiki/Irradiance",  # incident flux per area
            "https://en.wikipedia.org/wiki/Stefan%E2%80%93Boltzmann_law",  # M = sigma T^4
            "https://science.nasa.gov/ems/01_intro/",  # electromagnetic spectrum
            "https://science.nasa.gov/ems/02_anatomy/",  # anatomy of a wave
            "https://science.nasa.gov/ems/03_behaviors/",  # reflection, absorption, transmission
            "https://science.nasa.gov/ems/07_infraredwaves/",  # infrared as heat radiation
            "https://science.nasa.gov/ems/08_nearinfraredwaves/",  # emitted vs reflected infrared
            "https://science.nasa.gov/ems/09_visiblelight/",  # incandescent emission
            "https://imagine.gsfc.nasa.gov/science/toolbox/emspectrum1.html",  # photon energy and blackbody temperature
            "https://science.nasa.gov/earth/earth-observatory/climate-and-earths-energy-budget/",  # absorbed vs emitted radiation
            "https://gml.noaa.gov/grad/about/rad.html",  # solar and thermal IR in the energy budget
            "https://gml.noaa.gov/about/theme2.html",  # radiation and aerosol forcing
            "https://gml.noaa.gov/grad/surfrad/index.html",  # surface radiation budget measurement
            # --- collecting radiant energy
            "https://en.wikipedia.org/wiki/Incandescent_light_bulb",  # filament temperature, radiant output
            "https://en.wikipedia.org/wiki/Solar_thermal_collector",  # flat-plate collectors, glazing, absorber
            "https://en.wikipedia.org/wiki/Solar_water_heating",  # collector to water heat transfer
            "https://en.wikipedia.org/wiki/Solar_cooker",  # reflector geometry, aperture, absorber colour
            "https://www.energy.gov/cmei/systems/solar-radiation-basics",  # direct and diffuse radiation
            "https://www.energy.gov/cmei/systems/concentrating-solar-thermal-power",  # concentrating onto a receiver
            "https://www.energy.gov/cmei/systems/how-does-solar-work",  # the solar resource
            # --- absorptivity and insulation
            "https://en.wikipedia.org/wiki/Absorptance",  # absorptance and emissivity
            "https://en.wikipedia.org/wiki/Emissivity",  # emissivity by surface and finish
            "https://en.wikipedia.org/wiki/Kirchhoff%27s_law_of_thermal_radiation",  # good absorbers are good emitters
            "https://en.wikipedia.org/wiki/Albedo",  # reflectance and surface colour
            "https://en.wikipedia.org/wiki/Thermal_insulation",  # insulation mechanisms and materials
            "https://en.wikipedia.org/wiki/R-value_(insulation)",  # R-value, U-factor, units
            "https://en.wikipedia.org/wiki/Radiant_barrier",  # low-emissivity foil
            "https://en.wikipedia.org/wiki/Aerogel",  # very low conductivity insulation
            "https://en.wikipedia.org/wiki/Thermal_mass",  # heat storage and temperature swing
            "https://en.wikipedia.org/wiki/Greenhouse_effect",  # glazing and trapped infrared
            "https://www.energy.gov/cmei/buildings/articles/innovative-aerogel-production-low-cost-and-high-r-insulation",  # aerogel R-value
            "https://en.wikipedia.org/wiki/Vacuum_flask",  # defeating all three transfer modes
            # --- measurement and geometry
            "https://en.wikipedia.org/wiki/Inverse-square_law",  # flux falling as 1/d^2
            "https://en.wikipedia.org/wiki/Thermal_equilibrium",  # equilibrium and approach to room temperature
            "https://en.wikipedia.org/wiki/Significant_figures",  # significant figure rules
            "https://en.wikipedia.org/wiki/International_System_of_Units",  # SI base units and prefixes
            "https://www.nist.gov/pml/owm/metric-si/si-units",  # SI base and derived units
            "https://www.nist.gov/pml/owm/si-units-length",  # metric length and conversions
        ],
    },
    # 2027 Meteorology: Severe Weather & Storms. The federal teaching resources for exactly
    # this — NOAA JetStream, the SPC FAQs, the oceanservice facts pages — are JavaScript
    # shells or refuse this crawler outright, and an earlier pass concluded the subject was
    # blocked on a browser-rendered snapshot path. It was blocked on having tried only
    # federal hosts: 83 of 87 candidate pages here return substantive text, 3.4M characters
    # with no two bodies identical, every one measured with `ground_event._fetch` before it
    # was added. Wikipedia is rights-cleared in this project for fact grounding with
    # attribution, never for reproducing its expression.
    #
    # Figures remain the open gap: radar imagery, hodographs and Stüve diagrams ARE this
    # event, and no amount of prose teaches reading one.
    "severe_weather": {
        "publisher": "Wikipedia contributors / NOAA",
        "license": "CC-BY-SA 4.0 (facts used with attribution)",
        "urls": [
            "https://en.wikipedia.org/wiki/Severe_weather",  # storm types and severe-weather overview
            "https://en.wikipedia.org/wiki/Thunderstorm",  # single cell, multicell, life cycle
            "https://en.wikipedia.org/wiki/Supercell",  # supercell structure and classification
            "https://en.wikipedia.org/wiki/Mesocyclone",  # rotating updraft
            "https://en.wikipedia.org/wiki/Squall_line",  # squall lines
            "https://en.wikipedia.org/wiki/Derecho",  # derechos
            "https://en.wikipedia.org/wiki/Bow_echo",  # bow echo radar signature
            "https://en.wikipedia.org/wiki/Mesoscale_convective_system",  # MCS and MCC
            "https://en.wikipedia.org/wiki/Downburst",  # downbursts and macrobursts
            "https://en.wikipedia.org/wiki/Microburst",  # microbursts, wet and dry
            "https://en.wikipedia.org/wiki/Outflow_boundary",  # gust fronts
            "https://en.wikipedia.org/wiki/Tornado",  # tornado life cycle, tracks, geography
            "https://en.wikipedia.org/wiki/Tornadogenesis",  # formation conditions
            "https://en.wikipedia.org/wiki/Waterspout",  # waterspouts
            "https://en.wikipedia.org/wiki/Fujita_scale",  # F scale
            "https://en.wikipedia.org/wiki/Enhanced_Fujita_scale",  # EF scale and damage indicators
            "https://en.wikipedia.org/wiki/Hook_echo",  # hook echo and debris ball
            "https://en.wikipedia.org/wiki/Tornado_vortex_signature",  # TVS
            "https://en.wikipedia.org/wiki/Weather_radar",  # radar products and interpretation
            "https://en.wikipedia.org/wiki/NEXRAD",  # the US radar network
            "https://en.wikipedia.org/wiki/Doppler_radar",  # base velocity, storm relative motion
            "https://en.wikipedia.org/wiki/Polarimetric_radar",  # correlation coefficient, dual pol
            "https://en.wikipedia.org/wiki/Hodograph",  # hodographs and wind profiles
            "https://en.wikipedia.org/wiki/Skew-T_log-P_diagram",  # skew-T, LCL, CAPE on a sounding
            "https://en.wikipedia.org/wiki/Atmospheric_sounding",  # soundings and St\u00fcve diagrams
            "https://en.wikipedia.org/wiki/Radiosonde",  # radiosonde observation
            "https://en.wikipedia.org/wiki/METAR",  # METAR decoding
            "https://en.wikipedia.org/wiki/Station_model",  # surface station models
            "https://en.wikipedia.org/wiki/Automated_airport_weather_station",  # ASOS and surface networks
            "https://en.wikipedia.org/wiki/Convective_available_potential_energy",  # CAPE
            "https://en.wikipedia.org/wiki/Lifted_condensation_level",  # LCL
            "https://en.wikipedia.org/wiki/Convective_inhibition",  # CIN and capping
            "https://en.wikipedia.org/wiki/Wind_shear",  # speed and directional shear
            "https://en.wikipedia.org/wiki/Atmospheric_instability",  # stability and lapse rates
            "https://en.wikipedia.org/wiki/Jet_stream",  # jet streams and large-scale circulation
            "https://en.wikipedia.org/wiki/Air_mass",  # air masses
            "https://en.wikipedia.org/wiki/Weather_front",  # fronts
            "https://en.wikipedia.org/wiki/Dry_line",  # drylines
            "https://en.wikipedia.org/wiki/Atmospheric_river",  # atmospheric rivers
            "https://en.wikipedia.org/wiki/Precipitation",  # precipitation types and formation
            "https://en.wikipedia.org/wiki/Wegener%E2%80%93Bergeron%E2%80%93Findeisen_process",  # Bergeron process
            "https://en.wikipedia.org/wiki/Riming",  # riming and graupel
            "https://en.wikipedia.org/wiki/Hail",  # hail growth and size
            "https://en.wikipedia.org/wiki/Freezing_rain",  # freezing rain and temperature layers
            "https://en.wikipedia.org/wiki/Ice_pellets",  # sleet
            "https://en.wikipedia.org/wiki/Snow",  # snow, aggregation, snow load
            "https://en.wikipedia.org/wiki/Lightning",  # electrification, charge separation, types
            "https://en.wikipedia.org/wiki/Cloud_physics",  # collision-coalescence, droplet growth
            "https://en.wikipedia.org/wiki/Thunder",  # thunder and lightning detection
            "https://en.wikipedia.org/wiki/Tropical_cyclone",  # structure, stages, tracks
            "https://en.wikipedia.org/wiki/Saffir%E2%80%93Simpson_scale",  # Saffir-Simpson
            "https://en.wikipedia.org/wiki/Storm_surge",  # storm surge
            "https://en.wikipedia.org/wiki/Tropical_cyclogenesis",  # formation conditions, shear, SST
            "https://en.wikipedia.org/wiki/El_Ni%C3%B1o%E2%80%93Southern_Oscillation",  # ENSO influence on tracks
            "https://en.wikipedia.org/wiki/Blizzard",  # blizzards
            "https://en.wikipedia.org/wiki/Nor%27easter",  # nor'easters
            "https://en.wikipedia.org/wiki/Lake-effect_snow",  # lake effect snow and fetch
            "https://en.wikipedia.org/wiki/Ice_storm",  # ice storms
            "https://en.wikipedia.org/wiki/Drought",  # drought definitions and causes
            "https://en.wikipedia.org/wiki/Heat_wave",  # heat waves
            "https://en.wikipedia.org/wiki/Flash_flood",  # flash flooding
            "https://en.wikipedia.org/wiki/Flood",  # stream, river and urban flooding
            "https://en.wikipedia.org/wiki/Debris_flow",  # debris flows and mudslides
            "https://en.wikipedia.org/wiki/List_of_cloud_types",  # cloud types
            "https://en.wikipedia.org/wiki/Cumulonimbus_cloud",  # cumulonimbus
            "https://en.wikipedia.org/wiki/Mammatus_cloud",  # mammatus
            "https://en.wikipedia.org/wiki/Arcus_cloud",  # shelf and roll clouds
            "https://en.wikipedia.org/wiki/Severe_weather_terminology_(United_States)",  # watches and warnings
            "https://en.wikipedia.org/wiki/Storm_Prediction_Center",  # SPC outlooks
            "https://en.wikipedia.org/wiki/Weather_satellite",  # satellite imagery bands
            "https://en.wikipedia.org/wiki/Geostationary_Operational_Environmental_Satellite",  # GOES
            "https://en.wikipedia.org/wiki/Numerical_weather_prediction",  # computer model predictions
            "https://en.wikipedia.org/wiki/Intensity-duration-frequency_curve",  # IDF curves and return periods
            "https://en.wikipedia.org/wiki/Hurricane_Katrina",  # named event: Katrina 2005
            "https://en.wikipedia.org/wiki/Hurricane_Andrew",  # named event: Andrew 1992
            "https://en.wikipedia.org/wiki/Hurricane_Sandy",  # named event: Sandy 2012
            "https://en.wikipedia.org/wiki/1900_Galveston_hurricane",  # named event: Galveston 1900
            "https://en.wikipedia.org/wiki/2011_Super_Outbreak",  # named event: April 2011 outbreak
            "https://en.wikipedia.org/wiki/Great_Flood_of_1993",  # named event: 1993 flood
            "https://en.wikipedia.org/wiki/1993_Storm_of_the_Century",  # named event: March 1993
            "https://en.wikipedia.org/wiki/Dust_Bowl",  # named event: Dust Bowl
            "https://www.nhc.noaa.gov/aboutsshws.php",  # NHC on the Saffir-Simpson scale
            "https://www.spc.noaa.gov/misc/about.html",  # SPC mission and products
        ],
    },
    # 2027 Solar System: habitability, within the Solar System and beyond. 131 pages measured
    # with `ground_event._fetch`; 73 federal (science.nasa.gov, NSSDC, GSFC Imagine, NPS) and
    # 58 Wikipedia, which is rights-cleared here for fact grounding with attribution.
    #
    # Two measurement traps found while assembling this, both of which would have inflated the
    # count:
    #
    # 1. Every science.nasa.gov page carries ~5,750 characters of identical navigation and
    #    footer chrome, interleaved with the article so a content hash never collides. A
    #    7,600-character NASA page holds under 1,900 characters of actual content. Three
    #    mission pages kept here are that thin and are marked; each is the ONLY federal page
    #    for a named entity the manual lists, and each is paired with a Wikipedia article
    #    rather than pretending the entity is covered.
    # 2. The exoplanet catalog pages are a template: `trappist-1-e`, `kepler-452-b` and
    #    `lhs-1140-b` return ~6,200 characters of which ~500 differ between them. They pass a
    #    length threshold and teach nothing, and they are rejected.
    #
    # Honest gaps, recorded rather than papered over: Kepler-452 and LHS 1140 have no usable
    # federal page at all, and every physical law the manual names — Stefan-Boltzmann, Wien,
    # Kepler's laws, Newton's gravitation, escape velocity, the ideal gas law, Arrhenius —
    # has zero federal coverage, because NASA no longer hosts the derivations and the GRC
    # Beginner's Guide pages now 404. Those rest on Wikipedia. Reading and sketching data
    # displays has no grounding source at all; it is a skill to be authored, not a fact to be
    # cited.
    "astrobiology": {
        "publisher": "NASA / Wikipedia contributors",
        "license": "public_domain (NASA) and CC-BY-SA 4.0 (Wikipedia, facts with attribution)",
        "urls": [
            "https://science.nasa.gov/astrobiology/program-overview/",  # habitability, life's requirements
            "https://astrobiology.nasa.gov/about/",  # origin, evolution, distribution of life
            "https://science.nasa.gov/astrobiology/strategy/",  # biosignatures, habitable environments
            "https://science.nasa.gov/exoplanets/search-for-life/",  # searching for life beyond the Solar System
            "https://science.nasa.gov/exoplanets/can-we-find-life/",  # atmospheric biosignatures, false positives
            "https://science.nasa.gov/exoplanets/habitable-zone/",  # habitable zone, stellar-type dependence
            "https://en.wikipedia.org/wiki/Planetary_habitability",  # temperature, atmosphere retention
            "https://en.wikipedia.org/wiki/Astrobiology",  # discipline overview, habitability criteria
            "https://en.wikipedia.org/wiki/Circumstellar_habitable_zone",  # HZ boundaries, equilibrium temperature
            "https://en.wikipedia.org/wiki/Biosignature",  # biosignature types, chemical disequilibrium
            "https://science.nasa.gov/solar-system/ocean-worlds/",  # ocean worlds survey
            "https://en.wikipedia.org/wiki/Ocean_world",  # subsurface oceans, ice shells, evidence
            "https://en.wikipedia.org/wiki/Subsurface_ocean",  # extraterrestrial ocean physics
            "https://en.wikipedia.org/wiki/Tidal_heating",  # tidal dissipation as energy source
            "https://en.wikipedia.org/wiki/Tidal_force",  # tidal force, differential gravity
            "https://en.wikipedia.org/wiki/Cryovolcano",  # cryovolcanism
            "https://science.nasa.gov/venus/",  # Venus overview
            "https://science.nasa.gov/venus/venus-facts/",  # Venus atmosphere, surface, greenhouse
            "https://nssdc.gsfc.nasa.gov/planetary/factsheet/venusfact.html",  # numeric fact sheet: albedo, T_eq
            "https://en.wikipedia.org/wiki/Atmosphere_of_Venus",  # CO2 atmosphere, super-rotation, water loss
            "https://en.wikipedia.org/wiki/Runaway_greenhouse_effect",  # runaway greenhouse, inner HZ edge
            "https://science.nasa.gov/mars/",  # Mars overview
            "https://science.nasa.gov/mars/facts/",  # Mars properties, atmosphere, water history
            "https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html",  # gravity, escape velocity, albedo, T_eq
            "https://science.nasa.gov/planetary-science/programs/mars-exploration/science-goals/",  # follow the water, biosignatures
            "https://en.wikipedia.org/wiki/Water_on_Mars",  # morphological evidence, brines, polar ice
            "https://science.nasa.gov/mission/viking/",  # Viking biology experiments
            "https://science.nasa.gov/mission/msl-curiosity/",  # Gale crater lakebed, organics
            "https://science.nasa.gov/jupiter/jupiter-moons/ganymede/",  # magnetic field, subsurface ocean
            "https://en.wikipedia.org/wiki/Ganymede_(moon)",  # interior structure, aurorae ocean evidence
            "https://science.nasa.gov/jupiter/jupiter-moons/europa/",  # ice shell, chaos terrain, plumes
            "https://en.wikipedia.org/wiki/Europa_(moon)",  # composition, tidal heating, habitability
            "https://science.nasa.gov/saturn/moons/enceladus/",  # south-polar plumes, tiger stripes
            "https://en.wikipedia.org/wiki/Enceladus",  # plume chemistry, silica, hydrothermal activity
            "https://science.nasa.gov/saturn/moons/titan/",  # N2 atmosphere, methane lakes
            "https://en.wikipedia.org/wiki/Titan_(moon)",  # surface, methane cycle, prebiotic chemistry
            "https://en.wikipedia.org/wiki/Atmosphere_of_Titan",  # composition, haze, tholins
            "https://science.nasa.gov/saturn/moons/",  # Saturn satellite system context
            "https://science.nasa.gov/dwarf-planets/makemake/",  # KBO properties, methane ice
            "https://en.wikipedia.org/wiki/Makemake",  # orbit, spectra, thermal properties
            "https://science.nasa.gov/solar-system/asteroids/101955-bennu/",  # carbonaceous rubble pile, organics
            "https://en.wikipedia.org/wiki/101955_Bennu",  # composition, sample analysis, Yarkovsky
            "https://science.nasa.gov/solar-system/comets/67p-churyumov-gerasimenko/",  # nucleus, outgassing, Rosetta
            "https://en.wikipedia.org/wiki/67P/Churyumov%E2%80%93Gerasimenko",  # D/H ratio, organics, coma chemistry
            "https://science.nasa.gov/universe/exoplanets/hubble-probes-atmosphere-of-exoplanets-in-trappist-1-habitable-zone/",  # the only substantive federal TRAPPIST-1 page
            "https://en.wikipedia.org/wiki/TRAPPIST-1",  # seven planets, resonances, HZ members
            "https://en.wikipedia.org/wiki/Kepler-452b",  # Kepler-452; no usable federal page exists
            "https://en.wikipedia.org/wiki/LHS_1140",  # LHS 1140; no usable federal page exists
            "https://science.nasa.gov/mission/venus-express/",  # Venus Express science results
            "https://science.nasa.gov/mission/davinci/",  # DAVINCI descent probe
            "https://en.wikipedia.org/wiki/DAVINCI",  # instrument suite, descent profile
            "https://science.nasa.gov/mission/veritas/",  # VERITAS radar and emissivity mapping
            "https://science.nasa.gov/mission/mars-2020-perseverance/",  # Jezero delta, sample caching, SHERLOC
            "https://science.nasa.gov/mission/mars-reconnaissance-orbiter/",  # HiRISE, CRISM, SHARAD
            "https://science.nasa.gov/mission/maven/",  # atmospheric escape and volatile loss
            "https://science.nasa.gov/mission/galileo/",  # Europa ocean evidence, Ganymede magnetosphere
            "https://science.nasa.gov/mission/europa-clipper/",  # Europa Clipper overview
            "https://science.nasa.gov/mission/europa-clipper/mission-science/",  # ice shell, ocean, chemistry objectives
            "https://science.nasa.gov/mission/europa-clipper/spacecraft-instruments/",  # payload, radiation and power trade-offs
            "https://science.nasa.gov/mission/europa-clipper/why-europa-evidence-for-an-ocean/",  # induced magnetic field evidence
            "https://science.nasa.gov/mission/europa-clipper/why-europa-ingredients-for-life/",  # water, chemistry, energy
            "https://science.nasa.gov/mission/juice/",  # JUICE overview (thin: ~1.8k net of chrome)
            "https://en.wikipedia.org/wiki/Jupiter_Icy_Moons_Explorer",  # payload, Ganymede orbit phase
            "https://science.nasa.gov/mission/cassini/",  # Cassini, Enceladus plume discovery
            "https://en.wikipedia.org/wiki/Cassini%E2%80%93Huygens",  # orbiter and Huygens lander, instruments
            "https://science.nasa.gov/mission/dragonfly/",  # Dragonfly rotorcraft to Titan
            "https://science.nasa.gov/mission/dragonfly/science/",  # prebiotic chemistry objectives
            "https://science.nasa.gov/mission/dragonfly/spacecraft-and-instruments/",  # DraMS, DraGNS, flight design
            "https://en.wikipedia.org/wiki/Dragonfly_(Titan_space_probe)",  # design detail, landing sites, RTG power
            "https://science.nasa.gov/mission/osiris-rex/",  # OSIRIS-REx overview (thin: ~1.8k net)
            "https://en.wikipedia.org/wiki/OSIRIS-REx",  # TAGSAM, Bennu sample, amino acids
            "https://science.nasa.gov/mission/rosetta-philae/",  # Rosetta/Philae overview (thin: ~1.8k net)
            "https://en.wikipedia.org/wiki/Rosetta_(spacecraft)",  # instruments, 67P D/H ratio, glycine
            "https://science.nasa.gov/mission/kepler/",  # transit photometry, planet statistics
            "https://science.nasa.gov/mission/webb/",  # JWST overview
            "https://science.nasa.gov/mission/webb/other-worlds/",  # exoplanet transmission spectroscopy
            "https://science.nasa.gov/mission/webb/science-overview/",  # four science themes
            "https://science.nasa.gov/mission/webb/fact-sheet/",  # mirror, sunshield, L2, cryogenics
            "https://science.nasa.gov/mission/webb/nirspec/",  # NIRSpec design and modes
            "https://science.nasa.gov/mission/roman-space-telescope/exoplanets/",  # microlensing survey, coronagraph
            "https://en.wikipedia.org/wiki/Nancy_Grace_Roman_Space_Telescope",  # instruments, survey design
            "https://science.nasa.gov/exoplanets/missions/",  # exoplanet mission roster
            "https://science.nasa.gov/exoplanets/",  # exoplanet hub, five detection methods
            "https://science.nasa.gov/exoplanets/how-we-find-and-characterize/",  # transit, RV, microlensing, imaging
            "https://science.nasa.gov/exoplanets/planet-types/",  # planet classes
            "https://science.nasa.gov/exoplanets/facts/",  # discovery statistics
            "https://science.nasa.gov/exoplanets/stars/",  # host-star types and habitability
            "https://science.nasa.gov/exoplanets/glossary/",  # transit depth, RV semi-amplitude
            "https://en.wikipedia.org/wiki/Methods_of_detecting_exoplanets",  # all methods with governing equations
            "https://en.wikipedia.org/wiki/Transit_(astronomy)",  # transit geometry, depth, duration
            "https://en.wikipedia.org/wiki/Doppler_spectroscopy",  # radial velocity and its mass limits
            "https://en.wikipedia.org/wiki/Gravitational_microlensing",  # light curves, planet signatures
            "https://en.wikipedia.org/wiki/Radial_velocity",  # definition and measurement
            "https://science.nasa.gov/ems/",  # electromagnetic spectrum hub
            "https://science.nasa.gov/ems/01_intro/",  # wave and photon basics
            "https://imagine.gsfc.nasa.gov/science/toolbox/emspectrum1.html",  # EM spectrum primer, plain HTML
            "https://imagine.gsfc.nasa.gov/science/toolbox/spectra1.html",  # emission and absorption spectra
            "https://en.wikipedia.org/wiki/Stefan%E2%80%93Boltzmann_law",  # Stefan-Boltzmann law
            "https://en.wikipedia.org/wiki/Wien%27s_displacement_law",  # Wien's displacement law
            "https://en.wikipedia.org/wiki/Black-body_radiation",  # blackbody spectrum, Planck function
            "https://en.wikipedia.org/wiki/Planetary_equilibrium_temperature",  # T_eq from albedo and flux
            "https://en.wikipedia.org/wiki/Albedo",  # Bond vs geometric albedo
            "https://en.wikipedia.org/wiki/Inverse-square_law",  # inverse-square flux scaling
            "https://en.wikipedia.org/wiki/Doppler_effect",  # Doppler shift including light
            "https://en.wikipedia.org/wiki/Spectroscopy",  # spectral identification of composition
            "https://en.wikipedia.org/wiki/Greenhouse_effect",  # greenhouse forcing, surface temperature
            "https://en.wikipedia.org/wiki/Kepler%27s_laws_of_planetary_motion",  # Kepler's three laws
            "https://en.wikipedia.org/wiki/Newton%27s_law_of_universal_gravitation",  # Newtonian gravitation
            "https://en.wikipedia.org/wiki/Escape_velocity",  # escape velocity, atmospheric retention
            "https://en.wikipedia.org/wiki/Atmospheric_escape",  # Jeans, hydrodynamic, sputtering escape
            "https://en.wikipedia.org/wiki/Kinetic_energy",  # kinetic energy in orbital contexts
            "https://en.wikipedia.org/wiki/Potential_energy",  # gravitational potential energy
            "https://en.wikipedia.org/wiki/Ideal_gas_law",  # ideal gas law
            "https://en.wikipedia.org/wiki/Arrhenius_equation",  # reaction-rate temperature dependence
            "https://en.wikipedia.org/wiki/Chemical_equilibrium",  # equilibrium and disequilibrium
            "https://en.wikipedia.org/wiki/Organic_compound",  # organics delivered and detected
            "https://en.wikipedia.org/wiki/Properties_of_water",  # phase diagram, solvent properties
            "https://en.wikipedia.org/wiki/Ice",  # crystalline ice phases
            "https://en.wikipedia.org/wiki/Amorphous_ice",  # LDA/HDA ice, comets and icy moons
            "https://en.wikipedia.org/wiki/Clathrate_hydrate",  # clathrates, methane hydrate
            "https://en.wikipedia.org/wiki/Brine",  # brines, freezing-point depression
            "https://en.wikipedia.org/wiki/Protein",  # proteins and amino acids
            "https://en.wikipedia.org/wiki/Nucleic_acid",  # DNA and RNA structure
            "https://en.wikipedia.org/wiki/Lipid",  # lipids and membranes
            "https://en.wikipedia.org/wiki/Carbohydrate",  # carbohydrates
            "https://en.wikipedia.org/wiki/Abiogenesis",  # prebiotic chemistry, origin of life
            "https://en.wikipedia.org/wiki/Extremophile",  # categories and limits of life
            "https://en.wikipedia.org/wiki/Chemolithotroph",  # chemolithoautotrophic metabolism
            "https://en.wikipedia.org/wiki/Tardigrade",  # cryptobiosis and survival limits
            "https://www.nps.gov/yell/learn/nature/life-in-extreme-heat.htm",  # Yellowstone thermophiles, federal
            "https://science.nasa.gov/solar-system/planetary-analogs/",  # terrestrial analog environments
            "https://science.nasa.gov/asteroids-comets-meteors/",  # small-body volatile inventory
            "https://science.nasa.gov/solar-system/comets/",  # comet structure, coma, volatiles
            "https://science.nasa.gov/solar-system/asteroids/",  # asteroid classes
            "https://science.nasa.gov/solar-system/kuiper-belt/",  # Kuiper Belt reservoir
            "https://en.wikipedia.org/wiki/Comet",  # composition, D/H ratios, organics
            "https://en.wikipedia.org/wiki/Origin_of_water_on_Earth",  # cometary vs asteroidal delivery
            "https://en.wikipedia.org/wiki/Late_Heavy_Bombardment",  # impact delivery epoch
            "https://en.wikipedia.org/wiki/Dimensional_analysis",  # dimensional analysis
            "https://en.wikipedia.org/wiki/Order_of_magnitude",  # order-of-magnitude estimation
            "https://en.wikipedia.org/wiki/Scientific_notation",  # scientific notation arithmetic
        ],
    },
    # 2027 Anatomy & Physiology: respiratory, digestive and immune. 207 pages measured with
    # `ground_event._fetch`, all >= 2,000 characters with 207 distinct content hashes: 115
    # federal (NHLBI, NIDDK, NIAID, NIAMS, MedlinePlus, CDC, NCI) and 92 Wikipedia.
    #
    # Three findings that shaped this list:
    #
    # 1. NIAID SERVES ITS 404 PAGE WITH HTTP 200 AND 8,807 CHARACTERS. Five candidate URLs
    #    passed a length threshold while containing nothing but a navigation menu; only the
    #    content hash, identical across all five, gave them away. Length is not a validity
    #    test. `ensure_snapshot` now rejects a body whose hash it has already stored for a
    #    different URL in the same run, which is what catches this class.
    # 2. `/all-content` is the whole game on NIDDK. A tabbed topic page returns ~2,500
    #    characters of teaser; the same URL plus `/all-content` returns the full article.
    #    Crohn's disease goes from 2,511 to 20,429 characters. Twelve URLs here use it.
    # 3. NCBI BOOKSHELF IS A .GOV HOST THAT SERVES COPYRIGHTED TEXTBOOKS. Janeway's
    #    Immunobiology, Molecular Biology of the Cell and InformedHealth were all checked and
    #    all rejected; StatPearls is CC BY-NC-ND, whose NoDerivatives term a generated course
    #    would violate. That is exactly why complement, Toll-like receptors and the Gell and
    #    Coombs typing fall back to Wikipedia: the ideal sources exist and we may not use them.
    #
    # One topic is genuinely uncovered and recorded rather than faked: "digestive effects of
    # exercise". Obesity is covered well; exercise and digestion is taught by no page in
    # either source pool.
    "anatomy_2027": {
        "publisher": "National Institutes of Health / CDC / Wikipedia contributors",
        "license": "public_domain (federal) and CC-BY-SA 4.0 (Wikipedia, facts with attribution)",
        "urls": [
            # --- respiratory
            "https://www.nhlbi.nih.gov/health/lung-tests",  # spirometry, lung volume tests, diffusion capacity
            "https://www.nhlbi.nih.gov/health/blood-tests",  # blood chemistry panels including blood gases
            "https://www.nhlbi.nih.gov/health/copd",  # COPD, airway and alveolar damage
            "https://www.nhlbi.nih.gov/health/copd/causes",  # COPD causes, alpha-1 antitrypsin deficiency
            "https://www.nhlbi.nih.gov/health/copd/diagnosis",  # COPD diagnosis, spirometry interpretation
            "https://www.nhlbi.nih.gov/health/copd/treatment",  # COPD drugs, oxygen, surgery
            "https://www.nhlbi.nih.gov/health/asthma",  # asthma basics
            "https://www.nhlbi.nih.gov/health/asthma/causes",  # asthma triggers, airway inflammation
            "https://www.nhlbi.nih.gov/health/asthma/diagnosis",  # asthma diagnosis, lung function testing
            "https://www.nhlbi.nih.gov/health/sleep-apnea",  # obstructive and central sleep apnea
            "https://www.nhlbi.nih.gov/health/cystic-fibrosis",  # CFTR, mucus, lung involvement
            "https://www.nhlbi.nih.gov/health/idiopathic-pulmonary-fibrosis",  # pulmonary fibrosis
            "https://medlineplus.gov/copd.html",  # COPD summary
            "https://medlineplus.gov/asthma.html",  # asthma summary
            "https://medlineplus.gov/genetics/condition/cystic-fibrosis/",  # CF genetics and pathophysiology
            "https://medlineplus.gov/genetics/condition/alpha-1-antitrypsin-deficiency/",  # emphysema mechanism
            "https://www.cdc.gov/copd/about/index.html",  # COPD epidemiology and risk
            "https://www.cdc.gov/asthma/about/index.html",  # asthma attack mechanism, triggers
            "https://www.cdc.gov/pneumonia/about/index.html",  # pneumonia causes and types
            "https://www.cdc.gov/tb/about/index.html",  # TB infection vs disease
            "https://www.cdc.gov/tb/signs-symptoms/index.html",  # TB clinical picture
            "https://www.cdc.gov/cystic-fibrosis/about/index.html",  # cystic fibrosis
            "https://www.cdc.gov/sleep/about/index.html",  # sleep and apnea context
            "https://www.cdc.gov/lung-cancer/about/index.html",  # lung cancer basics
            "https://www.cdc.gov/niosh/pneumoconioses/about/index.html",  # pneumoconioses
            "https://www.niaid.nih.gov/diseases-conditions/tuberculosis",  # TB immunology
            "https://www.cancer.gov/types/lung/patient/non-small-cell-lung-treatment-pdq",  # NSCLC, NCI public domain
            "https://www.cancer.gov/types/lung/patient/lung-prevention-pdq",  # lung cancer prevention
            "https://www.cancer.gov/about-cancer/causes-prevention/risk/tobacco/cessation-fact-sheet",  # smoking and prevention
            "https://en.wikipedia.org/wiki/Respiratory_system",  # whole-system anatomy and function
            "https://en.wikipedia.org/wiki/Respiratory_tract",  # conducting vs respiratory zone
            "https://en.wikipedia.org/wiki/Lung",  # lobes and lung anatomy
            "https://en.wikipedia.org/wiki/Pulmonary_alveolus",  # alveoli, surfactant, type I and II cells
            "https://en.wikipedia.org/wiki/Bronchus",  # bronchial tree
            "https://en.wikipedia.org/wiki/Trachea",  # airway histology
            "https://en.wikipedia.org/wiki/Pleural_cavity",  # pleura and pleural pressure
            "https://en.wikipedia.org/wiki/Thoracic_diaphragm",  # diaphragm mechanics
            "https://en.wikipedia.org/wiki/Breathing",  # ventilation mechanics, breathing patterns
            "https://en.wikipedia.org/wiki/Control_of_ventilation",  # regulation of breathing
            "https://en.wikipedia.org/wiki/Respiratory_center",  # respiratory rhythm generation
            "https://en.wikipedia.org/wiki/Chemoreceptor",  # central and peripheral chemoreceptors
            "https://en.wikipedia.org/wiki/Spirometry",  # spirogram reading, FEV1/FVC
            "https://en.wikipedia.org/wiki/Lung_volumes",  # TV, IRV, ERV, RV and capacities
            "https://en.wikipedia.org/wiki/Vital_capacity",  # vital capacity
            "https://en.wikipedia.org/wiki/Gas_exchange",  # diffusion and partial pressures
            "https://en.wikipedia.org/wiki/Oxygen%E2%80%93hemoglobin_dissociation_curve",  # dissociation curve and shifts
            "https://en.wikipedia.org/wiki/Hemoglobin",  # O2 transport, cooperativity
            "https://en.wikipedia.org/wiki/Bohr_effect",  # curve right-shift
            "https://en.wikipedia.org/wiki/Blood_gas_tension",  # PaO2 and PaCO2
            "https://en.wikipedia.org/wiki/Arterial_blood_gas_test",  # ABG interpretation
            "https://en.wikipedia.org/wiki/Acid%E2%80%93base_homeostasis",  # respiratory acidosis and alkalosis
            "https://en.wikipedia.org/wiki/Effects_of_high_altitude_on_humans",  # altitude acclimatization
            "https://en.wikipedia.org/wiki/Altitude_sickness",  # AMS, HAPE, HACE
            "https://en.wikipedia.org/wiki/Exercise_physiology",  # respiratory response to exercise
            "https://en.wikipedia.org/wiki/VO2_max",  # aerobic capacity
            "https://en.wikipedia.org/wiki/Emphysema",  # emphysema
            "https://en.wikipedia.org/wiki/Pulmonary_edema",  # pulmonary edema; no federal page
            "https://en.wikipedia.org/wiki/Pleurisy",  # pleurisy; no federal page
            "https://en.wikipedia.org/wiki/Pulmonary_fibrosis",  # pulmonary fibrosis
            "https://en.wikipedia.org/wiki/Pneumoconiosis",  # pneumoconioses
            "https://en.wikipedia.org/wiki/Asbestosis",  # a named pneumoconiosis
            "https://en.wikipedia.org/wiki/Bronchodilator",  # treatment: drugs
            "https://en.wikipedia.org/wiki/Mechanical_ventilation",  # treatment
            "https://en.wikipedia.org/wiki/Oxygen_therapy",  # treatment
            "https://en.wikipedia.org/wiki/Lung_transplantation",  # treatment: surgery
            # --- digestive
            "https://www.niddk.nih.gov/health-information/digestive-diseases/digestive-system-how-it-works",  # alimentary canal, accessory organs, enzymes
            "https://www.niddk.nih.gov/health-information/digestive-diseases/peptic-ulcers-stomach-ulcers/all-content",  # peptic ulcer disease
            "https://www.niddk.nih.gov/health-information/digestive-diseases/acid-reflux-ger-gerd-adults/all-content",  # GERD
            "https://www.niddk.nih.gov/health-information/digestive-diseases/ulcerative-colitis/all-content",  # ulcerative colitis
            "https://www.niddk.nih.gov/health-information/digestive-diseases/crohns-disease/all-content",  # Crohn's disease
            "https://www.niddk.nih.gov/health-information/digestive-diseases/celiac-disease/all-content",  # celiac disease
            "https://www.niddk.nih.gov/health-information/digestive-diseases/diverticulosis-diverticulitis/all-content",  # diverticular disease
            "https://www.niddk.nih.gov/health-information/digestive-diseases/lactose-intolerance/all-content",  # lactose intolerance, lactase
            "https://www.niddk.nih.gov/health-information/digestive-diseases/diarrhea/all-content",  # diarrhea
            "https://www.niddk.nih.gov/health-information/digestive-diseases/appendicitis/all-content",  # appendicitis
            "https://www.niddk.nih.gov/health-information/digestive-diseases/gastritis-gastropathy/all-content",  # gastric mucosal injury, H. pylori
            "https://www.niddk.nih.gov/health-information/digestive-diseases/microscopic-colitis/all-content",  # colonic lining, IBD contrast
            "https://www.niddk.nih.gov/health-information/liver-disease/cirrhosis/all-content",  # liver function and failure
            "https://www.niddk.nih.gov/health-information/liver-disease/viral-hepatitis/hepatitis-a",  # hepatitis A
            "https://www.niddk.nih.gov/health-information/liver-disease/viral-hepatitis/hepatitis-b",  # hepatitis B
            "https://www.niddk.nih.gov/health-information/liver-disease/viral-hepatitis/hepatitis-c",  # hepatitis C
            "https://www.niddk.nih.gov/health-information/weight-management/adult-overweight-obesity/all-content",  # obesity and digestive effects
            "https://www.cdc.gov/hepatitis/about/index.html",  # viral hepatitis overview
            "https://www.cdc.gov/hepatitis-a/about/index.html",  # hepatitis A transmission
            "https://www.cdc.gov/hepatitis-b/about/index.html",  # hepatitis B
            "https://www.cdc.gov/hepatitis-c/about/index.html",  # hepatitis C
            "https://www.cancer.gov/types/colorectal/patient/colon-treatment-pdq",  # colon cancer
            "https://www.cancer.gov/types/stomach/patient/stomach-treatment-pdq",  # gastric cancer
            "https://www.cancer.gov/types/esophageal/patient/esophageal-treatment-pdq",  # esophageal cancer, Barrett link
            "https://www.cancer.gov/types/liver/patient/adult-liver-treatment-pdq",  # liver cancer
            "https://en.wikipedia.org/wiki/Human_digestive_system",  # full GI anatomy
            "https://en.wikipedia.org/wiki/Gastrointestinal_tract",  # alimentary canal
            "https://en.wikipedia.org/wiki/Gastrointestinal_wall",  # the four layers of the gut wall
            "https://en.wikipedia.org/wiki/Mucosa",  # layer 1
            "https://en.wikipedia.org/wiki/Submucosa",  # layer 2, Meissner plexus
            "https://en.wikipedia.org/wiki/Muscular_layer",  # layer 3, muscularis externa, Auerbach plexus
            "https://en.wikipedia.org/wiki/Serous_membrane",  # layer 4, serosa and adventitia
            "https://en.wikipedia.org/wiki/Mucous_membrane",  # epithelial lining types
            "https://en.wikipedia.org/wiki/Esophagus",  # stratified squamous lining
            "https://en.wikipedia.org/wiki/Stomach",  # rugae and gastric glands
            "https://en.wikipedia.org/wiki/Gastric_mucosa",  # parietal, chief and G cells
            "https://en.wikipedia.org/wiki/Small_intestine",  # duodenum, jejunum, ileum
            "https://en.wikipedia.org/wiki/Intestinal_villus",  # villi and microvilli
            "https://en.wikipedia.org/wiki/Intestinal_epithelium",  # enterocytes, goblet, Paneth, crypts
            "https://en.wikipedia.org/wiki/Large_intestine",  # colon, no villi
            "https://en.wikipedia.org/wiki/Digestion",  # mechanical vs chemical digestion
            "https://en.wikipedia.org/wiki/Digestive_enzyme",  # enzyme and substrate table
            "https://en.wikipedia.org/wiki/Peristalsis",  # motility
            "https://en.wikipedia.org/wiki/Pepsin",  # protein digestion
            "https://en.wikipedia.org/wiki/Trypsin",  # pancreatic protein digestion
            "https://en.wikipedia.org/wiki/Amylase",  # carbohydrate digestion
            "https://en.wikipedia.org/wiki/Lipase",  # fat digestion
            "https://en.wikipedia.org/wiki/Bile",  # emulsification, liver role
            "https://en.wikipedia.org/wiki/Liver",  # liver role in digestion
            "https://en.wikipedia.org/wiki/Pancreas",  # pancreas role in digestion
            "https://en.wikipedia.org/wiki/Kupffer_cell",  # Kupffer cells; no federal page exists
            "https://en.wikipedia.org/wiki/Gastrointestinal_physiology",  # secretion, motility, absorption
            "https://en.wikipedia.org/wiki/Obesity",  # obesity effects
            # --- immune
            "https://www.niaid.nih.gov/research/immune-system-overview",  # immune anatomy: marrow, thymus, spleen, nodes, skin
            "https://www.niaid.nih.gov/diseases-conditions/autoimmune-diseases",  # autoimmunity and tolerance
            "https://www.niaid.nih.gov/diseases-conditions/primary-immune-deficiency-diseases-pidds",  # primary immunodeficiency, CVID
            "https://www.niaid.nih.gov/diseases-conditions/severe-combined-immunodeficiency-scid",  # SCID
            "https://www.niaid.nih.gov/diseases-conditions/hivaids",  # HIV/AIDS immunopathogenesis
            "https://www.niaid.nih.gov/diseases-conditions/food-allergy",  # IgE allergic reaction
            "https://www.niaid.nih.gov/research/vaccines",  # vaccines and prevention
            "https://medlineplus.gov/immunesystemanddisorders.html",  # immune system summary
            "https://medlineplus.gov/autoimmunediseases.html",  # autoimmunity summary
            "https://medlineplus.gov/hiv.html",  # HIV/AIDS
            "https://medlineplus.gov/multiplesclerosis.html",  # multiple sclerosis
            "https://medlineplus.gov/myastheniagravis.html",  # myasthenia gravis
            "https://medlineplus.gov/myositis.html",  # dermatomyositis and polymyositis
            "https://medlineplus.gov/organtransplantation.html",  # transplantation
            "https://medlineplus.gov/genetics/condition/common-variable-immune-deficiency/",  # CVID
            "https://medlineplus.gov/genetics/condition/systemic-lupus-erythematosus/",  # lupus
            "https://medlineplus.gov/genetics/condition/multiple-sclerosis/",  # MS mechanism
            "https://medlineplus.gov/genetics/condition/rheumatoid-arthritis/",  # RA mechanism
            "https://medlineplus.gov/genetics/condition/celiac-disease/",  # celiac as immune disease
            "https://www.niams.nih.gov/health-topics/lupus",  # lupus
            "https://www.niams.nih.gov/health-topics/rheumatoid-arthritis",  # rheumatoid arthritis
            "https://www.niams.nih.gov/health-topics/psoriasis",  # psoriasis
            "https://www.niams.nih.gov/health-topics/psoriatic-arthritis",  # psoriatic arthritis
            "https://www.niams.nih.gov/health-topics/scleroderma",  # scleroderma
            "https://www.niddk.nih.gov/health-information/endocrine-diseases/hashimotos-disease",  # Hashimoto thyroiditis
            "https://www.niddk.nih.gov/health-information/endocrine-diseases/graves-disease",  # Graves' disease
            "https://www.cdc.gov/hiv/about/index.html",  # HIV transmission and stages
            "https://www.cdc.gov/vaccines/basics/index.html",  # how vaccines work
            "https://www.cancer.gov/about-cancer/treatment/types/immunotherapy",  # cancer immunotherapies
            "https://www.cancer.gov/about-cancer/treatment/types/immunotherapy/t-cell-transfer-therapy",  # T-cell transfer and TIL
            "https://www.cancer.gov/about-cancer/treatment/research/car-t-cells",  # CAR-T cell therapy
            "https://www.cancer.gov/about-cancer/treatment/types/immunotherapy/monoclonal-antibodies",  # antibody therapies
            "https://en.wikipedia.org/wiki/Immune_system",  # whole-system overview
            "https://en.wikipedia.org/wiki/Lymphatic_system",  # immune anatomy
            "https://en.wikipedia.org/wiki/Lymph_node",  # immune anatomy
            "https://en.wikipedia.org/wiki/Thymus",  # T-cell maturation
            "https://en.wikipedia.org/wiki/Spleen",  # red and white pulp
            "https://en.wikipedia.org/wiki/Bone_marrow",  # haematopoiesis
            "https://en.wikipedia.org/wiki/Human_skin",  # barrier immunity
            "https://en.wikipedia.org/wiki/Innate_immune_system",  # innate immunity
            "https://en.wikipedia.org/wiki/Complement_system",  # complement; no federal page exists
            "https://en.wikipedia.org/wiki/Toll-like_receptor",  # Toll-like receptors; no federal page
            "https://en.wikipedia.org/wiki/Inflammation",  # inflammatory cascade
            "https://en.wikipedia.org/wiki/Macrophage",  # innate cells
            "https://en.wikipedia.org/wiki/Neutrophil",  # innate cells
            "https://en.wikipedia.org/wiki/Natural_killer_cell",  # innate cells
            "https://en.wikipedia.org/wiki/Dendritic_cell",  # innate to adaptive bridge
            "https://en.wikipedia.org/wiki/Adaptive_immune_system",  # adaptive immunity
            "https://en.wikipedia.org/wiki/T_cell",  # CD4 and CD8 subsets
            "https://en.wikipedia.org/wiki/B_cell",  # humoral immunity
            "https://en.wikipedia.org/wiki/Antibody",  # immunoglobulin classes and structure
            "https://en.wikipedia.org/wiki/Major_histocompatibility_complex",  # MHC I and II, transplant matching
            "https://en.wikipedia.org/wiki/Antigen-presenting_cell",  # antigen presentation
            "https://en.wikipedia.org/wiki/Allergy",  # allergic reaction
            "https://en.wikipedia.org/wiki/Hypersensitivity",  # Gell and Coombs types 1-4
            "https://en.wikipedia.org/wiki/Type_I_hypersensitivity",  # type 1
            "https://en.wikipedia.org/wiki/Type_II_hypersensitivity",  # type 2
            "https://en.wikipedia.org/wiki/Type_III_hypersensitivity",  # type 3
            "https://en.wikipedia.org/wiki/Type_IV_hypersensitivity",  # type 4
            "https://en.wikipedia.org/wiki/Anaphylaxis",  # type 1 exemplar
            "https://en.wikipedia.org/wiki/Hives",  # urticaria
            "https://en.wikipedia.org/wiki/Myasthenia_gravis",  # type 2 exemplar
            "https://en.wikipedia.org/wiki/Serum_sickness",  # type 3 exemplar
            "https://en.wikipedia.org/wiki/Arthus_reaction",  # Arthus reaction; no federal page
            "https://en.wikipedia.org/wiki/Immunodeficiency",  # immunodeficiency overview
            "https://en.wikipedia.org/wiki/HIV/AIDS",  # HIV/AIDS
            "https://en.wikipedia.org/wiki/Common_variable_immunodeficiency",  # CVID
            "https://en.wikipedia.org/wiki/Severe_combined_immunodeficiency",  # SCID
            "https://en.wikipedia.org/wiki/Autoimmune_disease",  # autoimmunity
            "https://en.wikipedia.org/wiki/Multiple_sclerosis",  # multiple sclerosis
            "https://en.wikipedia.org/wiki/Rheumatoid_arthritis",  # rheumatoid arthritis
            "https://en.wikipedia.org/wiki/Hashimoto%27s_thyroiditis",  # Hashimoto thyroiditis
            "https://en.wikipedia.org/wiki/Graves%27_disease",  # Graves' disease
            "https://en.wikipedia.org/wiki/Organ_transplantation",  # transplant types
            "https://en.wikipedia.org/wiki/Transplant_rejection",  # rejection prevention
            "https://en.wikipedia.org/wiki/Allotransplantation",  # allograft
            "https://en.wikipedia.org/wiki/Autotransplantation",  # autograft
            "https://en.wikipedia.org/wiki/Chimeric_antigen_receptor_T_cell",  # CAR-T mechanism
            "https://en.wikipedia.org/wiki/Cancer_immunotherapy",  # cancer immunotherapy
            "https://en.wikipedia.org/wiki/Monoclonal_antibody_therapy",  # antibody therapies
            "https://en.wikipedia.org/wiki/Systemic_lupus_erythematosus",  # lupus
            "https://en.wikipedia.org/wiki/Dermatomyositis",  # dermatomyositis; NIAMS has no page
            "https://en.wikipedia.org/wiki/Systemic_scleroderma",  # scleroderma
            "https://en.wikipedia.org/wiki/Psoriasis",  # psoriasis
            "https://en.wikipedia.org/wiki/Psoriatic_arthritis",  # psoriatic arthritis
            "https://en.wikipedia.org/wiki/Immunosuppressive_drug",  # treatments for immune disorders
            "https://en.wikipedia.org/wiki/Vaccine",  # prevention
            "https://en.wikipedia.org/wiki/Corticosteroid",  # treatments, both systems
            "https://en.wikipedia.org/wiki/Antihistamine",  # allergy treatment
        ],
    },
    # 2027 Water Quality: marine, estuary and coral reef. 144 pages measured with
    # `ground_event._fetch`, no two bodies identical.
    #
    # NOAA is the authority for this subject and is also where the measuring gets dangerous.
    # Eleven guessed `oceanservice.noaa.gov/facts/` slugs return a 330-character "Page Not
    # Found" body with HTTP 200 and the same hash — a soft 404 that an earlier pass recorded
    # as one real page counted three times. The slugs here were harvested from the real index
    # pages instead of guessed. All four `coris.noaa.gov/about/` pages redirect to a homepage,
    # so CoRIS, which the plan named as a preferred host, cannot be used at all.
    #
    # `www.usgs.gov` is slow and intermittently 504s but is NOT blocked: six pages came
    # through and carry turbidity, dissolved oxygen, pH, coliform, nitrate and phosphate. Five
    # more timed out and are worth retrying rather than dropping.
    #
    # Wikipedia titles here are the CANONICAL ones, resolved through the MediaWiki API. A
    # redirect is internal — the URL and status do not change and a "(Redirected from X)"
    # banner adds about 35 characters — so `Grouper` and `Epinephelinae`, or `Dissolved
    # oxygen` and `Oxygen saturation`, hash DIFFERENTLY while being the same article, and a
    # content-hash guard cannot see it. 17 such alias pairs were resolved out of this list.
    "water_quality_marine": {
        "publisher": "NOAA / EPA / USGS / NPS / Wikipedia contributors",
        "license": "public_domain (federal) and CC-BY-SA 4.0 (Wikipedia, facts with attribution)",
        "urls": [
            # --- NOAA estuaries tutorial
            "https://oceanservice.noaa.gov/education/tutorial_estuaries/est01_whatis.html",  # what an estuary is
            "https://oceanservice.noaa.gov/education/tutorial_estuaries/est02_economy.html",  # importance of estuaries
            "https://oceanservice.noaa.gov/education/tutorial_estuaries/est03_ecosystem.html",  # estuary ecosystem structure
            "https://oceanservice.noaa.gov/education/tutorial_estuaries/est04_geology.html",  # estuary formation
            "https://oceanservice.noaa.gov/education/tutorial_estuaries/est05_circulation.html",  # salinity gradients, stratification
            "https://oceanservice.noaa.gov/education/tutorial_estuaries/est06_habitats.html",  # estuarine habitats
            "https://oceanservice.noaa.gov/education/tutorial_estuaries/est07_adaptations.html",  # osmoregulation, salinity tolerance
            "https://oceanservice.noaa.gov/education/tutorial_estuaries/est08_natdisturb.html",  # natural disturbance
            "https://oceanservice.noaa.gov/education/tutorial_estuaries/est09_humandis.html",  # human disturbance, nutrients, sediment
            "https://oceanservice.noaa.gov/education/tutorial_estuaries/est10_monitor.html",  # every monitoring parameter and why each test
            "https://oceanservice.noaa.gov/education/tutorial_estuaries/est11_future.html",  # estuary management
            # --- NOAA corals tutorial
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral01_intro.html",  # coral anatomy and polyp
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral02_zooxanthellae.html",  # symbiosis, zooxanthellae
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral03_growth.html",  # calcification, aragonite skeleton
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral04_reefs.html",  # reef types and formation
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral05_distribution.html",  # Indo-Pacific vs Atlantic distribution
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral06_reproduction.html",  # reef organism life cycles
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral07_importance.html",  # reef ecosystem services
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral08_climatechange.html",  # bleaching, acidification, SST
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral09_pollution.html",  # sedimentation and nutrient pollution
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral10_disease.html",  # recently killed coral, reef health
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral11_fishing.html",  # overfishing, indicator fish
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral12_other_threats.html",  # crown-of-thorns, invasives
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral13_protecting-coral-law.html",  # reef management and law
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral14_protecting-coral-places.html",  # marine protected areas
            "https://oceanservice.noaa.gov/education/tutorial_corals/coral15_restoring-corals.html",  # restoration
            # --- NOAA ocean facts
            "https://oceanservice.noaa.gov/hazards/hab/",  # harmful algal blooms, red tide, hypoxia
            "https://oceanservice.noaa.gov/facts/estuary.html",  # estuary definition
            "https://oceanservice.noaa.gov/facts/coral.html",  # coral as animal, plant and mineral
            "https://oceanservice.noaa.gov/facts/coral_bleach.html",  # bleaching mechanism
            "https://oceanservice.noaa.gov/facts/coral-pollution.html",  # land-based pollution on reefs
            "https://oceanservice.noaa.gov/facts/coral-overfishing.html",  # overfishing, herbivore loss
            "https://oceanservice.noaa.gov/facts/coral-spawning.html",  # coral reproduction
            "https://oceanservice.noaa.gov/facts/reef-resilience.html",  # reef health indicators
            "https://oceanservice.noaa.gov/facts/coral_economy.html",  # reef value
            "https://oceanservice.noaa.gov/facts/coralreef-climate.html",  # climate and reefs
            "https://oceanservice.noaa.gov/facts/artificial-reef.html",  # artificial reefs
            "https://oceanservice.noaa.gov/facts/brain-coral.html",  # stony coral example
            "https://oceanservice.noaa.gov/facts/sponge.html",  # demosponge ecology
            "https://oceanservice.noaa.gov/facts/lionfish.html",  # harmful invasive species
            "https://oceanservice.noaa.gov/facts/acidification.html",  # acidification, aragonite saturation
            "https://oceanservice.noaa.gov/facts/thermocline.html",  # temperature structure
            "https://oceanservice.noaa.gov/facts/sea-surface-temperature.html",  # SST measurement
            "https://oceanservice.noaa.gov/facts/ocean-oxygen.html",  # dissolved oxygen
            "https://oceanservice.noaa.gov/facts/eutrophication.html",  # nutrient enrichment
            "https://oceanservice.noaa.gov/facts/deadzone.html",  # hypoxic dead zones
            "https://oceanservice.noaa.gov/facts/redtide.html",  # red tide
            "https://oceanservice.noaa.gov/facts/hab-solutions.html",  # HAB management
            "https://oceanservice.noaa.gov/facts/nutpollution.html",  # nutrient pollution
            "https://oceanservice.noaa.gov/facts/pollution.html",  # marine pollution overview
            "https://oceanservice.noaa.gov/facts/plankton.html",  # base of the marine food web
            "https://oceanservice.noaa.gov/facts/garbagepatch.html",  # the five garbage patches
            "https://oceanservice.noaa.gov/facts/microplastics.html",  # microplastics
            "https://oceanservice.noaa.gov/facts/disaster-debris.html",  # marine debris sources
            "https://oceanservice.noaa.gov/facts/watershed.html",  # watersheds
            "https://oceanservice.noaa.gov/facts/wetland.html",  # wetlands
            "https://oceanservice.noaa.gov/facts/nature-based.html",  # nature-based coastal management
            "https://www.pmel.noaa.gov/co2/story/Ocean+Acidification",  # carbonate chemistry, saturation state
            # --- EPA
            "https://www.epa.gov/nep/overview-national-estuary-program",  # estuary management
            "https://www.epa.gov/coral-reefs/basic-information-about-coral-reefs",  # reef ecology
            "https://www.epa.gov/coral-reefs/threats-coral-reefs",  # factors that harm reefs
            "https://www.epa.gov/nutrientpollution/basic-information-nutrient-pollution",  # nitrogen and phosphorus pollution
            "https://www.epa.gov/nutrientpollution/sources-and-solutions",  # nutrient sources
            "https://www.epa.gov/nutrientpollution/effects-environment",  # HABs and hypoxia effects
            "https://www.epa.gov/nps/basic-information-about-nonpoint-source-nps-pollution",  # nonpoint source pollution
            "https://www.epa.gov/nps/nonpoint-source-agriculture",  # agricultural runoff, sediment
            "https://www.epa.gov/npdes/stormwater-discharges-construction-activities",  # sedimentation pollution control
            "https://www.epa.gov/wqc/national-recommended-water-quality-criteria-aquatic-life-criteria-table",  # numeric criteria per parameter
            "https://www.epa.gov/sdwa/drinking-water-regulations-and-contaminants",  # potable water standards
            "https://www.epa.gov/sdwa/how-epa-regulates-drinking-water-contaminants",  # treatment and regulation
            "https://www.epa.gov/pfas/pfas-explained",  # PFAS basics
            "https://www.epa.gov/pfas/our-current-understanding-human-health-and-environmental-risks-pfas",  # emerging contaminants
            "https://www.epa.gov/marine-protection-permitting/about-marine-protection-research-and-sanctuaries-act",  # ocean dumping
            # --- NPS
            "https://www.nps.gov/subjects/oceans/coral-reefs.htm",  # reef ecology
            "https://www.nps.gov/subjects/oceans/estuaries.htm",  # estuary ecology
            # --- USGS water science school
            "https://www.usgs.gov/water-science-school/science/turbidity-and-water",  # turbidity
            "https://www.usgs.gov/water-science-school/science/dissolved-oxygen-and-water",  # dissolved oxygen
            "https://www.usgs.gov/water-science-school/science/ph-and-water",  # pH
            "https://www.usgs.gov/water-science-school/science/bacteria-and-e-coli-water",  # fecal coliform and E. coli
            "https://www.usgs.gov/water-science-school/science/nitrogen-and-water",  # nitrates
            "https://www.usgs.gov/water-science-school/science/phosphorus-and-water",  # phosphates
            # --- Wikipedia
            "https://en.wikipedia.org/wiki/Water_quality",  # parameters and their relationships
            "https://en.wikipedia.org/wiki/Salinity",  # salinity
            "https://en.wikipedia.org/wiki/Seawater",  # composition, density and salinity
            "https://en.wikipedia.org/wiki/Oxygen_saturation",  # DO saturation; canonical title
            "https://en.wikipedia.org/wiki/Turbidity",  # turbidity, NTU, Secchi
            "https://en.wikipedia.org/wiki/PH",  # pH
            "https://en.wikipedia.org/wiki/Ocean_temperature",  # temperature
            "https://en.wikipedia.org/wiki/Nitrate",  # nitrates
            "https://en.wikipedia.org/wiki/Phosphate",  # phosphates
            "https://en.wikipedia.org/wiki/Biochemical_oxygen_demand",  # BOD
            "https://en.wikipedia.org/wiki/Total_dissolved_solids",  # total solids
            "https://en.wikipedia.org/wiki/Total_suspended_solids",  # suspended solids
            "https://en.wikipedia.org/wiki/Fecal_coliform",  # fecal coliform
            "https://en.wikipedia.org/wiki/Aragonite",  # aragonite
            "https://en.wikipedia.org/wiki/Ocean_acidification",  # aragonite saturation state
            "https://en.wikipedia.org/wiki/Density",  # density, salinometer theory
            "https://en.wikipedia.org/wiki/Hydrometer",  # hydrometer build and calibration
            "https://en.wikipedia.org/wiki/Salinometer",  # salinometer
            "https://en.wikipedia.org/wiki/Mass_fraction_(chemistry)",  # percent salinity by mass
            "https://en.wikipedia.org/wiki/Estuary",  # estuary ecology
            "https://en.wikipedia.org/wiki/Seagrass",  # estuarine and reef macroflora
            "https://en.wikipedia.org/wiki/Mangrove",  # estuarine habitat
            "https://en.wikipedia.org/wiki/Coral_reef",  # reef ecology
            "https://en.wikipedia.org/wiki/Coral_bleaching",  # bleaching, recently killed coral
            "https://en.wikipedia.org/wiki/Coral_disease",  # reef health indicators
            "https://en.wikipedia.org/wiki/Stony_coral_tissue_loss_disease",  # SCTLD
            "https://en.wikipedia.org/wiki/Environmental_issues_with_coral_reefs",  # threats
            "https://en.wikipedia.org/wiki/Coral_reef_protection",  # reef management
            "https://en.wikipedia.org/wiki/Coral_reef_fish",  # reef fish ecology and distribution
            "https://en.wikipedia.org/wiki/Zooxanthellae",  # symbiosis
            "https://en.wikipedia.org/wiki/Symbiodinium",  # symbiont biology
            "https://en.wikipedia.org/wiki/Algae",  # fleshy algae overview
            "https://en.wikipedia.org/wiki/Harmful_algal_bloom",  # HABs
            "https://en.wikipedia.org/wiki/Eutrophication",  # nutrient enrichment
            "https://en.wikipedia.org/wiki/Dead_zone_(ecology)",  # hypoxic zones
            "https://en.wikipedia.org/wiki/Hypoxia_(environmental)",  # hypoxia
            "https://en.wikipedia.org/wiki/Great_Pacific_Garbage_Patch",  # garbage patch
            "https://en.wikipedia.org/wiki/Ocean_gyre",  # the five gyres
            "https://en.wikipedia.org/wiki/Marine_debris",  # marine debris
            "https://en.wikipedia.org/wiki/PFAS",  # PFAS
            "https://en.wikipedia.org/wiki/Environmental_impact_of_pharmaceuticals_and_personal_care_products",  # medicines as contaminants
            "https://en.wikipedia.org/wiki/Water_purification",  # potable water treatment
            "https://en.wikipedia.org/wiki/Sewage_treatment",  # waste water treatment
            "https://en.wikipedia.org/wiki/Wastewater_treatment",  # treatment overview
            "https://en.wikipedia.org/wiki/Water_cycle",  # water cycle
            "https://en.wikipedia.org/wiki/Nutrient_cycle",  # nutrient cycling
            "https://en.wikipedia.org/wiki/Nitrogen_cycle",  # nitrogen cycling in water
            "https://en.wikipedia.org/wiki/Watershed_management",  # watershed management
            "https://en.wikipedia.org/wiki/Drainage_basin",  # watersheds
            "https://en.wikipedia.org/wiki/Siltation",  # sedimentation pollution; canonical title
            "https://en.wikipedia.org/wiki/Nonpoint_source_pollution",  # nonpoint source pollution
            "https://en.wikipedia.org/wiki/Marine_food_web",  # aquatic food webs
            "https://en.wikipedia.org/wiki/Food_web",  # food chains and webs
            "https://en.wikipedia.org/wiki/Trophic_level",  # trophic structure
            "https://en.wikipedia.org/wiki/Symbiosis",  # community interactions
            "https://en.wikipedia.org/wiki/Herbivore",  # grazing by parrotfish and urchins
            "https://en.wikipedia.org/wiki/Population_dynamics",  # population dynamics
            "https://en.wikipedia.org/wiki/Bioindicator",  # indicator organisms
            "https://en.wikipedia.org/wiki/Reef_Check",  # the survey protocol behind the indicator list
            "https://en.wikipedia.org/wiki/Indo-Pacific",  # Indo-Pacific distribution
            "https://en.wikipedia.org/wiki/Atlantic_Ocean",  # Atlantic distribution
            "https://en.wikipedia.org/wiki/Marine_protected_area",  # reef management
            "https://en.wikipedia.org/wiki/Overfishing",  # overfishing
            # --- the 23 organisms the manual names, one page each
            #
            # Identification is 30% of this event (Part II), and the manual asks for the
            # general ecology, life cycle and feeding habits of each listed organism. The
            # topic sources above cover reefs and estuaries and say almost nothing about any
            # INDIVIDUAL organism, and the course said so itself: its identification lessons
            # reported "Sweetlips identification and feeding", "identify a demosponge" and
            # "Banded coral shrimp cleaning" as unsupported. Thirty percent of the event had
            # no evidence behind it.
            #
            # These are the same pages the specimen-image roster uses, so the photograph a
            # student sees and the text the course teaches from come from one place. All 25
            # measured, all distinct.
            "https://en.wikipedia.org/wiki/Stenopus_hispidus",  # Banded coral shrimp (Stenopus hispidus)
            "https://en.wikipedia.org/wiki/Chaetodon",  # Butterfly fish (Chaetodon spp.)
            "https://en.wikipedia.org/wiki/Crown-of-thorns_starfish",  # Crown of thorns starfish (Acanthaster planci)
            "https://en.wikipedia.org/wiki/Red_algae",  # Fleshy algae: Rhodophyta
            "https://en.wikipedia.org/wiki/Green_algae",  # Fleshy algae: Chlorophyta
            "https://en.wikipedia.org/wiki/Brown_algae",  # Fleshy algae: Phaeophyta
            "https://en.wikipedia.org/wiki/Grouper",  # Grouper >30 cm (Serranidae, Epinephelinae)
            "https://en.wikipedia.org/wiki/Scleractinia",  # Hard/stony corals (Scleractinia)
            "https://en.wikipedia.org/wiki/Lobster",  # Lobsters (Nephropidae)
            "https://en.wikipedia.org/wiki/Diadema_(echinoderm)",  # Long-spined black sea urchins (Diadematidae/Diadema spp.)
            "https://en.wikipedia.org/wiki/Moray_eel",  # Moray eel (Muraenidae)
            "https://en.wikipedia.org/wiki/Parrotfish",  # Parrotfish >20 cm (Scaridae)
            "https://en.wikipedia.org/wiki/Eucidaris",  # Pencil urchins (Eucidaris spp.)
            "https://en.wikipedia.org/wiki/Sea_cucumber",  # Sea cucumber (Holothuroidea)
            "https://en.wikipedia.org/wiki/Lutjanidae",  # Snapper (Lutjanidae)
            "https://en.wikipedia.org/wiki/Demosponge",  # Demosponges (Demospongiae)
            "https://en.wikipedia.org/wiki/Haemulidae",  # Sweetlips (Haemulidae)
            "https://en.wikipedia.org/wiki/Charonia_tritonis",  # Triton (Charoniidae/Charonia spp.)
            "https://en.wikipedia.org/wiki/Humpback_grouper",  # Barramundi cod (Cromileptes altivelis)
            "https://en.wikipedia.org/wiki/Green_humphead_parrotfish",  # Bumphead parrotfish (Bolbometopon muricatum)
            "https://en.wikipedia.org/wiki/Tridacna",  # Giant clams (Tridacna spp.)
            "https://en.wikipedia.org/wiki/Humphead_wrasse",  # Humphead wrasse (Cheilinus undulatus)
            "https://en.wikipedia.org/wiki/Flamingo_tongue_snail",  # Flamingo tongue snail (Cyphoma gibbosum)
            "https://en.wikipedia.org/wiki/Gorgonia_ventalina",  # Gorgonia (Octocorallia)
            "https://en.wikipedia.org/wiki/Nassau_grouper",  # Nassau grouper (Epinephelus striatus)
        ],
    },
    "hydrology": {
        "publisher": "USGS Water Science School / National Park Service",
        "license": "public_domain",
        "urls": [
            "https://www.usgs.gov/special-topics/water-science-school/science/water-cycle",
            "https://www.usgs.gov/special-topics/water-science-school/science/watersheds-and-drainage-basins",
            "https://www.usgs.gov/special-topics/water-science-school/science/surface-runoff-and-water-cycle",
            "https://www.usgs.gov/special-topics/water-science-school/science/infiltration-and-water-cycle",
            "https://www.usgs.gov/special-topics/water-science-school/science/evaporation-and-water-cycle",
            "https://www.usgs.gov/special-topics/water-science-school/science/evapotranspiration-and-water-cycle",
            "https://www.usgs.gov/special-topics/water-science-school/science/groundwater-storage-and-water-cycle",
            "https://www.usgs.gov/special-topics/water-science-school/science/aquifers-and-groundwater",
            "https://www.usgs.gov/special-topics/water-science-school/science/groundwater-decline-and-depletion",
            "https://www.usgs.gov/special-topics/water-science-school/science/streamflow-and-water-cycle",
            "https://www.usgs.gov/special-topics/water-science-school/science/how-streamflow-measured",
            "https://www.usgs.gov/special-topics/water-science-school/science/floods-and-recurrence-intervals",
            "https://www.usgs.gov/special-topics/water-science-school/science/sediment-and-suspended-sediment",
            "https://www.usgs.gov/special-topics/water-science-school/science/lakes-and-reservoirs",
            "https://www.usgs.gov/special-topics/water-science-school/science/springs-and-water-cycle",
            "https://www.nps.gov/subjects/caves/index.htm",
            "https://www.nps.gov/subjects/geology/fluvial-landforms.htm",
            "https://www.nps.gov/subjects/rivers/index.htm",
            "https://en.wikipedia.org/wiki/Drainage_basin",
            "https://en.wikipedia.org/wiki/Drainage_system_(geomorphology)",
            "https://en.wikipedia.org/wiki/Strahler_number",
            "https://en.wikipedia.org/wiki/Drainage_density",
            "https://en.wikipedia.org/wiki/Fluvial_processes",
            "https://en.wikipedia.org/wiki/Sediment_transport",
            "https://en.wikipedia.org/wiki/Hjulstr%C3%B6m_curve",
            "https://en.wikipedia.org/wiki/Braided_river",
            "https://en.wikipedia.org/wiki/Meander",
            "https://en.wikipedia.org/wiki/Sinuosity",
            "https://en.wikipedia.org/wiki/Oxbow_lake",
            "https://en.wikipedia.org/wiki/Floodplain",
            "https://en.wikipedia.org/wiki/Alluvial_fan",
            "https://en.wikipedia.org/wiki/River_delta",
            "https://en.wikipedia.org/wiki/Levee",
            "https://en.wikipedia.org/wiki/Point_bar",
            "https://en.wikipedia.org/wiki/Cut_bank",
            "https://en.wikipedia.org/wiki/Base_level",
            "https://en.wikipedia.org/wiki/Knickpoint",
            "https://en.wikipedia.org/wiki/Graded_stream",
            "https://en.wikipedia.org/wiki/Stream_capture",
            "https://en.wikipedia.org/wiki/Discharge_(hydrology)",
            "https://en.wikipedia.org/wiki/Hydrograph",
            "https://en.wikipedia.org/wiki/Return_period",
            "https://en.wikipedia.org/wiki/Manning_formula",
            "https://en.wikipedia.org/wiki/Bed_form",
            "https://en.wikipedia.org/wiki/Aquifer",
            "https://en.wikipedia.org/wiki/Water_table",
            "https://en.wikipedia.org/wiki/Artesian_aquifer",
            "https://en.wikipedia.org/wiki/Karst",
            "https://en.wikipedia.org/wiki/Sinkhole",
            "https://en.wikipedia.org/wiki/Speleothem",
            "https://en.wikipedia.org/wiki/Rain_shadow",
            "https://en.wikipedia.org/wiki/Orographic_lift",
            "https://en.wikipedia.org/wiki/Ephemeral_stream",
            "https://en.wikipedia.org/wiki/Playa_lake",
            "https://en.wikipedia.org/wiki/Evaporite",
            "https://en.wikipedia.org/wiki/Critical_zone",
            "https://en.wikipedia.org/wiki/Water_balance",
            "https://en.wikipedia.org/wiki/Residence_time",
            # Lakes, wetlands and the climate controls on them. The 2027 course's first
            # authoring run keyed nine checkpoints to "the supplied evidence does not define
            # this" — continentality, lake effect, turnover, wetland types — and a count of the
            # retained passages shows why: 0 mentioned continentality and 1 mentioned turnover.
            # The prompt has since been told to return insufficient_evidence instead of writing
            # a lesson about the absence, which turns that gap into a refusal to author; these
            # close the gap itself. Each measured with `ground_event._fetch` before being added.
            "https://en.wikipedia.org/wiki/Lake_stratification",
            "https://en.wikipedia.org/wiki/Thermocline",
            "https://en.wikipedia.org/wiki/Dimictic_lake",
            "https://en.wikipedia.org/wiki/Limnology",
            "https://en.wikipedia.org/wiki/Eutrophication",
            "https://en.wikipedia.org/wiki/Continental_climate",
            "https://en.wikipedia.org/wiki/Lake-effect_snow",
            "https://en.wikipedia.org/wiki/Wetland",
            "https://en.wikipedia.org/wiki/Marsh",
            "https://en.wikipedia.org/wiki/Swamp",
            "https://en.wikipedia.org/wiki/Bog",
            "https://en.wikipedia.org/wiki/Fen",
            "https://en.wikipedia.org/wiki/Riparian_zone",
            "https://en.wikipedia.org/wiki/Estuary",
            "https://www.epa.gov/wetlands/what-wetland",
        ],
    },
}

# event slug (division-agnostic) -> domain
def domain_for_event(slug: str) -> str | None:
    """The open-source domain for an event slug, checked against the season first.

    A rotating-topic event keeps its name and changes its subject. Dynamic Planet was mapped
    to `oceanography` with no season in the key, so grounding a 2027 freshwater event pulled
    ocean circulation and tides — and produced eight lessons on the wrong body of material,
    which no audit of "does this course have sources?" would ever flag, because it does.
    `EVENT_DOMAIN_BY_SEASON` is consulted before `EVENT_DOMAIN` so a rotation is a data change
    rather than a silently wrong course.

    `EVENT_DOMAIN` is keyed on base slugs — `heredity`, not `heredity-b`. `build_courses`
    already stripped the suffix before looking one up; `ground_event` did not, and looked up
    the full slug. So grounding raised "no open-source domain mapped" for essentially the whole
    catalog, because almost every real event carries a division suffix: of 102 active events
    only the three unsuffixed rocks-and-minerals rows ever matched. Two call sites, two
    spellings of the same key, and the mismatch read as "this event has no sources" — a content
    gap — rather than as a lookup bug.

    Seasoned slugs (`botany-b-2027`) are handled here too, for the same reason.
    """
    raw = str(slug or "")
    season_match = re.search(r"-((?:19|20)\d{2})$", raw)
    season = int(season_match.group(1)) if season_match else None
    base = re.sub(r"-(19|20)\d{2}$", "", raw)
    base = re.sub(r"-[bc]$", "", base)
    if season is not None and (base, season) in EVENT_DOMAIN_BY_SEASON:
        return EVENT_DOMAIN_BY_SEASON[(base, season)]
    return EVENT_DOMAIN.get(base)


# (base slug, season) -> domain, for events whose tested subject rotates between seasons.
# Every entry here is a topic confirmed against that season's official rules manual, and an
# event that rotates MUST be listed for each season it is authored for — the fallback in
# EVENT_DOMAIN is the last season someone checked, not a safe default.
EVENT_DOMAIN_BY_SEASON = {
    # 2027 Division B/C: "Earth's fresh waters" — drainage basins, fluvial landforms,
    # streamflow, groundwater and karst. 2026 was oceanography, 2025 glaciers.
    ("dynamic-planet", 2027): "hydrology",
    # 2027 Division B/C: "Severe Weather & Storms" — radar and sounding interpretation, storm
    # types, hazards and safety. 2026 was everyday weather and climate, which is what the
    # `meteorology` domain still holds.
    ("meteorology", 2027): "severe_weather",
    # 2027 Division B: "Habitability within and beyond the Solar System". 2026 was an object
    # survey, which is what the `astronomy` domain still holds.
    ("solar-system", 2027): "astrobiology",
    # 2027 Division B/C: respiratory, digestive and immune systems. 2026 was nervous and
    # endocrine, which is what the `anatomy` domain still holds.
    ("anatomy-and-physiology", 2027): "anatomy_2027",
    # 2027 Division B: marine and estuary ecology, coral reef organisms and water monitoring.
    # 2026 was freshwater macroinvertebrates, which is what the `water` domain still holds, and
    # reusing it would teach a whole season of the wrong ecosystem.
    ("water-quality", 2027): "water_quality_marine",
    # 2027 Division B: the manual's Heredity topic list runs from Mendelian crosses to Sanger
    # sequencing and calls itself exhaustive. The `genetics` domain holds eighteen pages,
    # which grounded 350 claims across a thirty-two lesson blueprint — a course written from
    # that would be thin everywhere and say so nowhere.
    ("heredity", 2027): "genetics_2027",
    # 2027 Division B: Food Science is a DAIRY event this season and the manual scopes its
    # written exam to dairy topics only. There was no `food-science` domain at all, so
    # `domain_for_event` returned None and grounding would have skipped the event entirely.
    ("food-science", 2027): "dairy_food_science",
    # 2027 Division B: the manual lists Crime Busters' unknowns by name and half the score is
    # identifying them. `forensics` holds thirteen general pages and not one of the named
    # substances, so an identification lesson had nothing about the thing being identified.
    ("crime-busters", 2027): "forensics_2027",
    # 2027 Division B: the manual's cipher list is exhaustive and the `cryptography` domain
    # names four of its thirteen types.
    ("codebusters", 2027): "cryptography_2027",
    # 2027 Division B: `circuit-lab` reaches the shared `physics` domain, which covers
    # mechanics for the build events. It has nothing on logic gates, PN junctions, GFCIs or
    # De Morgan's law, all of which the manual puts on the written test.
    ("circuit-lab", 2027): "circuits_2027",
    # 2027 Division B/C: "Observable Earth". Interpretation is 65-75% of the points and is
    # limited to a closed list of platforms; `remote_sensing` held fourteen pages and named
    # three of them.
    ("remote-sensing", 2027): "remote_sensing_2027",
    # 2027 Division B: neither of these events has a written exam. Experimental Design is
    # scored by the official checklist against a report written on site; Write It Do It by a
    # rubric against an object a partner built from a description. The domain is built from
    # what those two instruments score, not from a paper that does not exist.
    ("experimental-design", 2027): "methodology_2027",
    ("write-it-do-it", 2027): "methodology_2027",
}

# Rotations confirmed against the 2027 Division B rules manual that still have no source set,
# listed so the gap is recorded rather than discovered later as a wrong course. Each needs a
# DOMAIN_SOURCES entry before its event is grounded or re-authored for 2027:
#   water-quality          2026 freshwater macroinvertebrates -> 2027 marine, estuary, coral reef
#   anatomy-and-physiology 2026 nervous system                -> 2027 respiratory, digestive, immune
#   solar-system           2026 object survey                 -> 2027 habitability and astrobiology
#   meteorology            2026 everyday weather and climate   -> 2027 severe weather and storms
# Until then `domain_for_event` returns their pre-rotation domain, which is the honest answer:
# no 2027 sources have been assembled for them yet.

# A domain named for a season must actually exist, or grounding skips the event and reports it
# as having no sources — indistinguishable from a real content gap.
_unknown = {d for d in EVENT_DOMAIN_BY_SEASON.values() if d not in DOMAIN_SOURCES}
assert not _unknown, f"EVENT_DOMAIN_BY_SEASON names domains with no sources: {sorted(_unknown)}"


EVENT_DOMAIN = {
    "thermodynamics": "thermodynamics",
    "rocks-and-minerals": "geology",
    "rocks-and-minerals-b": "geology",
    "rocks-and-minerals-c": "geology",
    "dynamic-planet": "oceanography",
    "meteorology": "meteorology",
    "remote-sensing": "remote_sensing",
    "solar-system": "astronomy",
    "astronomy": "astronomy",
    "codebusters": "cryptography",
    "experimental-design": "methodology",
    "metric-mastery": "metrology",
    "write-it-do-it": "methodology",
    "bungee-drop": "physics",
    "engineering-cad": "methodology",
    "anatomy-and-physiology": "anatomy",
    "disease-detectives": "epidemiology",
    "entomology": "entomology",
    "heredity": "genetics",
    "designer-genes": "genetics",
    "water-quality": "water",
    "hovercraft": "physics",
    "circuit-lab": "physics",
    "machines": "physics",
    "crime-busters": "forensics",
    "potions-and-poisons": "chemistry",
    "chemistry-lab": "chemistry",
    "forensics": "forensics",
    "materials-science": "chemistry",
    "boomilever": "physics",
    "helicopter": "physics",
    "mission-possible": "physics",
    "scrambler": "physics",
    "electric-vehicle": "physics",
    "robot-tour": "physics",
    # 2027 events that had no mapping at all, so grounding refused them as "no domain" and
    # their courses stayed empty. Roller Coaster, Ping Pong Parachute and the gliders are
    # mechanics events; Thermodynamics is heat transfer, which `physics` does not yet cover
    # and is therefore left out rather than mapped to a set that cannot ground it.
    "roller-coaster": "physics",
    "botany": "botany",
    "ping-pong-parachute": "physics",
    "elastic-launched-glider": "physics",
    "elastic-launch-glider": "physics",
}
