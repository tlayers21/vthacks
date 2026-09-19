# Brand images

Drop-in slot. Every file here is optional: templates check what is actually on disk
(`inject_brand` in `src/api/routes/ui.py`) and fall back to the built-in inline SVG mark, so an
empty folder still renders a finished-looking app rather than broken images.

| File | Size | Where it shows |
|---|---|---|
| `logo.png` | 512×512, square, transparent corners | Sidebar, mobile bar, landing page header |
| `favicon.png` | 64×64 | Browser tab |
| `apple-touch-icon.png` | 180×180 | iOS home screen |
| `og-image.png` | 1200×630 | Link previews (Slack, iMessage, Twitter) |

`logo.png` is rendered inside `rounded-full`, so give it transparent corners or a design that
survives a circular crop.

## Regenerating from the master artwork

`nessence.png` at the repo root is the master (1254×1254). The files here are derived from it —
edit the master, then re-run:

```bash
uv run --with pillow python - <<'PY'
from PIL import Image, ImageChops, ImageDraw

src = Image.open("nessence.png").convert("RGB")
W, H = src.size
bg = Image.new("RGB", src.size, src.getpixel((0, 0)))
mask = ImageChops.difference(src, bg).convert("L").point(lambda v: 255 if v > 16 else 0)
px = mask.load()

def extent(coords):
    hits = [i for i, xy in coords if px[xy] > 0]
    return hits[0], hits[-1]

# The circle's widest row is its centre, so that row gives the true diameter and centre x.
# Vertical bounds pick up the drop shadow, so take only the top edge from the centre column.
x0, x1 = extent([(i, (i, H // 2)) for i in range(W)])
y0, _ = extent([(j, (W // 2, j)) for j in range(H)])
d = x1 - x0 + 1
cx, cy = x0 + d / 2, y0 + d / 2

square = Image.new("RGBA", (d, d), (0, 0, 0, 0))
left, top = round(cx - d / 2), round(cy - d / 2)
square.paste(src.crop((left, top, left + d, top + d)).convert("RGBA"), (0, 0))

# 4x supersampled circular clip: the master's corners are off-white and must never show
m = Image.new("L", (d * 4, d * 4), 0)
ImageDraw.Draw(m).ellipse((0, 0, d * 4 - 1, d * 4 - 1), fill=255)
square.putalpha(m.resize((d, d), Image.LANCZOS))

out = "src/static/brand"
for name, size in [("logo.png", 512), ("apple-touch-icon.png", 180), ("favicon.png", 64)]:
    square.resize((size, size), Image.LANCZOS).save(f"{out}/{name}", optimize=True)

# Link previews want a wide image on the brand navy, not a transparent square
og = Image.new("RGBA", (1200, 630), (8, 37, 76, 255))
og.alpha_composite(square.resize((460, 460), Image.LANCZOS), (370, 85))
og.convert("RGB").save(f"{out}/og-image.png", optimize=True)
PY
```

Run it from the repo root. Pillow is not a project dependency — `uv run --with pillow` borrows
it for the one command, since this is a build step, not something the app does at runtime.

## Colours

The palette in `src/templates/base.html` is taken from this artwork: navy `#08254C` ground,
blue `#0C77D5` accent, teal `#35C9A3` for the creature. Dark mode uses the navy as the page
colour, so the mark dissolves into the page instead of floating on a dark square.
