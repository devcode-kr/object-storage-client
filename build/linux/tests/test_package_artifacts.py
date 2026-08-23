from __future__ import annotations

import hashlib
import importlib.util
import os
import pathlib
import re
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[3]
LINUX = ROOT / "build" / "linux"

from build.linux import package_deb, package_rpm, stage_payload
from build.linux.package_contract import NativeVersion


EXPECTED_CONTROL = """Package: object-storage-client
Version: 1.2.3-4
Section: net
Priority: optional
Architecture: amd64
Installed-Size: 50000
Maintainer: Devcode <129266150+devcode-kr@users.noreply.github.com>
Depends: libx11-6, libice6, libsm6, libfontconfig1, ca-certificates
Homepage: https://github.com/devcode-kr/object-storage-client
Description: Desktop client for S3-compatible object storage
 Browse local files and remote S3-compatible object storage in a two-pane interface.
"""


class PackageImportTests(unittest.TestCase):
    def test_package_qualified_imports_work_from_repo_root(self):
        self.assertTrue(callable(stage_payload.stage_payload))
        self.assertTrue(callable(package_deb.render_control))
        self.assertTrue(callable(package_rpm.render_spec))
        self.assertTrue(callable(NativeVersion.parse))

    def test_rpm_module_supports_direct_script_import(self):
        spec = importlib.util.spec_from_file_location(
            "package_rpm_direct", LINUX / "package_rpm.py"
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.render_spec))


def make_publish(parent: pathlib.Path, executable: bool = True) -> pathlib.Path:
    publish = parent / "publish"
    publish.mkdir()
    apphost = publish / "ObjectStorageClient.App"
    apphost.write_bytes(b"fake apphost")
    apphost.chmod(0o755 if executable else 0o644)
    (publish / "ObjectStorageClient.App.dll").write_bytes(b"fake dll")
    return publish


def make_fake_repo(parent: pathlib.Path) -> pathlib.Path:
    repo = parent / "repo"
    sources = (
        "build/linux/object-storage-client",
        "build/linux/object-storage-client.desktop",
        "src/ObjectStorageClient.App/Assets/appicon.png",
        "README.md",
        "PRIVACY.md",
        "LICENSE",
    )
    for relative in sources:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
    return repo


def make_fake_rpm_repo(parent: pathlib.Path) -> pathlib.Path:
    repo = make_fake_repo(parent)
    for relative in (
        "build/linux/package_rpm.py",
        "build/linux/package_deb.py",
        "build/linux/stage_payload.py",
        "build/linux/package_contract.py",
        "build/linux/object-storage-client.spec",
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
    return repo


def deb_output(output_dir: pathlib.Path) -> pathlib.Path:
    return output_dir / "ObjectStorageClient-1.2.3-4-linux-x64.deb"


class StagePayloadTests(unittest.TestCase):
    def test_finds_symlink_components_in_absolute_and_relative_lexical_paths(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            temporary = pathlib.Path(directory)
            target = temporary / "target"
            target.mkdir()
            alias = temporary / "alias"
            try:
                alias.symlink_to(target, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")

            absolute = alias / "staging/root"
            relative = absolute.relative_to(ROOT)
            self.assertEqual(alias, stage_payload.existing_symlink_component(absolute))
            self.assertEqual(alias, stage_payload.existing_symlink_component(relative))

    def test_stages_exact_payload_and_preserves_publish_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish = make_publish(temporary)
            package_root = temporary / "root"
            package_root.mkdir()
            (package_root / "stale-file").write_text("remove me", encoding="utf-8")
            source_snapshot = {
                path.relative_to(publish): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                for path in publish.iterdir()
            }
            nested = publish / "runtimes/linux-x64/native"
            nested.mkdir(parents=True)
            (nested / "library.so").write_bytes(b"native library")
            try:
                (publish / "apphost-link").symlink_to("ObjectStorageClient.App")
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")

            stage_payload.stage_payload(repo, publish, package_root)

            expected_files = {
                pathlib.Path("usr/lib/object-storage-client/ObjectStorageClient.App"),
                pathlib.Path("usr/lib/object-storage-client/ObjectStorageClient.App.dll"),
                pathlib.Path("usr/lib/object-storage-client/apphost-link"),
                pathlib.Path("usr/lib/object-storage-client/runtimes/linux-x64/native/library.so"),
                pathlib.Path("usr/bin/object-storage-client"),
                pathlib.Path("usr/share/applications/object-storage-client.desktop"),
                pathlib.Path("usr/share/icons/hicolor/256x256/apps/object-storage-client.png"),
                pathlib.Path("usr/share/doc/object-storage-client/README.md"),
                pathlib.Path("usr/share/doc/object-storage-client/PRIVACY.md"),
                pathlib.Path("usr/share/doc/object-storage-client/LICENSE"),
            }
            installed_files = {
                path.relative_to(package_root)
                for path in package_root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(expected_files, installed_files)
            self.assertEqual(
                0o755,
                stat.S_IMODE((package_root / "usr/bin/object-storage-client").stat().st_mode),
            )
            self.assertTrue(
                (package_root / "usr/lib/object-storage-client/ObjectStorageClient.App").stat().st_mode
                & stat.S_IXUSR
            )
            installed_link = package_root / "usr/lib/object-storage-client/apphost-link"
            self.assertTrue(installed_link.is_symlink())
            self.assertEqual(pathlib.Path("ObjectStorageClient.App"), installed_link.readlink())
            self.assertEqual(
                (repo / "build/linux/object-storage-client.desktop").read_bytes(),
                (package_root / "usr/share/applications/object-storage-client.desktop").read_bytes(),
            )
            source_icon = (
                repo / "src/ObjectStorageClient.App/Assets/appicon.png"
            ).read_bytes()
            installed_icon = (
                package_root
                / "usr/share/icons/hicolor/256x256/apps/object-storage-client.png"
            ).read_bytes()
            self.assertEqual(source_icon, installed_icon)
            self.assertEqual(b"\x89PNG\r\n\x1a\n", installed_icon[:8])
            self.assertEqual((256, 256), struct.unpack(">II", installed_icon[16:24]))
            for name in ("README.md", "PRIVACY.md", "LICENSE"):
                self.assertEqual(
                    (repo / name).read_bytes(),
                    (package_root / "usr/share/doc/object-storage-client" / name).read_bytes(),
                )
            self.assertEqual(
                source_snapshot,
                {
                    relative: (
                        (publish / relative).read_bytes(),
                        stat.S_IMODE((publish / relative).stat().st_mode),
                    )
                    for relative in source_snapshot
                },
            )

    def test_normalizes_all_staged_modes_without_following_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish = make_publish(temporary)
            package_root = temporary / "root"
            apphost = publish / "ObjectStorageClient.App"
            executable = publish / "tool"
            plain = publish / "payload.dat"
            nested = publish / "nested"
            apphost.chmod(0o4755)
            executable.write_bytes(b"tool")
            executable.chmod(0o2777)
            plain.write_bytes(b"payload")
            plain.chmod(0o666)
            nested.mkdir()
            nested.chmod(0o2777)
            link_target = temporary / "outside-target"
            link_target.write_bytes(b"outside")
            link_target.chmod(0o666)
            try:
                (publish / "outside-link").symlink_to(link_target)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")

            for relative in (
                "build/linux/object-storage-client.desktop",
                "src/ObjectStorageClient.App/Assets/appicon.png",
                "README.md",
                "PRIVACY.md",
                "LICENSE",
            ):
                (repo / relative).chmod(0o2777)
            (repo / "build/linux/object-storage-client").chmod(0o4755)

            stage_payload.stage_payload(repo, publish, package_root)

            self.assertEqual(0o755, stat.S_IMODE(package_root.stat().st_mode))
            for path in package_root.rglob("*"):
                if path.is_dir() and not path.is_symlink():
                    self.assertEqual(0o755, stat.S_IMODE(path.stat().st_mode), path)
            expected_modes = {
                "usr/lib/object-storage-client/ObjectStorageClient.App": 0o755,
                "usr/lib/object-storage-client/tool": 0o755,
                "usr/lib/object-storage-client/payload.dat": 0o644,
                "usr/bin/object-storage-client": 0o755,
                "usr/share/applications/object-storage-client.desktop": 0o644,
                "usr/share/icons/hicolor/256x256/apps/object-storage-client.png": 0o644,
                "usr/share/doc/object-storage-client/README.md": 0o644,
                "usr/share/doc/object-storage-client/PRIVACY.md": 0o644,
                "usr/share/doc/object-storage-client/LICENSE": 0o644,
            }
            for relative, expected in expected_modes.items():
                actual = stat.S_IMODE((package_root / relative).stat().st_mode)
                self.assertEqual(expected, actual, relative)
            self.assertEqual(0o666, stat.S_IMODE(link_target.stat().st_mode))

    def test_rejects_package_root_inside_publish_without_changing_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish = make_publish(temporary)
            source = publish / "ObjectStorageClient.App.dll"
            package_root = publish / "staging/root"
            package_root.mkdir(parents=True)
            sentinel = package_root / "sentinel"
            sentinel.write_bytes(b"keep")

            with self.assertRaisesRegex(ValueError, "overlap"):
                stage_payload.stage_payload(repo, publish, package_root)

            self.assertEqual(b"fake dll", source.read_bytes())
            self.assertEqual(b"keep", sentinel.read_bytes())

    def test_rejects_publish_inside_package_root_without_changing_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            package_root = temporary / "staging"
            package_root.mkdir()
            sentinel = package_root / "sentinel"
            sentinel.write_bytes(b"keep")
            publish = make_publish(package_root)
            source = publish / "ObjectStorageClient.App.dll"

            with self.assertRaisesRegex(ValueError, "overlap"):
                stage_payload.stage_payload(repo, publish, package_root)

            self.assertEqual(b"fake dll", source.read_bytes())
            self.assertEqual(b"keep", sentinel.read_bytes())

    def test_rejects_package_root_equal_to_or_containing_repo_sources(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            tempfile.TemporaryDirectory() as publish_directory,
        ):
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish = make_publish(pathlib.Path(publish_directory))
            launcher = repo / "build/linux/object-storage-client"

            for package_root in (repo, repo / "build"):
                with self.subTest(package_root=package_root):
                    sentinel = package_root / "sentinel"
                    sentinel.write_bytes(b"keep")
                    with self.assertRaisesRegex(ValueError, "source"):
                        stage_payload.stage_payload(repo, publish, package_root)
                    self.assertEqual(
                        (ROOT / "build/linux/object-storage-client").read_bytes(),
                        launcher.read_bytes(),
                    )
                    self.assertEqual(b"keep", sentinel.read_bytes())
                    sentinel.unlink()

    def test_rejects_symlinked_package_root_parent_resolving_to_source_tree(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            tempfile.TemporaryDirectory() as publish_directory,
        ):
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish = make_publish(pathlib.Path(publish_directory))
            alias = temporary / "repo-alias"
            try:
                alias.symlink_to(repo, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            package_root = alias / "build"
            sentinel = repo / "build/sentinel"
            sentinel.write_bytes(b"keep")

            with self.assertRaisesRegex(ValueError, str(package_root)):
                stage_payload.stage_payload(repo, publish, package_root)

            launcher = repo / "build/linux/object-storage-client"
            self.assertEqual(
                (ROOT / "build/linux/object-storage-client").read_bytes(),
                launcher.read_bytes(),
            )
            self.assertEqual(b"keep", sentinel.read_bytes())

    def test_rejects_arbitrary_symlinked_package_root_parent_without_deleting_target(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish = make_publish(temporary)
            unrelated = temporary / "unrelated"
            staging = unrelated / "staging"
            staging.mkdir(parents=True)
            sentinel = staging / "sentinel"
            sentinel.write_bytes(b"keep")
            alias = temporary / "alias"
            try:
                alias.symlink_to(unrelated, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            package_root = alias / "staging"

            with self.assertRaisesRegex(ValueError, str(package_root)):
                stage_payload.stage_payload(repo, publish, package_root)

            self.assertEqual(b"keep", sentinel.read_bytes())

    def test_rejects_publish_path_that_is_not_a_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish_file = temporary / "publish"
            publish_file.write_text("not a directory", encoding="utf-8")
            with self.assertRaises(NotADirectoryError):
                stage_payload.stage_payload(repo, publish_file, temporary / "root")

    def test_rejects_missing_apphost(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish = temporary / "publish"
            publish.mkdir()
            with self.assertRaises(FileNotFoundError):
                stage_payload.stage_payload(repo, publish, temporary / "root")

    def test_rejects_non_executable_apphost(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish = make_publish(temporary, executable=False)
            with self.assertRaises(PermissionError):
                stage_payload.stage_payload(repo, publish, temporary / "root")


class DebianControlTests(unittest.TestCase):
    def test_render_control_is_the_exact_complete_body(self):
        control = package_deb.render_control(
            NativeVersion.parse("1.2.3", 4), installed_size_kib=50000
        )
        self.assertEqual(EXPECTED_CONTROL, control)
        self.assertTrue(control.endswith("\n"))
        self.assertNotIn(".devcode", control)

    def test_installed_size_rounds_each_file_and_counts_non_regular_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "directory").mkdir()
            (root / "first").write_bytes(b"a" * 1025)
            (root / "directory/second").write_bytes(b"b")
            (root / "empty").write_bytes(b"")
            os.link(root / "first", root / "first-hardlink")
            try:
                (root / "large-link").symlink_to(root / "first")
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            fifo = root / "pipe"
            os.mkfifo(fifo)

            # Regular files contribute 2 + 1 + 0 KiB; the hardlink is counted
            # once. The directory, symlink, and FIFO each contribute 1 KiB.
            self.assertEqual(6, package_deb.installed_size(root))

    def test_source_date_epoch_accepts_only_nonnegative_decimal_integers(self):
        self.assertEqual(946684800, package_deb.source_date_epoch({}))
        self.assertEqual(0, package_deb.source_date_epoch({"SOURCE_DATE_EPOCH": "0"}))
        self.assertEqual(123, package_deb.source_date_epoch({"SOURCE_DATE_EPOCH": "123"}))
        for invalid in ("", "-1", "+1", " 1", "1 ", "1.0", "true", "False"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "SOURCE_DATE_EPOCH"):
                    package_deb.source_date_epoch({"SOURCE_DATE_EPOCH": invalid})

    def test_render_control_rejects_invalid_installed_sizes(self):
        version = NativeVersion.parse("1.2.3", 4)
        for invalid in (-1, True, 1.5, "50000", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    package_deb.render_control(version, installed_size_kib=invalid)


class DebianCliTests(unittest.TestCase):
    def run_cli(
        self, *arguments: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(LINUX / "package_deb.py"), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    def test_cli_requires_all_arguments(self):
        result = self.run_cli()
        self.assertNotEqual(0, result.returncode)
        for option in ("--version", "--release", "--publish-dir", "--output-dir"):
            self.assertIn(option, result.stderr)

    def test_cli_reports_strict_version_and_release_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            common = ("--publish-dir", directory, "--output-dir", directory)
            bad_version = self.run_cli(
                "--version", "v1.2.3", "--release", "4", *common
            )
            bad_release = self.run_cli(
                "--version", "1.2.3", "--release", "0", *common
            )
        self.assertNotEqual(0, bad_version.returncode)
        self.assertIn("Major.Minor.Patch", bad_version.stderr)
        self.assertNotEqual(0, bad_release.returncode)
        self.assertIn("between 1 and 65535", bad_release.stderr)

    def test_missing_dpkg_deb_fails_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish_parent = temporary / "payload"
            publish_parent.mkdir()
            publish = make_publish(publish_parent)
            with mock.patch.object(package_deb.shutil, "which", return_value=None):
                with self.assertRaisesRegex(FileNotFoundError, "dpkg-deb"):
                    package_deb.build_deb(
                        repo,
                        NativeVersion.parse("1.2.3", 4),
                        publish,
                        temporary / "out",
                    )

    def test_build_invokes_dpkg_deb_with_temp_output_epoch_and_normalized_mtimes(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish_parent = temporary / "payload"
            publish_parent.mkdir()
            publish = make_publish(publish_parent)
            output_dir = temporary / "output"
            epoch = 123456789
            link_target = temporary / "outside-target"
            link_target.write_bytes(b"outside")
            target_timestamp_ns = 1_700_000_000_000_000_000
            os.utime(link_target, ns=(target_timestamp_ns, target_timestamp_ns))
            try:
                (publish / "outside-link").symlink_to(link_target)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")

            def create_output(command, **kwargs):
                temporary_output = pathlib.Path(command[-1])
                self.assertEqual(output_dir, temporary_output.parent)
                self.assertNotEqual(deb_output(output_dir), temporary_output)
                self.assertFalse(temporary_output.exists())
                self.assertRegex(
                    temporary_output.name,
                    re.escape(deb_output(output_dir).name) + r"\..*\.tmp$",
                )
                self.assertEqual(str(epoch), kwargs["env"]["SOURCE_DATE_EPOCH"])
                temporary_output.write_bytes(b"fake deb")
                return subprocess.CompletedProcess(command, 0)

            previous_umask = os.umask(0o077)
            try:
                with (
                    mock.patch.object(
                        package_deb.shutil, "which", return_value="/usr/bin/dpkg-deb"
                    ),
                    mock.patch.object(
                        package_deb.os,
                        "environ",
                        {"SOURCE_DATE_EPOCH": str(epoch)},
                    ),
                    mock.patch.object(
                        package_deb.subprocess, "run", side_effect=create_output
                    ) as run,
                ):
                    output = package_deb.build_deb(
                        repo,
                        NativeVersion.parse("1.2.3", 4),
                        publish,
                        output_dir,
                    )
            finally:
                os.umask(previous_umask)

            expected_root = repo / "obj/linux-packages/deb/root"
            self.assertEqual(deb_output(output_dir), output)
            command = run.call_args.args[0]
            self.assertEqual(
                [
                    "/usr/bin/dpkg-deb",
                    "--root-owner-group",
                    "--build",
                    str(expected_root),
                ],
                command[:-1],
            )
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertTrue(
                all(
                    path.lstat().st_mtime_ns == epoch * 1_000_000_000
                    for path in [expected_root, *expected_root.rglob("*")]
                )
            )
            self.assertEqual(target_timestamp_ns, link_target.stat().st_mtime_ns)
            self.assertEqual(
                0o644,
                stat.S_IMODE((expected_root / "DEBIAN/control").stat().st_mode),
            )
            self.assertEqual(
                0o755,
                stat.S_IMODE((expected_root / "DEBIAN").stat().st_mode),
            )

    def test_build_rejects_output_tree_overlaps_before_stale_removal_or_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            package_root = repo / "obj/linux-packages/deb/root"
            publish_parent = temporary / "payload"
            publish_parent.mkdir()
            publish = make_publish(publish_parent)
            cases = {
                "output inside package": package_root / "output",
                "package inside output": package_root.parent,
                "output inside publish": publish / "output",
                "publish inside output": publish.parent,
            }

            for name, output_dir in cases.items():
                with self.subTest(name=name):
                    output_dir.mkdir(parents=True, exist_ok=True)
                    stale = deb_output(output_dir)
                    stale.write_bytes(b"old package")
                    with (
                        mock.patch.object(package_deb.shutil, "which", return_value="dpkg-deb"),
                        mock.patch.object(package_deb, "stage_payload") as stage,
                        mock.patch.object(package_deb.subprocess, "run") as run,
                        self.assertRaisesRegex(ValueError, "overlap"),
                    ):
                        package_deb.build_deb(
                            repo,
                            NativeVersion.parse("1.2.3", 4),
                            publish,
                            output_dir,
                        )
                    self.assertEqual(b"old package", stale.read_bytes())
                    stage.assert_not_called()
                    run.assert_not_called()

    def test_build_rejects_output_file_resolving_inside_protected_trees(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish_parent = temporary / "payload"
            publish_parent.mkdir()
            publish = make_publish(publish_parent)
            output_dir = temporary / "output"
            output_dir.mkdir()
            package_root = repo / "obj/linux-packages/deb/root"
            package_root.mkdir(parents=True)
            output = deb_output(output_dir)
            targets = {
                "package root": package_root / "existing.deb",
                "publish directory": publish / "existing.deb",
            }

            for tree_name, target in targets.items():
                with self.subTest(tree_name=tree_name):
                    target.write_bytes(b"keep")
                    try:
                        output.symlink_to(target)
                    except OSError as error:
                        self.skipTest(f"symlinks unavailable: {error}")

                    with (
                        mock.patch.object(
                            package_deb.shutil, "which", return_value="dpkg-deb"
                        ),
                        mock.patch.object(package_deb, "stage_payload") as stage,
                        self.assertRaisesRegex(ValueError, "overlap"),
                    ):
                        package_deb.build_deb(
                            repo,
                            NativeVersion.parse("1.2.3", 4),
                            publish,
                            output_dir,
                        )
                    self.assertTrue(output.is_symlink())
                    self.assertEqual(b"keep", target.read_bytes())
                    stage.assert_not_called()
                    output.unlink()

    def test_build_rejects_symlinked_fixed_staging_parents_before_deleting_target(self):
        for symlink_parent in ("obj", "obj/linux-packages"):
            with (
                self.subTest(symlink_parent=symlink_parent),
                tempfile.TemporaryDirectory() as directory,
            ):
                temporary = pathlib.Path(directory)
                repo = make_fake_repo(temporary)
                publish_parent = temporary / "payload"
                publish_parent.mkdir()
                publish = make_publish(publish_parent)
                unrelated = temporary / "unrelated"
                target_root = unrelated / (
                    "linux-packages/deb/root" if symlink_parent == "obj" else "deb/root"
                )
                target_root.mkdir(parents=True)
                sentinel = target_root / "sentinel"
                sentinel.write_bytes(b"keep")
                link = repo / symlink_parent
                link.parent.mkdir(parents=True, exist_ok=True)
                try:
                    link.symlink_to(unrelated, target_is_directory=True)
                except OSError as error:
                    self.skipTest(f"symlinks unavailable: {error}")

                with (
                    mock.patch.object(package_deb.shutil, "which", return_value="dpkg-deb"),
                    mock.patch.object(package_deb.subprocess, "run") as run,
                    self.assertRaisesRegex(ValueError, str(link)),
                ):
                    package_deb.build_deb(
                        repo,
                        NativeVersion.parse("1.2.3", 4),
                        publish,
                        temporary / "output",
                    )

                self.assertEqual(b"keep", sentinel.read_bytes())
                run.assert_not_called()

    def test_build_rejects_output_symlink_resolving_to_ancestor_of_protected_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish_parent = temporary / "payload"
            publish_parent.mkdir()
            publish = make_publish(publish_parent)
            package_root = repo / "obj/linux-packages/deb/root"
            package_root.mkdir(parents=True)
            sentinel = package_root / "sentinel"
            sentinel.write_bytes(b"keep")
            output_dir = temporary / "output"
            output_dir.mkdir()
            output = deb_output(output_dir)

            for tree_name, ancestor in (
                ("package root", repo),
                ("publish directory", publish_parent),
            ):
                with self.subTest(tree_name=tree_name):
                    try:
                        output.symlink_to(ancestor, target_is_directory=True)
                    except OSError as error:
                        self.skipTest(f"symlinks unavailable: {error}")
                    with (
                        mock.patch.object(package_deb.shutil, "which", return_value="dpkg-deb"),
                        mock.patch.object(package_deb, "stage_payload") as stage,
                        mock.patch.object(package_deb.subprocess, "run") as run,
                        self.assertRaisesRegex(ValueError, "overlap"),
                    ):
                        package_deb.build_deb(
                            repo,
                            NativeVersion.parse("1.2.3", 4),
                            publish,
                            output_dir,
                        )
                    self.assertTrue(output.is_symlink())
                    self.assertEqual(b"keep", sentinel.read_bytes())
                    stage.assert_not_called()
                    run.assert_not_called()
                    output.unlink()

    def test_failed_build_preserves_old_output_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish_parent = temporary / "payload"
            publish_parent.mkdir()
            publish = make_publish(publish_parent)
            output_dir = temporary / "output"
            output_dir.mkdir()
            output = deb_output(output_dir)
            output.write_bytes(b"old package")

            def fail_after_writing(command, **kwargs):
                pathlib.Path(command[-1]).write_bytes(b"partial package")
                raise subprocess.CalledProcessError(1, command)

            with (
                mock.patch.object(package_deb.shutil, "which", return_value="dpkg-deb"),
                mock.patch.object(package_deb.subprocess, "run", side_effect=fail_after_writing),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                package_deb.build_deb(
                    repo,
                    NativeVersion.parse("1.2.3", 4),
                    publish,
                    output_dir,
                )

            self.assertEqual(b"old package", output.read_bytes())
            self.assertEqual([output], list(output_dir.iterdir()))

    def test_successful_build_atomically_replaces_old_output(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish_parent = temporary / "payload"
            publish_parent.mkdir()
            publish = make_publish(publish_parent)
            output_dir = temporary / "output"
            output_dir.mkdir()
            output = deb_output(output_dir)
            output.write_bytes(b"old package")

            def create_temporary_output(command, **kwargs):
                self.assertEqual(b"old package", output.read_bytes())
                pathlib.Path(command[-1]).write_bytes(b"new package")
                return subprocess.CompletedProcess(command, 0)

            with (
                mock.patch.object(package_deb.shutil, "which", return_value="dpkg-deb"),
                mock.patch.object(package_deb.subprocess, "run", side_effect=create_temporary_output),
                mock.patch.object(package_deb.os, "replace", wraps=os.replace) as replace,
            ):
                result = package_deb.build_deb(
                    repo,
                    NativeVersion.parse("1.2.3", 4),
                    publish,
                    output_dir,
                )

            self.assertEqual(output, result)
            self.assertEqual(b"new package", output.read_bytes())
            replace.assert_called_once()
            self.assertEqual(output, pathlib.Path(replace.call_args.args[1]))
            self.assertEqual([output], list(output_dir.iterdir()))

    def test_native_build_is_byte_identical_with_same_epoch_across_wall_clock_time(self):
        if package_deb.shutil.which("dpkg-deb") is None:
            self.skipTest("dpkg-deb is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish_parent = temporary / "payload"
            publish_parent.mkdir()
            publish = make_publish(publish_parent)
            version = NativeVersion.parse("1.2.3", 4)

            with mock.patch.dict(
                os.environ, {"SOURCE_DATE_EPOCH": "946684800"}, clear=False
            ):
                first = package_deb.build_deb(
                    repo, version, publish, temporary / "first-output"
                )
                first_hash = hashlib.sha256(first.read_bytes()).hexdigest()
                for source in publish.rglob("*"):
                    os.utime(source, (1_700_000_000, 1_700_000_000))
                second = package_deb.build_deb(
                    repo, version, publish, temporary / "second-output"
                )
                second_hash = hashlib.sha256(second.read_bytes()).hexdigest()

            self.assertEqual(first_hash, second_hash)

    def test_installed_size_matches_extracted_data_archive(self):
        if package_deb.shutil.which("dpkg-deb") is None:
            self.skipTest("dpkg-deb is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish_parent = temporary / "payload"
            publish_parent.mkdir()
            publish = make_publish(publish_parent)
            package = package_deb.build_deb(
                repo,
                NativeVersion.parse("1.0.0", 1),
                publish,
                temporary / "output",
            )
            field = subprocess.run(
                ["dpkg-deb", "--field", str(package), "Installed-Size"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            extracted_data_root = temporary / "extracted-data"
            subprocess.run(
                ["dpkg-deb", "--extract", str(package), str(extracted_data_root)],
                check=True,
            )

            self.assertEqual(
                package_deb.installed_size(extracted_data_root),
                int(field),
            )

    def test_build_rejects_and_cleans_non_regular_temporary_output(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish_parent = temporary / "payload"
            publish_parent.mkdir()
            publish = make_publish(publish_parent)
            output_dir = temporary / "output"
            target = temporary / "target"
            target.write_bytes(b"not the package")

            def create_symlink_output(command, **kwargs):
                pathlib.Path(command[-1]).symlink_to(target)
                return subprocess.CompletedProcess(command, 0)

            with (
                mock.patch.object(package_deb.shutil, "which", return_value="dpkg-deb"),
                mock.patch.object(
                    package_deb.subprocess, "run", side_effect=create_symlink_output
                ),
                self.assertRaisesRegex(FileNotFoundError, "not a regular file"),
            ):
                package_deb.build_deb(
                    repo,
                    NativeVersion.parse("1.2.3", 4),
                    publish,
                    output_dir,
                )

            self.assertEqual([], list(output_dir.iterdir()))
            self.assertEqual(b"not the package", target.read_bytes())

    def test_build_rejects_and_cleans_temporary_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish_parent = temporary / "payload"
            publish_parent.mkdir()
            publish = make_publish(publish_parent)
            output_dir = temporary / "output"

            def create_directory_output(command, **kwargs):
                temporary_output = pathlib.Path(command[-1])
                temporary_output.mkdir()
                (temporary_output / "partial").write_bytes(b"not a package")
                return subprocess.CompletedProcess(command, 0)

            with (
                mock.patch.object(package_deb.shutil, "which", return_value="dpkg-deb"),
                mock.patch.object(
                    package_deb.subprocess, "run", side_effect=create_directory_output
                ),
                self.assertRaisesRegex(FileNotFoundError, "not a regular file"),
            ):
                package_deb.build_deb(
                    repo,
                    NativeVersion.parse("1.2.3", 4),
                    publish,
                    output_dir,
                )

            self.assertEqual([], list(output_dir.iterdir()))

    def test_serialized_direct_cli_builds_from_real_repository_root(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            publish = make_publish(temporary)
            output_dir = temporary / "output"
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            fake_dpkg = fake_bin / "dpkg-deb"
            fake_dpkg.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                "import sys\n"
                "Path(sys.argv[-1]).write_bytes(b'fake deb')\n",
                encoding="utf-8",
            )
            fake_dpkg.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

            result = self.run_cli(
                "--version",
                "1.2.3",
                "--release",
                "4",
                "--publish-dir",
                str(publish),
                "--output-dir",
                str(output_dir),
                env=env,
            )

            output = deb_output(output_dir)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(f"{output}\n", result.stdout)
            self.assertEqual(b"fake deb", output.read_bytes())

    def test_build_fails_if_dpkg_deb_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo = make_fake_repo(temporary)
            publish_parent = temporary / "payload"
            publish_parent.mkdir()
            publish = make_publish(publish_parent)
            with (
                mock.patch.object(package_deb.shutil, "which", return_value="dpkg-deb"),
                mock.patch.object(package_deb.subprocess, "run"),
                self.assertRaisesRegex(FileNotFoundError, "did not create"),
            ):
                package_deb.build_deb(
                    repo,
                    NativeVersion.parse("1.2.3", 4),
                    publish,
                    temporary / "output",
                )


EXPECTED_RPM_SPEC = """Name: object-storage-client
Version: 1.2.3
Release: 4%{?dist}
Summary: Desktop client for S3-compatible object storage
License: MIT
URL: https://github.com/devcode-kr/object-storage-client
Source0: payload.tar.gz
BuildArch: x86_64
Requires: libX11
Requires: libICE
Requires: libSM
Requires: fontconfig
Requires: ca-certificates

%description
Browse local files and remote S3-compatible object storage in a two-pane interface.

%prep
%setup -q -c -T
%{__tar} -xzf %{SOURCE0}

%build

%install
rm -rf %{buildroot}
mkdir -p %{buildroot}
cp -a .%{_prefix} %{buildroot}/

%files
%license /usr/share/doc/object-storage-client/LICENSE
%doc /usr/share/doc/object-storage-client/README.md
%doc /usr/share/doc/object-storage-client/PRIVACY.md
/usr/bin/object-storage-client
/usr/lib/object-storage-client/
/usr/share/applications/object-storage-client.desktop
/usr/share/icons/hicolor/256x256/apps/object-storage-client.png
"""


def rpm_output(output_dir: pathlib.Path) -> pathlib.Path:
    return output_dir / "ObjectStorageClient-1.2.3-4-linux-x64.rpm"


class RpmSpecTests(unittest.TestCase):
    def test_source_date_epoch_defaults_to_zero_and_accepts_ascii_decimals(self):
        self.assertEqual(0, package_rpm.rpm_source_date_epoch({}))
        self.assertEqual(
            0, package_rpm.rpm_source_date_epoch({"SOURCE_DATE_EPOCH": "0"})
        )
        self.assertEqual(
            123, package_rpm.rpm_source_date_epoch({"SOURCE_DATE_EPOCH": "123"})
        )

    def test_source_date_epoch_rejects_invalid_values(self):
        for invalid in ("", "-1", "+1", "1.0", "abc", "１２３"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "SOURCE_DATE_EPOCH"):
                    package_rpm.rpm_source_date_epoch({"SOURCE_DATE_EPOCH": invalid})

    def test_render_spec_is_the_exact_complete_body(self):
        rendered = package_rpm.render_spec(
            NativeVersion.parse("1.2.3", 4), "payload.tar.gz"
        )
        self.assertEqual(EXPECTED_RPM_SPEC, rendered)
        self.assertNotIn(".devcode", rendered)
        self.assertIsNone(re.search(r"^%(?:pre|post|preun|postun)\b", rendered, re.MULTILINE))
        self.assertIsNone(re.search(r"@[A-Z][A-Z0-9_]*@", rendered))

    def test_render_spec_rejects_unsafe_source_names(self):
        version = NativeVersion.parse("1.2.3", 4)
        for source in ("../payload.tar.gz", "/payload.tar.gz", "nested/payload.tar.gz", "bad\nname"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "source"):
                    package_rpm.render_spec(version, source)

    def test_render_spec_rejects_unknown_template_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            template = pathlib.Path(directory) / "package.spec"
            template.write_text("Version: @VERSION@\nUnexpected: @UNKNOWN_TOKEN@\n", encoding="utf-8")
            with (
                mock.patch.object(package_rpm, "SPEC_TEMPLATE_PATH", template),
                self.assertRaisesRegex(ValueError, "template token"),
            ):
                package_rpm.render_spec(NativeVersion.parse("1.2.3", 4), "payload.tar.gz")


class RpmPayloadTarTests(unittest.TestCase):
    def test_tar_is_deterministic_normalized_sorted_and_preserves_symlinks_at_default_epoch(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            root = temporary / "root"
            (root / "usr/lib/object-storage-client").mkdir(parents=True)
            executable = root / "usr/lib/object-storage-client/app"
            executable.write_bytes(b"app")
            executable.chmod(0o755)
            plain = root / "usr/lib/object-storage-client/data"
            plain.write_bytes(b"data")
            plain.chmod(0o644)
            outside = temporary / "outside"
            outside.write_bytes(b"secret")
            try:
                (root / "usr/lib/object-storage-client/outside-link").symlink_to(outside)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            first = temporary / "first.tar.gz"
            second = temporary / "second.tar.gz"

            epoch = package_rpm.rpm_source_date_epoch({})
            package_rpm.create_payload_tar(root, first, epoch)
            os.utime(executable, (1_700_000_000, 1_700_000_000))
            package_rpm.create_payload_tar(root, second, epoch)

            self.assertEqual(hashlib.sha256(first.read_bytes()).digest(), hashlib.sha256(second.read_bytes()).digest())
            with tarfile.open(first, "r:gz") as archive:
                members = archive.getmembers()
                self.assertEqual(sorted(member.name for member in members), [member.name for member in members])
                self.assertTrue(all(not member.name.startswith(("/", "../")) for member in members))
                for member in members:
                    self.assertEqual(0, member.uid)
                    self.assertEqual(0, member.gid)
                    self.assertEqual("", member.uname)
                    self.assertEqual("", member.gname)
                    self.assertEqual(0, member.mtime)
                by_name = {member.name: member for member in members}
                self.assertEqual(0o755, by_name["usr/lib/object-storage-client/app"].mode)
                self.assertEqual(0o644, by_name["usr/lib/object-storage-client/data"].mode)
                link = by_name["usr/lib/object-storage-client/outside-link"]
                self.assertTrue(link.issym())
                self.assertEqual(str(outside), link.linkname)
                self.assertNotIn(b"secret", first.read_bytes())


class RpmBuildTests(unittest.TestCase):
    def _fixture(self, temporary: pathlib.Path):
        repo = make_fake_repo(temporary)
        publish_parent = temporary / "payload"
        publish_parent.mkdir()
        publish = make_publish(publish_parent)
        return repo, publish, temporary / "output"

    @staticmethod
    def _write_fake_rpm(command, **kwargs):
        topdir = pathlib.Path(command[command.index("--define") + 1].split(" ", 1)[1])
        rpm_dir = topdir / "RPMS/x86_64"
        rpm_dir.mkdir(parents=True, exist_ok=True)
        (rpm_dir / "object-storage-client.rpm").write_bytes(b"fake rpm")
        return subprocess.CompletedProcess(command, 0)

    def test_missing_rpmbuild_fails_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo, publish, output = self._fixture(temporary)
            with mock.patch.object(package_rpm.shutil, "which", return_value=None):
                with self.assertRaisesRegex(FileNotFoundError, "rpmbuild"):
                    package_rpm.build_rpm(repo, NativeVersion.parse("1.2.3", 4), publish, output)

    def test_fake_build_uses_isolated_topdir_and_publishes_expected_output(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo, publish, output_dir = self._fixture(temporary)
            epoch = 123456789
            with (
                mock.patch.object(package_rpm.shutil, "which", return_value="/usr/bin/rpmbuild"),
                mock.patch.object(package_rpm.os, "environ", {"SOURCE_DATE_EPOCH": str(epoch)}),
                mock.patch.object(package_rpm.subprocess, "run", side_effect=self._write_fake_rpm) as run,
                mock.patch.object(package_rpm.os, "replace", wraps=os.replace) as replace,
            ):
                output = package_rpm.build_rpm(
                    repo, NativeVersion.parse("1.2.3", 4), publish, output_dir
                )

            topdir = repo / "obj/linux-packages/rpm"
            self.assertEqual(rpm_output(output_dir), output)
            self.assertEqual(b"fake rpm", output.read_bytes())
            self.assertEqual(
                [
                    "/usr/bin/rpmbuild", "-bb", "--define", f"_topdir {topdir}",
                    str(topdir / "SPECS/object-storage-client.spec"),
                ],
                run.call_args.args[0],
            )
            self.assertTrue(run.call_args.kwargs["check"])
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertEqual(str(epoch), run.call_args.kwargs["env"]["SOURCE_DATE_EPOCH"])
            for name in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
                self.assertTrue((topdir / name).is_dir())
            self.assertTrue((topdir / "SOURCES/payload.tar.gz").is_file())
            self.assertEqual(
                epoch * 1_000_000_000,
                (topdir / "SOURCES/payload.tar.gz").stat().st_mtime_ns,
            )
            self.assertEqual(EXPECTED_RPM_SPEC, (topdir / "SPECS/object-storage-client.spec").read_text())
            self.assertEqual(0o644, stat.S_IMODE((topdir / "SPECS/object-storage-client.spec").stat().st_mode))
            self.assertEqual(epoch * 1_000_000_000, (topdir / "SPECS/object-storage-client.spec").stat().st_mtime_ns)
            replace.assert_called_once()
            self.assertEqual(output, pathlib.Path(replace.call_args.args[1]))

    def test_build_rejects_zero_multiple_and_symlink_rpm_outputs(self):
        def callback(kind):
            def create(command, **kwargs):
                topdir = pathlib.Path(command[-1]).parents[1]
                rpm_dir = topdir / "RPMS/x86_64"
                rpm_dir.mkdir(parents=True, exist_ok=True)
                if kind == "multiple":
                    (rpm_dir / "one.rpm").write_bytes(b"one")
                    (rpm_dir / "two.rpm").write_bytes(b"two")
                elif kind == "symlink":
                    target = topdir / "outside.rpm"
                    target.write_bytes(b"outside")
                    (rpm_dir / "one.rpm").symlink_to(target)
                return subprocess.CompletedProcess(command, 0)
            return create

        for kind in ("zero", "multiple", "symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                temporary = pathlib.Path(directory)
                repo, publish, output = self._fixture(temporary)
                with (
                    mock.patch.object(package_rpm.shutil, "which", return_value="rpmbuild"),
                    mock.patch.object(package_rpm.subprocess, "run", side_effect=callback(kind)),
                    self.assertRaisesRegex(FileNotFoundError, "exactly one.*x86_64 RPM"),
                ):
                    package_rpm.build_rpm(repo, NativeVersion.parse("1.2.3", 4), publish, output)

    def test_failed_build_preserves_old_output_and_cleans_temporary_output(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo, publish, output_dir = self._fixture(temporary)
            output_dir.mkdir()
            final = rpm_output(output_dir)
            final.write_bytes(b"old rpm")

            def fail(command, **kwargs):
                raise subprocess.CalledProcessError(1, command)

            with (
                mock.patch.object(package_rpm.shutil, "which", return_value="rpmbuild"),
                mock.patch.object(package_rpm.subprocess, "run", side_effect=fail),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                package_rpm.build_rpm(repo, NativeVersion.parse("1.2.3", 4), publish, output_dir)
            self.assertEqual(b"old rpm", final.read_bytes())
            self.assertEqual([final], list(output_dir.iterdir()))

    def test_failed_final_copy_preserves_old_output_and_cleans_partial_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo, publish, output_dir = self._fixture(temporary)
            output_dir.mkdir()
            final = rpm_output(output_dir)
            final.write_bytes(b"old rpm")

            def fail_copy(source, destination, **kwargs):
                pathlib.Path(destination).write_bytes(b"partial rpm")
                raise OSError("copy failed")

            with (
                mock.patch.object(package_rpm.shutil, "which", return_value="rpmbuild"),
                mock.patch.object(package_rpm.subprocess, "run", side_effect=self._write_fake_rpm),
                mock.patch.object(package_rpm.shutil, "copyfile", side_effect=fail_copy),
                self.assertRaisesRegex(OSError, "copy failed"),
            ):
                package_rpm.build_rpm(repo, NativeVersion.parse("1.2.3", 4), publish, output_dir)
            self.assertEqual(b"old rpm", final.read_bytes())
            self.assertEqual([final], list(output_dir.iterdir()))

    def test_success_atomically_replaces_stale_final(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo, publish, output_dir = self._fixture(temporary)
            output_dir.mkdir()
            final = rpm_output(output_dir)
            final.write_bytes(b"old rpm")

            def build(command, **kwargs):
                self.assertEqual(b"old rpm", final.read_bytes())
                return self._write_fake_rpm(command, **kwargs)

            with (
                mock.patch.object(package_rpm.shutil, "which", return_value="rpmbuild"),
                mock.patch.object(package_rpm.subprocess, "run", side_effect=build),
                mock.patch.object(package_rpm.os, "replace", wraps=os.replace) as replace,
            ):
                package_rpm.build_rpm(repo, NativeVersion.parse("1.2.3", 4), publish, output_dir)
            self.assertEqual(b"fake rpm", final.read_bytes())
            replace.assert_called_once()

    def test_rejects_output_publish_topdir_overlaps_before_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo, publish, normal_output = self._fixture(temporary)
            topdir = repo / "obj/linux-packages/rpm"
            cases = (topdir / "output", topdir.parent, publish / "output", publish.parent)
            for output in cases:
                with (
                    self.subTest(output=output),
                    mock.patch.object(package_rpm.shutil, "which", return_value="rpmbuild"),
                    mock.patch.object(package_rpm, "stage_payload") as stage,
                    mock.patch.object(package_rpm.subprocess, "run") as run,
                    self.assertRaisesRegex(ValueError, "overlap"),
                ):
                    package_rpm.build_rpm(repo, NativeVersion.parse("1.2.3", 4), publish, output)
                stage.assert_not_called()
                run.assert_not_called()

    def test_rejects_symlinked_topdir_parent_without_deleting_target(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo, publish, output = self._fixture(temporary)
            unrelated = temporary / "unrelated"
            staging = unrelated / "linux-packages/rpm/staging-root"
            staging.mkdir(parents=True)
            sentinel = staging / "sentinel"
            sentinel.write_bytes(b"keep")
            try:
                (repo / "obj").symlink_to(unrelated, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            with (
                mock.patch.object(package_rpm.shutil, "which", return_value="rpmbuild"),
                mock.patch.object(package_rpm.subprocess, "run") as run,
                self.assertRaisesRegex(ValueError, str(repo / "obj")),
            ):
                package_rpm.build_rpm(repo, NativeVersion.parse("1.2.3", 4), publish, output)
            self.assertEqual(b"keep", sentinel.read_bytes())
            run.assert_not_called()

    def test_rejects_final_symlink_resolving_into_protected_trees(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            repo, publish, output_dir = self._fixture(temporary)
            output_dir.mkdir()
            topdir = repo / "obj/linux-packages/rpm"
            topdir.mkdir(parents=True)
            final = rpm_output(output_dir)
            for target in (topdir / "keep.rpm", publish / "keep.rpm"):
                with self.subTest(target=target):
                    target.write_bytes(b"keep")
                    try:
                        final.symlink_to(target)
                    except OSError as error:
                        self.skipTest(f"symlinks unavailable: {error}")
                    with (
                        mock.patch.object(package_rpm.shutil, "which", return_value="rpmbuild"),
                        mock.patch.object(package_rpm, "stage_payload") as stage,
                        mock.patch.object(package_rpm.subprocess, "run") as run,
                        self.assertRaisesRegex(ValueError, "overlap"),
                    ):
                        package_rpm.build_rpm(
                            repo, NativeVersion.parse("1.2.3", 4), publish, output_dir
                        )
                    self.assertTrue(final.is_symlink())
                    self.assertEqual(b"keep", target.read_bytes())
                    stage.assert_not_called()
                    run.assert_not_called()
                    final.unlink()


class RpmCliTests(unittest.TestCase):
    def run_cli(self, *arguments: str, env=None, repo_root=ROOT):
        return subprocess.run(
            [sys.executable, str(repo_root / "build/linux/package_rpm.py"), *arguments],
            cwd=repo_root, text=True, capture_output=True, check=False, env=env,
        )

    def test_cli_requires_all_arguments(self):
        result = self.run_cli()
        self.assertNotEqual(0, result.returncode)
        for option in ("--version", "--release", "--publish-dir", "--output-dir"):
            self.assertIn(option, result.stderr)

    def test_serialized_direct_cli_builds_with_fake_rpmbuild_from_repo_root(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            fake_repo = make_fake_rpm_repo(temporary)
            publish = make_publish(fake_repo)
            output_dir = fake_repo / "output"
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            fake = fake_bin / "rpmbuild"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                "import sys\n"
                "top = Path(sys.argv[sys.argv.index('--define') + 1].split(' ', 1)[1])\n"
                "out = top / 'RPMS/x86_64/fake.rpm'\n"
                "out.parent.mkdir(parents=True, exist_ok=True)\n"
                "out.write_bytes(b'cli fake rpm')\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
            rpm_work = ROOT / "obj/linux-packages/rpm"
            rpm_work_existed = rpm_work.exists()
            rpm_work.mkdir(parents=True, exist_ok=True)
            sentinel = rpm_work / f"test-cli-sentinel-{os.getpid()}"
            sentinel.write_bytes(b"preserve real RPM work tree")
            try:
                result = self.run_cli(
                    "--version", "1.2.3", "--release", "4",
                    "--publish-dir", str(publish), "--output-dir", str(output_dir), env=env,
                    repo_root=fake_repo,
                )
                output = rpm_output(output_dir)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(f"{output}\n", result.stdout)
                self.assertEqual(b"cli fake rpm", output.read_bytes())
                self.assertEqual(b"preserve real RPM work tree", sentinel.read_bytes())
                self.assertTrue((fake_repo / "obj/linux-packages/rpm").is_dir())
            finally:
                sentinel.unlink(missing_ok=True)
                if not rpm_work_existed:
                    try:
                        rpm_work.rmdir()
                    except OSError:
                        pass


if __name__ == "__main__":
    unittest.main()
