from __future__ import annotations

import os
import pathlib
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[3]
LINUX = ROOT / "build" / "linux"

from build.linux import package_deb, stage_payload
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
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from build.linux.stage_payload import stage_payload; "
                    "from build.linux.package_deb import render_control; "
                    "from build.linux.package_contract import NativeVersion"
                ),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)


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
    sources = {
        "build/linux/object-storage-client": b"#!/bin/sh\n",
        "build/linux/object-storage-client.desktop": b"[Desktop Entry]\n",
        "src/ObjectStorageClient.App/Assets/appicon.png": b"fake png",
        "README.md": b"readme",
        "PRIVACY.md": b"privacy",
        "LICENSE": b"license",
    }
    for relative, contents in sources.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
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

            stage_payload.stage_payload(ROOT, publish, package_root)

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
                (ROOT / "build/linux/object-storage-client.desktop").read_bytes(),
                (package_root / "usr/share/applications/object-storage-client.desktop").read_bytes(),
            )
            source_icon = (
                ROOT / "src/ObjectStorageClient.App/Assets/appicon.png"
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
                    (ROOT / name).read_bytes(),
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

    def test_rejects_package_root_inside_publish_without_changing_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            publish = make_publish(temporary)
            source = publish / "ObjectStorageClient.App.dll"
            package_root = publish / "staging/root"
            package_root.mkdir(parents=True)
            sentinel = package_root / "sentinel"
            sentinel.write_bytes(b"keep")

            with self.assertRaisesRegex(ValueError, "overlap"):
                stage_payload.stage_payload(ROOT, publish, package_root)

            self.assertEqual(b"fake dll", source.read_bytes())
            self.assertEqual(b"keep", sentinel.read_bytes())

    def test_rejects_publish_inside_package_root_without_changing_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            package_root = temporary / "staging"
            package_root.mkdir()
            sentinel = package_root / "sentinel"
            sentinel.write_bytes(b"keep")
            publish = make_publish(package_root)
            source = publish / "ObjectStorageClient.App.dll"

            with self.assertRaisesRegex(ValueError, "overlap"):
                stage_payload.stage_payload(ROOT, publish, package_root)

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
                    self.assertEqual(b"#!/bin/sh\n", launcher.read_bytes())
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
            self.assertEqual(b"#!/bin/sh\n", launcher.read_bytes())
            self.assertEqual(b"keep", sentinel.read_bytes())

    def test_rejects_arbitrary_symlinked_package_root_parent_without_deleting_target(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
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
                stage_payload.stage_payload(ROOT, publish, package_root)

            self.assertEqual(b"keep", sentinel.read_bytes())

    def test_rejects_publish_path_that_is_not_a_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            publish_file = temporary / "publish"
            publish_file.write_text("not a directory", encoding="utf-8")
            with self.assertRaises(NotADirectoryError):
                stage_payload.stage_payload(ROOT, publish_file, temporary / "root")

    def test_rejects_missing_apphost(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            publish = temporary / "publish"
            publish.mkdir()
            with self.assertRaises(FileNotFoundError):
                stage_payload.stage_payload(ROOT, publish, temporary / "root")

    def test_rejects_non_executable_apphost(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            publish = make_publish(temporary, executable=False)
            with self.assertRaises(PermissionError):
                stage_payload.stage_payload(ROOT, publish, temporary / "root")


class DebianControlTests(unittest.TestCase):
    def test_render_control_is_the_exact_complete_body(self):
        control = package_deb.render_control(NativeVersion.parse("1.2.3", 4), 50000)
        self.assertEqual(EXPECTED_CONTROL, control)
        self.assertTrue(control.endswith("\n"))
        self.assertNotIn(".devcode", control)

    def test_installed_size_ceilings_regular_file_bytes_and_ignores_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "directory").mkdir()
            (root / "first").write_bytes(b"a" * 1024)
            (root / "directory/second").write_bytes(b"b")
            try:
                (root / "large-link").symlink_to(root / "first")
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            self.assertEqual(2, package_deb.installed_size(root))

    def test_render_control_rejects_invalid_installed_sizes(self):
        version = NativeVersion.parse("1.2.3", 4)
        for invalid in (-1, True, 1.5, "50000", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    package_deb.render_control(version, invalid)


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
            publish = make_publish(temporary)
            with mock.patch.object(package_deb.shutil, "which", return_value=None):
                with self.assertRaisesRegex(FileNotFoundError, "dpkg-deb"):
                    package_deb.build_deb(
                        ROOT,
                        NativeVersion.parse("1.2.3", 4),
                        publish,
                        temporary / "out",
                    )

    def test_build_invokes_dpkg_deb_with_an_argument_list_and_no_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            publish = make_publish(temporary)
            output_dir = temporary / "output"

            def create_output(command, **kwargs):
                pathlib.Path(command[-1]).write_bytes(b"fake deb")
                return subprocess.CompletedProcess(command, 0)

            with (
                mock.patch.object(package_deb.shutil, "which", return_value="/usr/bin/dpkg-deb"),
                mock.patch.object(
                    package_deb.subprocess, "run", side_effect=create_output
                ) as run,
            ):
                output = package_deb.build_deb(
                    ROOT,
                    NativeVersion.parse("1.2.3", 4),
                    publish,
                    output_dir,
                )

            expected_root = ROOT / "obj/linux-packages/deb/root"
            self.assertEqual(
                output_dir / "ObjectStorageClient-1.2.3-4-linux-x64.deb", output
            )
            run.assert_called_once_with(
                [
                    "/usr/bin/dpkg-deb",
                    "--root-owner-group",
                    "--build",
                    str(expected_root),
                    str(output),
                ],
                check=True,
            )
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertEqual(
                0o644,
                stat.S_IMODE((expected_root / "DEBIAN/control").stat().st_mode),
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

    def test_build_removes_stale_output_before_invoking_dpkg_deb(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            publish = make_publish(temporary)
            output_dir = temporary / "output"
            output_dir.mkdir()
            output = deb_output(output_dir)
            output.write_bytes(b"old package")

            def replace_output(command, **kwargs):
                self.assertFalse(output.exists())
                pathlib.Path(command[-1]).write_bytes(b"new package")
                return subprocess.CompletedProcess(command, 0)

            with (
                mock.patch.object(package_deb.shutil, "which", return_value="dpkg-deb"),
                mock.patch.object(package_deb.subprocess, "run", side_effect=replace_output),
            ):
                result = package_deb.build_deb(
                    ROOT,
                    NativeVersion.parse("1.2.3", 4),
                    publish,
                    output_dir,
                )

            self.assertEqual(output, result)
            self.assertEqual(b"new package", output.read_bytes())

    def test_cli_builds_from_repository_root_with_dpkg_deb_on_path(self):
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
            publish = make_publish(temporary)
            with (
                mock.patch.object(package_deb.shutil, "which", return_value="dpkg-deb"),
                mock.patch.object(package_deb.subprocess, "run"),
                self.assertRaisesRegex(FileNotFoundError, "did not create"),
            ):
                package_deb.build_deb(
                    ROOT,
                    NativeVersion.parse("1.2.3", 4),
                    publish,
                    temporary / "output",
                )


if __name__ == "__main__":
    unittest.main()
