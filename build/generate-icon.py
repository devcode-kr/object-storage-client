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


if __name__ == "__main__":
    main()
