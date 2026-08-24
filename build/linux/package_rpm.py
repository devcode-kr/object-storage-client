from __future__ import annotations

import argparse
import gzip
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if __package__:
    from .package_contract import NativeVersion
    from .package_deb import source_date_epoch
    from .stage_payload import (
        existing_symlink_component,
        paths_overlap,
        resolved_path,
        stage_payload,
    )
else:
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from package_contract import NativeVersion
    from package_deb import source_date_epoch
    from stage_payload import (
        existing_symlink_component,
        paths_overlap,
        resolved_path,
        stage_payload,
    )

REPO_ROOT = SCRIPT_DIR.parents[1]
SPEC_TEMPLATE_PATH = SCRIPT_DIR / "object-storage-client.spec"
SOURCE_NAME = "payload.tar.gz"
_SPEC_TOKEN = re.compile(r"@[A-Z][A-Z0-9_]*@")
_SAFE_SOURCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_RPM_TOPDIRS = ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS")


def rpm_source_date_epoch(environment: Mapping[str, str] | None = None) -> int:
    environment = os.environ if environment is None else environment
    if "SOURCE_DATE_EPOCH" not in environment:
        return 0
    return source_date_epoch(environment)


def render_spec(version: NativeVersion, source_name: str) -> str:
    if (
        not isinstance(source_name, str)
        or not _SAFE_SOURCE_NAME.fullmatch(source_name)
        or Path(source_name).name != source_name
    ):
        raise ValueError(f"unsafe RPM source name: {source_name!r}")

    rendered = SPEC_TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "@VERSION@": version.rpm_version,
        "@RELEASE@": version.rpm_release,
        "@SOURCE@": source_name,
    }
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    leftover = _SPEC_TOKEN.search(rendered)
    if leftover is not None:
        raise ValueError(f"unexpanded RPM spec template token: {leftover.group(0)}")
    return rendered


def _normalized_tar_info(archive: tarfile.TarFile, path: Path, arcname: str, epoch: int):
    info = archive.gettarinfo(str(path), arcname=arcname)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = epoch
    info.mode = stat.S_IMODE(path.lstat().st_mode)
    return info


def create_payload_tar(package_root: Path, destination: Path, epoch: int) -> None:
    package_root = Path(package_root)
    destination = Path(destination)
    if not package_root.is_dir() or package_root.is_symlink():
        raise NotADirectoryError(f"package root is not a normal directory: {package_root}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    paths = sorted(package_root.rglob("*"), key=lambda path: path.relative_to(package_root).as_posix())
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT, dereference=False) as archive:
                for path in paths:
                    arcname = path.relative_to(package_root).as_posix()
                    info = _normalized_tar_info(archive, path, arcname, epoch)
                    if info.isreg():
                        with path.open("rb") as source:
                            archive.addfile(info, source)
                    else:
                        archive.addfile(info)
    destination.chmod(0o644)
    os.utime(destination, (epoch, epoch), follow_symlinks=False)


def _remove_path(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def _reject_overlap(output_dir: Path, output: Path, publish_dir: Path, topdir: Path) -> None:
    protected = (("RPM top directory", topdir), ("publish directory", publish_dir))
    if paths_overlap(topdir, publish_dir):
        raise ValueError(
            f"RPM top directory and publish directory must not overlap: {topdir} and {publish_dir}"
        )
    for tree_name, tree in protected:
        if paths_overlap(output_dir, tree):
            raise ValueError(
                f"output directory and {tree_name} must not overlap: {output_dir} and {tree}"
            )
        if paths_overlap(output, tree):
            raise ValueError(
                f"output path must not overlap the {tree_name}: {resolved_path(output)} and {tree}"
            )


def _prepare_topdir(topdir: Path) -> None:
    unsafe_component = existing_symlink_component(topdir)
    if unsafe_component is not None:
        raise ValueError(
            f"unsafe RPM top directory contains symlink component: {topdir} ({unsafe_component})"
        )
    if topdir.exists():
        if topdir.is_symlink() or not topdir.is_dir():
            raise ValueError(f"RPM top directory is not a normal directory: {topdir}")
        shutil.rmtree(topdir)
    for name in _RPM_TOPDIRS:
        directory = topdir / name
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o755)


def _built_rpm(topdir: Path) -> Path:
    architecture_dir = topdir / "RPMS/x86_64"
    candidates = []
    if architecture_dir.is_dir() and not architecture_dir.is_symlink():
        for path in architecture_dir.rglob("*.rpm"):
            metadata = path.lstat()
            if stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                candidates.append(path)
    if len(candidates) != 1:
        raise FileNotFoundError(
            "rpmbuild must create exactly one regular non-symlink x86_64 RPM; "
            f"found {len(candidates)}"
        )
    return candidates[0]


def build_rpm(
    repo_root: Path,
    version: NativeVersion,
    publish_dir: Path,
    output_dir: Path,
) -> Path:
    tool = shutil.which("rpmbuild")
    if tool is None:
        raise FileNotFoundError("required packaging tool was not found: rpmbuild")
    epoch = rpm_source_date_epoch()

    repo_root = resolved_path(repo_root)
    publish_dir = resolved_path(publish_dir)
    output_dir = resolved_path(output_dir)
    topdir = repo_root / "obj/linux-packages/rpm"
    staging_root = topdir / "staging-root"
    output = output_dir / (
        f"ObjectStorageClient-{version.application}-{version.package_release}-linux-x64.rpm"
    )

    _reject_overlap(output_dir, output, publish_dir, topdir)
    _prepare_topdir(topdir)
    stage_payload(repo_root, publish_dir, staging_root)

    source = topdir / "SOURCES" / SOURCE_NAME
    spec = topdir / "SPECS/object-storage-client.spec"
    create_payload_tar(staging_root, source, epoch)
    spec.write_text(render_spec(version, SOURCE_NAME), encoding="utf-8")
    spec.chmod(0o644)
    os.utime(spec, (epoch, epoch), follow_symlinks=False)

    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = str(epoch)
    subprocess.run(
        [tool, "-bb", "--define", f"_topdir {topdir}", str(spec)],
        check=True,
        env=environment,
    )
    built = _built_rpm(topdir)

    output_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{output.name}.", suffix=".tmp", dir=output_dir
    )
    os.close(descriptor)
    temporary_output = Path(temporary_name)
    try:
        shutil.copyfile(built, temporary_output, follow_symlinks=False)
        temporary_output.chmod(0o644)
        os.utime(temporary_output, (epoch, epoch), follow_symlinks=False)
        os.replace(temporary_output, output)
    finally:
        _remove_path(temporary_output)
    return output


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the RPM package")
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
    output = build_rpm(REPO_ROOT, version, arguments.publish_dir, arguments.output_dir)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
