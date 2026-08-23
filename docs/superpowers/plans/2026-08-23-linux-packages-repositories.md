# Linux Packages and Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish installable `.deb` and `.rpm` packages plus signed stable APT and DNF/YUM repositories for Object Storage Client on GitHub Pages, with package-manager-managed updates and automated Linux compatibility checks.

**Architecture:** A single self-contained `linux-x64` publish payload is staged into a shared filesystem layout, then distribution-native tools produce Debian and RPM packages. Python contract helpers keep names, versions, paths, dependencies, and repository layout deterministic; shell wrappers invoke `dpkg-deb`, `rpmbuild`, `apt-ftparchive`, `createrepo_c`, GnuPG, and distro containers. Pull requests use an ephemeral signing key and publish nothing, while `v*` tags use a dedicated three-year GPG key to sign release packages and update a persistent `gh-pages` repository.

**Tech Stack:** .NET 9, Avalonia 11, Python 3 standard library, POSIX shell, `dpkg-deb`, `rpmbuild`, `apt-ftparchive`, `createrepo_c`, GnuPG, Docker, GitHub Actions, GitHub Pages.

---

## File structure

### Files to create

- `build/linux/package_contract.py` — canonical package names, paths, dependency lists, version parsing, and metadata rendering.
- `build/linux/tests/test_package_contract.py` — unit tests for version mapping, metadata, install layout, desktop entry, and security invariants.
- `build/linux/object-storage-client` — installed launcher for `/usr/bin`.
- `build/linux/object-storage-client.desktop` — Linux application-menu entry.
- `build/linux/stage_payload.py` — stages the self-contained publish output and documentation into a package root.
- `build/linux/package_deb.py` — creates a Debian package with `dpkg-deb`.
- `build/linux/object-storage-client.spec` — RPM package specification.
- `build/linux/package_rpm.py` — prepares RPM sources and invokes `rpmbuild`.
- `build/linux/tests/test_package_artifacts.py` — verifies generated `.deb` and `.rpm` metadata and payloads.
- `build/linux/repository.py` — creates APT and DNF repository metadata and signs/verifies it.
- `build/linux/tests/test_repository.py` — validates repository paths, metadata, signing gates, and public-key fingerprints.
- `build/linux/smoke-package.sh` — installs, launches, removes, and repository-installs packages inside a selected distro container.
- `build/linux/tests/test_workflow_contract.py` — checks release workflow event and publication gates.
- `build/linux/pages-index.html` — static installation landing page copied to GitHub Pages.
- `build/linux/repository-key.asc` — generated public half of the dedicated Linux repository signing key.
- `.github/workflows/linux-packages.yml` — PR/manual package and distro smoke-test workflow.
- `.github/workflows/publish-linux-repositories.yml` — tag-only signed repository publication workflow.

### Files to modify

- `.github/workflows/release.yml` — attach `.deb` and `.rpm` to tagged GitHub Releases and expose their artifact to the repository publisher.
- `README.md` — Korean APT/DNF install, update, removal, support, and fallback instructions.
- `README.en.md` — matching English instructions.
- `CODE_SIGNING_POLICY.md` — document Linux package/repository GPG signatures.
- `CODE_SIGNING_POLICY.en.md` — matching English signing policy.
- `.gitignore` — ignore local package, repository, GnuPG, and smoke-test outputs.

---

### Task 1: Define and test the Linux package contract

**Files:**
- Create: `build/linux/package_contract.py`
- Create: `build/linux/tests/test_package_contract.py`
- Create: `build/linux/object-storage-client`
- Create: `build/linux/object-storage-client.desktop`
- Modify: `.gitignore`

- [ ] **Step 1: Write failing package-contract tests**

Create `build/linux/tests/test_package_contract.py` with tests that import a not-yet-created contract module and assert the approved names, versions, dependencies, paths, desktop entry, launcher, and user-data invariant:

```python
from __future__ import annotations

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
LINUX = ROOT / "build" / "linux"


def load_contract():
    path = LINUX / "package_contract.py"
    spec = importlib.util.spec_from_file_location("package_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackageContractTests(unittest.TestCase):
    def test_package_identity_and_paths_are_stable(self):
        contract = load_contract()
        self.assertEqual("object-storage-client", contract.PACKAGE_NAME)
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

    def test_version_mapping_uses_native_package_release(self):
        contract = load_contract()
        version = contract.NativeVersion.parse("1.2.3", 4)
        self.assertEqual("1.2.3-4", version.debian)
        self.assertEqual("1.2.3", version.rpm_version)
        self.assertEqual("4", version.rpm_release)

    def test_invalid_versions_and_releases_are_rejected(self):
        contract = load_contract()
        for value in ("1.2", "v1.2.3", "1.2.3.4", "1.2.x", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    contract.NativeVersion.parse(value, 1)
        for release in (0, -1, 65536):
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
        launcher = (LINUX / "object-storage-client").read_text(encoding="utf-8")
        self.assertEqual(
            "#!/bin/sh\nexec /usr/lib/object-storage-client/ObjectStorageClient.App \"$@\"\n",
            launcher,
        )

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

    def test_packaging_sources_never_reference_user_state(self):
        forbidden = ".devcode/object-storage-client"
        for path in LINUX.glob("*"):
            if path.is_file() and path.name not in {"package_contract.py"}:
                self.assertNotIn(forbidden, path.read_text(encoding="utf-8", errors="ignore"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python3 -m unittest build/linux/tests/test_package_contract.py -v
```

Expected: FAIL because `build/linux/package_contract.py`, launcher, and desktop entry do not exist.

- [ ] **Step 3: Implement the package contract and static assets**

Create `build/linux/package_contract.py` with immutable constants and a validated version type:

```python
from __future__ import annotations

from dataclasses import dataclass
import re

PACKAGE_NAME = "object-storage-client"
PRODUCT_NAME = "Object Storage Client"
DEB_ARCH = "amd64"
RPM_ARCH = "x86_64"
APP_DIR = "/usr/lib/object-storage-client"
LAUNCHER_PATH = "/usr/bin/object-storage-client"
DESKTOP_PATH = "/usr/share/applications/object-storage-client.desktop"
ICON_PATH = "/usr/share/icons/hicolor/256x256/apps/object-storage-client.png"
DOC_DIR = "/usr/share/doc/object-storage-client"

DEB_DEPENDENCIES = (
    "libx11-6",
    "libice6",
    "libsm6",
    "libfontconfig1",
    "ca-certificates",
)
RPM_DEPENDENCIES = (
    "libX11",
    "libICE",
    "libSM",
    "fontconfig",
    "ca-certificates",
)

_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


@dataclass(frozen=True)
class NativeVersion:
    application: str
    package_release: int

    @classmethod
    def parse(cls, application: str, package_release: int) -> "NativeVersion":
        if not _VERSION.fullmatch(application):
            raise ValueError(f"application version must be Major.Minor.Patch: {application!r}")
        if package_release < 1 or package_release > 65535:
            raise ValueError("package release must be between 1 and 65535")
        return cls(application, package_release)

    @property
    def debian(self) -> str:
        return f"{self.application}-{self.package_release}"

    @property
    def rpm_version(self) -> str:
        return self.application

    @property
    def rpm_release(self) -> str:
        return str(self.package_release)
```

Create executable `build/linux/object-storage-client`:

```sh
#!/bin/sh
exec /usr/lib/object-storage-client/ObjectStorageClient.App "$@"
```

Create `build/linux/object-storage-client.desktop`:

```ini
[Desktop Entry]
Name=Object Storage Client
Comment=Browse and transfer files in S3-compatible object storage
Exec=object-storage-client
Icon=object-storage-client
Type=Application
Categories=Network;FileTransfer;
Terminal=false
```

Append these local-output patterns to `.gitignore`:

```gitignore
artifacts/linux-packages/
obj/linux-packages/
obj/linux-repositories/
obj/linux-smoke/
obj/gnupg-test/
```

- [ ] **Step 4: Run contract tests and verify GREEN**

Run:

```bash
chmod +x build/linux/object-storage-client
python3 -m unittest build/linux/tests/test_package_contract.py -v
```

Expected: all package-contract tests PASS.

- [ ] **Step 5: Commit the package contract**

```bash
git add .gitignore build/linux/package_contract.py build/linux/tests/test_package_contract.py \
  build/linux/object-storage-client build/linux/object-storage-client.desktop
git commit -m "build: define Linux package contract"
```

---

### Task 2: Stage the payload and build a Debian package

**Files:**
- Create: `build/linux/stage_payload.py`
- Create: `build/linux/package_deb.py`
- Create: `build/linux/tests/test_package_artifacts.py`
- Test: `build/linux/tests/test_package_artifacts.py`

- [ ] **Step 1: Write failing staging and Debian metadata tests**

Create `build/linux/tests/test_package_artifacts.py` with unit tests that build a small fake publish tree and exercise the desired Python APIs without requiring .NET:

```python
from __future__ import annotations

import pathlib
import stat
import tempfile
import unittest

from build.linux.package_contract import NativeVersion
from build.linux.package_deb import render_control
from build.linux.stage_payload import stage_payload

ROOT = pathlib.Path(__file__).resolve().parents[3]


class PackageArtifactTests(unittest.TestCase):
    def test_stage_payload_installs_application_launcher_desktop_icon_and_docs(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp = pathlib.Path(temporary)
            publish = temp / "publish"
            root = temp / "root"
            publish.mkdir()
            executable = publish / "ObjectStorageClient.App"
            executable.write_bytes(b"app")
            executable.chmod(0o755)
            (publish / "ObjectStorageClient.App.dll").write_bytes(b"dll")

            stage_payload(ROOT, publish, root)

            self.assertEqual(b"app", (root / "usr/lib/object-storage-client/ObjectStorageClient.App").read_bytes())
            self.assertEqual(b"dll", (root / "usr/lib/object-storage-client/ObjectStorageClient.App.dll").read_bytes())
            self.assertTrue((root / "usr/bin/object-storage-client").stat().st_mode & stat.S_IXUSR)
            self.assertTrue((root / "usr/share/applications/object-storage-client.desktop").is_file())
            self.assertEqual(
                (ROOT / "src/ObjectStorageClient.App/Assets/appicon.png").read_bytes(),
                (root / "usr/share/icons/hicolor/256x256/apps/object-storage-client.png").read_bytes(),
            )
            for name in ("README.md", "PRIVACY.md", "LICENSE"):
                self.assertTrue((root / "usr/share/doc/object-storage-client" / name).is_file())

    def test_stage_payload_rejects_missing_or_non_executable_apphost(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp = pathlib.Path(temporary)
            publish = temp / "publish"
            publish.mkdir()
            with self.assertRaises(FileNotFoundError):
                stage_payload(ROOT, publish, temp / "missing")
            apphost = publish / "ObjectStorageClient.App"
            apphost.write_bytes(b"app")
            apphost.chmod(0o644)
            with self.assertRaises(PermissionError):
                stage_payload(ROOT, publish, temp / "not-executable")

    def test_debian_control_has_exact_metadata(self):
        control = render_control(NativeVersion.parse("1.2.3", 4), installed_size_kib=50000)
        self.assertIn("Package: object-storage-client\n", control)
        self.assertIn("Version: 1.2.3-4\n", control)
        self.assertIn("Architecture: amd64\n", control)
        self.assertIn("Installed-Size: 50000\n", control)
        self.assertIn(
            "Depends: libx11-6, libice6, libsm6, libfontconfig1, ca-certificates\n",
            control,
        )
        self.assertNotIn(".devcode", control)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python3 -m unittest build/linux/tests/test_package_artifacts.py -v
```

Expected: import errors because `stage_payload.py` and `package_deb.py` do not exist.

- [ ] **Step 3: Implement shared payload staging**

Create `build/linux/stage_payload.py` with `stage_payload(repo_root, publish_dir, package_root)`. It must:

```python
from __future__ import annotations

import pathlib
import shutil
import stat

from build.linux import package_contract as contract


def _destination(root: pathlib.Path, absolute_path: str) -> pathlib.Path:
    return root / absolute_path.removeprefix("/")


def stage_payload(repo_root: pathlib.Path, publish_dir: pathlib.Path, package_root: pathlib.Path) -> None:
    apphost = publish_dir / "ObjectStorageClient.App"
    if not apphost.is_file():
        raise FileNotFoundError(f"missing published apphost: {apphost}")
    if not apphost.stat().st_mode & stat.S_IXUSR:
        raise PermissionError(f"published apphost is not executable: {apphost}")

    if package_root.exists():
        shutil.rmtree(package_root)
    app_dir = _destination(package_root, contract.APP_DIR)
    app_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(publish_dir, app_dir)

    launcher = _destination(package_root, contract.LAUNCHER_PATH)
    launcher.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "build/linux/object-storage-client", launcher)
    launcher.chmod(0o755)

    desktop = _destination(package_root, contract.DESKTOP_PATH)
    desktop.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "build/linux/object-storage-client.desktop", desktop)

    icon = _destination(package_root, contract.ICON_PATH)
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "src/ObjectStorageClient.App/Assets/appicon.png", icon)

    doc_dir = _destination(package_root, contract.DOC_DIR)
    doc_dir.mkdir(parents=True, exist_ok=True)
    for name in ("README.md", "PRIVACY.md", "LICENSE"):
        shutil.copy2(repo_root / name, doc_dir / name)
```

- [ ] **Step 4: Implement Debian metadata and package creation**

Create `build/linux/package_deb.py` with:

- `render_control(version, installed_size_kib)` returning exact Debian metadata;
- CLI arguments `--version`, `--release`, `--publish-dir`, `--output-dir`;
- staging under `obj/linux-packages/deb/root`;
- `DEBIAN/control` mode `0644`;
- `dpkg-deb --root-owner-group --build` invocation;
- output `ObjectStorageClient-{version}-{release}-linux-x64.deb`;
- failure if `dpkg-deb` is unavailable or output is missing.

The rendered control body must be:

```text
Package: object-storage-client
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
```

Calculate installed size as the ceiling of total staged regular-file bytes divided by 1024. Invoke native tooling with `subprocess.run(..., check=True)` and no shell interpolation.

- [ ] **Step 5: Run unit tests and build a real Debian package in a Debian container**

Run locally available tests:

```bash
python3 -m unittest build/linux/tests/test_package_contract.py build/linux/tests/test_package_artifacts.py -v
```

Expected: PASS.

Run on a GitHub runner or Docker-capable host:

```bash
docker run --rm -v "$PWD:/src" -w /src debian:12 bash -eu -c '
  apt-get update -qq
  apt-get install -y -qq python3 dpkg-dev >/dev/null
  python3 build/linux/package_deb.py \
    --version 1.0.0 \
    --release 1 \
    --publish-dir artifacts/publish/linux-x64 \
    --output-dir artifacts/linux-packages
  dpkg-deb --info artifacts/linux-packages/ObjectStorageClient-1.0.0-1-linux-x64.deb
  dpkg-deb --contents artifacts/linux-packages/ObjectStorageClient-1.0.0-1-linux-x64.deb
'
```

Expected: package metadata reports `object-storage-client`, version `1.0.0-1`, architecture `amd64`, and every approved installed path.

- [ ] **Step 6: Commit Debian packaging**

```bash
git add build/linux/stage_payload.py build/linux/package_deb.py build/linux/tests/test_package_artifacts.py
git commit -m "build: create Debian package"
```

---

### Task 3: Build and verify the RPM package

**Files:**
- Create: `build/linux/object-storage-client.spec`
- Create: `build/linux/package_rpm.py`
- Modify: `build/linux/tests/test_package_artifacts.py`

- [ ] **Step 1: Add failing RPM rendering tests**

Extend `test_package_artifacts.py` to import `render_spec` from `package_rpm.py` and assert:

```python
    def test_rpm_spec_has_exact_metadata_and_paths(self):
        from build.linux.package_rpm import render_spec

        spec = render_spec(NativeVersion.parse("1.2.3", 4), "payload.tar.gz")
        self.assertIn("Name: object-storage-client\n", spec)
        self.assertIn("Version: 1.2.3\n", spec)
        self.assertIn("Release: 4%{?dist}\n", spec)
        self.assertIn("BuildArch: x86_64\n", spec)
        for dependency in ("libX11", "libICE", "libSM", "fontconfig", "ca-certificates"):
            self.assertIn(f"Requires: {dependency}\n", spec)
        self.assertIn("/usr/bin/object-storage-client\n", spec)
        self.assertIn("/usr/share/applications/object-storage-client.desktop\n", spec)
        self.assertIn("/usr/share/icons/hicolor/256x256/apps/object-storage-client.png\n", spec)
        self.assertNotIn(".devcode", spec)
```

- [ ] **Step 2: Run the test and verify RED**

```bash
python3 -m unittest build/linux/tests/test_package_artifacts.py -v
```

Expected: FAIL because `package_rpm.py` does not exist.

- [ ] **Step 3: Create the RPM spec template**

Create `build/linux/object-storage-client.spec` with placeholders `@VERSION@`, `@RELEASE@`, and `@SOURCE@`. The spec must unpack a tar archive containing the final filesystem root and copy it into `%{buildroot}`. It must list the exact package-owned paths, use `%license` for LICENSE and `%doc` for README/PRIVACY, and contain no `%pre`, `%post`, `%preun`, or `%postun` scriptlets.

Required header and files sections:

```spec
Name: object-storage-client
Version: @VERSION@
Release: @RELEASE@%{?dist}
Summary: Desktop client for S3-compatible object storage
License: MIT
URL: https://github.com/devcode-kr/object-storage-client
Source0: @SOURCE@
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
```

- [ ] **Step 4: Implement RPM package creation**

Create `build/linux/package_rpm.py` with:

- `render_spec(version, source_name)` replacing only the three approved placeholders and rejecting leftovers;
- the same CLI arguments as Debian packaging;
- shared `stage_payload` use;
- deterministic `tar.gz` creation from the package root, with sorted paths, uid/gid zero, empty owner/group names, and `mtime` from `SOURCE_DATE_EPOCH` or zero;
- isolated `_topdir` under `obj/linux-packages/rpm`;
- `rpmbuild -bb --define _topdir ...` invocation;
- copy of exactly one resulting x86-64 RPM to `ObjectStorageClient-{version}-{release}-linux-x64.rpm`;
- failure on missing tools, placeholder remnants, multiple RPMs, or absent output.

- [ ] **Step 5: Run unit tests and build a real RPM in Fedora**

```bash
python3 -m unittest build/linux/tests/test_package_artifacts.py -v
```

Expected: PASS.

On a Docker-capable host:

```bash
docker run --rm -v "$PWD:/src" -w /src fedora:44 bash -eu -c '
  dnf install -y -q python3 rpm-build tar gzip >/dev/null
  python3 build/linux/package_rpm.py \
    --version 1.0.0 \
    --release 1 \
    --publish-dir artifacts/publish/linux-x64 \
    --output-dir artifacts/linux-packages
  rpm -qip artifacts/linux-packages/ObjectStorageClient-1.0.0-1-linux-x64.rpm
  rpm -qlp artifacts/linux-packages/ObjectStorageClient-1.0.0-1-linux-x64.rpm
'
```

Expected: RPM metadata and files match the package contract.

- [ ] **Step 6: Commit RPM packaging**

```bash
git add build/linux/object-storage-client.spec build/linux/package_rpm.py \
  build/linux/tests/test_package_artifacts.py
git commit -m "build: create RPM package"
```

---

### Task 4: Generate, sign, and verify APT and DNF repositories

**Files:**
- Create: `build/linux/repository.py`
- Create: `build/linux/tests/test_repository.py`
- Create: `build/linux/pages-index.html`
- Create during secure provisioning: `build/linux/repository-key.asc`

- [ ] **Step 1: Write failing repository-layout and fingerprint tests**

Create `build/linux/tests/test_repository.py` with temporary fake package files and tests for these pure functions:

```python
from __future__ import annotations

import pathlib
import tempfile
import unittest

from build.linux.repository import (
    apt_paths,
    normalize_fingerprint,
    rpm_paths,
    verify_public_key_fingerprint,
)


class RepositoryTests(unittest.TestCase):
    def test_apt_paths_are_stable_only(self):
        root = pathlib.Path("site")
        paths = apt_paths(root)
        self.assertEqual(root / "apt/pool/main/o/object-storage-client", paths.pool)
        self.assertEqual(root / "apt/dists/stable/main/binary-amd64", paths.binary)
        self.assertEqual(root / "apt/dists/stable", paths.release)

    def test_rpm_paths_are_stable_x86_64_only(self):
        root = pathlib.Path("site")
        paths = rpm_paths(root)
        self.assertEqual(root / "rpm/stable/x86_64", paths.packages)
        self.assertEqual(root / "rpm/stable/x86_64/repodata", paths.repodata)

    def test_fingerprint_normalization_rejects_short_or_non_hex_values(self):
        self.assertEqual(
            "0123456789ABCDEF0123456789ABCDEF01234567",
            normalize_fingerprint("0123 4567 89ab cdef 0123 4567 89ab cdef 0123 4567"),
        )
        for value in ("DEADBEEF", "", "not-a-key", "0" * 39, "0" * 41):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_fingerprint(value)

    def test_public_key_must_match_expected_fingerprint(self):
        with tempfile.TemporaryDirectory() as temporary:
            public_key = pathlib.Path(temporary) / "repository-key.asc"
            public_key.write_text("not a key", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                verify_public_key_fingerprint(public_key, "0" * 40)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify RED**

```bash
python3 -m unittest build/linux/tests/test_repository.py -v
```

Expected: import failure because `repository.py` does not exist.

- [ ] **Step 3: Implement repository paths and key verification**

Create `build/linux/repository.py` with frozen dataclasses for APT and RPM paths, exact 40-hex fingerprint normalization, and GPG public-key inspection using an ephemeral `GNUPGHOME` plus `gpg --with-colons --import-options show-only --import`. Parse the first `fpr` record and require exact equality.

The CLI must accept:

```text
--site-dir
--deb
--rpm
--public-key
--expected-fingerprint
--private-key
--passphrase-file
--origin
--label
--base-url
```

`--origin` and `--label` default to `Object Storage Client`; `--base-url` defaults to `https://devcode-kr.github.io/object-storage-client`.

- [ ] **Step 4: Implement APT repository generation**

The APT path must:

1. copy the `.deb` into `apt/pool/main/o/object-storage-client/` without replacing a different existing file;
2. run `apt-ftparchive packages` from the `apt` root and write `Packages`;
3. gzip `Packages` deterministically with `mtime=0`;
4. render `Release` with `Origin`, `Label`, `Suite`, `Codename`, `Architectures`, `Components`, `Description`, and apt-generated hashes;
5. create armored `InRelease` and `Release.gpg` signatures using batch/loopback mode and the passphrase file;
6. verify both signatures with a clean keyring containing only `repository-key.asc`.

- [ ] **Step 5: Implement RPM repository generation**

The RPM path must:

1. copy the RPM into `rpm/stable/x86_64/` without replacing a different existing file;
2. sign the package with `rpmsign --addsign` using the imported private key;
3. verify the package signature with an RPM key database containing only the committed public key;
4. run `createrepo_c --update` on `rpm/stable/x86_64`;
5. create armored `repodata/repomd.xml.asc`;
6. verify the detached metadata signature with a clean GPG keyring.

The function must abort rather than publish unsigned output on every missing tool, missing key, wrong fingerprint, expired key, signature error, or verification error.

- [ ] **Step 6: Add the Pages installation index**

Create `build/linux/pages-index.html` as a small static page containing exact APT and DNF setup commands, links to `repository-key.asc`, GitHub Releases, `PRIVACY.md`, source, and issues. The page must not use JavaScript or third-party assets.

- [ ] **Step 7: Provision the dedicated deployment key without exposing it**

From the controller session, not a subagent transcript:

1. Create `/workspace/hermes_home/secure/object-storage-client-linux-repository/` with mode `0700`.
2. Generate a random 48-byte base64 passphrase into `passphrase` with mode `0600`.
3. Create a private `GNUPGHOME` under the secure directory with mode `0700`.
4. Generate RSA 4096 signing-only key identity `Object Storage Client Linux Repository <devcode-kr@users.noreply.github.com>` with expiry `3y` using batch/loopback mode.
5. Export the armored public key to `build/linux/repository-key.asc`.
6. Export the encrypted armored private key to secure `private-key.asc` mode `0600`.
7. Derive the full fingerprint programmatically from `gpg --with-colons`; never print key material or passphrase.
8. Set GitHub Secrets from files:

```bash
GH_CONFIG_DIR=/workspace/hermes_home/gh gh secret set LINUX_REPO_GPG_PRIVATE_KEY \
  -R devcode-kr/object-storage-client < /workspace/hermes_home/secure/object-storage-client-linux-repository/private-key.asc
GH_CONFIG_DIR=/workspace/hermes_home/gh gh secret set LINUX_REPO_GPG_PASSPHRASE \
  -R devcode-kr/object-storage-client < /workspace/hermes_home/secure/object-storage-client-linux-repository/passphrase
```

9. Set `LINUX_REPO_GPG_FINGERPRINT` with `gh variable set --body "$fingerprint"` without logging it as a secret; fingerprint is public metadata.
10. Read back only Secret names, variable name, public-key fingerprint, file modes, and expiry.

- [ ] **Step 8: Run repository tests with a throwaway key**

Use a temporary key identity `Object Storage Client CI <ci@example.invalid>`, expiry one day, then run:

```bash
python3 -m unittest build/linux/tests/test_repository.py -v
python3 build/linux/repository.py \
  --site-dir obj/linux-repositories/site \
  --deb artifacts/linux-packages/ObjectStorageClient-1.0.0-1-linux-x64.deb \
  --rpm artifacts/linux-packages/ObjectStorageClient-1.0.0-1-linux-x64.rpm \
  --public-key obj/gnupg-test/public.asc \
  --expected-fingerprint "$CI_GPG_FINGERPRINT" \
  --private-key obj/gnupg-test/private.asc \
  --passphrase-file obj/gnupg-test/passphrase
```

Expected: signed APT and DNF repository trees are generated and all signatures verify.

- [ ] **Step 9: Commit repository generation and public key**

```bash
git add build/linux/repository.py build/linux/tests/test_repository.py \
  build/linux/pages-index.html build/linux/repository-key.asc
git commit -m "build: generate signed Linux repositories"
```

---

### Task 5: Add cross-distribution package and repository smoke tests

**Files:**
- Create: `build/linux/smoke-package.sh`
- Modify: `build/linux/tests/test_package_artifacts.py`

- [ ] **Step 1: Add failing smoke-script contract tests**

Extend `test_package_artifacts.py` to read `smoke-package.sh` and require:

```python
    def test_smoke_script_covers_install_launch_remove_and_repository_install(self):
        script = (ROOT / "build/linux/smoke-package.sh").read_text(encoding="utf-8")
        for marker in (
            "install_local_package",
            "validate_installed_files",
            "launch_under_xvfb",
            "preserve_user_fixture_on_remove",
            "install_from_repository",
        ):
            self.assertIn(f"{marker}()", script)
        self.assertNotIn("--nogpgcheck", script)
        self.assertNotIn("trusted=yes", script)
        self.assertNotIn("setenforce 0", script)
```

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest build/linux/tests/test_package_artifacts.py -v
```

Expected: FAIL because `smoke-package.sh` does not exist.

- [ ] **Step 3: Implement the smoke-test entrypoint**

Create executable `build/linux/smoke-package.sh`. It accepts:

```text
smoke-package.sh deb /packages/package.deb /repository
smoke-package.sh rpm /packages/package.rpm /repository
```

It must use `set -eu`, define the five tested functions, and:

- install desktop runtime dependencies, Xvfb, desktop-file-utils, curl, and GPG tools using the container's package manager;
- create `/root/.devcode/object-storage-client/preserve-me` before package installation;
- install the local package through `apt-get install /packages/*.deb` or `dnf install /packages/*.rpm`;
- validate all approved files and executable modes;
- run `desktop-file-validate`;
- start Xvfb on `:99`, launch `/usr/bin/object-storage-client`, wait 15 seconds, fail if it exited, then stop it;
- remove the package through apt/dnf;
- assert package-owned files are gone and `preserve-me` remains;
- trust only the supplied repository public key;
- configure the local HTTP-served repository with signature checking enabled;
- install `object-storage-client` by package name;
- query and print only installed package name/version/architecture.

- [ ] **Step 4: Execute the distro matrix**

Run the same built packages and local repository against:

```text
debian:12
ubuntu:22.04
ubuntu:24.04
fedora:44
fedora:43
rockylinux:9
almalinux:9
```

Use an isolated Docker network and a `python:3-alpine` HTTP server container for repository content. Expected: every container installs, validates, stays running for 15 seconds under Xvfb, removes without deleting the fixture, and installs again from the signed repository.

- [ ] **Step 5: Commit smoke testing**

```bash
git add build/linux/smoke-package.sh build/linux/tests/test_package_artifacts.py
git commit -m "test: smoke Linux packages across distributions"
```

---

### Task 6: Integrate package validation and tag-only publication into GitHub Actions

**Files:**
- Create: `.github/workflows/linux-packages.yml`
- Create: `.github/workflows/publish-linux-repositories.yml`
- Create: `build/linux/tests/test_workflow_contract.py`
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Write failing workflow contract tests**

Create `build/linux/tests/test_workflow_contract.py` using `yaml.safe_load` when PyYAML is available in CI, with a fallback textual parser for local stdlib runs. It must assert:

- `linux-packages.yml` runs on `pull_request` and `workflow_dispatch`, but has no `contents: write` or `pages: write` permission;
- validation uses a throwaway key and never references deployment secrets;
- the distro matrix lists the seven approved container images exactly;
- `publish-linux-repositories.yml` is callable only from a successful tag release path and has `contents: write` plus `pages: write` only where needed;
- publication references all three configured GPG values;
- manual dispatch and pull requests cannot push `gh-pages`;
- `release.yml` attaches `.deb` and `.rpm` in addition to tar/macOS artifacts;
- no workflow uses `trusted=yes`, `--nogpgcheck`, or prints secret environment values.

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest build/linux/tests/test_workflow_contract.py -v
```

Expected: FAIL because both workflows and release integration are absent.

- [ ] **Step 3: Add the package validation workflow**

Create `.github/workflows/linux-packages.yml` with:

1. checkout and .NET setup;
2. `dotnet test ObjectStorageClient.sln --configuration Release --nologo`;
3. one `dotnet publish` to `artifacts/publish/linux-x64`;
4. Debian packaging in `debian:12`;
5. RPM packaging in `fedora:44`;
6. disposable GPG key generation and signed local repository creation;
7. a matrix job for the seven approved containers invoking `smoke-package.sh`;
8. artifact upload for `.deb`, `.rpm`, repository tree, and contract-test logs;
9. no release, branch push, Pages deployment, or deployment secrets.

Pin every third-party action to a verified immutable 40-character commit SHA rather than a mutable tag.

- [ ] **Step 4: Extend the existing release workflow**

Modify `.github/workflows/release.yml` so tagged releases wait for native package validation, download the `.deb` and `.rpm`, include them in checksums, and attach them to the GitHub Release. Manual runs continue to upload artifacts without creating a release. Preserve the existing Microsoft Store MSIX behavior and macOS/Linux tar artifacts.

- [ ] **Step 5: Add tag-only repository publication**

Create `.github/workflows/publish-linux-repositories.yml` as a reusable workflow called by the tagged release workflow after GitHub Release success. It must:

- require the `.deb` and `.rpm` artifact plus version and release inputs;
- import `LINUX_REPO_GPG_PRIVATE_KEY` and passphrase into an ephemeral keyring;
- verify `LINUX_REPO_GPG_FINGERPRINT` against the imported private key and committed public key;
- check out or initialize `gh-pages` without discarding old packages;
- generate and verify signed metadata;
- commit only the Pages tree with message `Publish Linux packages {version}-{release}`;
- push `gh-pages` using the repository token;
- wait for Pages and read back public indexes, packages, and signatures;
- fail without fallback on every secret/signature/publication/read-back error.

- [ ] **Step 6: Run workflow tests and YAML validation**

```bash
python3 -m unittest build/linux/tests/test_workflow_contract.py -v
python3 - <<'PY'
from pathlib import Path
import yaml
for path in Path('.github/workflows').glob('*.yml'):
    yaml.safe_load(path.read_text(encoding='utf-8'))
    print(f'valid: {path}')
PY
```

Expected: all workflow contract tests PASS and every workflow parses.

- [ ] **Step 7: Commit workflow integration**

```bash
git add .github/workflows/linux-packages.yml \
  .github/workflows/publish-linux-repositories.yml \
  .github/workflows/release.yml \
  build/linux/tests/test_workflow_contract.py
git commit -m "ci: publish signed Linux packages"
```

---

### Task 7: Document installation, updates, signatures, and support

**Files:**
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `CODE_SIGNING_POLICY.md`
- Modify: `CODE_SIGNING_POLICY.en.md`
- Modify: `build/linux/tests/test_package_contract.py`

- [ ] **Step 1: Add failing documentation contract tests**

Extend `test_package_contract.py` to assert both READMEs contain:

- GitHub Pages APT and DNF base URLs;
- `signed-by=/etc/apt/keyrings/object-storage-client.gpg`;
- `gpgcheck=1` and `repo_gpgcheck=1`;
- `sudo apt update && sudo apt upgrade` and `sudo dnf upgrade`;
- package removal and optional user-data deletion as separate actions;
- Debian 12+, Ubuntu 22.04+, Fedora 44/43, Rocky/Alma/RHEL 9, x86-64, X11/XWayland;
- explicit statement that the application does not self-update;
- tar.gz fallback;
- no `trusted=yes`, `--nogpgcheck`, or SELinux disabling instructions.

Assert both signing-policy files describe APT metadata signatures, RPM package signatures, DNF metadata signatures, the public key URL, three-year expiry, rotation, and Microsoft Store's separate signing path.

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest build/linux/tests/test_package_contract.py -v
```

Expected: FAIL because native repository documentation is absent.

- [ ] **Step 3: Write Korean documentation**

Update `README.md` with copy-pasteable one-time repository setup, install, update, remove, complete-data-delete, supported systems, XWayland/font notes, manual RHEL gate, and tar fallback. Use the exact URLs and commands from the approved design.

Update `CODE_SIGNING_POLICY.md` to explain:

- Microsoft signs Store MSIX packages;
- the project GPG key signs APT Release metadata, RPM packages, and DNF repomd metadata;
- users verify through package-manager configuration;
- key fingerprint and expiry are public;
- private key is stored only in GitHub Secrets and restricted persistent recovery storage;
- key rotation overlaps public keys before switching metadata signatures.

- [ ] **Step 4: Write matching English documentation**

Apply the same factual contract to `README.en.md` and `CODE_SIGNING_POLICY.en.md`, without adding unsupported platforms or different commands.

- [ ] **Step 5: Run documentation tests and link checks**

```bash
python3 -m unittest build/linux/tests/test_package_contract.py -v
python3 - <<'PY'
from pathlib import Path
for name in ('README.md', 'README.en.md', 'CODE_SIGNING_POLICY.md', 'CODE_SIGNING_POLICY.en.md'):
    text = Path(name).read_text(encoding='utf-8')
    assert 'trusted=yes' not in text
    assert '--nogpgcheck' not in text
    assert 'setenforce 0' not in text
    print(f'policy-safe: {name}')
PY
```

Expected: PASS.

- [ ] **Step 6: Commit documentation**

```bash
git add README.md README.en.md CODE_SIGNING_POLICY.md CODE_SIGNING_POLICY.en.md \
  build/linux/tests/test_package_contract.py
git commit -m "docs: add native Linux installation"
```

---

### Task 8: Run full verification, code review, and open the PR

**Files:**
- Verify all changed files
- No new production files unless a review finding requires a tested correction

- [ ] **Step 1: Run all local contract tests**

```bash
python3 -m unittest discover -s build/linux/tests -p 'test_*.py' -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run the existing .NET quality gates**

```bash
dotnet restore ObjectStorageClient.sln
dotnet build ObjectStorageClient.sln --configuration Release --no-restore --nologo
dotnet test ObjectStorageClient.sln --configuration Release --no-build --nologo
```

Expected: restore/build PASS and all existing tests PASS with zero warnings. If the local Pod still lacks .NET, install the SDK under `/workspace/.dotnet` using the official installer without changing system packages, then rerun these exact commands.

- [ ] **Step 3: Run real package, repository, and distro tests**

Execute `.github/workflows/linux-packages.yml` from the feature branch through a pull request or equivalent branch CI. Verify:

- `.deb` and `.rpm` artifacts exist;
- both package metadata inspections pass;
- ephemeral signatures verify;
- all seven public container jobs pass;
- no publication job runs;
- no secret is printed;
- source tree remains clean after local tests.

- [ ] **Step 4: Run security and diff checks**

```bash
git diff --check origin/main...HEAD
git status --short
git diff --name-status origin/main...HEAD
python3 - <<'PY'
from pathlib import Path
patterns = ('BEGIN PGP PRIVATE KEY BLOCK', 'LINUX_REPO_GPG_PASSPHRASE=', 'trusted=yes', '--nogpgcheck')
for path in Path('.').rglob('*'):
    if not path.is_file() or '.git' in path.parts or '.worktrees' in path.parts:
        continue
    text = path.read_text(encoding='utf-8', errors='ignore')
    for pattern in patterns:
        if pattern in text and path.as_posix() != 'build/linux/tests/test_workflow_contract.py':
            raise SystemExit(f'forbidden pattern {pattern!r} in {path}')
print('secret and unsafe-repository scan passed')
PY
```

Expected: no whitespace errors, no unexpected files, no private key, no passphrase assignment, and no signature bypass instructions.

- [ ] **Step 5: Request spec compliance review**

Dispatch a fresh reviewer with the complete design and diff. Require explicit confirmation that every package path, distro, signature, update, publication, security, and manual RHEL requirement is met and that no extra behavior was added. Fix findings with failing tests first and re-review until approved.

- [ ] **Step 6: Request code quality review**

After spec approval, dispatch a separate reviewer for Python/shell safety, deterministic packaging, subprocess handling, workflow permissions, secret masking, repository immutability, and maintainability. Fix findings with tests and re-review until approved.

- [ ] **Step 7: Push and open the PR**

```bash
git push -u origin feat/linux-package-repositories
GH_CONFIG_DIR=/workspace/hermes_home/gh gh pr create \
  --repo devcode-kr/object-storage-client \
  --base main \
  --head feat/linux-package-repositories \
  --title "build: publish signed Linux packages" \
  --body "## Summary
- add native Debian and RPM packages with desktop integration
- publish signed stable APT and DNF repositories through GitHub Pages
- validate supported Debian, Ubuntu, Fedora, Rocky, and Alma environments
- leave updates to apt/dnf and preserve user configuration on removal

## Verification
- Python package and repository contract tests
- existing .NET build and test suite
- signed local repository install tests
- seven-distribution container smoke matrix
- secret and unsafe-repository scan

## Manual release gate
- validate the signed RPM on a subscribed RHEL 9 desktop before the first public tag
- GitHub Pages publication remains tag-only" 
```

- [ ] **Step 8: Verify the PR and live CI**

Read the PR back and verify base, head, commits, changed files, workflow permissions, and checks. Inspect failed logs rather than rerunning blindly. Report CI honestly, distinguishing local verification, public-container CI, and the pending manual RHEL gate.

- [ ] **Step 9: Do not publish `v1.0.0` yet**

The PR may be merged only after review and CI. The first tag remains blocked until:

- Microsoft Store status/launch timing is decided;
- actual RHEL 9 GUI/S3 QA is complete;
- GitHub Pages is configured for the `gh-pages` branch;
- dedicated GPG Secret names and fingerprint variable are verified;
- public key and secure recovery backup are read back;
- the user explicitly approves the release.
