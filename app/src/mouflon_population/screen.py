"""Demo screen for a portrait colour e-ink frame (MOUL-56), device-agnostic.

Design, after the owner's feedback: a free, eclectic plate rather than a grid.

- Collage: each plate is printed on an aged taupe paper and dissolves into it
  along an irregular, soft edge (no rectangle, no oval; ``vintage.py``), at varied
  sizes and positions; silhouettes sometimes perch on a twig or stand on a tuft, as
  on 19th-century plates. The last bird heard is the largest figure, near the
  centre. Placement uses a fixed seed per day, so the page is stable for a day.
- Minimal text, in French by default: tiny handwritten-style names near the birds
  and a small cartouche with the latest bird's name and time. No camera or source
  name on the frame.
- Views: "collage" (one page, latest bird emphasised) or "alternate" (a page for
  the last bird, then the collage of today's birds).
- E-ink realism: previews through a six-colour panel palette with dithering. The
  e-ink paper is a fine, irregular speckle of exact palette colours (white with a
  little yellow and red) that reads as warm aged paper on the panel, without the
  blue and black confetti that plain dithering of a taupe gives.

Species without a drawing in the library are a faint sepia pen sketch (no flat
fill), smaller than the plates.

    python -m mouflon_population.screen --input app/samples/detections.json \\
        --output docs/screen-preview [--watch]

``--watch`` regenerates the preview on every change (MOUL-57); the VS Code task
"Aperçu écran e-ink" runs it next to the Live Preview panel.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from mouflon_population import vintage

FONTS = Path(__file__).resolve().parents[2] / "fonts"
if not FONTS.is_dir():
    FONTS = Path("/opt/mouflon/fonts")
DEFAULT_SIZE = (480, 800)
# Six-colour e-ink palette (black, white, red, yellow, blue, green), close to what
# typical panels show rather than pure sRGB primaries.
EINK_PALETTE = [
    (25, 25, 25),
    (238, 236, 225),
    (178, 46, 38),
    (230, 196, 60),
    (40, 70, 140),
    (60, 110, 60),
]
SCREEN_PAPER = vintage.PAPER  # aged taupe paper, flat
# Target tone of the e-ink paper speckle: lighter than the screen paper and made
# of white, yellow and red dots only. The panel's own white is already a dim warm
# grey, so it reads as aged paper there; black dots would make the tiny names
# hard to read (checked at 1:1 on the 480 x 800 page).
EINK_PAPER = (232, 220, 200)
EINK_PAPER_INKS = (1, 3, 2)  # palette white, yellow, red
INK = (58, 54, 52)
SOFT_INK = (110, 104, 98)
SEPIA = (120, 92, 64)  # pen line of the sketches and their twigs
WORDS = {
    "fr": {
        "heard": "entendu à",
        "none": "En attente du premier oiseau",
        "demo": "démo",
        "provisional": "Confirmation en cours",
    },
    "en": {
        "heard": "heard at",
        "none": "Waiting for the first bird",
        "demo": "demo",
        "provisional": "Confirmation in progress",
    },
}


@dataclass(frozen=True)
class Bird:
    common_name: str
    scientific_name: str
    heard_at: str = ""
    source: str = ""
    count: int = 0
    labels: tuple[str, ...] = ()
    credit: str = ""
    demo: bool = False
    image: bytes | None = None
    status: str = ""


@dataclass(frozen=True)
class Options:
    language: str = "fr"
    view: str = "collage"  # collage | alternate


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), max(8, size))


def seed_for(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16)


def words(options: Options) -> dict[str, str]:
    return WORDS.get(options.language, WORDS["fr"])


# --- figures ------------------------------------------------------------------------


def paper_sheet(size: tuple[int, int], paper: tuple[int, int, int]) -> Image.Image:
    """The page's blank paper. On e-ink, a fixed speckle of exact palette colours."""
    if paper != EINK_PAPER:
        return Image.new("RGB", size, paper)
    width, height = size
    pad = 8  # error diffusion leaves a streak along the first rows: cut it off
    big = (width + 2 * pad, height + 2 * pad)
    # Fixed, seeded grain (about +/-24 levels) so the speckle is irregular, like
    # paper fibres, yet identical on every refresh.
    noise = random.Random(seed_for("paper", *map(str, size))).randbytes(big[0] * big[1])
    grain = Image.frombytes("L", big, noise).point(lambda v: 104 + v * 48 // 255)
    flat = ImageChops.add(Image.new("RGB", big, paper), grain.convert("RGB"), 1, -128)
    inks = [EINK_PALETTE[i] for i in EINK_PAPER_INKS]
    palette = [v for colour in inks for v in colour]
    palette += palette[:3] * (256 - len(inks))
    palette_image = Image.new("P", (1, 1))
    palette_image.putpalette(palette)
    sheet = flat.quantize(palette=palette_image, dither=Image.Dither.FLOYDSTEINBERG)
    return sheet.convert("RGB").crop((pad, pad, pad + width, pad + height))


def plate_ink(bird: Bird, size: tuple[int, int]) -> Image.Image:
    """The bird's plate fitted to ``size``, as an ink layer with an organic edge."""
    image = vintage.trim_blank(Image.open(io.BytesIO(bird.image)))
    # Fit both ways: the library renditions are small, the large frame is not.
    room = vintage.fit(size)
    scale = min(room[0] / image.width, room[1] / image.height)
    image = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.LANCZOS,
    )
    key = bird.scientific_name or bird.common_name
    return vintage.ink_layer(image, vintage.seed_of(key))


def silhouette(
    name: str, size: tuple[int, int], eink_safe: bool = False
) -> Image.Image:
    """A faint sepia pen sketch for a species without a plate (0.5.3).

    Outline and a few strokes only, no flat fill, so it sits with the engravings.
    Pose and proportions vary per species. On e-ink the line is the palette black
    (a thin sepia line would be dithered into broken dots).
    """
    width, height = size
    rng = random.Random(seed_for(name))
    shape = Image.new("L", size, 0)
    draw = ImageDraw.Draw(shape)
    upright = rng.random() < 0.4
    body_w = width * (0.42 if upright else 0.58)
    body_h = height * (0.48 if upright else 0.34)
    cx, cy = width * 0.5, height * (0.48 if upright else 0.55)
    draw.ellipse(
        (cx - body_w / 2, cy - body_h / 2, cx + body_w / 2, cy + body_h / 2), fill=255
    )
    facing = 1 if rng.random() < 0.5 else -1
    head_r = min(width, height) * rng.uniform(0.11, 0.15)
    hx = cx + facing * body_w * (0.28 if upright else 0.38)
    hy = cy - body_h * (0.62 if upright else 0.55)
    draw.ellipse((hx - head_r, hy - head_r, hx + head_r, hy + head_r), fill=255)
    draw.polygon(
        [
            (hx - head_r * 0.8, hy),
            (hx + head_r * 0.8, hy),
            (cx + facing * body_w * 0.2, cy - body_h * 0.2),
            (cx - facing * body_w * 0.05, cy - body_h * 0.3),
        ],
        fill=255,
    )
    beak = head_r * rng.uniform(0.7, 1.3)
    draw.polygon(
        [
            (hx + facing * head_r * 0.8, hy - head_r * 0.2),
            (hx + facing * (head_r + beak), hy + head_r * 0.1),
            (hx + facing * head_r * 0.8, hy + head_r * 0.35),
        ],
        fill=255,
    )
    tail = body_w * rng.uniform(0.35, 0.6)
    tx = cx - facing * body_w * 0.45
    ty = cy + body_h * (0.25 if upright else 0.05)
    drop = tail * (0.9 if upright else 0.35)
    draw.polygon(
        [
            (tx, ty - body_h * 0.12),
            (tx - facing * tail, ty + drop - tail * 0.12),
            (tx - facing * tail * 0.9, ty + drop + tail * 0.12),
            (tx, ty + body_h * 0.12),
        ],
        fill=255,
    )
    # The outline of the whole bird, then a wing line, an eye and the legs.
    line = max(1, round(min(width, height) / 110))
    edge = ImageChops.subtract(shape, shape.filter(ImageFilter.MinFilter(2 * line + 1)))
    ink = EINK_PALETTE[0] if eink_safe else SEPIA
    figure = Image.new("RGBA", size, (*ink, 0))
    figure.putalpha(edge.point(lambda v: 255 if eink_safe and v else v * 3 // 4))
    pen = ImageDraw.Draw(figure)
    colour = (*ink, 255 if eink_safe else 190)
    pen.arc(
        (cx - body_w * 0.35, cy - body_h * 0.4, cx + body_w * 0.35, cy + body_h * 0.3),
        200 if facing > 0 else -20,
        340 if facing > 0 else 120,
        fill=colour,
        width=line,
    )
    eye = max(1.5, head_r * 0.12)
    ex, ey = hx + facing * head_r * 0.35, hy - head_r * 0.2
    pen.ellipse((ex - eye, ey - eye, ex + eye, ey + eye), fill=colour)
    leg_top, foot = cy + body_h * 0.42, height * 0.93
    for dx in (-0.08, 0.06):
        x = cx + dx * width
        pen.line((x, leg_top, x + facing * 2, foot), fill=colour, width=line)
    return figure


def perch(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, ...],
    rng: random.Random,
    scale: float,
    eink_safe: bool = False,
):
    """A twig or a ground tuft under a figure, as on old plates."""
    branch = tuft = EINK_PALETTE[0] if eink_safe else SEPIA
    x0, y0, x1, y1 = box
    foot = y1 - (y1 - y0) * 0.07
    if rng.random() < 0.55:
        start, end = x0 - (x1 - x0) * 0.25, x1 + (x1 - x0) * 0.2
        tilt = rng.uniform(-0.12, 0.12) * (x1 - x0)
        draw.line(
            (start, foot - tilt, end, foot + tilt),
            fill=branch,
            width=max(1, round(2 * scale)),
        )
        for _ in range(rng.randint(1, 3)):
            t = rng.uniform(0.1, 0.9)
            bx, by = start + (end - start) * t, foot - tilt + 2 * tilt * t
            tip = (bx + rng.uniform(-18, 18) * scale, by - rng.uniform(8, 22) * scale)
            draw.line((bx, by, *tip), fill=branch, width=max(1, round(1.4 * scale)))
    else:
        cx = (x0 + x1) / 2
        for _ in range(rng.randint(5, 9)):
            dx = rng.uniform(-0.3, 0.3) * (x1 - x0)
            tip = (
                cx + dx + rng.uniform(-8, 8) * scale,
                foot - rng.uniform(6, 16) * scale,
            )
            draw.line(
                (cx + dx, foot + 3 * scale, *tip),
                fill=tuft,
                width=max(1, round(1.4 * scale)),
            )


# --- layout -------------------------------------------------------------------------


@dataclass
class Placed:
    bird: Bird
    box: tuple[float, float, float, float]


def overlap(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / smaller


def centre(box: tuple[float, ...]) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def best_spot(
    placed: list[Placed],
    area: tuple[float, float, float, float],
    size: tuple[float, float],
    rng: random.Random,
) -> tuple[float, float, float, float] | None:
    """Best of a few random spots: far from the others, little overlap."""
    x0, y0, x1, y1 = area
    w, h = size
    best, best_score = None, -math.inf
    for _ in range(80):
        cx = rng.uniform(x0 + w / 2, x1 - w / 2)
        cy = rng.uniform(y0 + h / 2, y1 - h / 2)
        box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        worst = max((overlap(box, p.box) for p in placed), default=0.0)
        # Faded edges may overlap a little, as on a crowded old plate.
        if worst > 0.24:
            continue
        gap = min((math.dist((cx, cy), centre(p.box)) for p in placed), default=x1 - x0)
        score = gap - worst * (x1 - x0) + rng.uniform(0, (x1 - x0) * 0.05)
        if score > best_score:
            best, best_score = box, score
    return best


def aspect(bird: Bird) -> float:
    """Height / width of the bird's figure: its trimmed plate, or 1 for a sketch."""
    if not bird.image:
        return 1.0
    image = vintage.trim_blank(Image.open(io.BytesIO(bird.image)))
    return min(1.8, max(0.55, image.height / image.width))


def shaped(
    area: float, ratio: float, max_w: float, max_h: float
) -> tuple[float, float]:
    """A box of about ``area`` with height / width ``ratio``, within the limits."""
    w = math.sqrt(area / ratio)
    h = w * ratio
    scale = min(1.0, max_w / w, max_h / h)
    return w * scale, h * scale


def place(
    birds: list[Bird],
    area: tuple[float, float, float, float],
    seed: int,
    feature_first: bool,
) -> list[Placed]:
    """Balanced but irregular placement: best-candidate sampling, slight overlaps."""
    rng = random.Random(seed)
    x0, y0, x1, y1 = area
    width, height = x1 - x0, y1 - y0
    placed: list[Placed] = []
    for index, bird in enumerate(birds):
        if index == 0 and feature_first:
            alone = len(birds) == 1
            # A full page gives the featured bird a little less room.
            w = width * (0.92 if alone else 0.66 if len(birds) <= 6 else 0.58)
            w, h = shaped(w * w * 1.05, aspect(bird), width * 0.92, height * 0.62)
            cx = x0 + width * rng.uniform(0.46, 0.54)
            cy = y0 + height * (0.5 if alone else 0.42)
            placed.append(
                Placed(bird, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
            )
            continue
        # Larger than the plates themselves: each figure carries its soft bleed.
        w = width * rng.uniform(0.34, 0.46) * (1.0 if index < 6 else 0.9)
        # The box takes the plate's own shape, so no room is wasted beside it.
        w, h = shaped(w * w * 1.08, aspect(bird), width * 0.6, height * 0.4)
        best = None
        # A crowded page shrinks a figure rather than leave the bird out.
        for _ in range(12):
            best = best_spot(placed, area, (w, h), rng)
            if best is not None:
                break
            w, h = w * 0.88, h * 0.88
        if best is not None:
            placed.append(Placed(bird, best))
    return placed


def tiny_label(draw, text: str, box: tuple[float, ...], scale: float, ink=SOFT_INK):
    f = shrink(
        text, "PinyonScript-Regular.ttf", round(15 * scale), (box[2] - box[0]) * 1.3
    )
    x = (box[0] + box[2]) / 2 - f.getlength(text) / 2
    draw.text((x, box[3] + 2 * scale), text, font=f, fill=ink)


def shrink(
    text: str, name: str, start: int, max_width: float
) -> ImageFont.FreeTypeFont:
    f = font(name, start)
    while f.getlength(text) > max_width and f.size > 9:
        f = font(name, f.size - 1)
    return f


def cartouche(
    draw,
    bird: Bird | None,
    size: tuple[int, int],
    options: Options,
    inks: tuple[tuple[int, int, int], tuple[int, int, int]] = (INK, SOFT_INK),
) -> None:
    """Small cartouche with the latest bird's name and time. Never a source name."""
    ink, soft = inks
    width, height = size
    scale = width / 480
    w = words(options)
    name = bird.common_name if bird else w["none"]
    f_name = shrink(name, "PinyonScript-Regular.ttf", round(30 * scale), width * 0.7)
    detail = ""
    if bird:
        when = bird.heard_at[11:16] if len(bird.heard_at) >= 16 else bird.heard_at
        detail = f"{bird.scientific_name} · {w['heard']} {when}"
        if bird.status == "provisional":
            detail += f" · {w['provisional']}"
        elif bird.labels:
            detail += f" · {bird.labels[0]}"
        if bird.demo:
            detail += f" · {w['demo']}"
    f_detail = shrink(
        detail, "IMFellEnglish-Italic.ttf", round(13 * scale), width * 0.78
    )
    box_w = max(f_name.getlength(name), f_detail.getlength(detail)) + 44 * scale
    box_h = f_name.size + f_detail.size + 24 * scale
    x0 = (width - box_w) / 2
    y0 = height - box_h - height * 0.035
    draw.rounded_rectangle(
        (x0, y0, x0 + box_w, y0 + box_h),
        radius=box_h / 3,
        outline=soft,
        width=max(1, round(scale)),
    )
    draw.text(
        ((width - f_name.getlength(name)) / 2, y0 + 4 * scale),
        name,
        font=f_name,
        fill=ink,
    )
    draw.text(
        ((width - f_detail.getlength(detail)) / 2, y0 + 10 * scale + f_name.size),
        detail,
        font=f_detail,
        fill=soft,
    )


def compose(
    birds: list[Bird],
    size: tuple[int, int],
    day: datetime,
    options: Options,
    paper: tuple[int, int, int],
    feature_first: bool,
    caption_bird: Bird | None,
    labels: bool = True,
) -> Image.Image:
    width, height = size
    scale = width / 480
    canvas = paper_sheet(size, paper)
    draw = ImageDraw.Draw(canvas)
    margin = width * 0.06
    area = (margin, height * 0.04, width - margin, height * 0.84)
    seed = seed_for(day.date().isoformat(), *(b.scientific_name for b in birds))
    placements = place(birds, area, seed, feature_first)
    rng = random.Random(seed + 1)
    eink_safe = paper == EINK_PAPER
    # Text in exact palette colours on e-ink, so it is not dithered.
    inks = (EINK_PALETTE[0], EINK_PALETTE[0]) if eink_safe else (INK, SOFT_INK)
    band = 20 * scale if labels else 0
    for index, spot in enumerate(placements):
        if labels and not (feature_first and index == 0):
            x0, y0, x1, y1 = spot.box
            spot.box = (x0, y0, x1, y1 - band)
    for spot in sorted(placements, key=lambda p: p.box[1]):
        x0, y0, x1, y1 = spot.box
        size_px = (int(x1 - x0), int(y1 - y0))
        if spot.bird.image:
            # Printed (multiplied) onto the paper: its own paper vanishes and the
            # e-ink speckle shows through, so no patch or edge is visible.
            ink = plate_ink(spot.bird, size_px)
            position = (int((x0 + x1) / 2 - ink.width / 2), int(y1 - ink.height))
            vintage.print_on(canvas, ink, position)
            continue
        name = spot.bird.scientific_name or spot.bird.common_name
        # A modest sketch: smaller than the plates around it, sometimes on a
        # pen-drawn twig or tuft (real plates bring their own branches).
        sketch = (max(8, int(size_px[0] * 0.62)), max(8, int(size_px[1] * 0.62)))
        figure = silhouette(name, sketch, eink_safe)
        position = (int((x0 + x1) / 2 - figure.width / 2), int(y1 - figure.height))
        if rng.random() < 0.7:
            perch(
                draw,
                (position[0], position[1], position[0] + figure.width, y1),
                rng,
                scale,
                eink_safe,
            )
        canvas.paste(figure, position, figure)
    if labels:
        for index, spot in enumerate(placements):
            if not (feature_first and index == 0):
                tiny_label(draw, spot.bird.common_name, spot.box, scale, inks[1])
    cartouche(draw, caption_bird, size, options, inks)
    return canvas


def render_collage(
    last: Bird | None,
    today: list[Bird],
    day: datetime,
    size: tuple[int, int] = DEFAULT_SIZE,
    options: Options | None = None,
    paper: tuple[int, int, int] = SCREEN_PAPER,
) -> Image.Image:
    """One page: the last bird large near the centre, today's others around it."""
    options = options or Options()
    others = [b for b in today if not last or b.scientific_name != last.scientific_name]
    birds = ([last] if last else []) + others[:9]
    return compose(birds, size, day, options, paper, bool(last), last)


def render_last_bird(
    bird: Bird | None,
    size: tuple[int, int] = DEFAULT_SIZE,
    options: Options | None = None,
    paper: tuple[int, int, int] = SCREEN_PAPER,
    day: datetime | None = None,
) -> Image.Image:
    options = options or Options()
    day = day or datetime(2000, 1, 1)
    birds = [bird] if bird else []
    return compose(birds, size, day, options, paper, True, bird, labels=False)


def render_today(
    birds: list[Bird],
    day: datetime,
    size: tuple[int, int] = DEFAULT_SIZE,
    total: int | None = None,
    options: Options | None = None,
    paper: tuple[int, int, int] = SCREEN_PAPER,
) -> Image.Image:
    """Today's birds as a free collage of figures of similar weight."""
    del total
    options = options or Options()
    latest = birds[0] if birds else None
    return compose(birds[:10], size, day, options, paper, False, latest)


def eink(
    image: Image.Image, palette: list[tuple[int, int, int]] = EINK_PALETTE
) -> Image.Image:
    """Preview through a limited e-ink palette with Floyd-Steinberg dithering."""
    flat = [value for colour in palette for value in colour]
    flat += flat[:3] * (256 - len(palette))
    palette_image = Image.new("P", (1, 1))
    palette_image.putpalette(flat)
    dither = Image.Dither.FLOYDSTEINBERG
    return (
        image.convert("RGB")
        .quantize(palette=palette_image, dither=dither)
        .convert("RGB")
    )


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def bird_from_dict(item: dict, image: bytes | None = None) -> Bird:
    rarity = item.get("rarity") or {}
    return Bird(
        common_name=item.get("common_name", ""),
        scientific_name=item.get("scientific_name", ""),
        heard_at=item.get("detected_at") or item.get("last_heard") or "",
        source=item.get("source", ""),
        count=item.get("count", 0),
        labels=tuple(rarity.get("labels", [])),
        credit=item.get("credit") or "",
        demo=bool(item.get("demo")),
        image=image,
        status=item.get("status") or "",
    )


VIEWS = {
    "dernier-oiseau": "Dernier oiseau",
    "oiseaux-du-jour": "Oiseaux du jour",
    "collage": "Collage unique",
}
SIZES = {
    "480x800": "7,3 pouces (480 \u00d7 800)",
    "1200x1600": "13,3 pouces (1200 \u00d7 1600)",
}
RENDERS = {"ecran": "Écran", "eink": "E-ink"}


def preview_pages(
    last: Bird | None,
    today: list[Bird],
    day: datetime,
    size: tuple[int, int],
    language: str,
) -> dict[tuple[str, str], Image.Image]:
    """Every page the frame can show, for one size: (view, render) -> image."""
    options = Options(language)
    pages = {}
    for render, paper in (("ecran", SCREEN_PAPER), ("eink", EINK_PAPER)):
        views = {
            "dernier-oiseau": render_last_bird(last, size, options, paper, day),
            "oiseaux-du-jour": render_today(
                today, day, size, options=options, paper=paper
            ),
            "collage": render_collage(last, today, day, size, options, paper),
        }
        for view, image in views.items():
            pages[view, render] = eink(image) if render == "eink" else image
    return pages


def preview_html(images: dict[tuple[str, str, str], str], title: str, note: str) -> str:
    """Self-contained page with controls: view, size, normal or e-ink (in French).

    ``images`` maps (view, size, render) to a base64 PNG.
    """

    def radios(group: str, choices: dict[str, str]) -> str:
        return "".join(
            f"<label><input type=radio name={group} value={key}"
            f"{' checked' if index == 0 else ''}> {text}</label>"
            for index, (key, text) in enumerate(choices.items())
        )

    figures = "".join(
        f"<img data-key='{view}|{size}|{render}' hidden alt='{VIEWS[view]}' "
        f"src='data:image/png;base64,{data}'>"
        for (view, size, render), data in images.items()
    )
    return f"""<!DOCTYPE html><html lang=fr><head><meta charset=utf-8>
<title>{title}</title><style>
body{{font-family:system-ui,sans-serif;margin:1rem;background:#d9d9d9;color:#222}}
fieldset{{display:inline-block;border:1px solid #999;margin:0 .6rem .6rem 0}}
label{{margin-right:.8rem;white-space:nowrap}}
.frame{{display:inline-block;background:#5b3d22;padding:14px;border-radius:4px}}
.frame img{{display:block;max-width:min(92vw,480px);height:auto}}
</style></head><body>
<h1>{title}</h1><p>{note}</p>
<fieldset><legend>Vue</legend>{radios("view", VIEWS)}</fieldset>
<fieldset><legend>Taille</legend>{radios("size", SIZES)}</fieldset>
<fieldset><legend>Rendu</legend>{radios("render", RENDERS)}</fieldset>
<div class=frame>{figures}</div>
<script>
const groups = ["view", "size", "render"];
function show() {{
  const key = groups.map(g =>
    document.querySelector(`input[name=${{g}}]:checked`).value).join("|");
  document.querySelectorAll("img[data-key]").forEach(i => {{
    i.hidden = i.dataset.key !== key;
  }});
  try {{ localStorage.setItem("mouflon-screen", key); }} catch (e) {{}}
}}
try {{
  const saved = (localStorage.getItem("mouflon-screen") || "").split("|");
  groups.forEach((g, n) => {{
    const input = document.querySelector(`input[name=${{g}}][value="${{saved[n]}}"]`);
    if (input) input.checked = true;
  }});
}} catch (e) {{}}
document.querySelectorAll("input[type=radio]").forEach(i =>
  i.addEventListener("change", show));
show();
</script></body></html>"""


def sample_birds(path: Path, library: Path | None) -> tuple[Bird, list[Bird], datetime]:
    data = json.loads(path.read_text(encoding="utf-8"))
    detections = sorted(
        data["detections"], key=lambda d: d["detected_at"], reverse=True
    )

    def image_for(scientific: str) -> bytes | None:
        if not library:
            return None
        file = library / "images" / f"{scientific.lower().replace(' ', '_')}.jpg"
        return file.read_bytes() if file.is_file() else None

    newest = detections[0]
    day = datetime.fromisoformat(newest["detected_at"])
    today_items: dict[str, dict] = {}
    for d in detections:
        if d["detected_at"][:10] == newest["detected_at"][:10]:
            item = today_items.setdefault(d["scientific_name"], {**d, "count": 0})
            item["count"] += 1
    rarity = {"labels": ["Nouveau pour le jardin"]}
    last = bird_from_dict(
        {**newest, "rarity": rarity}, image_for(newest["scientific_name"])
    )
    today = [bird_from_dict(v, image_for(k)) for k, v in today_items.items()]
    return last, today, day


def write_preview(
    input_path: Path, output: Path, sizes: str, library: Path | None, language: str
) -> None:
    last, today, day = sample_birds(input_path, library)
    output.mkdir(parents=True, exist_ok=True)
    for old in output.glob("*.png"):
        old.unlink()
    images = {}
    for text in sizes.split(","):
        size = tuple(int(v) for v in text.lower().split("x"))
        key = f"{size[0]}x{size[1]}"
        for (view, render), image in preview_pages(
            last, today, day, size, language
        ).items():
            data = png_bytes(image)
            suffix = "-eink" if render == "eink" else ""
            (output / f"{view}-{key}{suffix}.png").write_bytes(data)
            images[view, key, render] = base64.b64encode(data).decode()
    note = (
        "Écran de démonstration à partir de données d'exemple (détections inventées). "
        "Les oiseaux ont leur gravure ancienne quand la bibliothèque en contient une, "
        "une silhouette sinon. « E-ink » montre la page à travers une "
        "palette à six couleurs avec tramage, comme sur un cadre couleur."
    )
    page = preview_html(images, "Mouflon Population — aperçu de l'écran e-ink", note)
    temporary = output / ".preview.html.tmp"
    temporary.write_text(page, encoding="utf-8")
    temporary.replace(output / "preview.html")


def watched_files(input_path: Path) -> list[Path]:
    here = Path(__file__).resolve()
    return [here, input_path, *sorted(FONTS.glob("*"))]


def watch(argv: list[str], input_path: Path, interval_s: float = 1.0) -> int:
    """Regenerate the preview whenever the renderer, fonts or sample data change.

    Each run is a fresh process, so code edits are picked up. Local only: no server,
    no network.
    """
    import subprocess
    import sys
    import time

    command = [sys.executable, "-m", "mouflon_population.screen", *argv]
    seen: dict[Path, float] = {}
    print("Surveillance de l'écran : Ctrl+C pour arrêter.", flush=True)
    try:
        while True:
            current = {
                p: p.stat().st_mtime for p in watched_files(input_path) if p.exists()
            }
            if current != seen:
                seen = current
                print("Rendu en cours…", flush=True)
                done = subprocess.run(command, check=False)
                status = "Aperçu prêt." if done.returncode == 0 else "Erreur de rendu."
                print(f"{status} ({time.strftime('%H:%M:%S')})", flush=True)
            time.sleep(interval_s)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True, help="detections JSON")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", default="480x800,1200x1600")
    parser.add_argument("--library", type=Path, help="library folder with images/")
    parser.add_argument("--language", default="fr", choices=sorted(WORDS))
    parser.add_argument(
        "--watch", action="store_true", help="regenerate on every change (MOUL-57)"
    )
    args = parser.parse_args(argv)
    if args.watch:
        return watch([a for a in argv if a != "--watch"], args.input)
    write_preview(args.input, args.output, args.sizes, args.library, args.language)
    print(f"Wrote {args.output}/preview.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
