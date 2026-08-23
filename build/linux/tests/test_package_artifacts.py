from __future__ import annotations

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
if str(LINUX) not in sys.path:
    sys.path.insert(0, str(LINUX))

import package_deb
import stage_payload
from package_contract import NativeVersion


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


def make_publish(parent: pathlib.Path, executable: bool = True) -> pathlib.Path:
    publish = parent / "publish"
    publish.mkdir()
    apphost = publish / "ObjectStorageClient.App"
    apphost.write_bytes(b"fake apphost")
    apphost.chmod(0o755 if executable else 0o644)
    (publish / "ObjectStorageClient.App.dll").write_bytes(b"fake dll")
    return publish


class StagePayloadTests(unittest.TestCase):
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

            stage_payload.stage_payload(ROOT, publish, package_root)

            expected_files = {
                pathlib.Path("usr/lib/object-storage-client/ObjectStorageClient.App"),
                pathlib.Path("usr/lib/object-storage-client/ObjectStorageClient.App.dll"),
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
                    path.relative_to(publish): (
                        path.read_bytes(),
                        stat.S_IMODE(path.stat().st_mode),
                    )
                    for path in publish.iterdir()
                },
            )

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
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(LINUX / "package_deb.py"), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
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
