from __future__ import annotations

from pathlib import Path, PurePosixPath
import os
import shutil
import stat

if __package__:
    from .package_contract import APP_DIR, DESKTOP_PATH, DOC_DIR, ICON_PATH, LAUNCHER_PATH
else:
    from package_contract import APP_DIR, DESKTOP_PATH, DOC_DIR, ICON_PATH, LAUNCHER_PATH

APPHOST_NAME = "ObjectStorageClient.App"
_APPROVED_DESTINATIONS = frozenset(
    {APP_DIR, LAUNCHER_PATH, DESKTOP_PATH, ICON_PATH, DOC_DIR}
)


def resolved_path(path: Path) -> Path:
    """Resolve a path, including symlinked parents, without requiring it to exist."""
    return Path(path).resolve()


def existing_symlink_component(path: Path) -> Path | None:
    """Return the first existing symlink in an absolute lexical path."""
    lexical_path = Path(path)
    if not lexical_path.is_absolute():
        lexical_path = Path.cwd() / lexical_path

    component = Path(lexical_path.anchor)
    for part in lexical_path.parts[1:]:
        component /= part
        if component.is_symlink():
            return component
    return None


def is_same_or_descendant(path: Path, ancestor: Path) -> bool:
    """Return whether path resolves to ancestor or anywhere below it."""
    return resolved_path(path).is_relative_to(resolved_path(ancestor))


def paths_overlap(first: Path, second: Path) -> bool:
    """Return whether two resolved paths are equal or contain one another."""
    resolved_first = resolved_path(first)
    resolved_second = resolved_path(second)
    return resolved_first.is_relative_to(
        resolved_second
    ) or resolved_second.is_relative_to(resolved_first)


def _destination(package_root: Path, installed_path: str) -> Path:
    """Map an approved absolute package path below the staging root."""
    if installed_path not in _APPROVED_DESTINATIONS:
        raise ValueError(f"unapproved package destination: {installed_path!r}")
    posix_path = PurePosixPath(installed_path)
    if not posix_path.is_absolute() or ".." in posix_path.parts:
        raise ValueError(f"unsafe package destination: {installed_path!r}")
    return package_root.joinpath(*posix_path.parts[1:])


def _normalize_staged_modes(package_root: Path) -> None:
    """Apply publish-safe modes without following staged symlinks."""
    for path in (package_root, *package_root.rglob("*")):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            continue
        if stat.S_ISDIR(metadata.st_mode):
            os.chmod(path, 0o755, follow_symlinks=False)
        elif stat.S_ISREG(metadata.st_mode):
            executable = metadata.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            os.chmod(path, 0o755 if executable else 0o644, follow_symlinks=False)


def stage_payload(repo_root: Path, publish_dir: Path, package_root: Path) -> None:
    repo_root = Path(repo_root)
    publish_dir = Path(publish_dir)
    package_root = Path(package_root)

    unsafe_component = existing_symlink_component(package_root)
    if unsafe_component is not None:
        raise ValueError(
            f"unsafe package root contains symlink component: "
            f"{package_root} ({unsafe_component})"
        )

    source_files = {
        LAUNCHER_PATH: repo_root / "build/linux/object-storage-client",
        DESKTOP_PATH: repo_root / "build/linux/object-storage-client.desktop",
        ICON_PATH: repo_root / "src/ObjectStorageClient.App/Assets/appicon.png",
    }
    documents = [repo_root / name for name in ("README.md", "PRIVACY.md", "LICENSE")]
    package_sources = (*source_files.values(), *documents)

    if paths_overlap(package_root, publish_dir):
        raise ValueError(
            f"package root and publish directory must not overlap: "
            f"{resolved_path(package_root)} and {resolved_path(publish_dir)}"
        )
    for source in package_sources:
        if is_same_or_descendant(source, package_root):
            raise ValueError(
                f"package root must not contain a package source: "
                f"{resolved_path(package_root)} contains {resolved_path(source)}"
            )

    if not publish_dir.is_dir():
        raise NotADirectoryError(f"publish path is not a directory: {publish_dir}")

    apphost = publish_dir / APPHOST_NAME
    if not apphost.is_file():
        raise FileNotFoundError(f"publish apphost is missing: {apphost}")
    if not apphost.stat().st_mode & stat.S_IXUSR:
        raise PermissionError(f"publish apphost is not owner-executable: {apphost}")

    for source in package_sources:
        if not source.is_file():
            raise FileNotFoundError(f"package source is missing: {source}")

    if package_root.exists():
        if package_root.is_symlink() or not package_root.is_dir():
            raise ValueError(f"package root is not a normal directory: {package_root}")
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True)

    app_destination = _destination(package_root, APP_DIR)
    shutil.copytree(publish_dir, app_destination, copy_function=shutil.copy2, symlinks=True)

    for installed_path, source in source_files.items():
        destination = _destination(package_root, installed_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    launcher = _destination(package_root, LAUNCHER_PATH)
    launcher.chmod(0o755)

    doc_destination = _destination(package_root, DOC_DIR)
    doc_destination.mkdir(parents=True, exist_ok=True)
    for document in documents:
        shutil.copy2(document, doc_destination / document.name)

    _normalize_staged_modes(package_root)
    _destination(package_root, LAUNCHER_PATH).chmod(0o755)
    for installed_path in (DESKTOP_PATH, ICON_PATH):
        _destination(package_root, installed_path).chmod(0o644)
    for document in documents:
        (doc_destination / document.name).chmod(0o644)
