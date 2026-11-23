"""Illustrated bird library pipeline (epic MOUL-42), run in GitHub Actions.

Steps (each reads the previous step's output in --work):

    species    species the geo model expects in Belgium over a full year
    taxa       Wikidata: accepted names, synonyms, IUCN status (CC0)
    catalogue  Commons: Naumann plates (and Dresser, if found) mapped to species
    download   original plates, checksums verified against Commons
    build      clean images (crops.json), Home Assistant + e-ink sizes, contact sheet
    songs      one short reference song per species (xeno-canto), normalised

Nothing here is published. Outputs go to the run's artifacts for review; the small
Home Assistant renditions, songs and the catalogue are then committed into app/.
Never touches sound from the garden cameras: songs are third-party reference
recordings of each species.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

from commons import (
    COMMONS_API,
    OutOfTime,
    category_members,
    depicts,
    file_info,
    get,
    get_bytes,
    get_json,
    public_user_agent,
    set_deadline,
    time_left,
)
from matching import STRENGTH, WEAK, Index
from progress import Progress

HERE = Path(__file__).resolve().parent
# The App's paper-and-edge module (Pillow only), so the contact sheet shows the
# plates as Home Assistant and the screen will.
sys.path.insert(0, str(HERE.parents[1] / "app" / "src" / "mouflon_population"))
import vintage  # noqa: E402

# Rough points across Belgium (no personal location): Brussels, Bruges, Liège.
BELGIAN_POINTS = ((50.85, 4.35), (51.21, 3.22), (50.63, 5.57))
GEO_THRESHOLD = 0.03
NAUMANN_CATEGORY = "Category:Naumann - Naturgeschichte der Vögel Mitteleuropas (1905)"
NAUMANN = {
    "book": "Naumann, Naturgeschichte der Vögel Mitteleuropas (3rd ed., 1896-1905)",
    "categories": [
        f"{NAUMANN_CATEGORY} - derivative",
        NAUMANN_CATEGORY,
    ],
}
DRESSER_SEARCH = "Dresser A History of the Birds of Europe"
PD_TAGS = ("public domain", "pd-", "cc0", "cc-pd")
IUCN = {
    "Q211005": "LC",
    "Q719675": "NT",
    "Q278113": "VU",
    "Q11394": "EN",
    "Q219127": "CR",
    "Q239509": "EW",
    "Q237350": "EX",
    "Q3245245": "DD",
}
HA_MAX_SIDE = 480
EINK_SIZE = (480, 800)  # portrait colour e-ink frame (7.3", 800x480)
SONG_SECONDS = 15


def today() -> str:
    return dt.date.today().isoformat()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# --- species ---------------------------------------------------------------------


def step_species(work: Path) -> None:
    import birdnet

    model = birdnet.load("geo", "2.4", "tf", lang="en_us", library="litert")
    species: dict[str, dict] = {}
    for lat, lon in BELGIAN_POINTS:
        for week in range(1, 49):
            result = model.predict(lat, lon, week=week, min_confidence=GEO_THRESHOLD)
            for row in result.to_structured_array():
                label = str(row["species_name"])
                scientific, _, common = label.partition("_")
                entry = species.setdefault(
                    scientific, {"common_name": common, "max_probability": 0.0}
                )
                entry["max_probability"] = max(
                    entry["max_probability"], float(row["confidence"])
                )
    write_json(work / "species.json", species)
    print(f"species: {len(species)} species expected in Belgium over a year")


DEMO_SOURCE = HERE.parents[1] / "app" / "src" / "mouflon_population" / "demo.py"


def demo_species_list() -> dict[str, dict]:
    """The demo mode's species, read from demo.py without importing the App."""
    import ast

    tree = ast.parse(DEMO_SOURCE.read_text(encoding="utf-8"))
    species: dict[str, dict] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign | ast.Assign):
            targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
            names = {t.id for t in targets if isinstance(t, ast.Name)}
            if names & {"BELGIAN_GARDEN_BIRDS", "DEMO_RARE"}:
                for row in ast.literal_eval(node.value):
                    species[row[0]] = {"common_name": row[1], "max_probability": None}
    return species


def step_demo_species(work: Path) -> None:
    """Species list for the demo starter pack: only the demo mode's birds."""
    species = demo_species_list()
    write_json(work / "species.json", species)
    print(f"demo species: {len(species)}", flush=True)


# --- taxa (Wikidata) ---------------------------------------------------------------

SPARQL = """
SELECT ?name ?item ?accepted ?synonym ?synonymItem ?iucn WHERE {
  VALUES ?name { %s }
  { ?item wdt:P225 ?name . } UNION { ?item wdt:P1420/wdt:P225 ?name . }
  ?item wdt:P225 ?accepted .
  OPTIONAL {
    ?item (wdt:P1420|wdt:P566|wdt:P1403) ?synonymItem .
    ?synonymItem wdt:P225 ?synonym .
  }
  OPTIONAL { ?item wdt:P141 ?iucn . }
}
"""
VERNACULAR_SPARQL = """
SELECT ?name ?vernacular WHERE {
  VALUES ?name { %s }
  ?item wdt:P225 ?name .
  { ?item wdt:P1843 ?vernacular . } UNION { ?item rdfs:label ?vernacular . }
  FILTER(LANG(?vernacular) IN ("de", "en"))
}
"""
GBIF = "https://api.gbif.org/v1"


def sparql(query: str) -> list[dict]:
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
        {"query": query, "format": "json"}
    )
    return get_json(url)["results"]["bindings"]


def gbif_names(scientific: str) -> tuple[set[str], set[str]]:
    """Synonyms (scientific) and German/English vernacular names from GBIF."""
    match = get_json(
        f"{GBIF}/species/match?" + urllib.parse.urlencode({"name": scientific})
    )
    key = match.get("acceptedUsageKey") or match.get("usageKey")
    if not key or match.get("matchType") == "NONE":
        return set(), set()
    synonyms = get_json(f"{GBIF}/species/{key}/synonyms?limit=200").get("results", [])
    names = {r["canonicalName"] for r in synonyms if r.get("canonicalName")}
    vernacular = get_json(f"{GBIF}/species/{key}/vernacularNames?limit=300").get(
        "results", []
    )
    common = {
        r["vernacularName"]
        for r in vernacular
        if r.get("language") in ("deu", "eng", "de", "en") and r.get("vernacularName")
    }
    return names, common


def step_taxa(work: Path) -> None:
    """Accepted names, synonyms (Wikidata + GBIF), vernacular names, IUCN status."""
    species = read_json(work / "species.json")
    taxa = {
        name: {
            "names": {name},
            "items": set(),
            "vernacular": set(),
            "iucn": None,
            "wikidata": None,
        }
        for name in species
    }
    names = sorted(species)
    for start in range(0, len(names), 60):
        chunk = names[start : start + 60]
        values = " ".join(json.dumps(n) for n in chunk)
        for row in sparql(SPARQL % values):
            entry = taxa[row["name"]["value"]]
            entry["names"].add(row["accepted"]["value"])
            item = row["item"]["value"].rsplit("/", 1)[1]
            entry["items"].add(item)
            entry["wikidata"] = entry["wikidata"] or item
            if "synonym" in row:
                entry["names"].add(row["synonym"]["value"])
                entry["items"].add(row["synonymItem"]["value"].rsplit("/", 1)[1])
            if "iucn" in row:
                code = IUCN.get(row["iucn"]["value"].rsplit("/", 1)[1])
                entry["iucn"] = entry["iucn"] or code
        for row in sparql(VERNACULAR_SPARQL % values):
            taxa[row["name"]["value"]]["vernacular"].add(row["vernacular"]["value"])
    failures = 0
    for index, name in enumerate(names, 1):
        try:
            synonyms, common = gbif_names(name)
        except Exception as error:
            failures += 1
            print(f"GBIF lookup failed for {name}: {type(error).__name__}", flush=True)
            continue
        taxa[name]["names"] |= synonyms
        taxa[name]["vernacular"] |= common
        if index % 25 == 0:
            print(f"taxa: GBIF names {index}/{len(names)}", flush=True)
    for entry in taxa.values():
        for key in ("names", "items", "vernacular"):
            entry[key] = sorted(entry[key])
    write_json(work / "taxa.json", taxa)
    with_iucn = sum(1 for t in taxa.values() if t["iucn"])
    synonyms = sum(len(t["names"]) - 1 for t in taxa.values())
    print(
        f"taxa: {len(taxa)} species, {synonyms} synonyms, "
        f"{with_iucn} with an IUCN category, {failures} GBIF failures"
    )


# --- catalogue (Commons) -----------------------------------------------------------


def find_dresser_categories() -> list[str]:
    data = get(
        COMMONS_API,
        {
            "action": "query",
            "list": "search",
            "srsearch": DRESSER_SEARCH,
            "srnamespace": "14",
            "srlimit": "20",
        },
    )
    titles = [r["title"] for r in data["query"]["search"]]
    print("Dresser category search:", titles)
    return [t for t in titles if "history of the birds of europe" in t.lower()]


def is_public_domain(meta: dict) -> bool:
    text = " ".join(
        [
            meta.get("license") or "",
            meta.get("usage_terms") or "",
            *meta.get("categories", []),
        ]
    ).lower()
    return any(tag in text for tag in PD_TAGS)


def plate_reference(title: str, description: str) -> str:
    text = f"{title} {re.sub('<[^>]+>', ' ', description or '')}"
    band = re.search(r"\b(?:Band|Bd\.?|Vol\.?)\s*([IVXL\d]+)", text)
    tafel = re.search(r"\b(?:Tafel|Taf\.?|Plate|Pl\.)\s*(\d+)", text)
    roman = re.search(r"\((?P<band>[IVXL]+)\.\s*(?P<tafel>\d+)\)", text)
    if roman:
        return f"Band {roman['band']}, Tafel {roman['tafel']}"
    parts = []
    if band:
        parts.append(f"Band {band.group(1)}")
    if tafel:
        parts.append(f"Tafel {tafel.group(1)}")
    return ", ".join(parts) or "plate not identified"


def with_subcategories(category: str, depth: int = 2) -> list[str]:
    """The category and its subcategories (plates are often filed per volume)."""
    found, frontier = [category], [category]
    for _ in range(depth):
        frontier = [sub for c in frontier for sub in category_members(c, "subcat")]
        frontier = [c for c in frontier if c not in found]
        found += frontier
    return found


def collect(book: dict, categories: list[str]) -> list[dict]:
    files, seen = [], set()
    for top in categories:
        derivative = top.endswith("- derivative")
        for category in with_subcategories(top):
            titles = category_members(category, "file")
            titles = [
                t
                for t in titles
                if not t.lower().endswith((".pdf", ".djvu")) and t not in seen
            ]
            seen.update(titles)
            for start in range(0, len(titles), 50):
                for title, meta in file_info(titles[start : start + 50]).items():
                    files.append(
                        {
                            "title": title,
                            "book": book["book"],
                            "derivative": derivative,
                            "public_domain": is_public_domain(meta),
                            "plate": plate_reference(
                                title, meta.get("description") or ""
                            ),
                            "categories": meta["categories"],
                            "description": meta.get("description") or "",
                            **{
                                k: meta[k]
                                for k in (
                                    "pageid",
                                    "url",
                                    "descriptionurl",
                                    "width",
                                    "height",
                                    "sha1",
                                    "mime",
                                    "license",
                                )
                            },
                        }
                    )
            print(f"{category}: {len(titles)} image files", flush=True)
    return files


def add_depicts(files: list[dict]) -> None:
    """Structured-data "depicts" items for each file (50 files per request)."""
    by_page = {f["pageid"]: f for f in files if f.get("pageid")}
    pages = sorted(by_page)
    for start in range(0, len(pages), 50):
        try:
            found = depicts(pages[start : start + 50])
        except Exception as error:
            print(f"depicts lookup failed: {type(error).__name__}", flush=True)
            continue
        for page, items in found.items():
            if page in by_page:
                by_page[page]["depicts"] = items


def score(candidate: dict) -> tuple:
    single = len(candidate["species_shown"]) == 1
    return (
        STRENGTH[candidate["match"]] >= STRENGTH["category"],
        candidate["book"].startswith("Naumann"),
        candidate["derivative"] and single,
        single,
        STRENGTH[candidate["match"]],
        (candidate["width"] or 0) * (candidate["height"] or 0),
    )


def step_catalogue(work: Path) -> None:
    taxa = read_json(work / "taxa.json")
    species = read_json(work / "species.json")
    files = collect(NAUMANN, NAUMANN["categories"])
    dresser = find_dresser_categories()
    for category in dresser:
        files += collect(
            {"book": "Dresser, A History of the Birds of Europe (1871-1896)"},
            [category],
        )
    files = [f for f in files if f["public_domain"] and f["url"]]
    add_depicts(files)
    index = Index(taxa)
    by_species: dict[str, list[dict]] = {}
    match_kinds: dict[str, int] = {}
    for f in files:
        found = index.matches(f, f.get("depicts", []))
        f["species_shown"] = sorted(found)
        for scientific, kind in found.items():
            by_species.setdefault(scientific, []).append({**f, "match": kind})

    catalogue = {}
    for scientific, taxon in sorted(taxa.items()):
        ranked = sorted(by_species.get(scientific, []), key=score, reverse=True)
        chosen = ranked[0] if ranked else None
        if chosen:
            match_kinds[chosen["match"]] = match_kinds.get(chosen["match"], 0) + 1
            chosen = {
                k: v
                for k, v in chosen.items()
                if k not in ("categories", "description")
            }
        catalogue[scientific] = {
            "common_name": species[scientific]["common_name"],
            "iucn": taxon["iucn"],
            "wikidata": taxon["wikidata"],
            "names": taxon["names"],
            "chosen": chosen,
            "match": chosen["match"] if chosen else None,
            "needs_review": bool(chosen) and chosen["match"] in WEAK,
            "needs_crop": bool(chosen) and len(chosen["species_shown"]) > 1,
            "alternatives": [c["title"] for c in ranked[1:6]],
        }
    write_json(work / "catalogue.json", catalogue)
    meta = {"n_files": len(files), "dresser": dresser, "match_kinds": match_kinds}
    write_json(work / "catalogue-meta.json", meta)
    write_coverage(work, catalogue, **meta)


def crop_pending(scientific: str, entry: dict, crops: dict) -> bool:
    """A multi-species plate without a reviewed crop box for that exact file."""
    crop = crops.get(scientific) or {}
    return (
        bool(entry.get("chosen"))
        and entry["needs_crop"]
        and (crop.get("commons_title") != entry["chosen"]["title"])
    )


def write_coverage(
    work: Path,
    catalogue: dict,
    *,
    n_files: int,
    dresser: list[str],
    match_kinds: dict[str, int] | None = None,
    status: dict | None = None,
) -> None:
    """Coverage report. Before the download (status None) it counts plates found on
    Commons; after it, also which were downloaded, which failed (throttled or
    unreachable: retry later, never counted as missing) and which the time limit
    left for the next run."""
    crops = load_crops()
    total = len(catalogue)
    found = [s for s, c in catalogue.items() if c["chosen"]]
    missing = [s for s, c in catalogue.items() if not c["chosen"]]
    failed = (status or {}).get("failed", {})
    not_attempted = (status or {}).get("not_attempted", [])
    fetched = [s for s in found if s not in failed and s not in not_attempted]
    crop = [s for s in fetched if crop_pending(s, catalogue[s], crops)]
    lines = [
        "# Illustration coverage",
        "",
        f"Generated {today()} by tools/illustrations/pipeline.py.",
        "",
        "- Species expected in Belgium over a year "
        f"(geo model 2.4, threshold {GEO_THRESHOLD}): **{total}**",
        f"- Public-domain plate files examined on Commons: {n_files}",
        f"- Dresser categories found on Commons: {', '.join(dresser) or 'none'}",
        f"- Species with a plate on Commons: **{len(found)}** "
        f"({100 * len(found) // max(total, 1)} %)",
    ]
    if status is None:
        lines.append("  - not downloaded yet")
    else:
        lines += [
            f"  - downloaded: **{len(fetched)}**",
            f"    - ready (single species, or reviewed crop box): "
            f"{len(fetched) - len(crop)}",
            f"    - on a multi-species plate (needs a crop box in crops.json): "
            f"{len(crop)}",
            f"  - failed, retry later (throttled or unreachable): **{len(failed)}**",
            f"  - not attempted (run stopped before its time limit): "
            f"**{len(not_attempted)}**",
        ]
    lines += [
        f"- Species without a plate on Commons (missing): **{len(missing)}**",
        "- How the chosen plate was matched: "
        + (
            ", ".join(f"{k} {v}" for k, v in sorted((match_kinds or {}).items()))
            or "n/a"
        ),
        "- Weak matches (name found only in the text) are marked for review on the "
        "contact sheet.",
        "",
        "## Missing (no plate on Commons)",
        "",
    ]
    lines += [f"- {s} — {catalogue[s]['common_name']}" for s in missing]
    if status is not None:
        lines += ["", "## Failed, retry later", ""]
        lines += [
            f"- {s} — {catalogue[s]['common_name']} ({reason})"
            for s, reason in sorted(failed.items())
        ]
        lines += ["", "## Not attempted (time limit)", ""]
        lines += [f"- {s} — {catalogue[s]['common_name']}" for s in not_attempted]
    lines += ["", "## Needs review (weak match)", ""]
    lines += [
        f"- {s} — {catalogue[s]['chosen']['title']} ({catalogue[s]['match']})"
        for s in found
        if catalogue[s].get("needs_review")
    ]
    lines += ["", "## Needs a crop box", ""]
    lines += [
        f"- {s} — {catalogue[s]['chosen']['title']}"
        for s in found
        if crop_pending(s, catalogue[s], crops)
    ]
    (work / "coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[: lines.index("## Missing (no plate on Commons)")]))


# --- download ----------------------------------------------------------------------


def slug(scientific: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", scientific.lower()).strip("_")


RENDITION_WIDTH = 1280
DOWNLOAD_PAUSE_S = 3.0


def thumbnail_url(title: str) -> str:
    data = get(
        COMMONS_API,
        {
            "action": "query",
            "titles": title,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": str(RENDITION_WIDTH),
        },
    )
    info = data["query"]["pages"][0]["imageinfo"][0]
    return info.get("thumburl") or info["url"]


class PlateCache:
    """Plates downloaded by earlier runs (work/originals, kept by the workflow's
    cache), so a cut-off build resumes instead of starting again. An entry is used
    only if its file still has the recorded checksum and Commons still serves the
    same original (same SHA-1)."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.path = folder / "cache.json"
        self.entries = read_json(self.path) if self.path.exists() else {}

    def get(self, title: str, original_sha1: str | None) -> dict | None:
        entry = self.entries.get(title)
        if not entry or entry.get("original_sha1") != original_sha1:
            return None
        path = self.folder / entry["file"]
        if not path.is_file():
            return None
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            return None
        return {"file": entry["file"], "sha256": entry["sha256"]}

    def put(self, title: str, original_sha1: str | None, item: dict) -> None:
        self.entries[title] = {**item, "original_sha1": original_sha1}

    def save(self) -> None:
        write_json(self.path, self.entries)


def short_reason(error: Exception) -> str:
    """A one-line reason with no URL or header (the contact must never be shown)."""
    text = str(error).split(":", 1)[0] if isinstance(error, OSError) else str(error)
    return f"{type(error).__name__}: {text}"[:120]


def step_download(work: Path) -> None:
    if not (work / "catalogue.json").exists():
        print("download: no catalogue, nothing to do", flush=True)
        return
    catalogue = read_json(work / "catalogue.json")
    originals = work / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    cache = PlateCache(originals)
    manifest = []
    done: dict[str, dict] = {}
    failed: dict[str, str] = {}
    failed_titles: dict[str, str] = {}
    not_attempted: list[str] = []
    reused = 0
    songs_path = work / "songs-manifest.json"
    songs = (
        {x["species"] for x in read_json(songs_path)} if songs_path.exists() else set()
    )
    progress = Progress(len(catalogue))

    def status() -> dict:
        return {
            "failed": failed,
            "not_attempted": not_attempted,
            "stopped_early": bool(not_attempted),
            "reused_from_cache": reused,
        }

    def save_partial() -> None:
        write_json(work / "manifest-originals.json", manifest)
        write_json(work / "download-status.json", status())
        cache.save()

    for scientific, entry in sorted(catalogue.items()):
        chosen = entry["chosen"]
        has_song = scientific in songs
        if not chosen:
            progress.species(scientific, None, has_song)
            continue
        title = chosen["title"]
        if not_attempted:
            not_attempted.append(scientific)
            progress.species(scientific, None, has_song, outcome="not attempted")
            continue
        if title in failed_titles:
            failed[scientific] = failed_titles[title]
            progress.species(scientific, None, has_song, outcome="failed")
            continue
        if title not in done:
            cached = cache.get(title, chosen["sha1"])
            if cached:
                done[title] = cached
                reused += 1
            else:
                # A 1280 px rendition from Commons' thumbnail service: enough for
                # every output size, and far gentler on Wikimedia than originals.
                try:
                    if time_left() <= 0:
                        raise OutOfTime
                    data = get_bytes(thumbnail_url(title))
                except OutOfTime:
                    print("download: time limit near, stopping to save", flush=True)
                    not_attempted.append(scientific)
                    progress.species(
                        scientific, None, has_song, outcome="not attempted"
                    )
                    continue
                except Exception as error:
                    failed[scientific] = failed_titles[title] = short_reason(error)
                    print(f"download failed for {title}: {failed[scientific]}")
                    progress.species(scientific, None, has_song, outcome="failed")
                    continue
                time.sleep(min(DOWNLOAD_PAUSE_S, max(0.0, time_left())))
                name = slug(title.removeprefix("File:")) + Path(title).suffix.lower()
                (originals / name).write_bytes(data)
                done[title] = {
                    "file": name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
                cache.put(title, chosen["sha1"], done[title])
        manifest.append(
            {
                "species": scientific,
                "common_name": entry["common_name"],
                "book": chosen["book"],
                "plate": chosen["plate"],
                "commons_title": title,
                "source_url": chosen["descriptionurl"],
                "file_url": chosen["url"].split("?")[0],
                "original_sha1": chosen["sha1"],
                "fetched_width": RENDITION_WIDTH,
                "licence": chosen["license"] or "Public domain",
                "fetched": today(),
                "original_file": done[title]["file"],
                "sha256": done[title]["sha256"],
                "species_on_plate": chosen["species_shown"],
            }
        )
        progress.species(scientific, chosen["book"].split(",")[0], has_song)
        if len(manifest) % 10 == 0:
            save_partial()
    save_partial()
    meta_path = work / "catalogue-meta.json"
    meta = read_json(meta_path) if meta_path.exists() else {"n_files": 0, "dresser": []}
    write_coverage(work, catalogue, **meta, status=status())
    print(
        f"download: {len(done)} plates for {len(manifest)} species "
        f"({reused} reused from earlier runs), {len(failed)} failed (retry later), "
        f"{len(not_attempted)} not attempted (time limit)",
        flush=True,
    )
    review = sum(1 for e in catalogue.values() if e.get("needs_review"))
    progress.summary(
        [
            f"- Distinct plate files: {len(done)} ({reused} reused from earlier runs)",
            f"- Failed, retry later: {len(failed)}",
            f"- Not attempted (time limit): {len(not_attempted)}",
            f"- Plates to review (weak name match): {review}",
        ]
    )


# --- build -------------------------------------------------------------------------


def load_crops() -> dict:
    path = HERE / "crops.json"
    return read_json(path) if path.exists() else {}


# Margin added around every box, as a share of the plate side (owner, 0.5.3: never
# cut a tail, beak, feet or perch tip). An automatic box that already covers most
# of the plate becomes the whole plate.
MARGIN = 0.06
WHOLE_PLATE_SHARE = 0.7


def auto_box(image) -> tuple[int, int, int, int]:
    """Bounding box of the drawing: darker or coloured pixels away from the edges."""
    import numpy as np

    rgb = np.asarray(image.convert("RGB"), dtype="float32")
    height, width, _ = rgb.shape
    gray = rgb.mean(axis=2)
    saturation = rgb.max(axis=2) - rgb.min(axis=2)
    margin_y, margin_x = int(height * 0.03), int(width * 0.03)
    paper = float(np.median(gray[margin_y:-margin_y, margin_x:-margin_x]))
    ink = (gray < paper - 35) | (saturation > 45)
    ink[:margin_y, :] = ink[-margin_y:, :] = False
    ink[:, :margin_x] = ink[:, -margin_x:] = False
    rows = np.where(ink.mean(axis=1) > 0.01)[0]
    cols = np.where(ink.mean(axis=0) > 0.01)[0]
    if len(rows) < 10 or len(cols) < 10:
        return (0, 0, width, height)
    box = widen((cols[0], rows[0], cols[-1], rows[-1]), width, height)
    if (box[2] - box[0]) * (box[3] - box[1]) >= WHOLE_PLATE_SHARE * width * height:
        return (0, 0, width, height)
    return box


def widen(box, width: int, height: int, margin: float = MARGIN) -> tuple[int, ...]:
    pad_x, pad_y = margin * width, margin * height
    return (
        int(max(0, box[0] - pad_x)),
        int(max(0, box[1] - pad_y)),
        int(min(width, box[2] + pad_x)),
        int(min(height, box[3] + pad_y)),
    )


def chosen_box(image, entry: dict | None) -> tuple[tuple[int, ...], str]:
    """The crop box and where it came from.

    A crops.json entry is only valid for the exact plate file it was drawn on. Its
    box is in fractions of the whole plate, or "whole"; it is used as given (the
    reviewer already left generous margins).
    """
    width, height = image.size
    if not entry:
        return auto_box(image), "automatic"
    if entry["box"] == "whole":
        return (0, 0, width, height), "crops.json (whole plate)"
    x0, y0, x1, y1 = entry["box"]
    box = (int(x0 * width), int(y0 * height), int(x1 * width), int(y1 * height))
    return box, "crops.json"


def erase(image, areas: list, paper: tuple[int, int, int]):
    """Blank printed captions and plate numbers with the plate's paper colour."""
    from PIL import ImageDraw

    width, height = image.size
    draw = ImageDraw.Draw(image)
    for x0, y0, x1, y1 in areas:
        draw.rectangle((x0 * width, y0 * height, x1 * width, y1 * height), fill=paper)
    return image


def paper_colour(image) -> tuple[int, int, int]:
    import numpy as np

    rgb = np.asarray(image.convert("RGB"))
    border = np.concatenate([rgb[:20].reshape(-1, 3), rgb[-20:].reshape(-1, 3)])
    return tuple(int(v) for v in np.median(border, axis=0))


def step_build(work: Path) -> None:
    from PIL import Image

    if not (work / "manifest-originals.json").exists():
        print("build: nothing downloaded, nothing to build", flush=True)
        return
    manifest = read_json(work / "manifest-originals.json")
    crops = load_crops()
    out_ha, out_eink, out_thumb = (work / d for d in ("ha", "eink", "thumbs"))
    for d in (out_ha, out_eink, out_thumb):
        d.mkdir(parents=True, exist_ok=True)
    built = []
    for item in manifest:
        image = Image.open(work / "originals" / item["original_file"]).convert("RGB")
        entry = crops.get(item["species"])
        if entry and entry.get("commons_title") != item["commons_title"]:
            entry = None
        box, crop_source = chosen_box(image, entry)
        needs_crop = len(item["species_on_plate"]) > 1 and not entry
        paper = paper_colour(image)
        if entry and entry.get("erase"):
            image = erase(image, entry["erase"], paper)
        clean = image.crop(box)
        name = slug(item["species"]) + ".jpg"

        ha = clean.copy()
        ha.thumbnail((HA_MAX_SIDE, HA_MAX_SIDE), Image.LANCZOS)
        ha.save(out_ha / name, "JPEG", quality=85, optimize=True, progressive=True)

        canvas = Image.new("RGB", EINK_SIZE, vintage.PAPER)
        fitted = clean.copy()
        fitted.thumbnail(vintage.fit(EINK_SIZE), Image.LANCZOS)
        ink = vintage.ink_layer(fitted, vintage.seed_of(item["species"]))
        vintage.print_on(
            canvas,
            ink,
            ((EINK_SIZE[0] - ink.width) // 2, (EINK_SIZE[1] - ink.height) // 2),
        )
        canvas.save(out_eink / name.replace(".jpg", ".png"), "PNG", optimize=True)

        thumb = clean.copy()
        thumb.thumbnail(vintage.fit((220, 220)), Image.LANCZOS)
        # As Home Assistant and the screen show it: aged paper, organic edge.
        thumb = vintage.on_paper(thumb, vintage.seed_of(item["species"]))
        thumb.save(out_thumb / name, "JPEG", quality=80)
        built.append(
            {
                **item,
                "image": name,
                "crop_box": list(box),
                "crop_source": crop_source,
                "needs_crop": needs_crop,
                "sha256_ha": hashlib.sha256((out_ha / name).read_bytes()).hexdigest(),
            }
        )
    write_json(work / "manifest.json", built)
    write_contact_sheet(work, built)
    print(
        f"build: {len(built)} images, "
        f"{sum(b['needs_crop'] for b in built)} need a crop box"
    )


def write_contact_sheet(work: Path, built: list[dict]) -> None:
    import base64

    catalogue = read_json(work / "catalogue.json")
    cards = []
    for item in sorted(built, key=lambda b: (not b["needs_crop"], b["species"])):
        data = base64.b64encode((work / "thumbs" / item["image"]).read_bytes()).decode()
        flag = (
            "<b class=warn>NEEDS CROP — multi-species plate</b><br>"
            if item["needs_crop"]
            else ""
        )
        credit = f"{item['book'].split(' (')[0]}, {item['plate']}. Public domain."
        cards.append(
            f"<figure><img src='data:image/jpeg;base64,{data}' alt=''>"
            f"<figcaption>{flag}<b>{html.escape(item['common_name'])}</b><br>"
            f"<i>{html.escape(item['species'])}</i><br>"
            f"{html.escape(credit)}<br>"
            f"<a href='{html.escape(item['source_url'])}'>source</a> · "
            f"crop: {item['crop_source']}</figcaption></figure>"
        )
    status_path = work / "download-status.json"
    status = read_json(status_path) if status_path.exists() else {}
    failed = status.get("failed", {})
    not_attempted = set(status.get("not_attempted", []))

    def items(names) -> str:
        return "".join(
            f"<li>{html.escape(catalogue[s]['common_name'])} "
            f"(<i>{html.escape(s)}</i>)</li>"
            for s in sorted(names)
        )

    missing = [s for s, c in catalogue.items() if not c["chosen"]]
    page = f"""<!DOCTYPE html><html lang=en><head><meta charset=utf-8>
<title>Mouflon Population — illustration contact sheet</title>
<style>body{{font-family:system-ui,sans-serif;margin:1rem}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}}
figure{{margin:0;border:1px solid #ccc;padding:6px;background:#fafafa}}
img{{max-width:220px;max-height:220px;display:block;margin:auto}}
figcaption{{font-size:12px;margin-top:4px}}.warn{{color:#b00}}</style></head><body>
<h1>Illustration contact sheet — for review before anything ships</h1>
<p>{len(built)} species with a drawing, {len(missing)} without a plate on Commons,
{len(failed)} failed (retry later), {len(not_attempted)} not attempted (time limit).
Sources: Wikimedia Commons public-domain scans. Generated {today()}.</p>
<div class=grid>{"".join(cards)}</div>
<h2>No plate on Commons ({len(missing)})</h2><ul>{items(missing)}</ul>
<h2>Failed, retry later ({len(failed)})</h2><ul>{items(failed)}</ul>
<h2>Not attempted, time limit ({len(not_attempted)})</h2><ul>{items(not_attempted)}</ul>
</body></html>"""
    (work / "contact-sheet.html").write_text(page, encoding="utf-8")


# --- songs (xeno-canto) ------------------------------------------------------------

LICENCE_PREFERENCE = ("by/", "by-sa/", "by-nc/", "by-nc-sa/")


def licence_rank(url: str) -> int | None:
    url = url.lower()
    if "-nd" in url:
        return None  # no derivatives: we trim and normalise
    for rank, key in enumerate(LICENCE_PREFERENCE):
        if f"/licenses/{key}" in url:
            return rank
    return None


def xeno_canto(scientific: str) -> list[dict]:
    key = os.environ.get("XENO_CANTO_API_KEY", "")
    query = f'sp:"{scientific}" grp:birds q:A len:8-120'
    if key:
        url = "https://xeno-canto.org/api/3/recordings?" + urllib.parse.urlencode(
            {"query": query, "key": key}
        )
    else:
        url = "https://xeno-canto.org/api/2/recordings?" + urllib.parse.urlencode(
            {"query": f"{scientific} q:A len:8-120"}
        )
    return get_json(url).get("recordings", [])


def step_songs(work: Path) -> None:
    species = read_json(work / "species.json")
    out = work / "songs"
    out.mkdir(parents=True, exist_ok=True)
    manifest, missing, problems = [], [], []
    names = sorted(species)
    for position, scientific in enumerate(names, 1):
        before = len(manifest)
        try:
            recordings = xeno_canto(scientific)
        except Exception as error:
            problems.append(f"{scientific}: {error}")
            if len(problems) == 3 and not manifest:
                print("songs: xeno-canto not reachable:", problems)
                break
            continue
        usable = [
            r
            for r in recordings
            if licence_rank(r.get("lic", "")) is not None and r.get("file")
        ]
        usable.sort(
            key=lambda r: (
                "song" not in (r.get("type") or "").lower(),
                licence_rank(r["lic"]),
                r.get("q") != "A",
            )
        )
        if not usable:
            missing.append(scientific)
            print(f"[{position}/{len(names)}] {scientific} — song: missing", flush=True)
            continue
        rec = usable[0]
        url = rec["file"] if rec["file"].startswith("http") else "https:" + rec["file"]
        raw = work / "songs-raw" / f"{slug(scientific)}.mp3"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(get_bytes(url, max_bytes=60_000_000))
        clip = out / f"{slug(scientific)}.mp3"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                "0.5",
                "-t",
                str(SONG_SECONDS),
                "-i",
                str(raw),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.3,"
                f"afade=t=out:st={SONG_SECONDS - 1}:d=1",
                "-ac",
                "1",
                "-ar",
                "44100",
                "-b:a",
                "48k",
                str(clip),
            ],
            check=True,
        )
        manifest.append(
            {
                "species": scientific,
                "file": clip.name,
                "xeno_canto_id": rec.get("id"),
                "recordist": rec.get("rec"),
                "licence": "https:" + rec["lic"]
                if rec["lic"].startswith("//")
                else rec["lic"],
                "url": f"https://xeno-canto.org/{rec.get('id')}",
                "type": rec.get("type"),
                "country": rec.get("cnt"),
                "fetched": today(),
                "sha256": hashlib.sha256(clip.read_bytes()).hexdigest(),
            }
        )
        if len(manifest) > before:
            print(f"[{position}/{len(names)}] {scientific} — song: found", flush=True)
    write_json(work / "songs-manifest.json", manifest)
    print(
        f"songs: {len(manifest)} species with a reference song, "
        f"{len(missing)} without, "
        f"{len(problems)} lookup errors"
    )
    if problems:
        print("first errors:", problems[:3])


def step_report(work: Path) -> None:
    """Print the catalogue as one JSON line per species, for review in the run log."""
    catalogue = read_json(work / "catalogue.json")
    songs_path = work / "songs-manifest.json"
    songs = (
        {s["species"]: s for s in read_json(songs_path)} if songs_path.exists() else {}
    )
    for scientific, entry in sorted(catalogue.items()):
        chosen = entry["chosen"] or {}
        song = songs.get(scientific, {})
        row = {
            "species": scientific,
            "common_name": entry["common_name"],
            "iucn": entry["iucn"],
            "plate": chosen.get("title"),
            "book": chosen.get("book"),
            "plate_ref": chosen.get("plate"),
            "source_url": chosen.get("descriptionurl"),
            "needs_crop": entry["needs_crop"],
            "song_xc": song.get("xeno_canto_id"),
            "song_licence": song.get("licence"),
            "song_recordist": song.get("recordist"),
        }
        print("REPORT " + json.dumps(row, ensure_ascii=False))


STEPS = {
    "demo_species": step_demo_species,
    "report": step_report,
    "species": step_species,
    "taxa": step_taxa,
    "catalogue": step_catalogue,
    "download": step_download,
    "build": step_build,
    "songs": step_songs,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("steps", nargs="+", choices=list(STEPS))
    parser.add_argument("--work", type=Path, default=Path("work"))
    parser.add_argument(
        "--deadline",
        type=float,
        default=float(os.environ.get("LIBRARY_DEADLINE") or 0) or None,
        help="Unix time after which no request starts (default: $LIBRARY_DEADLINE)",
    )
    args = parser.parse_args()
    set_deadline(args.deadline)
    print("user agent:", public_user_agent())
    if args.deadline:
        print(f"stops fetching in {time_left() / 60:.0f} min to save its results")
    for step in args.steps:
        print(f"=== {step}")
        try:
            STEPS[step](args.work)
        except OutOfTime:
            print(f"{step}: time limit near, step skipped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
