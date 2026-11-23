"""Plain HTML page of detections (MOUL-31).

Used for the preview here in Claude (from sample detections) and, later, for the
App's own page. Functional only: no design work. Every value is HTML-escaped.

    python -m mouflon_population.preview --input detections.json --output page.html
    python -m mouflon_population.preview --db birdlog.sqlite --output page.html
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from html import escape
from pathlib import Path

STYLE = """
body{font-family:system-ui,sans-serif;margin:1.5rem;max-width:60rem}
table{border-collapse:collapse;width:100%;margin-bottom:2rem}
th,td{text-align:left;padding:.35rem .6rem;border-bottom:1px solid #ccc}
th{background:#f2f2f2}
.note{color:#555;font-size:.9rem}
""".strip()


def _pct(value: float) -> str:
    return f"{value * 100:.0f} %"


def render(detections: list[dict], title: str, note: str = "") -> str:
    ordered = sorted(detections, key=lambda d: d["detected_at"], reverse=True)
    species: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "best": 0.0, "last": "", "sources": set()}
    )
    for d in ordered:
        s = species[d["scientific_name"]]
        s["common"] = d["common_name"]
        s["count"] += 1
        s["best"] = max(s["best"], d["confidence"])
        s["last"] = max(s["last"], d["detected_at"])
        s["sources"].add(d["source"])
    summary_rows = "".join(
        "<tr><td>{}</td><td><i>{}</i></td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            escape(v["common"]),
            escape(name),
            v["count"],
            _pct(v["best"]),
            escape(v["last"].replace("T", " ")[:16]),
            escape(", ".join(sorted(v["sources"]))),
        )
        for name, v in sorted(species.items(), key=lambda kv: -kv[1]["count"])
    )
    recent_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            escape(d["detected_at"].replace("T", " ")[:19]),
            escape(d["common_name"]),
            _pct(d["confidence"]),
            escape(d["source"]),
        )
        for d in ordered[:50]
    )
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{STYLE}</style>
</head>
<body>
<h1>{escape(title)}</h1>
<p class="note">{escape(note)}</p>
<p>{len(species)} espèces, {len(ordered)} détections.</p>
<h2>Espèces</h2>
<table>
<tr><th>Oiseau</th><th>Nom scientifique</th><th>Détections</th>
<th>Meilleure confiance</th><th>Dernière écoute</th><th>Entendu par</th></tr>
{summary_rows}
</table>
<h2>Dernières détections</h2>
<table>
<tr><th>Heure</th><th>Oiseau</th><th>Confiance</th><th>Entendu par</th></tr>
{recent_rows}
</table>
<p class="note">Journal des oiseaux uniquement : espèce, confiance, source et heure.
Aucun son n'est jamais conservé.</p>
</body>
</html>
"""


def _from_db(path: Path) -> list[dict]:
    from mouflon_population.birdlog import BirdLog

    log = BirdLog(path)
    try:
        return [d.as_dict() for d in log.recent(limit=10_000)]
    finally:
        log.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", type=Path, help="JSON file with detections")
    group.add_argument("--db", type=Path, help="bird log database")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="Mouflon Population — oiseaux entendus")
    args = parser.parse_args(argv)
    if args.input:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        detections, note = data["detections"], data.get("note", "")
    else:
        detections = _from_db(args.db)
        note = (
            f"Créé le {datetime.now().astimezone():%Y-%m-%d %H:%M} à partir du journal."
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(detections, args.title, note), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
