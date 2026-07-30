#!/usr/bin/env python3
"""Generate the application icon in every format the packaging needs.

This is a developer tool, not part of the build: the generated files are committed, because
the Linux and Windows release runners have neither Pillow nor `iconutil`. Re-run it only when
the artwork changes.

    python3 build/generate-icon.py

Requires Pillow. The .icns step additionally requires macOS (`iconutil`) and is skipped
elsewhere with a warning.

Outputs:
    build/icon/appicon-1024.png                     master artwork
    build/icon/ObjectStorageClient.icns             macOS .app bundle
    src/ObjectStorageClient.App/appicon.ico         Windows executable (<ApplicationIcon>)
    src/ObjectStorageClient.App/Assets/appicon.png  Avalonia Window.Icon (all platforms)

The artwork is a placeholder: stacked storage tiers on a blue-to-cyan rounded square. It is
deliberately simple and meant to be replaced by real artwork later.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("Pillow is required: python3 -m pip install pillow")

REPO_ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = REPO_ROOT / "build" / "icon"
APP_DIR = REPO_ROOT / "src" / "ObjectStorageClient.App"

SIZE = 1024
SUPERSAMPLE = 4

# Rounded square sized like a native macOS app icon: 824/1024 content, 185/824 corner radius.
MARGIN = 100
CORNER_RADIUS = 185

GRADIENT_TOP = (29, 78, 216)  # #1D4ED8
GRADIENT_BOTTOM = (6, 182, 212)  # #06B6D4

TIER_COUNT = 3
TIER_RX = 250
TIER_RY = 66
TIER_BODY_HEIGHT = 92
TIER_SPACING = 118

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
ICNS_SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def build_gradient(size: int) -> Image.Image:
    """A vertical linear gradient, drawn one scanline at a time."""
    gradient = Image.new("RGB", (1, size))
    pixels = gradient.load()
    assert pixels is not None
    for y in range(size):
        ratio = y / max(size - 1, 1)
        pixels[0, y] = tuple(
            round(start + (end - start) * ratio)
            for start, end in zip(GRADIENT_TOP, GRADIENT_BOTTOM)
        )
    return gradient.resize((size, size), Image.NEAREST)


def draw_tier(draw: ImageDraw.ImageDraw, centre_x: int, top_y: int, scale: int) -> None:
    """One storage tier: a cylinder drawn as body + bottom cap + a brighter lid."""
    rx = TIER_RX * scale
    ry = TIER_RY * scale
    body_height = TIER_BODY_HEIGHT * scale
    body = (255, 255, 255, 235)
    lid = (255, 255, 255, 255)

    draw.rectangle((centre_x - rx, top_y, centre_x + rx, top_y + body_height), fill=body)
    draw.ellipse(
        (centre_x - rx, top_y + body_height - ry, centre_x + rx, top_y + body_height + ry),
        fill=body,
    )
    draw.ellipse((centre_x - rx, top_y - ry, centre_x + rx, top_y + ry), fill=lid)


def render_master() -> Image.Image:
    scale = SUPERSAMPLE
    canvas = SIZE * scale

    # The rounded square, as a mask over the gradient, so the corners stay transparent.
    mask = Image.new("L", (canvas, canvas), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (MARGIN * scale, MARGIN * scale, (SIZE - MARGIN) * scale, (SIZE - MARGIN) * scale),
        radius=CORNER_RADIUS * scale,
        fill=255,
    )

    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    image.paste(build_gradient(canvas).convert("RGBA"), (0, 0), mask)

    # Tiers are drawn on their own layer, bottom first, so upper tiers overlap lower ones.
    tiers = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tiers)
    stack_height = (TIER_COUNT - 1) * TIER_SPACING + TIER_BODY_HEIGHT + 2 * TIER_RY
    first_top = (SIZE - stack_height) // 2 + TIER_RY
    for index in reversed(range(TIER_COUNT)):
        draw_tier(draw, (SIZE // 2) * scale, (first_top + index * TIER_SPACING) * scale, scale)

    image.alpha_composite(tiers)
    return image.resize((SIZE, SIZE), Image.LANCZOS)


def write_icns(master: Image.Image, destination: Path) -> None:
    if not shutil.which("iconutil"):
        print("! iconutil not found (macOS only) — skipping .icns", file=sys.stderr)
        return
    with tempfile.TemporaryDirectory() as workspace:
        iconset = Path(workspace) / "ObjectStorageClient.iconset"
        iconset.mkdir()
        for name, size in ICNS_SIZES:
            master.resize((size, size), Image.LANCZOS).save(iconset / name)
        subprocess.run(
            ["iconutil", "--convert", "icns", "--output", str(destination), str(iconset)],
            check=True,
        )
    print(f"  {destination.relative_to(REPO_ROOT)}")


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    (APP_DIR / "Assets").mkdir(parents=True, exist_ok=True)

    master = render_master()
    print("Generated:")

    master_path = ICON_DIR / "appicon-1024.png"
    master.save(master_path)
    print(f"  {master_path.relative_to(REPO_ROOT)}")

    window_icon = APP_DIR / "Assets" / "appicon.png"
    master.resize((256, 256), Image.LANCZOS).save(window_icon)
    print(f"  {window_icon.relative_to(REPO_ROOT)}")

    ico_path = APP_DIR / "appicon.ico"
    master.save(ico_path, sizes=[(size, size) for size in ICO_SIZES])
    print(f"  {ico_path.relative_to(REPO_ROOT)}")

    write_icns(master, ICON_DIR / "ObjectStorageClient.icns")


if __name__ == "__main__":
    main()
