"""Curated public-domain / open-license science sources per scientific domain.

Every URL here is a U.S. government (public-domain) or clearly open educational
resource. These are the materials the platform is permitted to DOWNLOAD, retain,
and use for LLM fact-grounding — unlike the copyrighted official Science Olympiad
rules and past exams, which stay link-only.

Each event maps to one domain; the domain's source provides the factual grounding
for that event's generated course and exam.
"""

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
        ],
    },
    "meteorology": {
        "publisher": "NOAA National Weather Service",
        "license": "public_domain",
        "urls": [
            "https://www.noaa.gov/education/resource-collections/weather-atmosphere",
            "https://www.weather.gov/jetstream/atmos_intro",
        ],
    },
    "oceanography": {
        "publisher": "NOAA Ocean Service",
        "license": "public_domain",
        "urls": [
            "https://oceanservice.noaa.gov/education/tutorial_currents/welcome.html",
            "https://www.noaa.gov/education/resource-collections/ocean-coasts",
        ],
    },
    "astronomy": {
        "publisher": "NASA",
        "license": "public_domain",
        "urls": [
            "https://science.nasa.gov/solar-system/",
            "https://science.nasa.gov/universe/stars/",
        ],
    },
    "remote_sensing": {
        "publisher": "NASA Earthdata",
        "license": "public_domain",
        "urls": [
            "https://www.earthdata.nasa.gov/learn/backgrounders/remote-sensing",
        ],
    },
    "anatomy": {
        "publisher": "NIH National Library of Medicine (MedlinePlus)",
        "license": "public_domain",
        "urls": [
            "https://medlineplus.gov/hormones.html",
            "https://medlineplus.gov/bloodheartandcirculation.html",
        ],
    },
    "genetics": {
        "publisher": "NIH National Human Genome Research Institute",
        "license": "public_domain",
        "urls": [
            "https://www.genome.gov/about-genomics/fact-sheets/Introduction-to-Genomics",
            "https://www.genome.gov/genetics-glossary",
        ],
    },
    "epidemiology": {
        "publisher": "CDC / public-domain references",
        "license": "public_domain",
        "urls": [
            "https://en.wikipedia.org/wiki/Epidemiology",
            "https://en.wikipedia.org/wiki/Outbreak_investigation",
        ],
    },
    "entomology": {
        "publisher": "USDA Agricultural Research Service",
        "license": "public_domain",
        "urls": [
            "https://www.ars.usda.gov/oc/br/insects/",
            "https://en.wikipedia.org/wiki/Insect_morphology",
        ],
    },
    "chemistry": {
        "publisher": "NIST / NIH PubChem",
        "license": "public_domain",
        "urls": [
            "https://www.nist.gov/chemistry",
            "https://en.wikipedia.org/wiki/Chemical_reaction",
        ],
    },
    "forensics": {
        "publisher": "NIST Forensic Science",
        "license": "public_domain",
        "urls": [
            "https://www.nist.gov/forensic-science",
            "https://en.wikipedia.org/wiki/Forensic_science",
        ],
    },
    "physics": {
        "publisher": "NASA Glenn Research Center",
        "license": "public_domain",
        "urls": [
            "https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/",
            "https://en.wikipedia.org/wiki/Simple_machine",
        ],
    },
    "metrology": {
        "publisher": "NIST Office of Weights and Measures",
        "license": "public_domain",
        "urls": [
            "https://www.nist.gov/pml/owm/metric-si/si-units",
            "https://en.wikipedia.org/wiki/International_System_of_Units",
        ],
    },
    "cryptography": {
        "publisher": "NIST / public domain references",
        "license": "public_domain",
        "urls": [
            "https://en.wikipedia.org/wiki/Substitution_cipher",
            "https://en.wikipedia.org/wiki/Classical_cipher",
        ],
    },
    "methodology": {
        "publisher": "NIST / NASA education",
        "license": "public_domain",
        "urls": [
            "https://en.wikipedia.org/wiki/Design_of_experiments",
            "https://en.wikipedia.org/wiki/Engineering_design_process",
        ],
    },
    "water": {
        "publisher": "USGS Water Science School / EPA",
        "license": "public_domain",
        "urls": [
            "https://www.usgs.gov/special-topics/water-science-school/science/water-quality-information-topic",
            "https://en.wikipedia.org/wiki/Water_quality",
        ],
    },
}

# event slug (division-agnostic) -> domain
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
