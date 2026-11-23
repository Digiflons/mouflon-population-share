"""Aged paper and organic plate edges (MOUL-56, owner's feedback on 0.5.2).

Every drawing is shown as ink printed on a vintage taupe paper:

- the plate's own paper (white or yellowed) becomes the taupe paper, so no white
  rectangle shows (multiply blend, as ink on paper);
- the plate's edge dissolves into the paper along an irregular, soft line: no
  straight edge, no visible oval or box. So that nothing drawn is lost (many plates
  are painted right up to their edge), the plate first bleeds outwards in a soft
  blur of its own colours, and the edge dissolves mostly inside that bleed.

Pillow only (no numpy in the App). Deterministic: the same plate and seed always
give the same edge, so pages stay stable between refreshes.
"""

from __future__ import annotations

import hashlib
import io
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageMath

# Aged taupe paper, shared by the screen, its previews and the Home Assistant images.
PAPER = (214, 203, 186)
# Soft bleed added around the plate, as a share of its shorter side.
BLEED = 0.14
# How far the dissolving line wanders in and out, in bleed widths.
WANDER = 0.6


def seed_of(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)


def _noise(size: tuple[int, int], rng: random.Random) -> Image.Image:
    """Smooth value noise in about [-1, 1], 'F' mode: a few octaves of random grids."""
    width, height = size
    total = Image.new("F", size, 0.0)
    for cells, weight in ((3, 0.55), (7, 0.3), (17, 0.15)):
        cols = max(2, round(cells * width / max(width, height)) + 1)
        rows = max(2, round(cells * height / max(width, height)) + 1)
        grid = Image.new("F", (cols, rows))
        grid.putdata([rng.uniform(-1, 1) * weight for _ in range(cols * rows)])
        layer = grid.resize(size, Image.BICUBIC)
        total = ImageMath.lambda_eval(lambda a: a["t"] + a["l"], t=total, l=layer)
    return total


def organic_mask(size: tuple[int, int], seed: int, band: float) -> Image.Image:
    """'L' mask: 0 on every border, 255 from about ``band`` pixels in, with an
    irregular, feathered line between (soft corners, no straight edge)."""
    width, height = size
    band = max(3.0, band)
    dx = Image.new("F", (width, 1))
    dx.putdata([min(x, width - 1 - x) / band for x in range(width)])
    dy = Image.new("F", (1, height))
    dy.putdata([min(y, height - 1 - y) / band for y in range(height)])
    dx, dy = dx.resize(size, Image.NEAREST), dy.resize(size, Image.NEAREST)
    noise = _noise(size, random.Random(seed))
    # Soft minimum of the two distances rounds the corners; the noise moves the
    # line in and out. The ramp starts beyond the noise's reach: every border is 0.
    alpha = ImageMath.lambda_eval(
        lambda a: a["min"](
            a["max"](
                (a["x"] * a["y"] / (a["x"] + a["y"] + 0.001) + a["n"] * WANDER)
                - WANDER * 0.8,
                0.0,
            )
            / 0.9,
            1.0,
        ),
        x=dx,
        y=dy,
        n=noise,
    )
    alpha = ImageMath.lambda_eval(
        lambda a: a["t"] * a["t"] * (3.0 - 2.0 * a["t"]) * 255.0, t=alpha
    )
    return alpha.convert("L").filter(ImageFilter.GaussianBlur(max(1.0, band * 0.06)))


def _bleed(rgb: Image.Image, pad: int) -> Image.Image:
    """The plate on a larger sheet, its colours running softly past its edge."""
    width, height = rgb.size
    size = (width + 2 * pad, height + 2 * pad)
    halo = rgb.resize(size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(pad * 0.6))
    feather = Image.new("L", rgb.size, 0)
    inset = max(1, pad // 3)
    feather.paste(255, (inset, inset, width - inset, height - inset))
    feather = feather.filter(ImageFilter.GaussianBlur(inset * 0.7))
    halo.paste(rgb, (pad, pad), feather)
    return halo


def _paper_white(rgb: Image.Image) -> tuple[int, int, int]:
    """The plate's lightest paper tone per channel (96th percentile), not too dark."""
    total = rgb.width * rgb.height
    white = []
    for histogram in (rgb.histogram()[i * 256 : (i + 1) * 256] for i in range(3)):
        seen, level = 0, 255
        for level in range(256):
            seen += histogram[level]
            if seen >= total * 0.96:
                break
        white.append(max(190, level))
    return tuple(white)


def trim_blank(image: Image.Image, margin: float = 0.05) -> Image.Image:
    """Drop empty plate paper around the drawing (it would only be paper on paper),
    keeping a margin; nothing drawn is ever cut."""
    rgb = image.convert("RGB")
    white = _paper_white(rgb)
    paper = Image.new("RGB", rgb.size, white)
    ink = ImageChops.difference(rgb, paper).convert("L").point(lambda v: v > 40 and 255)
    box = ink.filter(ImageFilter.MinFilter(3)).getbbox()
    if not box:
        return rgb
    pad_x, pad_y = margin * rgb.width, margin * rgb.height
    return rgb.crop(
        (
            int(max(0, box[0] - pad_x)),
            int(max(0, box[1] - pad_y)),
            int(min(rgb.width, box[2] + pad_x)),
            int(min(rgb.height, box[3] + pad_y)),
        )
    )


def ink_layer(image: Image.Image, seed: int, bleed: float = BLEED) -> Image.Image:
    """The plate as ink: white where there is no ink, dissolving to white at the edge.

    The result is larger than the plate by the bleed on every side. Multiply it onto
    any paper (flat or e-ink speckle) to print the plate there.
    """
    rgb = image.convert("RGB")
    white = _paper_white(rgb)
    # Plate paper to pure white; its faint mottling flattened (the top 4% clip).
    scaled = Image.merge(
        "RGB",
        [
            band.point(lambda v, w=w: min(255, round(v * 255 / (w * 0.96))))
            for band, w in zip(rgb.split(), white, strict=True)
        ],
    )
    pad = max(2, round(bleed * min(rgb.size)))
    sheet = _bleed(scaled, pad)
    mask = organic_mask(sheet.size, seed, pad * 1.25)
    ink = ImageChops.multiply(ImageChops.invert(sheet), Image.merge("RGB", [mask] * 3))
    return ImageChops.invert(ink)


def fit(size: tuple[int, int], bleed: float = BLEED) -> tuple[int, int]:
    """Largest plate size whose ink layer (plate plus bleed) fits in ``size``."""
    width, height = size
    # pad = bleed * shorter side on each side; solve for the plate conservatively.
    share = 1 + 2 * bleed
    return max(1, int(width / share)), max(1, int(height / share))


def print_on(canvas: Image.Image, ink: Image.Image, position: tuple[int, int]) -> None:
    """Print an ink layer onto the canvas at ``position`` (multiply, clipped)."""
    x, y = position
    box = (max(0, x), max(0, y), min(canvas.width, x + ink.width))
    box += (min(canvas.height, y + ink.height),)
    if box[2] <= box[0] or box[3] <= box[1]:
        return
    part = ink.crop((box[0] - x, box[1] - y, box[2] - x, box[3] - y))
    region = canvas.crop(box).convert("RGB")
    canvas.paste(ImageChops.multiply(region, part), box[:2])


def on_paper(image: Image.Image, seed: int, paper=PAPER) -> Image.Image:
    """The plate printed on a flat sheet of paper of the same size."""
    ink = ink_layer(image, seed)
    sheet = Image.new("RGB", ink.size, paper)
    return ImageChops.multiply(sheet, ink)


def rendition(data: bytes, key: str, quality: int = 88) -> bytes:
    """Home Assistant drawing: the plate on aged paper, as JPEG.

    Bytes that are not a readable image are returned unchanged.
    """
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:  # anything unreadable is passed through unchanged
        return data
    buffer = io.BytesIO()
    on_paper(image, seed_of(key)).save(buffer, "JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def placeholder(text: str, font_path: str, size: tuple[int, int] = (360, 480)) -> bytes:
    """Home Assistant image for a bird without a drawing: the text alone on the
    aged paper, like the plates (no frame, no white). JPEG."""
    width, height = size
    sheet = Image.new("RGB", size, PAPER)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(font_path, max(12, width // 11))
    while font.getlength(text) > width * 0.8 and font.size > 10:
        font = ImageFont.truetype(font_path, font.size - 1)
    x = (width - font.getlength(text)) / 2
    draw.text((x, height / 2 - font.size * 0.6), text, font=font, fill=(96, 78, 58))
    buffer = io.BytesIO()
    sheet.save(buffer, "JPEG", quality=88, optimize=True)
    return buffer.getvalue()
