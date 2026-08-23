from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if __package__:
    from .package_contract import DEB_ARCH, DEB_DEPENDENCIES, PACKAGE_NAME, NativeVersion
    from .stage_payload import paths_overlap, resolved_path, stage_payload
else:
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from package_contract import DEB_ARCH, DEB_DEPENDENCIES, PACKAGE_NAME, NativeVersion
    from stage_payload import paths_overlap, resolved_path, stage_payload

REPO_ROOT = SCRIPT_DIR.parents[1]
MAINTAINER = "Devcode <129266150+devcode-kr@users.noreply.github.com>"
HOMEPAGE = "https://github.com/devcode-kr/object-storage-client"


def installed_size(package_root: Path) -> int:
    total_bytes = 0
    for path in Path(package_root).rglob("*"):
        metadata = path.lstat()
        if stat.S_ISREG(metadata.st_mode):
            total_bytes += metadata.st_size
    return (total_bytes + 1023) // 1024


def render_control(version: NativeVersion, size_kib: int) -> str:
    if isinstance(size_kib, bool) or not isinstance(size_kib, int) or size_kib < 0:
        raise ValueError("installed size must be a non-negative integer")
    dependencies = ", ".join(DEB_DEPENDENCIES)
    return (
        f"Package: {PACKAGE_NAME}\n"
        f"Version: {version.debian}\n"
        "Section: net\n"
        "Priority: optional\n"
        f"Architecture: {DEB_ARCH}\n"
        f"Installed-Size: {size_kib}\n"
        f"Maintainer: {MAINTAINER}\n"
        f"Depends: {dependencies}\n"
        f"Homepage: {HOMEPAGE}\n"
        "Description: Desktop client for S3-compatible object storage\n"
        " Browse local files and remote S3-compatible object storage in a two-pane interface.\n"
    )


def build_deb(
    repo_root: Path,
    version: NativeVersion,
    publish_dir: Path,
    output_dir: Path,
) -> Path:
    tool = shutil.which("dpkg-deb")
    if tool is None:
        raise FileNotFoundError("required packaging tool was not found: dpkg-deb")

    repo_root = resolved_path(repo_root)
    publish_dir = resolved_path(publish_dir)
    output_dir = resolved_path(output_dir)
    package_root = repo_root / "obj/linux-packages/deb/root"
    output = output_dir / (
        f"ObjectStorageClient-{version.application}-{version.package_release}"
        "-linux-x64.deb"
    )

    for tree_name, tree in (("package root", package_root), ("publish directory", publish_dir)):
        if paths_overlap(output_dir, tree):
            raise ValueError(
                f"output directory and {tree_name} must not overlap: "
                f"{output_dir} and {tree}"
            )
        if paths_overlap(output, tree):
            raise ValueError(
                f"output path must not overlap the {tree_name}: "
                f"{resolved_path(output)} and {tree}"
            )

    stage_payload(repo_root, publish_dir, package_root)
    control_dir = package_root / "DEBIAN"
    control_dir.mkdir(parents=True)
    control = control_dir / "control"
    control.write_text(
        render_control(version, installed_size(package_root)), encoding="utf-8"
    )
    control.chmod(0o644)

    output_dir.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    subprocess.run(
        [
            tool,
            "--root-owner-group",
            "--build",
            str(package_root),
            str(output),
        ],
        check=True,
    )
    if not output.is_file():
        raise FileNotFoundError(f"dpkg-deb did not create expected output: {output}")
    return output


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the Debian package")
    parser.add_argument("--version", required=True, help="application version (Major.Minor.Patch)")
    parser.add_argument("--release", required=True, type=int, help="native package release")
    parser.add_argument("--publish-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    arguments = parser.parse_args(argv)
    try:
        version = NativeVersion.parse(arguments.version, arguments.release)
    except ValueError as error:
        parser.error(str(error))
    output = build_deb(REPO_ROOT, version, arguments.publish_dir, arguments.output_dir)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
