"""Build the bundled cross-check data (MOUL-55, MOUL-54). Runs in GitHub Actions.

Writes three files into ``app/crosscheck/``:

- ``belgium-weekly.json``: per bird species, the number of GBIF records in Belgium
  for each BirdNET week (4 per month), summed over the last ten full years, plus the
  total number of bird records per week. Country level: no coordinates at all.
- ``perch-aliases.json``: BirdNET scientific names that Perch's labels spell
  differently, resolved through GBIF's taxonomy.
- ``manifest.json``: where the data comes from, the exact filters, every
  contributing dataset with its licence, DOI and citation, and the GBIF citation.

Records kept: country BE, class Aves, occurrence present, human observations, no
geospatial issue, and only datasets under CC0 1.0 or CC BY 4.0 (no non-commercial
or share-alike licences). GBIF's occurrence search API is public and needs no
account; no secret is used. Needs only the Python standard library.

    python tools/crosscheck/crosscheck_data.py --catalogue app/library/catalogue.json \\
        --perch-labels perch_v2_labels.txt --out app/crosscheck
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

API = "https://api.gbif.org/v1"
USER_AGENT = "mouflon-population-crosscheck (GitHub Actions)"
WEEKS = 48
FILTERS = {
    "country": "BE",
    "classKey": "212",
    "occurrenceStatus": "PRESENT",
    "basisOfRecord": "HUMAN_OBSERVATION",
    "hasGeospatialIssue": "false",
}
LICENCES = ("CC0_1_0", "CC_BY_4_0")
FACET_LIMIT = 3000


def get(path: str, params: list[tuple[str, str]] | None = None) -> dict:
    url = f"{API}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except OSError as error:
            if attempt == 4:
                raise
            print(f"retrying after {error}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def base_params() -> list[tuple[str, str]]:
    params = list(FILTERS.items())
    params += [("license", licence) for licence in LICENCES]
    return params


def week_days(year: int, week: int) -> tuple[str, str]:
    """First and last day of a BirdNET week (weeks 1-4 of each month)."""
    month, quarter = divmod(week - 1, 4)
    month += 1
    first = 1 + 7 * quarter
    last = 7 * (quarter + 1) if quarter < 3 else calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-{first:02d}", f"{year}-{month:02d}-{last:02d}"


def week_counts(years: list[int], week: int) -> tuple[int, dict[str, int]]:
    params = base_params()
    # Repeated eventDate parameters are combined with OR by the API.
    params += [("eventDate", ",".join(week_days(y, week))) for y in years]
    params += [("limit", "0"), ("facet", "speciesKey")]
    params += [("facetLimit", str(FACET_LIMIT))]
    data = get("occurrence/search", params)
    counts = {c["name"]: c["count"] for c in data["facets"][0]["counts"]}
    return data["count"], counts


def overall(years: list[int]) -> tuple[int, list[dict]]:
    params = [*base_params(), ("year", f"{years[0]},{years[-1]}")]
    params += [("limit", "0"), ("facet", "datasetKey"), ("facetLimit", "1000")]
    data = get("occurrence/search", params)
    datasets = []
    for c in data["facets"][0]["counts"]:
        meta = get(f"dataset/{c['name']}")
        datasets.append(
            {
                "key": c["name"],
                "title": meta.get("title"),
                "publisher_key": meta.get("publishingOrganizationKey"),
                "license": meta.get("license"),
                "doi": meta.get("doi"),
                "records": c["count"],
                "citation": (meta.get("citation") or {}).get("text"),
            }
        )
    return data["count"], datasets


def species_name(key: str) -> str | None:
    data = get(f"species/{key}")
    if data.get("rank") != "SPECIES":
        return None
    return data.get("canonicalName")


def match(name: str) -> dict:
    return get("species/match", [("name", name), ("class", "Aves"), ("strict", "true")])


def synonyms(key: int) -> list[str]:
    data = get(f"species/{key}/synonyms", [("limit", "100")])
    results = data.get("results", [])
    return [r["canonicalName"] for r in results if r.get("canonicalName")]


def resolve(name: str, known: set[str]) -> str | None:
    """The name ``known`` uses for this species, through GBIF's taxonomy."""
    found = match(name)
    key = found.get("acceptedUsageKey") or found.get("usageKey")
    if not key:
        return None
    accepted = get(f"species/{key}").get("canonicalName")
    for candidate in [accepted, *synonyms(key)]:
        if candidate and candidate in known and candidate != name:
            return candidate
    return None


def perch_labels(text: str) -> list[str]:
    """Same parsing as the App's ``second_opinion.parse_labels``."""
    names = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.lower().startswith("inat2024"):
            names.append(line.split(",")[0].split("_")[0].strip().strip('"'))
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--perch-labels", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--last-year", type=int, default=datetime.now(UTC).year - 1)
    args = parser.parse_args(argv)

    years = list(range(args.last_year - 9, args.last_year + 1))
    totals: list[int] = []
    by_key: dict[str, list[int]] = {}
    for week in range(1, WEEKS + 1):
        total, counts = week_counts(years, week)
        if len(counts) >= FACET_LIMIT:
            sys.exit(f"week {week}: facet limit reached, raise FACET_LIMIT")
        totals.append(total)
        for key, count in counts.items():
            by_key.setdefault(key, [0] * WEEKS)[week - 1] = count
        print(f"week {week:2d}: {total} records, {len(counts)} species", flush=True)
        time.sleep(0.3)

    grand_total, datasets = overall(years)
    # Sanity check: the 48 weeks cover every day, so they must add up to the total.
    if abs(sum(totals) - grand_total) > 0.01 * grand_total:
        sys.exit(f"weeks add up to {sum(totals)}, overall count is {grand_total}")

    species: dict[str, list[int]] = {}
    for key, counts in by_key.items():
        name = species_name(key)
        if name:
            merged = species.setdefault(name, [0] * WEEKS)
            species[name] = [a + b for a, b in zip(merged, counts, strict=True)]
        time.sleep(0.05)

    catalogue = json.loads(args.catalogue.read_text(encoding="utf-8"))["species"]
    perch_names = set(perch_labels(args.perch_labels.read_text(encoding="utf-8")))
    gbif_aliases: dict[str, str] = {}
    perch_aliases: dict[str, str] = {}
    perch_missing: list[str] = []
    for name in sorted(catalogue):
        if name not in species and (found := resolve(name, set(species))):
            gbif_aliases[name] = found
        if name not in perch_names:
            if found := resolve(name, perch_names):
                perch_aliases[name] = found
            else:
                perch_missing.append(name)

    args.out.mkdir(parents=True, exist_ok=True)
    retrieved = datetime.now(UTC).strftime("%Y-%m-%d")
    weekly = {
        "version": 1,
        "calendar": "birdnet-48",
        "years": years,
        "totals": totals,
        "species": dict(sorted(species.items())),
        "aliases": dict(sorted(gbif_aliases.items())),
    }
    (args.out / "belgium-weekly.json").write_text(
        json.dumps(weekly, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (args.out / "perch-aliases.json").write_text(
        json.dumps(
            {
                "aliases": dict(sorted(perch_aliases.items())),
                "not_in_perch": perch_missing,
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    query = "https://www.gbif.org/occurrence/search?" + urllib.parse.urlencode(
        [*base_params(), ("year", f"{years[0]},{years[-1]}")]
    )
    manifest = {
        "source": "GBIF.org occurrence search API (public, no account)",
        "retrieved": retrieved,
        "years": [years[0], years[-1]],
        "filters": {**FILTERS, "license": list(LICENCES)},
        "level": "country (Belgium); no coordinates",
        "records": grand_total,
        "species": len(species),
        "query": query,
        "gbif_citation": (
            f"GBIF.org ({retrieved}) GBIF Occurrence Search, filtered as listed in "
            f"this manifest: {query}"
        ),
        "licence_note": (
            "Records are selected by their own licence (CC0 1.0 or CC BY 4.0). A few "
            "datasets whose overall licence is non-commercial contribute only the "
            "records their observers licensed CC0 or CC BY."
        ),
        "download_doi": None,
        "download_doi_note": (
            "A single download DOI needs a GBIF account (occurrence download API). "
            "Until the owner decides to create one, each dataset is cited below with "
            "its own DOI, as GBIF's citation guidelines allow."
        ),
        "datasets": datasets,
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"{len(species)} species, {grand_total} records, {len(datasets)} datasets, "
        f"{len(gbif_aliases)} GBIF aliases, {len(perch_aliases)} Perch aliases, "
        f"{len(perch_missing)} library species not in Perch"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
