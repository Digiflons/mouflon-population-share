"""Before/after contact sheet for a crop or style review (MOUL-42, 0.5.3, 0.6.0).

    python tools/illustrations/before_after.py <before images/> <after images/> \\
        <catalogue.json> <output.html> [<output.png>] [--crop-review]

Default (0.5.3 style review): "before" is shown as the files are (the earlier
release's renditions); "after" as Home Assistant and the screen show it now:
printed on aged paper with an organic edge (``vintage.py``).
``--crop-review`` (0.6.0): only species that have a "before" file, both sides on
the aged paper, so only the crop differs. Self-contained page, nothing fetched.
"""

from __future__ import annotations

import base64
import html
import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app" / "src" / "mouflon_population"))
import vintage  # noqa: E402

THUMB = 260


def _thumb(image: Image.Image) -> Image.Image:
    image = image.convert("RGB")
    image.thumbnail((THUMB, THUMB), Image.LANCZOS)
    return image


def _jpeg(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode()


def _on_paper(path: Path, scientific: str) -> Image.Image:
    return Image.open(io.BytesIO(vintage.rendition(path.read_bytes(), scientific)))


def pairs(
    before: Path, after: Path, catalogue: dict, crop_review: bool = False
) -> list[tuple[str, ...]]:
    rows = []
    for scientific, entry in sorted(catalogue.items()):
        name = entry.get("image")
        if not name or not (after / name).is_file():
            continue
        if crop_review and not (before / name).is_file():
            continue
        if crop_review:
            old = _thumb(_on_paper(before / name, scientific))
        else:
            old = (
                _thumb(Image.open(before / name)) if (before / name).is_file() else None
            )
        new_bytes = vintage.rendition((after / name).read_bytes(), scientific)
        new = _thumb(Image.open(io.BytesIO(new_bytes)))
        rows.append((entry.get("common_name", scientific), scientific, old, new))
    return rows


TEXTS = {
    False: {
        "labels": ("0.5.2", "0.5.3"),
        "title": "gravures avant / après (0.5.3)",
        "heading": "Gravures du pack de démo : avant (0.5.2) / après (0.5.3)",
        "intro": "À gauche, l'image envoyée à Home Assistant en 0.5.2. À droite, "
        "0.5.3 : recadrage plus large (planche entière dans le doute), papier taupe "
        "ancien, bord irrégulier qui se fond dans le papier.",
    },
    True: {
        "labels": ("planche", "0.6.0"),
        "title": "planches à plusieurs espèces, recadrage (0.6.0)",
        "heading": "Planches à plusieurs espèces : planche entière / recadrage 0.6.0",
        "intro": "À gauche, la planche entière telle que construite. À droite, le "
        "cadre retenu pour 0.6.0 : l'oiseau de l'espèce avec des marges "
        "généreuses, ou la planche entière quand les oiseaux se chevauchent ou se "
        "ressemblent trop. Même papier taupe et mêmes bords doux.",
    },
}


def write_html(rows, output: Path, crop_review: bool = False) -> None:
    text = TEXTS[crop_review]
    before_label, after_label = text["labels"]
    cards = []
    for common, scientific, old, new in rows:
        old_tag = (
            f"<img src='data:image/jpeg;base64,{_jpeg(old)}' alt='avant'>"
            if old
            else "<p>—</p>"
        )
        cards.append(
            "<figure><div class=pair>"
            f"<div><small>{before_label}</small>{old_tag}</div>"
            f"<div><small>{after_label}</small>"
            f"<img src='data:image/jpeg;base64,{_jpeg(new)}'"
            " alt='après'></div></div>"
            f"<figcaption><b>{html.escape(common)}</b> · "
            f"<i>{html.escape(scientific)}</i></figcaption></figure>"
        )
    page = f"""<!DOCTYPE html><html lang=fr><head><meta charset=utf-8>
<title>Mouflon Population — {text["title"]}</title>
<style>body{{font-family:system-ui,sans-serif;margin:1rem;background:#8a8278}}
h1,p{{color:#fff}}.grid{{display:grid;
grid-template-columns:repeat(auto-fill,minmax(560px,1fr));gap:14px}}
figure{{margin:0;background:#5d564e;padding:8px;border-radius:6px}}
.pair{{display:flex;gap:10px;align-items:flex-end;justify-content:center}}
.pair div{{text-align:center;color:#eee}} small{{display:block}}
img{{max-width:{THUMB}px;max-height:{THUMB}px}}
figcaption{{color:#fff;font-size:13px;margin-top:6px;text-align:center}}
</style></head><body>
<h1>{text["heading"]}</h1>
<p>{text["intro"]} {len(rows)} oiseaux.</p>
<div class=grid>{"".join(cards)}</div></body></html>"""
    output.write_text(page, encoding="utf-8")


def write_png(rows, output: Path, crop_review: bool = False) -> None:
    before_label, after_label = TEXTS[crop_review]["labels"]
    cell_w, cell_h, cols = 2 * THUMB + 30, THUMB + 40, 3
    sheet = Image.new(
        "RGB", (cols * cell_w, -(-len(rows) // cols) * cell_h), (93, 86, 78)
    )
    draw = ImageDraw.Draw(sheet)
    for index, (common, _, old, new) in enumerate(rows):
        x, y = (index % cols) * cell_w + 10, (index // cols) * cell_h + 8
        if old:
            sheet.paste(old, (x, y + THUMB - old.height))
        sheet.paste(new, (x + THUMB + 10, y + THUMB - new.height))
        draw.text(
            (x, y + THUMB + 8),
            f"{common}  ({before_label} | {after_label})",
            fill="white",
        )
    sheet.save(output, optimize=True)


def main(argv: list[str]) -> int:
    crop_review = "--crop-review" in argv
    argv = [a for a in argv if a != "--crop-review"]
    before, after, catalogue_path, output = (Path(a) for a in argv[:4])
    catalogue = json.loads(catalogue_path.read_text(encoding="utf-8"))["species"]
    rows = pairs(before, after, catalogue, crop_review)
    write_html(rows, output, crop_review)
    if len(argv) > 4:
        write_png(rows, Path(argv[4]), crop_review)
    print(f"{len(rows)} plates compared")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
