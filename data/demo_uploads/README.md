# Demo uploads

Raster copies of `data/sample_receipts/`, for dragging into the submit form during a
demo. They exist because the samples are SVG and `services/receipts.py` refuses an SVG
upload on purpose — an SVG can carry script, and nothing stops a browser running it if
the file is ever served as a document. Nothing in the app reads this folder;
`install_samples()` only looks at `sample_receipts/`.

Each one prints the same total as its SVG twin, so attaching `figma.png` to an $890
software expense is the fastest way to watch the receipt check hold a payout.

## Regenerating

Edit the SVG, then re-run from the repo root:

```bash
uv run --with pillow python - <<'PY'
"""Render each sample receipt SVG as a PNG a demo can actually upload."""

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SRC = Path("data/sample_receipts")
OUT = Path("data/demo_uploads")

FONTS = [
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]

TEXT = re.compile(r'<text[^>]*?x="(\d+)"[^>]*?y="(\d+)"[^>]*?>(.*?)</text>', re.DOTALL)
TAG = re.compile(r"<[^>]+>")
SIZE = re.compile(r'class="([a-z])"')
VIEWBOX = re.compile(r'viewBox="0 0 (\d+) (\d+)"')
CLASS_SIZE = {"h": 19, "s": 11, "i": 13, "t": 15, "f": 10, "r": 13}


def font(path_index, size, bold=False):
    for candidate in FONTS[path_index:]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(svg_path: Path) -> Path:
    svg = svg_path.read_text()
    width, height = (int(v) for v in VIEWBOX.search(svg).groups())
    scale = 2  # so the text survives being looked at

    image = Image.new("RGB", (width * scale, height * scale), "#fffdf8")
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        [8 * scale, 8 * scale, (width - 8) * scale, (height - 8) * scale],
        fill="#ffffff",
        outline="#e2ded4",
    )

    for match in re.finditer(r"<text[^>]*>.*?</text>", svg, re.DOTALL):
        block = match.group(0)
        x = int(re.search(r'x="(\d+)"', block).group(1))
        y = int(re.search(r'y="(\d+)"', block).group(1))
        cls = SIZE.search(block)
        classes = re.search(r'class="([^"]*)"', block)
        names = classes.group(1).split() if classes else []
        size = next((CLASS_SIZE[n] for n in names if n in CLASS_SIZE), 13)
        bold = "h" in names or "t" in names
        anchor = "rs" if "r" in names else ("ms" if "middle" in block else "ls")
        colour = "#666666" if "s" in names else ("#888888" if "f" in names else "#1a1a1a")
        text = " ".join(TAG.sub("", block).split())
        if not text:
            continue
        draw.text(
            (x * scale, y * scale),
            text,
            font=font(1 if bold else 0, size * scale),
            fill=colour,
            anchor=anchor,
        )

    for line in re.finditer(r"<line[^>]*/>", svg):
        attrs = dict(re.findall(r'(\w+[\w-]*)="([^"]+)"', line.group(0)))
        draw.line(
            [
                int(attrs["x1"]) * scale,
                int(attrs["y1"]) * scale,
                int(attrs["x2"]) * scale,
                int(attrs["y2"]) * scale,
            ],
            fill=attrs.get("stroke", "#ddd"),
            width=scale,
        )

    out = OUT / (svg_path.stem + ".png")
    image.save(out, optimize=True)
    return out


OUT.mkdir(parents=True, exist_ok=True)
for svg in sorted(SRC.glob("*.svg")):
    print(render(svg))
PY
```
