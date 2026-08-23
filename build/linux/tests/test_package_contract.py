from __future__ import annotations

import dataclasses
import importlib.util
import pathlib
import stat
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
LINUX = ROOT / "build" / "linux"


def load_contract():
    path = LINUX / "package_contract.py"
    module_name = "_osc_linux_package_contract_test"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
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

    def test_load_contract_leaves_no_module_entry_behind(self):
        module_name = "_osc_linux_package_contract_test"
        sys.modules.pop(module_name, None)

        load_contract()

        self.assertNotIn(module_name, sys.modules)

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

        for entry in required:
            with self.subTest(entry=entry):
                self.assertEqual(1, entries.count(entry))

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
        forbidden = ".devcode" + "/object-storage-client"
        for path in LINUX.rglob("*"):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
            ):
                self.assertNotIn(
                    forbidden,
                    path.read_text(encoding="utf-8", errors="ignore"),
                    str(path.relative_to(ROOT)),
                )


if __name__ == "__main__":
    unittest.main()
