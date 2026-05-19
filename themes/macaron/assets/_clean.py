"""One-shot tooling: tight-crop macaron PNG assets by flood-filling near-white
from the 4 corners → alpha = 0, then crop to alpha bbox.

The cleaned outputs are already committed alongside this script. This file
is kept as reference / for re-running when the source artwork changes.

Workflow when refreshing assets:
    1. mkdir _originals/ and place the new artwork PNGs there
       (filenames must match those used in theme.toml)
    2. Install Pillow: pip install Pillow
    3. python _clean.py
       — produces cleaned PNGs in this directory, replacing the committed ones.

`button_texture.png` is just downscaled to 64x64 (seamless texture, no border
to remove).
"""
from collections import deque
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
SRC = HERE / "_originals"

WHITE_THRESHOLD = 235  # min(r,g,b) above this counts as "near white"
ALPHA_CROP_THRESHOLD = 8


def flood_fill_alpha(img: Image.Image, threshold: int) -> Image.Image:
    """BFS from the 4 corners; any pixel reachable through near-white -> alpha=0."""
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()

    visited = bytearray(w * h)
    queue: deque[tuple[int, int]] = deque()
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        queue.append(corner)

    def is_near_white(r: int, g: int, b: int) -> bool:
        return min(r, g, b) >= threshold

    while queue:
        x, y = queue.popleft()
        if x < 0 or x >= w or y < 0 or y >= h:
            continue
        idx = y * w + x
        if visited[idx]:
            continue
        r, g, b, _ = px[x, y]
        if not is_near_white(r, g, b):
            continue
        visited[idx] = 1
        # Set transparent
        px[x, y] = (r, g, b, 0)
        queue.append((x + 1, y))
        queue.append((x - 1, y))
        queue.append((x, y + 1))
        queue.append((x, y - 1))

    return img


def crop_to_alpha(img: Image.Image, threshold: int) -> Image.Image:
    """Crop to bounding box of pixels with alpha > threshold."""
    alpha = img.split()[-1]
    bbox = alpha.point(lambda a: 255 if a > threshold else 0).getbbox()
    return img.crop(bbox) if bbox else img


def soften_edges_to_opaque(img: Image.Image, threshold: int) -> Image.Image:
    """After cropping, restore any remaining semi-transparent pixels back to opaque
    so the painted edges stay solid where they hit the crop boundary.

    Pixels that survived flood-fill (i.e. they were colored content) but happen
    to have a partial alpha would create faint halos when stretched. We force
    every surviving pixel back to alpha=255 — the flood-fill already separated
    background from content discretely.
    """
    img = img.convert("RGBA")
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a > 0:
                px[x, y] = (r, g, b, 255)
    return img


def clean(name: str) -> None:
    src = SRC / name
    dst = HERE / name
    im = Image.open(src)
    flooded = flood_fill_alpha(im, WHITE_THRESHOLD)
    cropped = crop_to_alpha(flooded, ALPHA_CROP_THRESHOLD)
    final = soften_edges_to_opaque(cropped, ALPHA_CROP_THRESHOLD)
    final.save(dst, "PNG", optimize=True)
    print(f"  {name}: {im.size} -> {final.size}")


def downscale_texture(name: str, size: int = 64) -> None:
    src = SRC / name
    dst = HERE / name
    im = Image.open(src).convert("RGB")
    out = im.resize((size, size), Image.LANCZOS)
    out.save(dst, "PNG", optimize=True)
    print(f"  {name}: {im.size} -> {out.size}")


if __name__ == "__main__":
    print("Cleaning band assets via flood-fill + crop:")
    for n in ("main_bg.png", "panel_bg.png", "table_bg.png",
              "header_bg.png", "statusbar_bg .png"):
        clean(n)
    print("Downscaling button texture:")
    downscale_texture("button_texture.png", size=64)
