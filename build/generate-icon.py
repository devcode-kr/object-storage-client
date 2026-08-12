#!/usr/bin/env python3
"""Rasterise the application icon from build/icon/appicon.svg.

The SVG is the source of truth; everything else is generated from it. Edit the SVG, run this,
commit the results — the Linux and Windows release runners have neither a rasteriser nor
`iconutil`, so nothing there could rebuild them.

    python3 build/generate-icon.py

Requires Pillow, plus one SVG rasteriser. It tries rsvg-convert, ImageMagick, cairosvg and
headless Chrome in that order, so a machine with any one of them works. The .icns step
additionally needs macOS (`iconutil`) and is skipped elsewhere with a warning.

Outputs:
    build/icon/appicon-1024.png                     master raster
    build/icon/ObjectStorageClient.icns             macOS .app bundle
    src/ObjectStorageClient.App/appicon.ico         Windows executable (<ApplicationIcon>)
    src/ObjectStorageClient.App/Assets/appicon.png  Avalonia Window.Icon (all platforms)
    build/msix/Assets/*.png                         Microsoft Store tiles and logos

Only the 1024 master is rasterised; every smaller size is resampled from it, so all the outputs
stay pixel-identical to one another.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: python3 -m pip install pillow")

REPO_ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = REPO_ROOT / "build" / "icon"
APP_DIR = REPO_ROOT / "src" / "ObjectStorageClient.App"
SOURCE = ICON_DIR / "appicon.svg"

MASTER = 1024
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

# Microsoft Store tiles. The square logos are the mark on its own shell; the wide tile puts that
# square on a matching background rather than stretching it, since a stretched icon looks broken.
# Each also gets a scale-200 variant, which is what a 200% display actually loads.
MSIX_SQUARE = {
    "StoreLogo.png": 50,
    "Square44x44Logo.png": 44,
    "Square71x71Logo.png": 71,
    "Square150x150Logo.png": 150,
    "Square310x310Logo.png": 310,
}
MSIX_WIDE = {"Wide310x150Logo.png": (310, 150)}
MSIX_SCALES = (100, 200)

# Taskbar, ALT+TAB and snap-assist use the "unplated" asset, drawn without the tile background.
MSIX_UNPLATED = "Square44x44Logo.targetsize-44_altform-unplated.png"

# Matches BackgroundColor in AppxManifest.xml.
MSIX_TILE_BACKGROUND = (31, 29, 27, 255)

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
    "chromium-browser",
]


def rasterise_rsvg(source: Path, destination: Path) -> bool:
    tool = shutil.which("rsvg-convert")
    if not tool:
        return False
    subprocess.run(
        [tool, "-w", str(MASTER), "-h", str(MASTER), "-o", str(destination), str(source)],
        check=True,
    )
    return True


def rasterise_magick(source: Path, destination: Path) -> bool:
    tool = shutil.which("magick") or shutil.which("convert")
    if not tool:
        return False
    command = [tool]
    if Path(tool).name == "magick":
        command.append("convert")
    subprocess.run(
        [*command, "-background", "none", "-density", "384",
         str(source), "-resize", f"{MASTER}x{MASTER}", str(destination)],
        check=True,
    )
    return True


def rasterise_cairosvg(source: Path, destination: Path) -> bool:
    try:
        import cairosvg
    except ImportError:
        return False
    cairosvg.svg2png(
        url=str(source), write_to=str(destination),
        output_width=MASTER, output_height=MASTER,
    )
    return True


def rasterise_chrome(source: Path, destination: Path) -> bool:
    tool = next(
        (candidate for candidate in CHROME_CANDIDATES
         if Path(candidate).exists() or shutil.which(candidate)),
        None,
    )
    if not tool:
        return False
    # --screenshot always writes to the working directory unless given an absolute path.
    subprocess.run(
        [tool, "--headless", "--disable-gpu", "--hide-scrollbars",
         "--default-background-color=00000000", "--force-device-scale-factor=1",
         f"--screenshot={destination}", f"--window-size={MASTER},{MASTER}",
         source.resolve().as_uri()],
        check=True, capture_output=True,
    )
    return destination.exists()


BACKENDS = [
    ("rsvg-convert", rasterise_rsvg),
    ("ImageMagick", rasterise_magick),
    ("cairosvg", rasterise_cairosvg),
    ("headless Chrome", rasterise_chrome),
]


def rasterise(source: Path, destination: Path) -> str:
    for name, backend in BACKENDS:
        try:
            if backend(source, destination):
                return name
        except subprocess.CalledProcessError as error:
            print(f"! {name} failed ({error}) — trying the next backend", file=sys.stderr)
    sys.exit(
        "No SVG rasteriser found. Install one of: librsvg (rsvg-convert), ImageMagick,\n"
        "cairosvg (pip install cairosvg), or Google Chrome / Chromium."
    )


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


def write_msix_assets(master: Image.Image, destination: Path) -> None:
    """Store tiles, in the sizes and naming the packaging manifest refers to."""
    destination.mkdir(parents=True, exist_ok=True)
    written = 0

    def save(image: Image.Image, name: str, scale: int) -> None:
        nonlocal written
        # scale-100 keeps the plain name: that is the filename the manifest points at.
        stem, suffix = name.rsplit(".", 1)
        actual = f"{stem}.{suffix}" if scale == 100 else f"{stem}.scale-{scale}.{suffix}"
        image.save(destination / actual)
        written += 1

    for name, size in MSIX_SQUARE.items():
        for scale in MSIX_SCALES:
            edge = round(size * scale / 100)
            save(master.resize((edge, edge), Image.LANCZOS), name, scale)

    for name, (width, height) in MSIX_WIDE.items():
        for scale in MSIX_SCALES:
            box = (round(width * scale / 100), round(height * scale / 100))
            tile = Image.new("RGBA", box, MSIX_TILE_BACKGROUND)
            # The mark keeps its own proportions and sits centred, filling the short edge.
            edge = round(box[1] * 0.66)
            mark = master.resize((edge, edge), Image.LANCZOS)
            tile.alpha_composite(mark, ((box[0] - edge) // 2, (box[1] - edge) // 2))
            save(tile, name, scale)

    for scale in MSIX_SCALES:
        edge = round(44 * scale / 100)
        save(master.resize((edge, edge), Image.LANCZOS), MSIX_UNPLATED, scale)

    print(f"  {destination.relative_to(REPO_ROOT)}/ ({written} files)")


def main() -> None:
    if not SOURCE.exists():
        sys.exit(f"{SOURCE.relative_to(REPO_ROOT)} is missing")

    ICON_DIR.mkdir(parents=True, exist_ok=True)
    (APP_DIR / "Assets").mkdir(parents=True, exist_ok=True)

    master_path = ICON_DIR / "appicon-1024.png"
    backend = rasterise(SOURCE, master_path)
    master = Image.open(master_path).convert("RGBA")
    if master.size != (MASTER, MASTER):
        master = master.resize((MASTER, MASTER), Image.LANCZOS)
        master.save(master_path)

    print(f"Rasterised with {backend}:")
    print(f"  {master_path.relative_to(REPO_ROOT)}")

    window_icon = APP_DIR / "Assets" / "appicon.png"
    master.resize((256, 256), Image.LANCZOS).save(window_icon)
    print(f"  {window_icon.relative_to(REPO_ROOT)}")

    ico_path = APP_DIR / "appicon.ico"
    master.save(ico_path, sizes=[(size, size) for size in ICO_SIZES])
    print(f"  {ico_path.relative_to(REPO_ROOT)}")

    write_icns(master, ICON_DIR / "ObjectStorageClient.icns")
    write_msix_assets(master, REPO_ROOT / "build" / "msix" / "Assets")


if __name__ == "__main__":
    main()
