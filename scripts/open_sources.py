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
}

# Hosts that refuse our crawler, recorded so the same URLs are not tried again. opentextbc.ca
# hosts an ideal CC-BY geology textbook and returns 403 to this user agent; using it would
# need permission or a different access route, not a retry.
BLOCKED_HOSTS = {"opentextbc.ca"}


def rights_for(url: str, spec: dict) -> dict:
    """Rights for one URL: an explicit host rule, else the domain's declared default."""
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    if host in HOST_RIGHTS:
        return dict(HOST_RIGHTS[host])
    return {"rights_status": "public_domain", "license_name": spec["license"],
            "publisher": spec["publisher"]}


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
    "epidemiology": {
        "publisher": "CDC / public-domain references",
        "license": "public_domain",
        "urls": [
            "https://en.wikipedia.org/wiki/Epidemiology",
            "https://en.wikipedia.org/wiki/Incidence_(epidemiology)",
            "https://en.wikipedia.org/wiki/Prevalence",
            "https://en.wikipedia.org/wiki/Case%E2%80%93control_study",
            "https://en.wikipedia.org/wiki/Cohort_study",
            "https://en.wikipedia.org/wiki/Odds_ratio",
            "https://en.wikipedia.org/wiki/Relative_risk",
            "https://en.wikipedia.org/wiki/Attack_rate",
            "https://en.wikipedia.org/wiki/Epidemic_curve",
            "https://en.wikipedia.org/wiki/Confounding",
            "https://en.wikipedia.org/wiki/Basic_reproduction_number",
            "https://en.wikipedia.org/wiki/Herd_immunity",
            "https://en.wikipedia.org/wiki/Koch%27s_postulates",
            "https://en.wikipedia.org/wiki/Outbreak",
            "https://en.wikipedia.org/wiki/Epidemiological_method",
            "https://en.wikipedia.org/wiki/Public_health_surveillance",
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
}

# event slug (division-agnostic) -> domain
def domain_for_event(slug: str) -> str | None:
    """The open-source domain for an event slug, division and season suffixes removed.

    `EVENT_DOMAIN` is keyed on base slugs — `heredity`, not `heredity-b`. `build_courses`
    already stripped the suffix before looking one up; `ground_event` did not, and looked up
    the full slug. So grounding raised "no open-source domain mapped" for essentially the whole
    catalog, because almost every real event carries a division suffix: of 102 active events
    only the three unsuffixed rocks-and-minerals rows ever matched. Two call sites, two
    spellings of the same key, and the mismatch read as "this event has no sources" — a content
    gap — rather than as a lookup bug.

    Seasoned slugs (`botany-b-2027`) are handled here too, for the same reason.
    """
    base = re.sub(r"-(19|20)\d{2}$", "", str(slug or ""))
    base = re.sub(r"-[bc]$", "", base)
    return EVENT_DOMAIN.get(base)


EVENT_DOMAIN = {
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
}
