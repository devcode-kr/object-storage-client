from __future__ import annotations

from pathlib import Path, PurePosixPath
import shutil
import stat

from package_contract import APP_DIR, DESKTOP_PATH, DOC_DIR, ICON_PATH, LAUNCHER_PATH

APPHOST_NAME = "ObjectStorageClient.App"
_APPROVED_DESTINATIONS = frozenset(
    {APP_DIR, LAUNCHER_PATH, DESKTOP_PATH, ICON_PATH, DOC_DIR}
)


def _destination(package_root: Path, installed_path: str) -> Path:
    """Map an approved absolute package path below the staging root."""
    if installed_path not in _APPROVED_DESTINATIONS:
        raise ValueError(f"unapproved package destination: {installed_path!r}")
    posix_path = PurePosixPath(installed_path)
    if not posix_path.is_absolute() or ".." in posix_path.parts:
        raise ValueError(f"unsafe package destination: {installed_path!r}")
    return package_root.joinpath(*posix_path.parts[1:])


def stage_payload(repo_root: Path, publish_dir: Path, package_root: Path) -> None:
    repo_root = Path(repo_root)
    publish_dir = Path(publish_dir)
    package_root = Path(package_root)

    if not publish_dir.is_dir():
        raise NotADirectoryError(f"publish path is not a directory: {publish_dir}")

    apphost = publish_dir / APPHOST_NAME
    if not apphost.is_file():
        raise FileNotFoundError(f"publish apphost is missing: {apphost}")
    if not apphost.stat().st_mode & stat.S_IXUSR:
        raise PermissionError(f"publish apphost is not owner-executable: {apphost}")

    source_files = {
        LAUNCHER_PATH: repo_root / "build/linux/object-storage-client",
        DESKTOP_PATH: repo_root / "build/linux/object-storage-client.desktop",
        ICON_PATH: repo_root / "src/ObjectStorageClient.App/Assets/appicon.png",
    }
    documents = [repo_root / name for name in ("README.md", "PRIVACY.md", "LICENSE")]
    for source in (*source_files.values(), *documents):
        if not source.is_file():
            raise FileNotFoundError(f"package source is missing: {source}")

    resolved_publish = publish_dir.resolve()
    resolved_package_root = package_root.resolve()
    if resolved_publish == resolved_package_root or resolved_publish.is_relative_to(
        resolved_package_root
    ):
        raise ValueError("package root must not contain the publish directory")

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
