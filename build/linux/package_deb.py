from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Mapping, Sequence

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
DEFAULT_SOURCE_DATE_EPOCH = 946684800  # 2000-01-01 UTC; accepted by dpkg-deb/tar.


def installed_size(package_root: Path) -> int:
    total_kib = 0
    regular_inodes: set[tuple[int, int]] = set()
    for path in Path(package_root).rglob("*"):
        metadata = path.lstat()
        if stat.S_ISREG(metadata.st_mode):
            inode = (metadata.st_dev, metadata.st_ino)
            if inode in regular_inodes:
                continue
            regular_inodes.add(inode)
            # Debian Installed-Size rounds each regular file independently;
            # an empty regular file therefore contributes zero KiB.
            total_kib += (metadata.st_size + 1023) // 1024
        else:
            # Installed directories, symlinks, and other filesystem objects
            # use the one-KiB policy interpretation required by this package.
            total_kib += 1
    return total_kib


def source_date_epoch(environment: Mapping[str, str] | None = None) -> int:
    value = (os.environ if environment is None else environment).get("SOURCE_DATE_EPOCH")
    if value is None:
        return DEFAULT_SOURCE_DATE_EPOCH
    if not value.isascii() or not value.isdecimal():
        raise ValueError("SOURCE_DATE_EPOCH must be a non-negative decimal integer")
    return int(value)


def _normalize_mtimes(package_root: Path, epoch: int) -> None:
    timestamp_ns = epoch * 1_000_000_000
    for path in (*package_root.rglob("*"), package_root):
        os.utime(
            path,
            ns=(timestamp_ns, timestamp_ns),
            follow_symlinks=False,
        )


def _remove_temporary_output(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISDIR(metadata.st_mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def render_control(version: NativeVersion, installed_size_kib: int) -> str:
    if (
        isinstance(installed_size_kib, bool)
        or not isinstance(installed_size_kib, int)
        or installed_size_kib < 0
    ):
        raise ValueError("installed size must be a non-negative integer")
    dependencies = ", ".join(DEB_DEPENDENCIES)
    return (
        f"Package: {PACKAGE_NAME}\n"
        f"Version: {version.debian}\n"
        "Section: net\n"
        "Priority: optional\n"
        f"Architecture: {DEB_ARCH}\n"
        f"Installed-Size: {installed_size_kib}\n"
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
    epoch = source_date_epoch()

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
    payload_installed_size = installed_size(package_root)
    control_dir = package_root / "DEBIAN"
    control_dir.mkdir(parents=True)
    control_dir.chmod(0o755)
    control = control_dir / "control"
    control.write_text(
        render_control(version, payload_installed_size), encoding="utf-8"
    )
    control.chmod(0o644)

    _normalize_mtimes(package_root, epoch)

    output_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{output.name}.", suffix=".tmp", dir=output_dir
    )
    os.close(descriptor)
    temporary_output = Path(temporary_name)
    temporary_output.unlink()
    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = str(epoch)
    try:
        subprocess.run(
            [
                tool,
                "--root-owner-group",
                "--build",
                str(package_root),
                str(temporary_output),
            ],
            check=True,
            env=environment,
        )
        try:
            metadata = temporary_output.lstat()
        except FileNotFoundError:
            raise FileNotFoundError(
                f"dpkg-deb did not create expected output: {temporary_output}"
            ) from None
        if not stat.S_ISREG(metadata.st_mode):
            raise FileNotFoundError(
                f"dpkg-deb output is not a regular file: {temporary_output}"
            )
        os.replace(temporary_output, output)
    finally:
        _remove_temporary_output(temporary_output)
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
