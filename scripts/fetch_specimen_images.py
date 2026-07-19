"""Download real, correctly-labeled, openly-licensed specimen images.

For each curated specimen (queried by its exact name so the label is
authoritative), fetch the Wikipedia lead image, verify the underlying
Wikimedia Commons file carries a public-domain or Creative Commons license,
capture attribution, and save the image into app/static/media/<event>/.

Only public-domain / CC0 / CC-BY / CC-BY-SA images are kept; non-free images
are skipped. Output: app/static/media/manifest.json for the content builder.

Usage: python -m scripts.fetch_specimen_images
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import unquote

import httpx

UA = "FieldstoneEdu/1.0 (educational Science Olympiad study platform; contact@fieldstone.example)"
MEDIA_DIR = Path(__file__).resolve().parent.parent / "app" / "static" / "media"
OK_LICENSES = re.compile(r"public domain|cc0|cc[- ]by", re.IGNORECASE)

# event base-slug -> list of (specimen name for Wikipedia, display label)
SPECIMENS = {
    "rocks-and-minerals": [
        ("Quartz", "Quartz"), ("Calcite", "Calcite"), ("Halite", "Halite"),
        ("Gypsum", "Gypsum"), ("Pyrite", "Pyrite"), ("Galena", "Galena"),
        ("Magnetite", "Magnetite"), ("Fluorite", "Fluorite"), ("Hematite", "Hematite"),
        ("Talc", "Talc"), ("Malachite", "Malachite"), ("Muscovite", "Muscovite (Mica)"),
        ("Biotite", "Biotite"), ("Orthoclase", "Orthoclase Feldspar"), ("Olivine", "Olivine"),
        ("Garnet", "Garnet"), ("Graphite", "Graphite"), ("Sulfur", "Sulfur"),
        ("Azurite", "Azurite"), ("Chalcopyrite", "Chalcopyrite"), ("Corundum", "Corundum"),
        ("Dolomite", "Dolomite"), ("Sphalerite", "Sphalerite"), ("Apatite", "Apatite"),
        ("Barite", "Barite"), ("Amethyst", "Amethyst"), ("Topaz", "Topaz"),
        ("Tourmaline", "Tourmaline"), ("Kyanite", "Kyanite"), ("Rhodochrosite", "Rhodochrosite"),
        ("Bornite", "Bornite"), ("Serpentine subgroup", "Serpentine"),
        # Rocks
        ("Granite", "Granite (igneous)"), ("Basalt", "Basalt (igneous)"),
        ("Obsidian", "Obsidian (igneous)"), ("Pumice", "Pumice (igneous)"),
        ("Sandstone", "Sandstone (sedimentary)"), ("Limestone", "Limestone (sedimentary)"),
        ("Shale", "Shale (sedimentary)"), ("Conglomerate (geology)", "Conglomerate (sedimentary)"),
        ("Marble", "Marble (metamorphic)"), ("Slate", "Slate (metamorphic)"),
        ("Gneiss", "Gneiss (metamorphic)"), ("Schist", "Schist (metamorphic)"),
        # Station specimens referenced by past tests but not yet in the library
        ("Rhyolite", "Rhyolite (igneous)"), ("Andesite", "Andesite (igneous)"),
        ("Phyllite", "Phyllite (metamorphic)"), ("Quartzite", "Quartzite (metamorphic)"),
        ("Diorite", "Diorite (igneous)"), ("Gabbro", "Gabbro (igneous)"),
        ("Almandine", "Almandine (Garnet)"), ("Chrysocolla", "Chrysocolla"),
        ("Microcline", "Microcline Feldspar"), ("Chert", "Chert (sedimentary)"),
        ("Breccia", "Breccia (sedimentary)"), ("Rock gypsum", "Rock Gypsum (sedimentary)"),
    ],
    "astronomy": [
        ("Mercury (planet)", "Mercury"), ("Venus", "Venus"), ("Mars", "Mars"),
        ("Jupiter", "Jupiter"), ("Orion Nebula", "Orion Nebula"),
        ("Andromeda Galaxy", "Andromeda Galaxy"), ("Crab Nebula", "Crab Nebula"),
        ("Pleiades", "Pleiades"), ("Ring Nebula", "Ring Nebula"),
        ("Whirlpool Galaxy", "Whirlpool Galaxy"), ("Sombrero Galaxy", "Sombrero Galaxy"),
        ("Eagle Nebula", "Eagle Nebula"), ("Horsehead Nebula", "Horsehead Nebula"),
        ("Helix Nebula", "Helix Nebula"), ("Lagoon Nebula", "Lagoon Nebula"),
        ("Triangulum Galaxy", "Triangulum Galaxy"), ("Pinwheel Galaxy", "Pinwheel Galaxy"),
        ("Cat's Eye Nebula", "Cat's Eye Nebula"), ("Tarantula Nebula", "Tarantula Nebula"),
        ("Veil Nebula", "Veil Nebula"),
    ],
    "solar-system": [
        ("Mercury (planet)", "Mercury"), ("Venus", "Venus"), ("Earth", "Earth"),
        ("Mars", "Mars"), ("Jupiter", "Jupiter"), ("Saturn", "Saturn"),
        ("Uranus", "Uranus"), ("Neptune", "Neptune"), ("Moon", "The Moon"), ("Sun", "The Sun"),
        ("Europa (moon)", "Europa"), ("Io (moon)", "Io"), ("Titan (moon)", "Titan"),
        ("Ganymede (moon)", "Ganymede"), ("Enceladus", "Enceladus"),
        ("Ceres (dwarf planet)", "Ceres"), ("Pluto", "Pluto"), ("Halley's Comet", "Halley's Comet"),
    ],
    "entomology": [
        ("Western honey bee", "Honey Bee (Hymenoptera)"), ("Monarch butterfly", "Monarch (Lepidoptera)"),
        ("Coccinellidae", "Lady Beetle (Coleoptera)"), ("Dragonfly", "Dragonfly (Odonata)"),
        ("Mantis", "Praying Mantis (Mantodea)"), ("Grasshopper", "Grasshopper (Orthoptera)"),
        ("Housefly", "House Fly (Diptera)"), ("Cicada", "Cicada (Hemiptera)"),
        ("Ant", "Ant (Hymenoptera)"), ("Firefly", "Firefly (Coleoptera)"),
        ("Damselfly", "Damselfly (Odonata)"), ("Cricket (insect)", "Cricket (Orthoptera)"),
        ("Cockroach", "Cockroach (Blattodea)"), ("Termite", "Termite (Blattodea)"),
        ("Aphid", "Aphid (Hemiptera)"), ("Weevil", "Weevil (Coleoptera)"),
        ("Paper wasp", "Paper Wasp (Hymenoptera)"), ("Mosquito", "Mosquito (Diptera)"),
        ("Earwig", "Earwig (Dermaptera)"), ("Green lacewing", "Lacewing (Neuroptera)"),
        ("Stonefly", "Stonefly (Plecoptera)"), ("Mayfly", "Mayfly (Ephemeroptera)"),
        ("Walking stick", "Walking Stick (Phasmatodea)"), ("Ground beetle", "Ground Beetle (Coleoptera)"),
    ],
}


def _commons_filename(file_url: str) -> str:
    """The canonical Commons File: name for a Wikipedia image URL. Thumbnail
    URLs look like .../thumb/a/ab/Real_Name.jpg/640px-Real_Name.jpg — there the
    real file is the segment BEFORE the NNNpx- thumbnail, not the last one."""
    parts = file_url.split("/")
    name = parts[-2] if "thumb" in parts and len(parts) >= 2 else parts[-1]
    return unquote(name)


def commons_license(file_url: str) -> dict | None:
    filename = _commons_filename(file_url)
    try:
        response = httpx.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query", "titles": f"File:{filename}", "prop": "imageinfo",
                "iiprop": "extmetadata|url", "format": "json",
            },
            headers={"User-Agent": UA}, timeout=25,
        )
        pages = response.json().get("query", {}).get("pages", {})
        info = next(iter(pages.values())).get("imageinfo", [{}])[0]
        meta = info.get("extmetadata", {})
        license_name = (meta.get("LicenseShortName", {}) or {}).get("value", "")
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist", {}) or {}).get("value", "")).strip()
        credit = re.sub(r"<[^>]+>", "", (meta.get("Credit", {}) or {}).get("value", "")).strip()
        if not OK_LICENSES.search(license_name):
            return None
        return {"license": license_name, "attribution": (artist or credit or "Wikimedia Commons")[:200]}
    except (httpx.HTTPError, StopIteration, KeyError, IndexError):
        return None


# Specimens whose Wikipedia article exposes no usable lead image: point straight
# at a hand-picked, openly-licensed Commons file instead. Keyed by (event, label).
DIRECT_COMMONS = {
    ("rocks-and-minerals", "Rock Gypsum (sedimentary)"): "File:Rock gypsum (gyprock) 2.jpg",
    ("rocks-and-minerals", "Dolomite"): "File:Dolomite-213058.jpg",
}


def commons_file_url(file_title: str) -> str | None:
    """Resolve a 'File:Name.jpg' Commons title to its actual upload URL."""
    try:
        response = httpx.get(
            "https://commons.wikimedia.org/w/api.php",
            params={"action": "query", "titles": file_title, "prop": "imageinfo",
                    "iiprop": "url", "format": "json"},
            headers={"User-Agent": UA}, timeout=25,
        )
        pages = response.json().get("query", {}).get("pages", {})
        return next(iter(pages.values())).get("imageinfo", [{}])[0].get("url")
    except (httpx.HTTPError, StopIteration, KeyError, IndexError):
        return None


def fetch_lead_image(title: str) -> str | None:
    try:
        response = httpx.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}",
            headers={"User-Agent": UA}, timeout=25, follow_redirects=True,
        )
        data = response.json()
        return (data.get("originalimage") or {}).get("source") or (data.get("thumbnail") or {}).get("source")
    except httpx.HTTPError:
        return None


def download(url: str, dest: Path) -> bool:
    try:
        response = httpx.get(url, headers={"User-Agent": UA}, timeout=40, follow_redirects=True)
        if response.status_code != 200 or not response.headers.get("content-type", "").startswith("image"):
            return False
        dest.write_bytes(response.content)
        return len(response.content) > 3000
    except httpx.HTTPError:
        return False


def main() -> None:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, list[dict]] = {}
    for event, specimens in SPECIMENS.items():
        event_dir = MEDIA_DIR / event
        event_dir.mkdir(exist_ok=True)
        rows = []
        for title, label in specimens:
            direct = DIRECT_COMMONS.get((event, label))
            lead = commons_file_url(direct) if direct else fetch_lead_image(title)
            if not lead:
                print(f"  [{event}] {label}: no lead image"); continue
            lic = commons_license(lead)
            if not lic:
                print(f"  [{event}] {label}: license not open, skip"); continue
            slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
            ext = ".jpg" if ".jp" in lead.lower() else (".png" if ".png" in lead.lower() else ".jpg")
            dest = event_dir / f"{slug}{ext}"
            if not download(lead, dest):
                print(f"  [{event}] {label}: download failed"); continue
            rows.append({
                "slug": slug, "label": label,
                "url": f"/static/media/{event}/{dest.name}",
                "alt": f"Photograph of {label} for identification",
                "attribution": lic["attribution"], "license": lic["license"],
                "source_url": lead,
            })
            print(f"  [{event}] {label}: OK ({lic['license']})")
            time.sleep(0.5)
        manifest[event] = rows
        print(f"[{event}] {len(rows)}/{len(specimens)} images")
    (MEDIA_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    total = sum(len(v) for v in manifest.values())
    print(f"\nSaved {total} openly-licensed images across {len(manifest)} events.")


if __name__ == "__main__":
    main()
