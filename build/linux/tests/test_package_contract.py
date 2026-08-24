from __future__ import annotations

import dataclasses
import importlib.util
import pathlib
import stat
import sys
import unittest
import uuid
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[3]
LINUX = ROOT / "build" / "linux"
GENERATED_PYTHON_CACHE_SUFFIXES = (".pyc", ".pyo", ".pyd")


def user_state_references():
    forbidden = ".devcode" + "/object-storage-client"
    references = []
    for path in LINUX.rglob("*"):
        if (
            path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in GENERATED_PYTHON_CACHE_SUFFIXES
            and forbidden in path.read_text(encoding="utf-8", errors="ignore")
        ):
            references.append(path)
    return references


def load_contract():
    path = LINUX / "package_contract.py"
    module_name = f"_osc_linux_package_contract_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


class PackageContractTests(unittest.TestCase):
    def test_package_identity_and_paths_are_stable(self):
        contract = load_contract()
        self.assertEqual("object-storage-client", contract.PACKAGE_NAME)
        self.assertEqual("Object Storage Client", contract.PRODUCT_NAME)
        self.assertEqual("amd64", contract.DEB_ARCH)
        self.assertEqual("x86_64", contract.RPM_ARCH)
        self.assertEqual("/usr/lib/object-storage-client", contract.APP_DIR)
        self.assertEqual("/usr/bin/object-storage-client", contract.LAUNCHER_PATH)
        self.assertEqual(
            "/usr/share/applications/object-storage-client.desktop",
            contract.DESKTOP_PATH,
        )
        self.assertEqual(
            "/usr/share/icons/hicolor/256x256/apps/object-storage-client.png",
            contract.ICON_PATH,
        )
        self.assertEqual(
            "/usr/share/doc/object-storage-client",
            contract.DOC_DIR,
        )

    def test_version_mapping_uses_native_package_release(self):
        contract = load_contract()
        version = contract.NativeVersion.parse("1.2.3", 4)
        self.assertEqual("1.2.3-4", version.debian)
        self.assertEqual("1.2.3", version.rpm_version)
        self.assertEqual("4", version.rpm_release)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            version.package_release = 5

    def test_valid_release_boundaries_map_to_native_versions(self):
        contract = load_contract()
        for release in (1, 65535):
            with self.subTest(release=release):
                version = contract.NativeVersion.parse("1.2.3", release)
                self.assertEqual(f"1.2.3-{release}", version.debian)
                self.assertEqual("1.2.3", version.rpm_version)
                self.assertEqual(str(release), version.rpm_release)

    def test_load_contract_uses_unique_temporary_module_names(self):
        first = load_contract()
        second = load_contract()

        self.assertNotEqual(first.__name__, second.__name__)
        self.assertNotIn(first.__name__, sys.modules)
        self.assertNotIn(second.__name__, sys.modules)

    def test_load_contract_removes_temporary_module_when_execution_raises(self):
        module_name = "_osc_linux_package_contract_test_failure"
        fake_uuid = mock.Mock(hex="failure")
        self.assertNotIn(module_name, sys.modules)

        try:
            with (
                mock.patch.object(uuid, "uuid4", return_value=fake_uuid),
                mock.patch(
                    "_frozen_importlib_external.SourceFileLoader.exec_module",
                    side_effect=RuntimeError("deliberate execution failure"),
                ),
                self.assertRaisesRegex(RuntimeError, "deliberate execution failure"),
            ):
                load_contract()
        finally:
            leaked_module = sys.modules.pop(module_name, None)

        self.assertIsNone(leaked_module)

    def test_invalid_versions_and_releases_are_rejected(self):
        contract = load_contract()
        for value in ("1.2", "v1.2.3", "1.2.3.4", "1.2.x", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    contract.NativeVersion.parse(value, 1)
        for release in (0, -1, 65536, True, False, 1.5, 65534.9, "1", None):
            with self.subTest(release=release):
                with self.assertRaises(ValueError):
                    contract.NativeVersion.parse("1.2.3", release)

    def test_debian_dependencies_are_exact(self):
        contract = load_contract()
        self.assertEqual(
            ("libx11-6", "libice6", "libsm6", "libfontconfig1", "ca-certificates"),
            contract.DEB_DEPENDENCIES,
        )

    def test_rpm_dependencies_are_exact(self):
        contract = load_contract()
        self.assertEqual(
            ("libX11", "libICE", "libSM", "fontconfig", "ca-certificates"),
            contract.RPM_DEPENDENCIES,
        )

    def test_launcher_uses_absolute_application_path(self):
        launcher_path = LINUX / "object-storage-client"
        launcher = launcher_path.read_text(encoding="utf-8")
        self.assertEqual(
            "#!/bin/sh\nexec /usr/lib/object-storage-client/ObjectStorageClient.App \"$@\"\n",
            launcher,
        )
        self.assertEqual(0o755, stat.S_IMODE(launcher_path.stat().st_mode))

    def test_desktop_entry_uses_installed_command_and_icon(self):
        desktop = (LINUX / "object-storage-client.desktop").read_text(encoding="utf-8")
        self.assertEqual(
            "[Desktop Entry]\n"
            "Name=Object Storage Client\n"
            "Comment=Browse and transfer files in S3-compatible object storage\n"
            "Exec=object-storage-client\n"
            "Icon=object-storage-client\n"
            "Type=Application\n"
            "Categories=Network;FileTransfer;\n"
            "Terminal=false\n",
            desktop,
        )

    def test_linux_packaging_ignore_entries_are_exact(self):
        required = {
            "__pycache__/",
            "*.py[cod]",
            "artifacts/linux-packages/",
            "obj/linux-packages/",
            "obj/linux-repositories/",
            "obj/linux-smoke/",
            "obj/gnupg-test/",
        }
        entries = [
            line
            for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line and not line.lstrip().startswith("#")
        ]
        normalized_entries = [entry.strip() for entry in entries]

        for entry in required:
            with self.subTest(entry=entry):
                self.assertEqual(1, entries.count(entry))
                self.assertEqual(1, normalized_entries.count(entry))

        linux_entries = {
            entry
            for entry in entries
            if entry.startswith(("artifacts/linux-", "obj/linux-", "obj/gnupg-"))
        }
        self.assertEqual(
            {
                "artifacts/linux-packages/",
                "obj/linux-packages/",
                "obj/linux-repositories/",
                "obj/linux-smoke/",
                "obj/gnupg-test/",
            },
            linux_entries,
        )

    def test_packaging_sources_never_reference_user_state(self):
        self.assertEqual([], user_state_references())

    def test_generated_python_caches_are_skipped_but_normal_files_are_scanned(self):
        forbidden = ".devcode" + "/object-storage-client"
        cache_fixture = LINUX / "contract-sabotage.pyo"
        text_fixture = LINUX / "contract-sabotage.txt"
        try:
            cache_fixture.write_text(forbidden, encoding="utf-8")
            self.assertNotIn(cache_fixture, user_state_references())

            text_fixture.write_text(forbidden, encoding="utf-8")
            self.assertIn(text_fixture, user_state_references())
        finally:
            cache_fixture.unlink(missing_ok=True)
            text_fixture.unlink(missing_ok=True)

    def test_readmes_document_native_linux_package_management(self):
        data_delete_marker = "rm -rf ~/.devcode" + "/object-storage-client"
        exact_markers = (
            "https://devcode-kr.github.io/object-storage-client/apt",
            "https://devcode-kr.github.io/object-storage-client/rpm/stable/x86_64",
            "https://devcode-kr.github.io/object-storage-client/repository-key.asc",
            "signed-by=/etc/apt/keyrings/object-storage-client.gpg",
            "gpgcheck=1",
            "repo_gpgcheck=1",
            "gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-object-storage-client",
            "843B0BB9F1A4488C8C7B60133F8AC712C8C56B90",
            "sudo apt install object-storage-client",
            "sudo dnf install object-storage-client",
            "sudo apt update && sudo apt upgrade",
            "sudo dnf upgrade",
            "sudo apt remove object-storage-client",
            "sudo dnf remove object-storage-client",
            data_delete_marker,
            "Debian 12+",
            "Ubuntu 22.04+",
            "Fedora 44",
            "Fedora 43",
            "Rocky Linux 9",
            "AlmaLinux 9",
            "RHEL 9",
            "x86-64",
            "X11",
            "XWayland",
            "tar.gz",
        )
        language_markers = {
            "README.md": (
                ("앱 자체 업데이트 기능은 없다", "앱은 스스로 업데이트하지 않는다"),
                ("RHEL 9 수동 검증", "RHEL 9에서 수동으로 검증"),
            ),
            "README.en.md": (
                ("The app does not update itself", "The application does not self-update"),
                ("manual RHEL 9 validation", "manually validated on RHEL 9"),
            ),
        }

        for name, alternatives in language_markers.items():
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(readme=name):
                for marker in exact_markers:
                    self.assertIn(marker, text)
                for accepted in alternatives:
                    self.assertTrue(
                        any(marker in text for marker in accepted),
                        f"{name} must contain one of {accepted!r}",
                    )

                package_remove = min(
                    text.index("sudo apt remove object-storage-client"),
                    text.index("sudo dnf remove object-storage-client"),
                )
                data_delete = text.index(data_delete_marker)
                self.assertLess(package_remove, data_delete)

                lowered = text.lower()
                for forbidden in (
                    "trusted=yes",
                    "--nogpgcheck",
                    "setenforce 0",
                    "setenforce=0",
                    "curl |",
                    "curl|",
                    "--no-check-certificate",
                ):
                    self.assertNotIn(forbidden, lowered)

    def test_signing_policies_document_linux_repository_trust(self):
        exact_markers = (
            "InRelease",
            "Release.gpg",
            "RPM",
            "repomd.xml.asc",
            "SHA256SUMS.txt",
            "https://devcode-kr.github.io/object-storage-client/repository-key.asc",
            "843B0BB9F1A4488C8C7B60133F8AC712C8C56B90",
            "2029-08-22",
            "3 years",
            "GitHub Secrets",
            "/workspace/hermes_home/secure/object-storage-client-linux-repository/",
            "Microsoft Store",
            "GitHub Pages",
        )
        language_markers = {
            "CODE_SIGNING_POLICY.md": (
                ("RPM 패키지 서명", "RPM 패키지를 서명"),
                ("이전 키와 새 키", "기존 키와 새 키"),
                ("겹치는 기간", "중첩 기간"),
                ("태그",),
                ("PR",),
                ("임시 키", "일회용 키"),
                ("서명되지 않은 상태로 대체", "서명 없는 배포로 전환"),
                ("macOS",),
                ("tar.gz",),
            ),
            "CODE_SIGNING_POLICY.en.md": (
                ("RPM package signatures", "signs each RPM package"),
                ("old and new public keys",),
                ("overlap",),
                ("tag",),
                ("PR",),
                ("throwaway key",),
                ("no unsigned fallback", "never falls back to unsigned"),
                ("macOS",),
                ("tar.gz",),
            ),
        }

        for name, alternatives in language_markers.items():
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(policy=name):
                for marker in exact_markers:
                    self.assertIn(marker, text)
                for accepted in alternatives:
                    self.assertTrue(
                        any(marker in text for marker in accepted),
                        f"{name} must contain one of {accepted!r}",
                    )
                lowered = text.lower()
                for forbidden in (
                    "trusted=yes",
                    "--nogpgcheck",
                    "setenforce 0",
                    "setenforce=0",
                ):
                    self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
