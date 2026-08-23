from __future__ import annotations

import dataclasses
import datetime as dt
import gzip
import hashlib
import html
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
from typing import Any
import unittest
from unittest import mock

import build.linux.repository as repository_module
from build.linux.repository import (
    AptPaths,
    PublicKeyInfo,
    RpmPaths,
    SigningKeyRecord,
    apt_paths,
    build_apt_repository,
    build_rpm_repository,
    build_parser,
    inspect_public_key,
    normalize_fingerprint,
    rpm_paths,
    verify_public_key_fingerprint,
    _publish_repodata,
    _verify_rpm_packages,
    _validate_packages,
    _validsig_primary_fingerprints,
)

ROOT = pathlib.Path(__file__).resolve().parents[3]
LINUX = ROOT / "build" / "linux"
EXPECTED_FINGERPRINT = "843B0BB9F1A4488C8C7B60133F8AC712C8C56B90"
BASE_URL = "https://devcode-kr.github.io/object-storage-client"


def _colon_record(
    record: str,
    *,
    validity: str = "-",
    created: int = 1_000,
    expires: int | None = 2_000,
    capabilities: str = "sc",
) -> str:
    expiry = "" if expires is None else str(expires)
    return (
        f"{record}:{validity}:2048:1:0123456789ABCDEF:{created}:{expiry}:::::"
        f"{capabilities}:"
    )


def _inspect_controlled_output(output: str) -> PublicKeyInfo:
    with tempfile.TemporaryDirectory() as temporary:
        public_key = pathlib.Path(temporary) / "controlled-public-key.asc"
        public_key.write_text("controlled public input\n", encoding="ascii")
        completed = subprocess.CompletedProcess(
            args=["gpg"], returncode=0, stdout=output, stderr=""
        )
        with mock.patch("build.linux.repository.subprocess.run", return_value=completed):
            return inspect_public_key(public_key)


def _verify_controlled_output(output: str, now: dt.datetime) -> PublicKeyInfo:
    with tempfile.TemporaryDirectory() as temporary:
        public_key = pathlib.Path(temporary) / "controlled-public-key.asc"
        public_key.write_text("controlled public input\n", encoding="ascii")
        completed = subprocess.CompletedProcess(
            args=["gpg"], returncode=0, stdout=output, stderr=""
        )
        with mock.patch("build.linux.repository.subprocess.run", return_value=completed):
            return verify_public_key_fingerprint(
                public_key, "A" * 40, now=now
            )


def _key_output(*records: str) -> str:
    return "\n".join(
        (
            _colon_record("pub", capabilities="c"),
            f"fpr:::::::::{'A' * 40}:",
            *records,
        )
    )


def _run_gpg(home: pathlib.Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["GNUPGHOME"] = os.fspath(home)
    return subprocess.run(
        ["gpg", "--batch", "--no-tty", *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


def _fake_apt_ftparchive(
    root: pathlib.Path,
    *,
    malformed_release: bool = False,
    malformed_packages: bool = False,
    release_overrides: tuple[tuple[str, str], ...] = (),
    omitted_release_fields: tuple[str, ...] = (),
    duplicate_release_fields: tuple[str, ...] = (),
) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    tool = root / "apt-ftparchive"
    release_body = "pass\n" if malformed_release else r'''
fields = {}
for item in args[:-2]:
    if item == "-o":
        continue
    if item.startswith("APT::FTPArchive::Release::"):
        key, value = item.split("=", 1)
        fields[key.rsplit("::", 1)[1]] = value
required = ("Origin", "Label", "Suite", "Codename", "Architectures", "Components", "Description", "Date", "Valid-Until")
if any(name not in fields for name in required):
    sys.exit(24)
output_fields = fields.copy()
output_fields.update(dict(RELEASE_OVERRIDES))
for name in OMITTED_RELEASE_FIELDS:
    output_fields.pop(name, None)
for name in required:
    if name in output_fields:
        print(f"{name}: {output_fields[name]}")
for name in DUPLICATE_RELEASE_FIELDS:
    print(f"{name}: {output_fields.get(name, 'duplicate')}")
algorithms = (("MD5Sum", "md5"), ("SHA1", "sha1"), ("SHA256", "sha256"), ("SHA512", "sha512"))
for section, algorithm in algorithms:
    print(f"{section}:")
    for relative in ("main/binary-amd64/Packages", "main/binary-amd64/Packages.gz"):
        path = cwd / "dists/stable" / relative
        digest = hashlib.new(algorithm, path.read_bytes()).hexdigest()
        print(f" {digest} {path.stat().st_size} {relative}")
'''
    tool.write_text(
        "#!/usr/bin/env python3\n"
        "import hashlib, os, pathlib, sys, time\n"
        f"RELEASE_OVERRIDES = {release_overrides!r}\n"
        f"OMITTED_RELEASE_FIELDS = {omitted_release_fields!r}\n"
        f"DUPLICATE_RELEASE_FIELDS = {duplicate_release_fields!r}\n"
        "args = sys.argv[1:]\n"
        "cwd = pathlib.Path.cwd()\n"
        "if args == ['packages', 'pool/main/o/object-storage-client']:\n"
        "    packages = sorted((cwd / args[1]).glob('*.deb'))\n"
        "    if not packages: sys.exit(23)\n"
        "    event_log = os.environ.get('OSC_APT_EVENT_LOG')\n"
        "    if event_log:\n"
        "        with open(event_log, 'a', encoding='utf-8') as stream:\n"
        "            stream.write('packages-start ' + ','.join(package.name for package in packages) + '\\n')\n"
        "            stream.flush(); os.fsync(stream.fileno())\n"
        "    blocked = os.environ.get('OSC_APT_BLOCK_PACKAGE')\n"
        "    if blocked and any(package.name == blocked for package in packages):\n"
        "        pathlib.Path(os.environ['OSC_APT_READY']).touch()\n"
        "        gate = pathlib.Path(os.environ['OSC_APT_GATE'])\n"
        "        while not gate.exists(): time.sleep(0.01)\n"
        "    for index, package in enumerate(packages):\n"
        "        if index: print()\n"
        "        print('Package: object-storage-client')\n"
        "        print('Architecture: amd64')\n"
        "        print(f'Filename: {package.relative_to(cwd).as_posix()}')\n"
        "        print(f'Size: {package.stat().st_size}')\n"
        "        data = package.read_bytes()\n"
        "        print(f'MD5sum: {hashlib.md5(data).hexdigest()}')\n"
        "        print(f'SHA1: {hashlib.sha1(data).hexdigest()}')\n"
        f"        print('SHA256: {'0' * 64}' if {malformed_packages!r} else f'SHA256: {{hashlib.sha256(data).hexdigest()}}')\n"
        "        print(f'SHA512: {hashlib.sha512(data).hexdigest()}')\n"
        "elif args[-2:] == ['release', 'dists/stable']:\n"
        f"{textwrap.indent(release_body, '    ')}"
        "else:\n"
        "    sys.exit(22)\n",
        encoding="utf-8",
    )
    tool.chmod(0o755)
    return tool


def _fake_rpm_tools(root: pathlib.Path, fingerprint: str) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    root.mkdir(parents=True, exist_ok=True)
    rpmsign = root / "rpmsign"
    rpmsign.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, re, shlex, subprocess, sys\n"
        f"fingerprint = {fingerprint!r}\n"
        "args = sys.argv[1:]\n"
        "major = os.environ.get('OSC_FAKE_RPM_MAJOR', '4')\n"
        "if major not in ('4', '6') or len(args) < 8 or args[-2] != '--addsign' or any(value != '--define' for value in args[:-2:2]): sys.exit(30)\n"
        "try: pairs = [value.split(' ', 1) for value in args[1:-2:2]]; defines = dict(pairs)\n"
        "except (ValueError, IndexError): sys.exit(30)\n"
        "if len(defines) != len(pairs) or not set(defines) <= {'_gpg_name', '_openpgp_sign', '_openpgp_sign_id', '_gpg_path', '_gpg_sign_cmd_extra_args'}: sys.exit(30)\n"
        "if not {'_gpg_path', '_gpg_sign_cmd_extra_args'} <= set(defines): sys.exit(30)\n"
        "if major == '4' and defines.get('_gpg_name') != fingerprint: sys.exit(30)\n"
        "if major == '6' and (defines.get('_openpgp_sign') != 'gpg' or defines.get('_openpgp_sign_id') != fingerprint): sys.exit(30)\n"
        "if '_openpgp_sign' in defines and defines['_openpgp_sign'] != 'gpg': sys.exit(30)\n"
        "if '_openpgp_sign_id' in defines and defines['_openpgp_sign_id'] != fingerprint: sys.exit(30)\n"
        "home = os.environ.get('GNUPGHOME', '')\n"
        "if defines['_gpg_path'] != home or not home: sys.exit(30)\n"
        "home_path = pathlib.Path(home)\n"
        "if home_path.is_symlink() or not home_path.is_dir(): sys.exit(30)\n"
        "if any('__gpg_sign_cmd' in value or '%{__signature_filename}' in value or '%{__plaintext_filename}' in value for value in args): sys.exit(30)\n"
        "try: extra = shlex.split(defines['_gpg_sign_cmd_extra_args'])\n"
        "except ValueError: sys.exit(30)\n"
        "if len(extra) != 8 or extra[:5] != ['--batch', '--no-tty', '--pinentry-mode', 'loopback', '--passphrase-file']: sys.exit(30)\n"
        "passphrase = pathlib.Path(extra[5])\n"
        "if passphrase.is_symlink() or not passphrase.is_file(): sys.exit(30)\n"
        "if extra[6] != '--faked-system-time' or re.fullmatch(r'[0-9]+!', extra[7]) is None: sys.exit(30)\n"
        "listing = subprocess.run(['gpg', '--batch', '--no-tty', '--homedir', home, '--with-colons', '--list-secret-keys'], capture_output=True, text=True)\n"
        "if listing.returncode != 0: sys.exit(30)\n"
        "signing_times = [int(fields[5]) for line in listing.stdout.splitlines() if len(fields := line.split(':')) > 11 and fields[0] in ('sec', 'ssb') and 's' in fields[11].lower()]\n"
        "if not signing_times or extra[7] != str(min(signing_times)) + '!': sys.exit(30)\n"
        "path = pathlib.Path(args[-1])\n"
        "if path.is_symlink() or not path.is_file(): sys.exit(30)\n"
        "if os.environ.get('OSC_RPM_SIGN_FAIL'): sys.exit(31)\n"
        "data = path.read_bytes()\n"
        "if not data.endswith(b'\\nFAKE-RPM-SIGNATURE\\n'):\n"
        "    path.write_bytes(data + b'\\nFAKE-RPM-SIGNATURE\\n')\n"
        "log = os.environ.get('OSC_RPM_TOOL_LOG')\n"
        "if log: pathlib.Path(log).write_text('rpmsign\\0' + '\\0'.join(args) + '\\n' + os.getcwd() + '\\n' + home, encoding='utf-8')\n",
        encoding="utf-8",
    )
    createrepo = root / "createrepo_c"
    createrepo.write_text(
        "#!/usr/bin/env python3\n"
        "import gzip, hashlib, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "if len(args) != 2 or args[0] != '--update': sys.exit(30)\n"
        "base = pathlib.Path(args[1])\n"
        "if base.is_symlink() or not base.is_dir(): sys.exit(30)\n"
        "if os.environ.get('OSC_RPM_METADATA_FAIL'): sys.exit(32)\n"
        "repodata = base / 'repodata'\n"
        "if repodata.exists(): sys.exit(30)\n"
        "repodata.mkdir()\n"
        "files = {}\n"
        "for kind in ('primary', 'filelists', 'other'):\n"
        "    name = kind + '.xml.gz'; data = gzip.compress(('<' + kind + '/>').encode(), mtime=0); (repodata / name).write_bytes(data); files[kind] = name\n"
        "body = ['<?xml version=\"1.0\" encoding=\"UTF-8\"?>', '<repomd xmlns=\"http://linux.duke.edu/metadata/repo\">']\n"
        "for kind, name in files.items(): body += [f'<data type=\"{kind}\"><checksum type=\"sha256\">{hashlib.sha256((repodata/name).read_bytes()).hexdigest()}</checksum><location href=\"repodata/{name}\"/></data>']\n"
        "body += ['</repomd>']; (repodata / 'repomd.xml').write_text(''.join(body), encoding='utf-8')\n",
        encoding="utf-8",
    )
    rpm = root / "rpm"
    rpm.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, subprocess, sys, tempfile\n"
        f"fingerprint = {fingerprint!r}\n"
        "args = sys.argv[1:]\n"
        "if len(args) != 4 or args[0] != '--dbpath' or args[2] not in ('--import', '--checksig'): sys.exit(30)\n"
        "db = pathlib.Path(args[1]); target = pathlib.Path(args[3])\n"
        "if db.is_symlink() or (db.exists() and not db.is_dir()): sys.exit(30)\n"
        "if target.is_symlink() or not target.is_file(): sys.exit(30)\n"
        "if args[2] == '--import':\n"
        "    with tempfile.TemporaryDirectory(prefix='fake-rpm-gpg-') as temporary:\n"
        "        home = pathlib.Path(temporary); home.chmod(0o700)\n"
        "        result = subprocess.run(['gpg', '--batch', '--no-tty', '--homedir', str(home), '--with-colons', '--import-options', 'show-only', '--dry-run', '--import', str(target)], capture_output=True, text=True)\n"
        "    if result.returncode != 0: sys.exit(36)\n"
        "    primary = []; waiting = False\n"
        "    for line in result.stdout.splitlines():\n"
        "        fields = line.split(':'); record = fields[0]\n"
        "        if record == 'pub': waiting = True\n"
        "        elif record == 'fpr' and waiting:\n"
        "            if len(fields) <= 9: sys.exit(36)\n"
        "            primary.append(fields[9]); waiting = False\n"
        "    if primary != [fingerprint]: sys.exit(36)\n"
        "    db.mkdir(parents=True, exist_ok=True)\n"
        "    (db / 'imported').write_text(fingerprint, encoding='ascii')\n"
        "    sys.exit(0)\n"
        "if os.environ.get('OSC_RPM_VERIFY_FAIL'): sys.exit(33)\n"
        "marker = db / 'imported'\n"
        "if not marker.is_file() or marker.is_symlink() or marker.read_text(encoding='ascii') != fingerprint: sys.exit(34)\n"
        "if not target.read_bytes().endswith(b'\\nFAKE-RPM-SIGNATURE\\n'): sys.exit(35)\n"
        "mode = os.environ.get('OSC_RPM_CHECKSIG_OUTPUT', 'ok')\n"
        "if mode == 'ok': print(f'{target}: digests signatures OK')\n"
        "elif mode == 'whitespace': print(f'{target}:  digests\\t signatures   OK  ')\n"
        "elif mode == 'not-ok': print(f'{target}: digests signatures NOT OK')\n"
        "elif mode == 'malformed-ok': print('wholly malformed but ending OK')\n"
        "elif mode == 'missing-signatures': print(f'{target}: digests OK')\n"
        "elif mode == 'uppercase-failures': print(f'{target}: DIGESTS SIGNATURES OK')\n"
        "elif mode == 'trailing': print(f'{target}: digests signatures OK\\ntrailing diagnostic')\n"
        "elif mode == 'wrong-package': print(f'{target}.other: digests signatures OK')\n"
        "else: sys.exit(30)\n",
        encoding="utf-8",
    )
    for tool in (rpmsign, createrepo, rpm):
        tool.chmod(0o755)
    return createrepo, rpmsign, rpm


def _page_bootstrap_blocks() -> tuple[str, str]:
    page = html.unescape((LINUX / "pages-index.html").read_text(encoding="utf-8"))
    apt = page[page.index("<h2>APT"):page.index("<h2>DNF")]
    dnf = page[page.index("<h2>DNF"):page.index("<h2>Links")]
    return apt, dnf


def _run_page_fingerprint_check(
    block: str, key_info: str
) -> subprocess.CompletedProcess[str]:
    start = block.index("fingerprint=$(awk ")
    pin = f'test "$fingerprint" = "{EXPECTED_FINGERPRINT}"'
    pin_start = block.index(pin, start)
    snippet = block[start : pin_start + len(pin)]
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        (root / "key-info").write_text(key_info, encoding="ascii")
        return subprocess.run(
            [
                "sh",
                "-c",
                f"set -eu\ntmpdir=$1\n{snippet}",
                "sh",
                os.fspath(root),
            ],
            check=False,
            capture_output=True,
            text=True,
        )


class RepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._keys = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls._keys.name)
        cls.gnupg_home = root / "gnupg"
        cls.gnupg_home.mkdir(mode=0o700)
        cls.public_key = root / "public.asc"
        cls.secret_key = root / "secret.asc"
        cls.passphrase_file = root / "key-passphrase"
        cls.passphrase_file.write_text("correct horse battery staple\n", encoding="utf-8")
        cls.passphrase_file.chmod(0o600)
        _run_gpg(
            cls.gnupg_home,
            "--pinentry-mode",
            "loopback",
            "--passphrase-file",
            os.fspath(cls.passphrase_file),
            "--quick-generate-key",
            "Repository Test <repository-test@example.invalid>",
            "rsa2048",
            "cert",
            "3y",
        )
        listing = _run_gpg(cls.gnupg_home, "--with-colons", "--list-keys").stdout
        fingerprints = [
            fields[9]
            for line in listing.splitlines()
            if (fields := line.split(":"))[0] == "fpr"
        ]
        if len(fingerprints) != 1:
            raise RuntimeError("throwaway primary key did not have exactly one fingerprint")
        cls.throwaway_fingerprint = fingerprints[0]
        _run_gpg(
            cls.gnupg_home,
            "--pinentry-mode",
            "loopback",
            "--passphrase-file",
            os.fspath(cls.passphrase_file),
            "--quick-add-key",
            cls.throwaway_fingerprint,
            "rsa2048",
            "sign",
            "3y",
        )
        cls.public_key.write_text(
            _run_gpg(
                cls.gnupg_home, "--armor", "--export", cls.throwaway_fingerprint
            ).stdout,
            encoding="ascii",
        )
        cls.secret_key.write_text(
            _run_gpg(
                cls.gnupg_home,
                "--pinentry-mode",
                "loopback",
                "--passphrase-file",
                os.fspath(cls.passphrase_file),
                "--armor",
                "--export-secret-keys",
                cls.throwaway_fingerprint,
            ).stdout,
            encoding="ascii",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._keys.cleanup()

    def _build(
        self,
        root: pathlib.Path,
        *,
        site: pathlib.Path | None = None,
        deb: pathlib.Path | None = None,
        public_key: pathlib.Path | None = None,
        private_key: pathlib.Path | None = None,
        passphrase_file: pathlib.Path | None = None,
        apt_ftparchive: str | None = None,
        gpg: str = "gpg",
        origin: str = "Object Storage Client",
        label: str = "Object Storage Client",
        base_url: str = BASE_URL,
        now: dt.datetime | None = None,
    ) -> pathlib.Path:
        package = deb or (root / "object-storage-client_1.2.3_amd64.deb")
        if deb is None:
            package.write_bytes(b"test deb package bytes\n")
        tool = apt_ftparchive or os.fspath(_fake_apt_ftparchive(root))
        destination = site or (root / "site")
        build_apt_repository(
            site_dir=destination,
            deb=package,
            public_key=public_key or self.public_key,
            expected_fingerprint=self.throwaway_fingerprint,
            private_key=private_key or self.secret_key,
            passphrase_file=passphrase_file or self.passphrase_file,
            origin=origin,
            label=label,
            base_url=base_url,
            apt_ftparchive=tool,
            gpg=gpg,
            now=now,
        )
        return destination

    def _build_rpm(self, root, *, site=None, rpm_package=None, tools=None, **overrides):
        package = rpm_package or (root / "object-storage-client-1.2.3-1.x86_64.rpm")
        if rpm_package is None:
            package.write_bytes(b"test rpm package bytes\n")
        createrepo, rpmsign, rpm = tools or _fake_rpm_tools(root / "rpm-tools", self.throwaway_fingerprint)
        destination = site or (root / "site")
        build_rpm_repository(
            site_dir=destination, rpm_package=package,
            public_key=overrides.get("public_key", self.public_key),
            expected_fingerprint=self.throwaway_fingerprint,
            private_key=overrides.get("private_key", self.secret_key),
            passphrase_file=overrides.get("passphrase_file", self.passphrase_file),
            createrepo_c=os.fspath(createrepo), rpmsign=os.fspath(rpmsign),
            rpm=os.fspath(rpm), gpg=overrides.get("gpg", "gpg"),
        )
        return destination

    def test_build_rpm_repository_signs_packages_and_metadata_with_real_gpg(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            log = root / "tool-log"
            with mock.patch.dict(os.environ, {"OSC_RPM_TOOL_LOG": os.fspath(log)}):
                site = self._build_rpm(root)
            paths = rpm_paths(site)
            package = paths.packages / "object-storage-client-1.2.3-1.x86_64.rpm"
            expected = {package, paths.repodata / "primary.xml.gz", paths.repodata / "filelists.xml.gz",
                        paths.repodata / "other.xml.gz", paths.repodata / "repomd.xml",
                        paths.repodata / "repomd.xml.asc", site / "repository-key.asc"}
            self.assertEqual(expected, {path for path in site.rglob("*") if path.is_file()})
            for path in expected:
                self.assertFalse(path.is_symlink())
                self.assertEqual(0o644, stat.S_IMODE(path.stat().st_mode))
            self.assertTrue(package.read_bytes().endswith(b"\nFAKE-RPM-SIGNATURE\n"))
            self.assertIn("BEGIN PGP SIGNATURE", (paths.repodata / "repomd.xml.asc").read_text())
            tool_log = log.read_text(encoding="utf-8")
            self.assertIn("_gpg_name " + self.throwaway_fingerprint, tool_log)
            self.assertIn("_openpgp_sign gpg", tool_log)
            self.assertIn("_openpgp_sign_id " + self.throwaway_fingerprint, tool_log)
            self.assertIn("_gpg_sign_cmd_extra_args --batch --no-tty --pinentry-mode loopback", tool_log)
            self.assertIn("--passphrase-file", tool_log)
            self.assertNotIn("__gpg_sign_cmd", tool_log)
            self.assertNotIn("%{__signature_filename}", tool_log)
            self.assertNotIn(self.passphrase_file.read_text().strip(), tool_log)
            self.assertEqual([], list(paths.repodata.parent.glob(".repodata.rollback-*")))

    def test_build_rpm_repository_uses_one_signing_contract_for_rpm_4_and_6(self):
        for rpm_major in ("4", "6"):
            with self.subTest(rpm_major=rpm_major), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                log = root / "tool-log"
                with mock.patch.dict(
                    os.environ,
                    {
                        "OSC_FAKE_RPM_MAJOR": rpm_major,
                        "OSC_RPM_TOOL_LOG": os.fspath(log),
                    },
                ):
                    self._build_rpm(root)
                arguments = log.read_text(encoding="utf-8")
                self.assertIn("_gpg_name " + self.throwaway_fingerprint, arguments)
                self.assertIn("_openpgp_sign gpg", arguments)
                self.assertIn("_openpgp_sign_id " + self.throwaway_fingerprint, arguments)
                self.assertIn("_gpg_path ", arguments)
                self.assertIn("_gpg_sign_cmd_extra_args ", arguments)
                self.assertIn("--addsign", arguments)
                self.assertNotIn("__gpg_sign_cmd", arguments)

    def test_fake_rpm_tools_reject_malformed_contracts_without_mutation_or_trust(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            createrepo, rpmsign, rpm = _fake_rpm_tools(
                root / "tools", self.throwaway_fingerprint
            )
            package = root / "package.rpm"
            original = b"unsigned package bytes\n"
            package.write_bytes(original)
            home = root / "signing-home"
            home.mkdir(mode=0o700)
            passphrase = root / "passphrase"
            passphrase.write_text("secret\n", encoding="utf-8")
            subprocess.run(
                [
                    "gpg", "--batch", "--no-tty", "--homedir", os.fspath(home),
                    "--pinentry-mode", "loopback", "--passphrase-file",
                    os.fspath(self.passphrase_file), "--import", os.fspath(self.secret_key),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            signing_created = min(
                key.created
                for key in inspect_public_key(self.public_key).signing_keys
                if "s" in key.capabilities.lower()
            )
            extra_args = (
                f"--batch --no-tty --pinentry-mode loopback --passphrase-file {passphrase} "
                f"--faked-system-time {int(signing_created.timestamp())}!"
            )
            valid_sign_arguments = [
                "--define", f"_gpg_name {self.throwaway_fingerprint}",
                "--define", "_openpgp_sign gpg",
                "--define", f"_openpgp_sign_id {self.throwaway_fingerprint}",
                "--define", f"_gpg_path {home}",
                "--define", f"_gpg_sign_cmd_extra_args {extra_args}",
                "--addsign", os.fspath(package),
            ]
            for rpm_major in ("4", "6"):
                with self.subTest(tool="rpmsign", rpm_major=rpm_major):
                    package.write_bytes(original)
                    result = subprocess.run(
                        [rpmsign, *valid_sign_arguments],
                        check=False,
                        env={
                            **os.environ,
                            "GNUPGHOME": os.fspath(home),
                            "OSC_FAKE_RPM_MAJOR": rpm_major,
                        },
                    )
                    self.assertEqual(0, result.returncode)
                    self.assertTrue(package.read_bytes().endswith(b"\nFAKE-RPM-SIGNATURE\n"))
            package.write_bytes(original)
            malformed_sign_arguments = (
                ("4", valid_sign_arguments[2:]),
                ("4", [*valid_sign_arguments[:1], "_gpg_name NOT-THE-EXPECTED-FINGERPRINT", *valid_sign_arguments[2:]]),
                ("6", valid_sign_arguments[4:]),
                ("6", [*valid_sign_arguments[:3], "_openpgp_sign not-gpg", *valid_sign_arguments[4:]]),
                ("6", [*valid_sign_arguments[:5], "_openpgp_sign_id NOT-THE-EXPECTED-FINGERPRINT", *valid_sign_arguments[6:]]),
                ("6", [*valid_sign_arguments[:-2], "--define", "__gpg_sign_cmd %{__gpg} --detach-sign", *valid_sign_arguments[-2:]]),
                ("4", valid_sign_arguments[:-2]),
                ("4", [*valid_sign_arguments[:-1], "--extra", valid_sign_arguments[-1]]),
                ("4", [*valid_sign_arguments[:7], "_gpg_path /wrong/home", *valid_sign_arguments[8:]]),
            )
            for index, (rpm_major, arguments) in enumerate(malformed_sign_arguments):
                with self.subTest(tool="rpmsign", case=index, rpm_major=rpm_major):
                    result = subprocess.run(
                        [rpmsign, *arguments],
                        check=False,
                        env={
                            **os.environ,
                            "GNUPGHOME": os.fspath(home),
                            "OSC_FAKE_RPM_MAJOR": rpm_major,
                        },
                    )
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(original, package.read_bytes())

            package_directory = root / "packages"
            package_directory.mkdir()
            (package_directory / "sample.rpm").write_bytes(b"sample\n")
            for index, arguments in enumerate(
                ([package_directory], ["--update", package_directory, "--extra"])
            ):
                with self.subTest(tool="createrepo_c", case=index):
                    malformed_metadata = subprocess.run(
                        [createrepo, *arguments], check=False
                    )
                    self.assertNotEqual(0, malformed_metadata.returncode)
                    self.assertFalse((package_directory / "repodata").exists())

            database = root / "rpmdb"
            arbitrary_key = root / "arbitrary-key.asc"
            arbitrary_key.write_bytes(b"not a public GPG export\n")
            malformed_import = subprocess.run(
                [rpm, "--dbpath", database, "--import", arbitrary_key], check=False
            )
            self.assertNotEqual(0, malformed_import.returncode)
            self.assertFalse((database / "imported").exists())

            signed = root / "signed.rpm"
            signed_bytes = original + b"\nFAKE-RPM-SIGNATURE\n"
            signed.write_bytes(signed_bytes)
            untrusted_check = subprocess.run(
                [rpm, "--dbpath", database, "--checksig", signed],
                check=False,
            )
            self.assertNotEqual(0, untrusted_check.returncode)
            self.assertEqual(signed_bytes, signed.read_bytes())

            valid_import = subprocess.run(
                [rpm, "--dbpath", database, "--import", self.public_key], check=False
            )
            self.assertEqual(0, valid_import.returncode)
            malformed_check = subprocess.run(
                [rpm, "--dbpath", database, "--checksig", signed, "--extra"],
                check=False,
            )
            self.assertNotEqual(0, malformed_check.returncode)
            unsigned_check = subprocess.run(
                [rpm, "--dbpath", database, "--checksig", package], check=False
            )
            self.assertNotEqual(0, unsigned_check.returncode)
            valid_check = subprocess.run(
                [rpm, "--dbpath", database, "--checksig", signed],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, valid_check.returncode)
            self.assertEqual(f"{signed}: digests signatures OK\n", valid_check.stdout)
            self.assertEqual(signed_bytes, signed.read_bytes())

            with mock.patch.dict(os.environ, {"OSC_RPM_CHECKSIG_OUTPUT": "whitespace"}):
                _verify_rpm_packages(
                    os.fspath(rpm), self.public_key, [signed], self.throwaway_fingerprint
                )

            for output in (
                "not-ok",
                "malformed-ok",
                "missing-signatures",
                "uppercase-failures",
                "trailing",
                "wrong-package",
            ):
                with self.subTest(checksig_output=output), mock.patch.dict(
                    os.environ, {"OSC_RPM_CHECKSIG_OUTPUT": output}
                ):
                    with self.assertRaisesRegex(RuntimeError, "verification"):
                        _verify_rpm_packages(
                            os.fspath(rpm), self.public_key, [signed], self.throwaway_fingerprint
                        )

    def test_publish_repodata_preserves_backup_when_publication_and_restore_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "source"
            destination = root / "repodata"
            (source / "nested").mkdir(parents=True)
            (destination / "nested").mkdir(parents=True)
            (source / "new.xml").write_bytes(b"new metadata\n")
            old_file = destination / "nested/old.xml"
            old_file.write_bytes(b"original metadata\n")
            destination.chmod(0o751)
            (destination / "nested").chmod(0o750)
            old_file.chmod(0o640)
            original_modes = {
                ".": stat.S_IMODE(destination.stat().st_mode),
                "nested": stat.S_IMODE((destination / "nested").stat().st_mode),
                "nested/old.xml": stat.S_IMODE(old_file.stat().st_mode),
            }
            real_replace = os.replace
            publication_failed = False
            restore_failed = False

            def fail_publication_and_restore(source_path, destination_path):
                nonlocal publication_failed, restore_failed
                source_candidate = pathlib.Path(source_path)
                destination_candidate = pathlib.Path(destination_path)
                if (
                    destination_candidate == destination
                    and source_candidate.name.startswith(".repodata.publish-")
                ):
                    publication_failed = True
                    raise OSError("simulated staged publication failure")
                if (
                    destination_candidate == destination
                    and source_candidate.name.startswith(".repodata.rollback-")
                ):
                    restore_failed = True
                    raise OSError("simulated rollback restore failure")
                return real_replace(source_path, destination_path)

            try:
                with mock.patch(
                    "build.linux.repository.os.replace",
                    side_effect=fail_publication_and_restore,
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "rollback incomplete|preserved.*rollback"
                    ) as raised:
                        _publish_repodata(source, destination)

                self.assertTrue(publication_failed)
                self.assertTrue(restore_failed)
                self.assertFalse(destination.exists())
                self.assertEqual([], list(root.glob(".repodata.publish-*")))
                backups = list(root.glob(".repodata.rollback-*"))
                self.assertEqual(1, len(backups))
                backup = backups[0]
                self.assertTrue(stat.S_ISDIR(backup.lstat().st_mode))
                self.assertFalse(backup.is_symlink())
                self.assertEqual(b"original metadata\n", (backup / "nested/old.xml").read_bytes())
                self.assertEqual(
                    original_modes,
                    {
                        ".": stat.S_IMODE(backup.stat().st_mode),
                        "nested": stat.S_IMODE((backup / "nested").stat().st_mode),
                        "nested/old.xml": stat.S_IMODE((backup / "nested/old.xml").stat().st_mode),
                    },
                )
                self.assertIn(os.fspath(backup), str(raised.exception))
                self.assertIsInstance(raised.exception.__cause__, OSError)
                self.assertIn("restore", str(raised.exception.__cause__))
            finally:
                for backup in root.glob(".repodata.rollback-*"):
                    if backup.is_dir() and not backup.is_symlink():
                        shutil.rmtree(backup)

    def test_rpm_build_recovers_one_stranded_valid_repodata_backup_before_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            tools = _fake_rpm_tools(root / "tools", self.throwaway_fingerprint)
            site = self._build_rpm(root, tools=tools)
            paths = rpm_paths(site)
            backup = paths.packages / ".repodata.rollback-stranded"
            os.replace(paths.repodata, backup)
            second = root / "object-storage-client-2.0.0-1.x86_64.rpm"
            second.write_bytes(b"second rpm version\n")
            replacements: list[tuple[pathlib.Path, pathlib.Path]] = []
            real_replace = os.replace

            def record_replace(source, destination):
                replacements.append((pathlib.Path(source), pathlib.Path(destination)))
                return real_replace(source, destination)

            with mock.patch("build.linux.repository.os.replace", side_effect=record_replace):
                self._build_rpm(root, site=site, rpm_package=second, tools=tools)

            repodata_replacements = [pair for pair in replacements if pair[1] == paths.repodata]
            self.assertGreaterEqual(len(repodata_replacements), 2)
            self.assertEqual((backup, paths.repodata), repodata_replacements[0])
            self.assertTrue(paths.repodata.is_dir())
            self.assertEqual([], list(paths.packages.glob(".repodata.rollback-*")))
            self.assertEqual(
                {"object-storage-client-1.2.3-1.x86_64.rpm", second.name},
                {path.name for path in paths.packages.glob("*.rpm")},
            )

    def test_rpm_build_rejects_and_preserves_ambiguous_or_unsafe_rollback_backups(self):
        for case in ("live-and-backup", "multiple", "symlink"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                tools = _fake_rpm_tools(root / "tools", self.throwaway_fingerprint)
                site = self._build_rpm(root, tools=tools)
                paths = rpm_paths(site)
                first = paths.packages / ".repodata.rollback-first"
                if case == "live-and-backup":
                    shutil.copytree(paths.repodata, first)
                elif case == "multiple":
                    os.replace(paths.repodata, first)
                    shutil.copytree(first, paths.packages / ".repodata.rollback-second")
                else:
                    rescued = paths.packages / ".rescued-repodata"
                    os.replace(paths.repodata, rescued)
                    first.symlink_to(rescued, target_is_directory=True)
                before = {
                    path.relative_to(paths.packages): (
                        "symlink", os.readlink(path)
                    ) if path.is_symlink() else (
                        "file", path.read_bytes()
                    ) if path.is_file() else ("directory", None)
                    for path in paths.packages.rglob("*")
                }
                package = root / "object-storage-client-2.0.0-1.x86_64.rpm"
                package.write_bytes(b"new package must not publish\n")
                expected_error = (
                    "ambiguous.*rollback|rollback.*ambiguous"
                    if case in {"live-and-backup", "multiple"}
                    else "unsafe.*rollback|rollback.*unsafe"
                )
                with self.assertRaisesRegex(RuntimeError, expected_error):
                    self._build_rpm(root, site=site, rpm_package=package, tools=tools)
                after = {
                    path.relative_to(paths.packages): (
                        "symlink", os.readlink(path)
                    ) if path.is_symlink() else (
                        "file", path.read_bytes()
                    ) if path.is_file() else ("directory", None)
                    for path in paths.packages.rglob("*")
                }
                self.assertEqual(before, after)

    def test_publish_repodata_fsyncs_staged_tree_bottom_up_before_first_rename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "source"
            destination = root / "repodata"
            (source / "nested").mkdir(parents=True)
            destination.mkdir()
            (source / "top.xml").write_bytes(b"top\n")
            (source / "nested/deep.xml").write_bytes(b"deep\n")
            (destination / "old.xml").write_bytes(b"old\n")
            fsynced: list[pathlib.Path] = []
            real_fsync = os.fsync
            real_replace = os.replace
            checked_first_rename = False

            def record_fsync(descriptor):
                fsynced.append(pathlib.Path(os.readlink(f"/proc/self/fd/{descriptor}")))
                return real_fsync(descriptor)

            def assert_tree_durable_before_rename(source_path, destination_path):
                nonlocal checked_first_rename
                if not checked_first_rename:
                    checked_first_rename = True
                    staged = next(root.glob(".repodata.publish-*"))
                    expected = [
                        staged / "top.xml",
                        staged / "nested/deep.xml",
                        staged / "nested",
                        staged,
                    ]
                    self.assertTrue(all(path in fsynced for path in expected), (expected, fsynced))
                    self.assertLess(fsynced.index(staged / "nested/deep.xml"), fsynced.index(staged / "nested"))
                    self.assertLess(fsynced.index(staged / "nested"), fsynced.index(staged))
                return real_replace(source_path, destination_path)

            with mock.patch("build.linux.repository.os.fsync", side_effect=record_fsync), mock.patch(
                "build.linux.repository.os.replace", side_effect=assert_tree_durable_before_rename
            ):
                _publish_repodata(source, destination)
            self.assertTrue(checked_first_rename)

    def test_rpm_repository_retains_versions_and_is_idempotent_but_rejects_collision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            tools = _fake_rpm_tools(root / "tools", self.throwaway_fingerprint)
            first = root / "object-storage-client-1.0.0-1.x86_64.rpm"
            second = root / "object-storage-client-2.0.0-1.x86_64.rpm"
            first.write_bytes(b"rpm one\n"); second.write_bytes(b"rpm two\n")
            site = self._build_rpm(root, rpm_package=first, tools=tools)
            self._build_rpm(root, site=site, rpm_package=second, tools=tools)
            before = (rpm_paths(site).packages / second.name).read_bytes()
            self._build_rpm(root, site=site, rpm_package=second, tools=tools)
            self.assertEqual({first.name, second.name}, {p.name for p in rpm_paths(site).packages.glob("*.rpm")})
            self.assertEqual(before, (rpm_paths(site).packages / second.name).read_bytes())
            second.write_bytes(b"changed same name\n")
            with self.assertRaisesRegex(RuntimeError, "collision|different"):
                self._build_rpm(root, site=site, rpm_package=second, tools=tools)

    def test_rpm_failures_preserve_existing_repodata(self):
        for variable, message in (("OSC_RPM_SIGN_FAIL", "rpmsign|sign"),
                                  ("OSC_RPM_VERIFY_FAIL", "rpm.*verif"),
                                  ("OSC_RPM_METADATA_FAIL", "createrepo")):
            with self.subTest(variable=variable), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary); tools = _fake_rpm_tools(root / "tools", self.throwaway_fingerprint)
                site = self._build_rpm(root, tools=tools); repodata = rpm_paths(site).repodata
                before = {p.name: p.read_bytes() for p in repodata.iterdir()}
                package = root / "object-storage-client-2.0.0-1.x86_64.rpm"; package.write_bytes(b"new rpm\n")
                with mock.patch.dict(os.environ, {variable: "1"}):
                    with self.assertRaisesRegex(RuntimeError, message):
                        self._build_rpm(root, site=site, rpm_package=package, tools=tools)
                self.assertEqual(before, {p.name: p.read_bytes() for p in repodata.iterdir()})

    def test_rpm_repodata_directory_publication_rolls_back_on_rename_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary); tools = _fake_rpm_tools(root / "tools", self.throwaway_fingerprint)
            site = self._build_rpm(root, tools=tools); repodata = rpm_paths(site).repodata
            before = {p.name: p.read_bytes() for p in repodata.iterdir()}
            package = root / "object-storage-client-2.0.0-1.x86_64.rpm"; package.write_bytes(b"new rpm\n")
            real_replace = os.replace
            failed = False
            def fail_new_directory(source, destination):
                nonlocal failed
                if pathlib.Path(destination) == repodata and not failed:
                    failed = True
                    raise OSError("simulated repodata publication failure")
                return real_replace(source, destination)
            with mock.patch("build.linux.repository.os.replace", side_effect=fail_new_directory):
                with self.assertRaisesRegex(OSError, "repodata publication"):
                    self._build_rpm(root, site=site, rpm_package=package, tools=tools)
            self.assertTrue(failed)
            self.assertEqual(before, {p.name: p.read_bytes() for p in repodata.iterdir()})
            self.assertEqual([], list(repodata.parent.glob(".repodata.publish-*")))
            self.assertEqual([], list(repodata.parent.glob(".repodata.rollback-*")))

    def test_rpm_inputs_existing_tree_and_missing_tools_are_rejected_safely(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary); tools = _fake_rpm_tools(root / "tools", self.throwaway_fingerprint)
            unsafe = root / "unsafe name.rpm"; unsafe.write_bytes(b"rpm")
            with self.assertRaisesRegex(ValueError, "safe|filename"): self._build_rpm(root, rpm_package=unsafe, tools=tools)
            wrong = root / "package.deb"; wrong.write_bytes(b"deb")
            with self.assertRaisesRegex(ValueError, "\\.rpm"): self._build_rpm(root, rpm_package=wrong, tools=tools)
            real = root / "safe.rpm"; real.write_bytes(b"rpm")
            linked = root / "linked.rpm"; linked.symlink_to(real)
            with self.assertRaisesRegex(RuntimeError, "symlink"): self._build_rpm(root, rpm_package=linked, tools=tools)
            with self.assertRaisesRegex((ValueError, RuntimeError), "overlap"): self._build_rpm(root, site=real, rpm_package=real, tools=tools)
            site = root / "existing-site"; packages = rpm_paths(site).packages; packages.mkdir(parents=True)
            (packages / "README").write_text("hazard")
            with self.assertRaisesRegex(RuntimeError, "unsafe|unexpected"): self._build_rpm(root, site=site, rpm_package=real, tools=tools)
            hazard_site = root / "hazard-site"; hazard_packages = rpm_paths(hazard_site).packages
            hazard_repodata = hazard_packages / "repodata"; hazard_repodata.mkdir(parents=True)
            (hazard_repodata / "repomd.xml").symlink_to(real)
            with self.assertRaisesRegex(RuntimeError, "symlink|regular"):
                self._build_rpm(root, site=hazard_site, rpm_package=real, tools=tools)
            for index, field in enumerate(("createrepo_c", "rpmsign", "rpm")):
                broken = list(tools); broken[index] = pathlib.Path("definitely-missing-" + field)
                with self.subTest(tool=field), self.assertRaisesRegex(RuntimeError, field.replace("_c", "") + ".*not available"):
                    self._build_rpm(root, rpm_package=real, tools=tuple(broken))

    def test_build_apt_repository_signs_complete_repository_with_real_gpg(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            site = self._build(root)
            paths = apt_paths(site)
            package = paths.pool / "object-storage-client_1.2.3_amd64.deb"
            expected_files = (
                package,
                paths.binary / "Packages",
                paths.binary / "Packages.gz",
                paths.release / "Release",
                paths.release / "InRelease",
                paths.release / "Release.gpg",
                site / "repository-key.asc",
            )
            for path in expected_files:
                with self.subTest(path=path):
                    self.assertTrue(path.is_file())
                    self.assertFalse(path.is_symlink())
                    self.assertEqual(0o644, stat.S_IMODE(path.stat().st_mode))
            for directory in (
                site / "apt",
                site / "apt/pool/main/o/object-storage-client",
                site / "apt/dists/stable",
                site / "apt/dists/stable/main/binary-amd64",
            ):
                with self.subTest(directory=directory):
                    self.assertEqual(0o755, stat.S_IMODE(directory.stat().st_mode))
            packages = (paths.binary / "Packages").read_text(encoding="utf-8")
            self.assertIn("Filename: pool/main/o/object-storage-client/", packages)
            compressed = (paths.binary / "Packages.gz").read_bytes()
            self.assertEqual(packages.encode(), gzip.decompress(compressed))
            self.assertEqual(0, int.from_bytes(compressed[4:8], "little"))
            release = (paths.release / "Release").read_text(encoding="utf-8")
            for field in (
                "Origin: Object Storage Client",
                "Label: Object Storage Client",
                "Suite: stable",
                "Codename: stable",
                "Architectures: amd64",
                "Components: main",
                "Description: Object Storage Client APT repository at " + BASE_URL,
                "SHA256:",
                "SHA512:",
            ):
                self.assertIn(field, release)
            self.assertIn("BEGIN PGP SIGNED MESSAGE", (paths.release / "InRelease").read_text())
            self.assertIn("BEGIN PGP SIGNATURE", (paths.release / "Release.gpg").read_text())
            self.assertEqual(self.public_key.read_bytes(), (site / "repository-key.asc").read_bytes())
            names = {path.name for path in site.rglob("*") if path.is_file()}
            self.assertNotIn(self.secret_key.name, names)
            self.assertNotIn(self.passphrase_file.name, names)

    def test_packages_gzip_is_deterministic_across_rebuilds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            site = self._build(root)
            first = (apt_paths(site).binary / "Packages.gz").read_bytes()
            self._build(root, site=site)
            second = (apt_paths(site).binary / "Packages.gz").read_bytes()
            self.assertEqual(first, second)

    def test_retained_package_versions_are_all_indexed_and_rebuild_idempotently(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            first = root / "object-storage-client_1.0.0_amd64.deb"
            second = root / "object-storage-client_2.0.0_amd64.deb"
            first.write_bytes(b"immutable package version 1.0.0\n")
            second.write_bytes(b"distinct immutable package version 2.0.0\n")

            site = self._build(root, deb=first)
            self._build(root, site=site, deb=second)
            self._build(root, site=site, deb=second)

            paths = apt_paths(site)
            expected = {
                f"pool/main/o/object-storage-client/{package.name}": package
                for package in (first, second)
            }
            self.assertEqual(
                {package.name for package in expected.values()},
                {package.name for package in paths.pool.iterdir()},
            )
            for filename, source in expected.items():
                retained = paths.pool / pathlib.PurePosixPath(filename).name
                with self.subTest(filename=filename):
                    self.assertEqual(source.read_bytes(), retained.read_bytes())
                    self.assertEqual(0o644, stat.S_IMODE(retained.stat().st_mode))

            packages_bytes = (paths.binary / "Packages").read_bytes()
            stanzas = [
                dict(line.split(": ", 1) for line in stanza.splitlines())
                for stanza in packages_bytes.decode("utf-8").strip().split("\n\n")
            ]
            self.assertEqual(2, len(stanzas))
            self.assertEqual(set(expected), {stanza["Filename"] for stanza in stanzas})
            for stanza in stanzas:
                source = expected[stanza["Filename"]]
                data = source.read_bytes()
                with self.subTest(filename=stanza["Filename"]):
                    self.assertEqual(str(len(data)), stanza["Size"])
                    self.assertEqual(hashlib.md5(data).hexdigest(), stanza["MD5sum"])
                    self.assertEqual(hashlib.sha1(data).hexdigest(), stanza["SHA1"])
                    self.assertEqual(hashlib.sha256(data).hexdigest(), stanza["SHA256"])
                    self.assertEqual(hashlib.sha512(data).hexdigest(), stanza["SHA512"])
            self.assertEqual(packages_bytes, gzip.decompress((paths.binary / "Packages.gz").read_bytes()))

    def test_concurrent_publications_are_process_serialized_and_retain_both_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            site = root / "site"
            first = root / "object-storage-client_1.0.0_amd64.deb"
            second = root / "object-storage-client_2.0.0_amd64.deb"
            first.write_bytes(b"concurrent version one\n")
            second.write_bytes(b"concurrent version two\n")
            tool = _fake_apt_ftparchive(root / "tools")
            ready = root / "first-ready"
            gate = root / "release-first"
            event_log = root / "apt-events"
            environment = os.environ.copy()
            environment.update(
                {
                    "OSC_APT_BLOCK_PACKAGE": first.name,
                    "OSC_APT_READY": os.fspath(ready),
                    "OSC_APT_GATE": os.fspath(gate),
                    "OSC_APT_EVENT_LOG": os.fspath(event_log),
                }
            )
            script = (
                "from build.linux.repository import build_apt_repository; import sys; "
                "build_apt_repository(site_dir=sys.argv[1], deb=sys.argv[2], "
                "public_key=sys.argv[3], expected_fingerprint=sys.argv[4], "
                "private_key=sys.argv[5], passphrase_file=sys.argv[6], "
                "apt_ftparchive=sys.argv[7], gpg='gpg')"
            )

            def command(package: pathlib.Path) -> list[str]:
                return [
                    sys.executable,
                    "-c",
                    script,
                    os.fspath(site),
                    os.fspath(package),
                    os.fspath(self.public_key),
                    self.throwaway_fingerprint,
                    os.fspath(self.secret_key),
                    os.fspath(self.passphrase_file),
                    os.fspath(tool),
                ]

            first_process = subprocess.Popen(
                command(first), cwd=ROOT, env=environment, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True
            )
            second_process = None
            try:
                deadline = time.monotonic() + 15
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "first publication never reached apt-ftparchive")
                active_locks = list(site.parent.glob(".osc-apt-*.lock"))
                self.assertEqual(1, len(active_locks))
                lock_inode = active_locks[0].stat().st_ino
                second_process = subprocess.Popen(
                    command(second), cwd=ROOT, env=environment, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True
                )
                time.sleep(0.5)
                self.assertEqual(
                    [f"packages-start {first.name}"],
                    event_log.read_text(encoding="utf-8").splitlines(),
                    "the second process entered metadata generation before the first released the site lock",
                )
                gate.touch()
                first_stdout, first_stderr = first_process.communicate(timeout=60)
                second_stdout, second_stderr = second_process.communicate(timeout=60)
                self.assertEqual(0, first_process.returncode, first_stdout + first_stderr)
                self.assertEqual(0, second_process.returncode, second_stdout + second_stderr)
            finally:
                gate.touch(exist_ok=True)
                for process in (first_process, second_process):
                    if process is not None:
                        if process.poll() is None:
                            process.kill()
                        process.communicate()

            paths = apt_paths(site)
            self.assertEqual({first.name, second.name}, {path.name for path in paths.pool.iterdir()})
            packages = (paths.binary / "Packages").read_text(encoding="utf-8")
            self.assertIn(first.name, packages)
            self.assertIn(second.name, packages)
            release = (paths.release / "Release").read_text(encoding="utf-8")
            release_sha256 = {
                fields[2]: (fields[0], fields[1])
                for line in release.split("SHA256:\n", 1)[1].split("SHA512:\n", 1)[0].splitlines()
                if len(fields := line.split()) == 3
            }
            for relative in ("main/binary-amd64/Packages", "main/binary-amd64/Packages.gz"):
                path = paths.release / relative
                self.assertEqual(
                    (hashlib.sha256(path.read_bytes()).hexdigest(), str(path.stat().st_size)),
                    release_sha256[relative],
                )
            lock_files = list(site.parent.glob(".osc-apt-*.lock"))
            self.assertEqual(1, len(lock_files))
            self.assertFalse(lock_files[0].is_symlink())
            self.assertTrue(stat.S_ISREG(lock_files[0].lstat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE(lock_files[0].stat().st_mode))
            self.assertEqual(lock_inode, lock_files[0].stat().st_ino)

    def test_release_dates_are_explicit_utc_and_exactly_seven_days_fresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            now = dt.datetime.now(tz=dt.timezone.utc).replace(microsecond=0)
            site = self._build(root, now=now)
            release = (apt_paths(site).release / "Release").read_text(encoding="utf-8")
            self.assertIn(now.strftime("Date: %a, %d %b %Y %H:%M:%S GMT"), release)
            self.assertIn(
                (now + dt.timedelta(days=7)).strftime("Valid-Until: %a, %d %b %Y %H:%M:%S GMT"),
                release,
            )

    def test_release_freshness_rejects_missing_malformed_stale_order_and_duplicates(self):
        now = dt.datetime.now(tz=dt.timezone.utc).replace(microsecond=0)
        formatted_now = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
        day = dt.timedelta(days=1)

        def formatted(value: dt.datetime) -> str:
            return value.strftime("%a, %d %b %Y %H:%M:%S GMT")

        cases: tuple[tuple[dict[str, Any], str], ...] = (
            ({"omitted_release_fields": ("Date",)}, "Date"),
            ({"omitted_release_fields": ("Valid-Until",)}, "Valid-Until"),
            ({"release_overrides": (("Date", "not-a-date"),)}, "Date"),
            ({"release_overrides": (("Valid-Until", "not-a-date"),)}, "Valid-Until"),
            ({"release_overrides": (("Date", "Mon, 24 Aug 2026 00:00:00"),)}, "Date"),
            ({"release_overrides": (("Valid-Until", formatted_now),)}, "ordering"),
            (
                {"release_overrides": (("Valid-Until", formatted(now + 6 * day)),)},
                "seven days|freshness",
            ),
            (
                {"release_overrides": (("Date", formatted(now - 8 * day)), ("Valid-Until", formatted(now - day))),},
                "expired",
            ),
            ({"duplicate_release_fields": ("Date",)}, "duplicate Date"),
            ({"duplicate_release_fields": ("Valid-Until",)}, "duplicate Valid-Until"),
        )
        for index, (tool_options, message) in enumerate(cases):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                tool = _fake_apt_ftparchive(root / "tool", **tool_options)
                with self.assertRaisesRegex(RuntimeError, message):
                    self._build(root, apt_ftparchive=os.fspath(tool), now=now)

    def test_same_package_and_key_are_idempotent_but_collisions_are_immutable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            site = self._build(root)
            package = apt_paths(site).pool / "object-storage-client_1.2.3_amd64.deb"
            self._build(root, site=site)
            package.write_bytes(b"other package")
            with self.assertRaisesRegex(RuntimeError, "collision|different"):
                self._build(root, site=site)
            self.assertEqual(b"other package", package.read_bytes())
            package.write_bytes(b"test deb package bytes\n")
            (site / "repository-key.asc").write_bytes(b"other key")
            with self.assertRaisesRegex(RuntimeError, "collision|different"):
                self._build(root, site=site)
            self.assertEqual(b"other key", (site / "repository-key.asc").read_bytes())

    def test_tool_or_signing_failures_preserve_previous_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            site = self._build(root)
            paths = apt_paths(site)
            metadata = tuple(
                paths.binary / name for name in ("Packages", "Packages.gz")
            ) + tuple(
                paths.release / name
                for name in ("Release", "InRelease", "Release.gpg")
            )
            before = {path: path.read_bytes() for path in metadata}
            malformed = _fake_apt_ftparchive(root / "malformed", malformed_release=True)
            with self.assertRaisesRegex(RuntimeError, "Release|field|hash"):
                self._build(root, site=site, apt_ftparchive=os.fspath(malformed))
            self.assertEqual(before, {path: path.read_bytes() for path in metadata})

            wrapper = root / "gpg-fail-sign"
            wrapper.write_text(
                "#!/usr/bin/env python3\nimport os, sys\n"
                "if '--clearsign' in sys.argv: sys.exit(9)\n"
                "os.execvp('gpg', ['gpg', *sys.argv[1:]])\n",
                encoding="utf-8",
            )
            wrapper.chmod(0o755)
            with self.assertRaisesRegex(RuntimeError, "sign"):
                self._build(root, site=site, gpg=os.fspath(wrapper))
            self.assertEqual(before, {path: path.read_bytes() for path in metadata})

    def test_signature_verification_failure_is_fatal_and_preserves_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            site = self._build(root)
            paths = apt_paths(site)
            release = paths.release / "Release"
            before = release.read_bytes()
            wrapper = root / "gpg-fail-verify"
            wrapper.write_text(
                "#!/usr/bin/env python3\nimport os, sys\n"
                "if '--verify' in sys.argv: sys.exit(8)\n"
                "os.execvp('gpg', ['gpg', *sys.argv[1:]])\n",
                encoding="utf-8",
            )
            wrapper.chmod(0o755)
            with self.assertRaisesRegex(RuntimeError, "verify|signature"):
                self._build(root, site=site, gpg=os.fspath(wrapper))
            self.assertEqual(before, release.read_bytes())

    def test_missing_inputs_and_tools_have_clear_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            missing = root / "missing.deb"
            cases = (
                ({"deb": missing}, "package|deb"),
                ({"public_key": missing}, "public key"),
                ({"private_key": missing}, "private key"),
                ({"passphrase_file": missing}, "passphrase"),
                ({"apt_ftparchive": "definitely-missing-apt-ftparchive"}, "apt-ftparchive.*not available"),
            )
            for overrides, message in cases:
                with self.subTest(overrides=overrides):
                    with self.assertRaisesRegex(RuntimeError, message):
                        self._build(root, **overrides)

    def test_wrong_passphrase_and_private_key_mismatch_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            wrong_passphrase = root / "wrong-passphrase"
            wrong_passphrase.write_text("wrong\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "private key|passphrase|import|signing"):
                self._build(root, passphrase_file=wrong_passphrase)
            with self.assertRaisesRegex(RuntimeError, "private key.*fingerprint|mismatch"):
                self._build(
                    root,
                    private_key=LINUX / "repository-key.asc",
                )

    def test_private_export_with_an_extra_primary_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            other_home = root / "other-home"
            other_home.mkdir(mode=0o700)
            _run_gpg(
                other_home,
                "--pinentry-mode",
                "loopback",
                "--passphrase-file",
                os.fspath(self.passphrase_file),
                "--quick-generate-key",
                "Other Repository Test <other-repository-test@example.invalid>",
                "rsa2048",
                "sign",
                "3y",
            )
            other_listing = _run_gpg(other_home, "--with-colons", "--list-keys").stdout
            other_fingerprints = [
                fields[9]
                for line in other_listing.splitlines()
                if (fields := line.split(":"))[0] == "fpr"
            ]
            self.assertEqual(1, len(other_fingerprints))
            other_secret = _run_gpg(
                other_home,
                "--pinentry-mode",
                "loopback",
                "--passphrase-file",
                os.fspath(self.passphrase_file),
                "--armor",
                "--export-secret-keys",
                other_fingerprints[0],
            ).stdout
            combined = root / "combined-private.asc"
            combined.write_text(
                self.secret_key.read_text(encoding="ascii") + other_secret,
                encoding="ascii",
            )
            with self.assertRaisesRegex(RuntimeError, "exactly one secret primary"):
                self._build(root, private_key=combined)

    def test_unsafe_package_names_symlinks_and_site_overlap_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            package = root / "unsafe name.deb"
            package.write_bytes(b"deb")
            with self.assertRaisesRegex((RuntimeError, ValueError), "filename|safe"):
                self._build(root, deb=package)
            package = root / "package.rpm"
            package.write_bytes(b"rpm")
            with self.assertRaisesRegex((RuntimeError, ValueError), "\.deb"):
                self._build(root, deb=package)
            real = root / "object-storage-client_1_amd64.deb"
            real.write_bytes(b"deb")
            link = root / "link.deb"
            link.symlink_to(real)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                self._build(root, deb=link)
            site_parent = root / "site-parent"
            site_parent.symlink_to(root / "real-site")
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                self._build(root, site=site_parent / "site", deb=real)
            with self.assertRaisesRegex((RuntimeError, ValueError), "overlap"):
                self._build(root, site=real, deb=real)

    def test_existing_symlink_in_apt_tree_is_rejected_without_following_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            site = root / "site"
            site.mkdir()
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            (site / "apt").symlink_to(elsewhere, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                self._build(root, site=site)
            self.assertEqual([], list(elsewhere.iterdir()))

    def test_site_lock_symlink_collision_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            site = self._build(root)
            lock_files = list(site.parent.glob(".osc-apt-*.lock"))
            self.assertEqual(1, len(lock_files))
            lock_files[0].unlink()
            target = root / "lock-target"
            target.write_bytes(b"must remain unchanged\n")
            lock_files[0].symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "lock|symlink|regular"):
                self._build(root, site=site)
            self.assertEqual(b"must remain unchanged\n", target.read_bytes())

    def test_missing_native_apt_ftparchive_status_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            with mock.patch("build.linux.repository.shutil.which", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "apt-ftparchive.*not available"):
                    self._build(root, apt_ftparchive="apt-ftparchive")

    def test_release_fields_reject_control_character_injection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            cases = (
                ({"origin": "Trusted\nCodename: injected"}, "origin"),
                ({"label": "Trusted\tLabel"}, "label"),
                ({"base_url": "https://example.invalid/\x7fhidden"}, "base_url"),
            )
            for overrides, field in cases:
                with self.subTest(field=field):
                    with self.assertRaisesRegex(ValueError, "control"):
                        self._build(root, **overrides)

    def test_packages_hashes_must_match_the_staged_pool_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            malformed = _fake_apt_ftparchive(root / "malformed", malformed_packages=True)
            with self.assertRaisesRegex(RuntimeError, "Packages|SHA256|hash"):
                self._build(root, apt_ftparchive=os.fspath(malformed))

    def test_packages_validation_rejects_duplicate_missing_and_extra_stanzas(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            first = root / "first.deb"
            second = root / "second.deb"
            first.write_bytes(b"first package\n")
            second.write_bytes(b"second package\n")
            filenames = {
                "pool/main/o/object-storage-client/first.deb": first,
                "pool/main/o/object-storage-client/second.deb": second,
            }

            def stanza(filename: str, package: pathlib.Path) -> str:
                data = package.read_bytes()
                return "\n".join(
                    (
                        "Package: object-storage-client",
                        f"Filename: {filename}",
                        f"Size: {len(data)}",
                        f"MD5sum: {hashlib.md5(data).hexdigest()}",
                        f"SHA1: {hashlib.sha1(data).hexdigest()}",
                        f"SHA256: {hashlib.sha256(data).hexdigest()}",
                        f"SHA512: {hashlib.sha512(data).hexdigest()}",
                    )
                )

            first_stanza = stanza(next(iter(filenames)), first)
            second_stanza = stanza(next(iter(tuple(filenames)[1:])), second)
            cases = (
                ("", "one or more"),
                (first_stanza + "\nSize: 999\n", "duplicate Size"),
                (first_stanza + "\n\n" + first_stanza + "\n", "duplicate Filename"),
                (first_stanza + "\n", "exactly match"),
                (
                    first_stanza
                    + "\n\n"
                    + second_stanza
                    + "\n\n"
                    + stanza("pool/main/o/object-storage-client/extra.deb", first)
                    + "\n",
                    "exactly match",
                ),
            )
            for output, message in cases:
                with self.subTest(message=message):
                    with self.assertRaisesRegex(RuntimeError, message):
                        _validate_packages(output, filenames)

    def test_existing_pool_rejects_unexpected_files_directories_and_symlinks(self):
        cases = ("unsafe-file", "directory", "symlink")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                site = root / "site"
                pool = apt_paths(site).pool
                pool.mkdir(parents=True)
                if case == "unsafe-file":
                    (pool / "README").write_text("unexpected\n", encoding="utf-8")
                    message = "unsafe entry"
                elif case == "directory":
                    (pool / "nested.deb").mkdir()
                    message = "regular non-symlink"
                else:
                    target = root / "target.deb"
                    target.write_bytes(b"target\n")
                    (pool / "linked.deb").symlink_to(target)
                    message = "regular non-symlink"
                with self.assertRaisesRegex(RuntimeError, message):
                    self._build(root, site=site)

    def test_validsig_requires_well_formed_signing_and_primary_fingerprints(self):
        primary = "A" * 40
        subkey = "B" * 40
        common = "2026-08-24 1787529600 0 4 0 1 10 00"
        primary_status = f"[GNUPG:] VALIDSIG {primary} {common} {primary}"
        subkey_status = f"[GNUPG:] VALIDSIG {subkey} {common} {primary}"
        self.assertEqual([primary], _validsig_primary_fingerprints(primary_status))
        self.assertEqual([primary], _validsig_primary_fingerprints(subkey_status))
        self.assertEqual(
            [],
            _validsig_primary_fingerprints(
                f"[GNUPG:] VALIDSIG not-a-fingerprint {common} ignored {primary}"
            ),
        )

    def test_replace_failure_rolls_back_all_existing_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            site = self._build(root)
            paths = apt_paths(site)
            metadata = tuple(paths.binary / name for name in ("Packages", "Packages.gz")) + tuple(
                paths.release / name for name in ("Release", "InRelease", "Release.gpg")
            )
            for index, path in enumerate(metadata):
                path.write_bytes(f"old metadata {index}\n".encode())
            before = {path: path.read_bytes() for path in metadata}
            real_replace = os.replace
            publications = 0

            def fail_third_publication(source, destination):
                nonlocal publications
                if pathlib.Path(destination) in metadata:
                    publications += 1
                    if publications == 3:
                        raise OSError("simulated publication failure")
                return real_replace(source, destination)

            with mock.patch("build.linux.repository.os.replace", side_effect=fail_third_publication):
                with self.assertRaisesRegex(OSError, "publication"):
                    self._build(root, site=site)
            self.assertEqual(before, {path: path.read_bytes() for path in metadata})

    def test_directory_open_failure_rolls_back_metadata_without_fd_or_backup_leaks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            site = self._build(root)
            paths = apt_paths(site)
            metadata = tuple(paths.binary / name for name in ("Packages", "Packages.gz")) + tuple(
                paths.release / name for name in ("Release", "InRelease", "Release.gpg")
            )
            for index, path in enumerate(metadata):
                path.write_bytes(f"old open-failure metadata {index}\n".encode())
            before = {path: path.read_bytes() for path in metadata}
            descriptors_before = len(list(pathlib.Path("/proc/self/fd").iterdir()))
            real_open = os.open
            metadata_directory_opens = 0

            def fail_second_metadata_directory_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal metadata_directory_opens
                candidate = pathlib.Path(path)
                if flags & os.O_DIRECTORY and candidate in {paths.binary, paths.release}:
                    metadata_directory_opens += 1
                    if metadata_directory_opens == 2:
                        raise OSError("simulated metadata directory open failure")
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch("build.linux.repository.os.open", side_effect=fail_second_metadata_directory_open):
                with self.assertRaisesRegex(OSError, "directory open failure"):
                    self._build(root, site=site)
            self.assertEqual(before, {path: path.read_bytes() for path in metadata})
            self.assertEqual(descriptors_before, len(list(pathlib.Path("/proc/self/fd").iterdir())))
            self.assertEqual([], list(site.rglob(".*.publish-*")))
            self.assertEqual([], list(site.rglob(".*.rollback-*")))

    def test_directory_fsync_failure_rolls_back_metadata_without_fd_or_backup_leaks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            site = self._build(root)
            paths = apt_paths(site)
            metadata = tuple(paths.binary / name for name in ("Packages", "Packages.gz")) + tuple(
                paths.release / name for name in ("Release", "InRelease", "Release.gpg")
            )
            for index, path in enumerate(metadata):
                path.write_bytes(f"old fsync-failure metadata {index}\n".encode())
            before = {path: path.read_bytes() for path in metadata}
            descriptors_before = len(list(pathlib.Path("/proc/self/fd").iterdir()))
            real_fsync = os.fsync
            failed = False

            def fail_first_release_directory_fsync(descriptor):
                nonlocal failed
                target = pathlib.Path(os.readlink(f"/proc/self/fd/{descriptor}"))
                if not failed and target == paths.release:
                    failed = True
                    raise OSError("simulated metadata directory fsync failure")
                return real_fsync(descriptor)

            with mock.patch("build.linux.repository.os.fsync", side_effect=fail_first_release_directory_fsync):
                with self.assertRaisesRegex(OSError, "directory fsync failure"):
                    self._build(root, site=site)
            self.assertTrue(failed)
            self.assertEqual(before, {path: path.read_bytes() for path in metadata})
            self.assertEqual(descriptors_before, len(list(pathlib.Path("/proc/self/fd").iterdir())))
            self.assertEqual([], list(site.rglob(".*.publish-*")))
            self.assertEqual([], list(site.rglob(".*.rollback-*")))

    def test_apt_paths_are_frozen_stable_only_and_pure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary) / "site"
            paths = apt_paths(root)
            self.assertIsInstance(paths, AptPaths)
            self.assertEqual(
                root / "apt/pool/main/o/object-storage-client", paths.pool
            )
            self.assertEqual(
                root / "apt/dists/stable/main/binary-amd64", paths.binary
            )
            self.assertEqual(root / "apt/dists/stable", paths.release)
            self.assertFalse(root.exists())
            with self.assertRaises(dataclasses.FrozenInstanceError):
                paths.pool = root

    def test_rpm_paths_are_frozen_stable_x86_64_only_and_pure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary) / "site"
            paths = rpm_paths(root)
            self.assertIsInstance(paths, RpmPaths)
            self.assertEqual(root / "rpm/stable/x86_64", paths.packages)
            self.assertEqual(root / "rpm/stable/x86_64/repodata", paths.repodata)
            self.assertFalse(root.exists())
            with self.assertRaises(dataclasses.FrozenInstanceError):
                paths.packages = root

    def test_path_constructors_accept_current_directory_but_reject_unsafe_roots(self):
        self.assertEqual(
            pathlib.Path("apt/dists/stable"), apt_paths(pathlib.Path(".")).release
        )
        self.assertEqual(
            pathlib.Path("rpm/stable/x86_64"), rpm_paths(pathlib.Path(".")).packages
        )
        with self.assertRaises(ValueError):
            apt_paths(pathlib.Path("/"))
        with self.assertRaises(ValueError):
            apt_paths(pathlib.Path("site") / ".." / "elsewhere")
        with self.assertRaises(TypeError):
            apt_paths(123)

    def test_fingerprint_normalization_is_exact(self):
        self.assertEqual(
            "0123456789ABCDEF0123456789ABCDEF01234567",
            normalize_fingerprint(
                "0123 4567\t89ab\ncdef\r0123\v4567\f89ab cdef 0123 4567"
            ),
        )

    def test_fingerprint_normalization_rejects_invalid_values(self):
        values = (
            "",
            "DEADBEEF",
            "0" * 39,
            "0" * 41,
            "G" * 40,
            "0" * 39 + "é",
            None,
            123,
            b"0" * 40,
        )
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError)):
                    normalize_fingerprint(value)

    def test_throwaway_public_key_is_inspected_in_ephemeral_home(self):
        info = inspect_public_key(self.public_key)
        self.assertIsInstance(info, PublicKeyInfo)
        self.assertEqual(self.throwaway_fingerprint, info.fingerprint)
        self.assertTrue(
            any("s" in key.capabilities.lower() for key in info.signing_keys)
        )
        self.assertIsInstance(info.created, dt.datetime)
        self.assertIsInstance(info.expires, dt.datetime)
        self.assertLess(info.created, info.expires)
        self.assertEqual("-", info.validity)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            info.fingerprint = "0" * 40

    def test_public_key_verification_requires_exact_fingerprint(self):
        info = verify_public_key_fingerprint(
            self.public_key,
            " ".join(
                self.throwaway_fingerprint[index : index + 4]
                for index in range(0, 40, 4)
            ).lower(),
        )
        self.assertEqual(self.throwaway_fingerprint, info.fingerprint)
        with self.assertRaisesRegex(RuntimeError, "fingerprint.*mismatch"):
            verify_public_key_fingerprint(self.public_key, "0" * 40)

    def test_expired_key_is_rejected_at_injected_time(self):
        info = inspect_public_key(self.public_key)
        assert info.expires is not None
        with self.assertRaisesRegex(RuntimeError, "expired"):
            verify_public_key_fingerprint(
                self.public_key,
                self.throwaway_fingerprint,
                now=info.expires + dt.timedelta(seconds=1),
            )

    def test_creation_boundary_is_inclusive(self):
        output = "\n".join((_colon_record("pub"), f"fpr:::::::::{'A' * 40}:"))
        created = dt.datetime.fromtimestamp(1_000, tz=dt.timezone.utc)
        self.assertEqual(created, _verify_controlled_output(output, created).created)
        with self.assertRaisesRegex(RuntimeError, "not valid before"):
            _verify_controlled_output(output, created - dt.timedelta(microseconds=1))

    def test_expiry_boundary_is_exclusive(self):
        output = "\n".join((_colon_record("pub"), f"fpr:::::::::{'A' * 40}:"))
        expires = dt.datetime.fromtimestamp(2_000, tz=dt.timezone.utc)
        self.assertEqual(
            expires,
            _verify_controlled_output(
                output, expires - dt.timedelta(microseconds=1)
            ).expires,
        )
        with self.assertRaisesRegex(RuntimeError, "expired"):
            _verify_controlled_output(output, expires)

    def test_non_utc_aware_now_uses_the_equivalent_instant(self):
        output = "\n".join((_colon_record("pub"), f"fpr:::::::::{'A' * 40}:"))
        equivalent_creation = dt.datetime.fromtimestamp(
            1_000, tz=dt.timezone(dt.timedelta(hours=9))
        )
        self.assertEqual(
            dt.datetime.fromtimestamp(1_000, tz=dt.timezone.utc),
            _verify_controlled_output(output, equivalent_creation).created,
        )

    def test_naive_now_is_rejected(self):
        output = "\n".join((_colon_record("pub"), f"fpr:::::::::{'A' * 40}:"))
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            _verify_controlled_output(output, dt.datetime(2026, 1, 1))

    def test_unusable_primary_validity_states_are_rejected_but_dash_is_accepted(self):
        for validity in ("r", "d", "i", "e", "n"):
            with self.subTest(validity=validity):
                output = "\n".join(
                    (
                        _colon_record("pub", validity=validity),
                        f"fpr:::::::::{'A' * 40}:",
                    )
                )
                with self.assertRaisesRegex(RuntimeError, "unusable|validity"):
                    _inspect_controlled_output(output)
        accepted = "\n".join(
            (_colon_record("pub", validity="-"), f"fpr:::::::::{'A' * 40}:")
        )
        self.assertEqual("-", _inspect_controlled_output(accepted).validity)

    def test_two_concatenated_primary_public_keys_are_rejected(self):
        output = "\n".join(
            (
                _colon_record("pub"),
                f"fpr:::::::::{'A' * 40}:",
                _colon_record("pub"),
                f"fpr:::::::::{'B' * 40}:",
            )
        )
        with self.assertRaisesRegex(RuntimeError, "exactly one primary"):
            _inspect_controlled_output(output)

    def test_signing_subkey_is_accepted_without_using_its_fingerprint_as_primary(self):
        output = "\n".join(
            (
                _colon_record("pub", capabilities="c"),
                f"fpr:::::::::{'A' * 40}:",
                _colon_record("sub", capabilities="s"),
                f"fpr:::::::::{'B' * 40}:",
            )
        )
        info = _inspect_controlled_output(output)
        self.assertEqual("A" * 40, info.fingerprint)
        self.assertEqual("c", info.capabilities)

    def test_pub_and_sub_records_are_preserved_as_immutable_metadata(self):
        output = "\n".join(
            (
                _colon_record("pub", validity="-", capabilities="c"),
                f"fpr:::::::::{'A' * 40}:",
                _colon_record(
                    "sub",
                    validity="u",
                    created=1_100,
                    expires=1_900,
                    capabilities="s",
                ),
            )
        )
        info = _inspect_controlled_output(output)
        self.assertEqual(
            (
                SigningKeyRecord(
                    record_type="pub",
                    validity="-",
                    capabilities="c",
                    created=dt.datetime.fromtimestamp(1_000, tz=dt.timezone.utc),
                    expires=dt.datetime.fromtimestamp(2_000, tz=dt.timezone.utc),
                ),
                SigningKeyRecord(
                    record_type="sub",
                    validity="u",
                    capabilities="s",
                    created=dt.datetime.fromtimestamp(1_100, tz=dt.timezone.utc),
                    expires=dt.datetime.fromtimestamp(1_900, tz=dt.timezone.utc),
                ),
            ),
            info.signing_keys,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            info.signing_keys[1].validity = "r"

    def test_cert_only_primary_with_expired_signing_subkey_is_rejected(self):
        output = _key_output(
            _colon_record("sub", created=1_000, expires=1_500, capabilities="s")
        )
        with self.assertRaisesRegex(RuntimeError, "usable signing key"):
            _verify_controlled_output(
                output, dt.datetime.fromtimestamp(1_500, tz=dt.timezone.utc)
            )

    def test_future_signing_subkey_is_rejected(self):
        output = _key_output(
            _colon_record("sub", created=1_501, expires=1_900, capabilities="s")
        )
        with self.assertRaisesRegex(RuntimeError, "usable signing key"):
            _verify_controlled_output(
                output, dt.datetime.fromtimestamp(1_500, tz=dt.timezone.utc)
            )

    def test_signing_subkey_creation_is_inclusive_and_expiry_is_exclusive(self):
        output = _key_output(
            _colon_record("sub", created=1_500, expires=1_900, capabilities="s")
        )
        created = dt.datetime.fromtimestamp(1_500, tz=dt.timezone.utc)
        self.assertEqual("A" * 40, _verify_controlled_output(output, created).fingerprint)
        with self.assertRaisesRegex(RuntimeError, "usable signing key"):
            _verify_controlled_output(
                output, dt.datetime.fromtimestamp(1_900, tz=dt.timezone.utc)
            )

    def test_one_expired_and_one_valid_signing_subkey_is_accepted(self):
        output = _key_output(
            _colon_record("sub", created=1_000, expires=1_400, capabilities="s"),
            _colon_record("sub", created=1_400, expires=1_900, capabilities="s"),
        )
        now = dt.datetime.fromtimestamp(1_500, tz=dt.timezone.utc)
        self.assertEqual("A" * 40, _verify_controlled_output(output, now).fingerprint)

    def test_unusable_signing_subkey_does_not_authorize_key(self):
        for validity in ("r", "n"):
            with self.subTest(validity=validity):
                output = _key_output(
                    _colon_record(
                        "sub",
                        validity=validity,
                        created=1_000,
                        expires=1_900,
                        capabilities="s",
                    )
                )
                with self.assertRaisesRegex(RuntimeError, "usable signing key"):
                    _verify_controlled_output(
                        output, dt.datetime.fromtimestamp(1_500, tz=dt.timezone.utc)
                    )

    def test_malformed_signing_record_timestamps_and_capabilities_are_clear(self):
        malformed = (
            (
                _colon_record("sub", capabilities="s").replace(
                    ":1000:", ":later:"
                ),
                "creation",
            ),
            (
                _colon_record("sub", capabilities="s").replace(
                    ":2000:", ":never:"
                ),
                "expiry",
            ),
            (
                _colon_record("sub", capabilities="s").replace(":1000:", ":-1:"),
                "creation",
            ),
            (_colon_record("sub", capabilities=""), "capabilities"),
            (_colon_record("sub", capabilities="s!"), "capabilities"),
        )
        for record, message in malformed:
            with self.subTest(message=message, record=record):
                with self.assertRaisesRegex(RuntimeError, message):
                    _inspect_controlled_output(_key_output(record))

    def test_mixed_public_and_secret_subkey_export_is_rejected(self):
        output = "\n".join(
            (
                _colon_record("pub"),
                f"fpr:::::::::{'A' * 40}:",
                _colon_record("ssb", capabilities="s"),
                f"fpr:::::::::{'B' * 40}:",
            )
        )
        with self.assertRaisesRegex(RuntimeError, "secret"):
            _inspect_controlled_output(output)

    def test_malformed_missing_symlink_and_secret_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            malformed = root / "malformed.asc"
            malformed.write_text("not a key\n", encoding="utf-8")
            symlink = root / "key-link.asc"
            symlink.symlink_to(self.public_key)
            missing = root / "missing.asc"
            directory = root / "directory"
            directory.mkdir()
            cases = (
                (malformed, "malformed|public key"),
                (symlink, "symlink|regular"),
                (missing, "regular|exist"),
                (directory, "regular"),
                (self.secret_key, "secret"),
            )
            for path, message in cases:
                with self.subTest(path=path.name):
                    with self.assertRaisesRegex(RuntimeError, message):
                        inspect_public_key(path)

    def test_missing_gpg_has_clear_error(self):
        with self.assertRaisesRegex(RuntimeError, "gpg.*not available"):
            inspect_public_key(self.public_key, gpg="definitely-missing-gpg")

    def test_committed_public_key_has_approved_metadata_and_mode(self):
        key_path = LINUX / "repository-key.asc"
        self.assertEqual(0o644, stat.S_IMODE(key_path.stat().st_mode))
        info = verify_public_key_fingerprint(key_path, EXPECTED_FINGERPRINT)
        self.assertEqual(EXPECTED_FINGERPRINT, info.fingerprint)
        self.assertIn("s", info.capabilities.lower())
        self.assertEqual(dt.date(2029, 8, 22), info.expires.date())

    def test_foundation_parser_has_planned_contract_without_execution(self):
        parser = build_parser()
        options = parser.parse_args(
            [
                "--site-dir",
                "site",
                "--deb",
                "package.deb",
                "--rpm",
                "package.rpm",
                "--public-key",
                "repository-key.asc",
                "--expected-fingerprint",
                "0" * 40,
                "--private-key",
                "private.asc",
                "--passphrase-file",
                "passphrase",
            ]
        )
        self.assertEqual("Object Storage Client", options.origin)
        self.assertEqual("Object Storage Client", options.label)
        self.assertEqual(BASE_URL, options.base_url)

    def test_main_passes_exact_cli_values_to_both_repository_builders(self):
        arguments = [
            "--site-dir", "published-site",
            "--deb", "input.deb",
            "--rpm", "input.rpm",
            "--public-key", "public.asc",
            "--expected-fingerprint", "A" * 40,
            "--private-key", "private.asc",
            "--passphrase-file", "secret-input",
        ]
        common = {
            "site_dir": pathlib.Path("published-site"),
            "public_key": pathlib.Path("public.asc"),
            "expected_fingerprint": "A" * 40,
            "private_key": pathlib.Path("private.asc"),
            "passphrase_file": pathlib.Path("secret-input"),
        }
        with (
            mock.patch.object(repository_module, "build_apt_repository") as apt,
            mock.patch.object(repository_module, "build_rpm_repository") as rpm,
            mock.patch.object(repository_module, "_publish_site_index") as publish,
        ):
            self.assertEqual(0, repository_module.main(arguments))
        apt.assert_called_once_with(
            deb=pathlib.Path("input.deb"),
            origin="Object Storage Client",
            label="Object Storage Client",
            base_url=BASE_URL,
            **common,
        )
        rpm.assert_called_once_with(rpm_package=pathlib.Path("input.rpm"), **common)
        publish.assert_called_once_with(
            pathlib.Path("published-site"),
            pathlib.Path(repository_module.__file__).with_name("pages-index.html"),
        )

    def test_site_index_publication_rejects_symlink_source_and_atomic_failure_preserves_old_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            site = root / "site"
            site.mkdir()
            source = root / "pages-index.html"
            source.write_bytes(b"new page\n")
            source_link = root / "page-link"
            source_link.symlink_to(source)
            destination = site / "index.html"
            destination.write_bytes(b"old page\n")
            with self.assertRaisesRegex(RuntimeError, "source.*symlink|symlink.*source"):
                repository_module._publish_site_index(site, source_link)
            self.assertEqual(b"old page\n", destination.read_bytes())

            with mock.patch.object(repository_module.os, "replace", side_effect=OSError("injected")):
                with self.assertRaisesRegex(RuntimeError, "publish.*index"):
                    repository_module._publish_site_index(site, source)
            self.assertEqual(b"old page\n", destination.read_bytes())
            self.assertEqual([], list(site.glob(".index.html.*")))

            with mock.patch.object(
                repository_module,
                "_fsync_directories",
                side_effect=OSError("injected fsync failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "publish.*index"):
                    repository_module._publish_site_index(site, source)
            self.assertEqual(b"old page\n", destination.read_bytes())
            self.assertEqual([], list(site.glob(".index.html.*")))

    def _run_repository_cli(
        self,
        root: pathlib.Path,
        *,
        fail_rpm: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], pathlib.Path, pathlib.Path, pathlib.Path]:
        tools = root / "tools"
        _fake_apt_ftparchive(tools)
        _fake_rpm_tools(tools, self.throwaway_fingerprint)
        deb = root / "object-storage-client_1.2.3_amd64.deb"
        rpm = root / "object-storage-client-1.2.3-1.x86_64.rpm"
        site = root / "site"
        deb.write_bytes(b"CLI test deb package\n")
        rpm.write_bytes(b"CLI test rpm package\n")
        environment = os.environ.copy()
        environment["PATH"] = os.fspath(tools) + os.pathsep + environment["PATH"]
        environment["OSC_RPM_TOOL_LOG"] = os.fspath(root / "rpm-tool.log")
        if fail_rpm:
            environment["OSC_RPM_METADATA_FAIL"] = "1"
        arguments = [
            sys.executable,
            os.fspath(LINUX / "repository.py"),
            "--site-dir", os.fspath(site),
            "--deb", os.fspath(deb),
            "--rpm", os.fspath(rpm),
            "--public-key", os.fspath(self.public_key),
            "--expected-fingerprint", self.throwaway_fingerprint,
            "--private-key", os.fspath(self.secret_key),
            "--passphrase-file", os.fspath(self.passphrase_file),
            "--origin", "CLI Origin",
            "--label", "CLI Label",
            "--base-url", "https://packages.example.invalid/client",
        ]
        result = subprocess.run(
            arguments,
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        return result, site, deb, rpm

    def test_package_import_is_quiet_and_direct_script_help_works_when_copied(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            before = set(root.iterdir())
            environment = os.environ.copy()
            environment["PYTHONPATH"] = os.fspath(ROOT)
            imported = subprocess.run(
                [sys.executable, "-c", "import build.linux.repository"],
                cwd=root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, imported.returncode, imported.stderr)
            self.assertEqual("", imported.stdout)
            self.assertEqual("", imported.stderr)
            self.assertEqual(before, set(root.iterdir()))

            for source in (LINUX / "repository.py", LINUX / "pages-index.html"):
                shutil.copy2(source, root / source.name)
            for script in (LINUX / "repository.py", root / "repository.py"):
                with self.subTest(script=script):
                    helped = subprocess.run(
                        [sys.executable, os.fspath(script), "--help"],
                        cwd=ROOT,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(0, helped.returncode, helped.stderr)
                    self.assertIn("--site-dir", helped.stdout)
                    self.assertEqual("", helped.stderr)

    def test_direct_cli_builds_complete_signed_apt_and_rpm_site_then_publishes_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            result, site, deb, rpm = self._run_repository_cli(root)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn(self.passphrase_file.read_text().strip(), result.stdout + result.stderr)
            self.assertNotIn(self.throwaway_fingerprint, result.stdout + result.stderr)
            expected_files = {
                "apt/dists/stable/InRelease",
                "apt/dists/stable/Release",
                "apt/dists/stable/Release.gpg",
                "apt/dists/stable/main/binary-amd64/Packages",
                "apt/dists/stable/main/binary-amd64/Packages.gz",
                f"apt/pool/main/o/object-storage-client/{deb.name}",
                "index.html",
                "repository-key.asc",
                f"rpm/stable/x86_64/{rpm.name}",
                "rpm/stable/x86_64/repodata/filelists.xml.gz",
                "rpm/stable/x86_64/repodata/other.xml.gz",
                "rpm/stable/x86_64/repodata/primary.xml.gz",
                "rpm/stable/x86_64/repodata/repomd.xml",
                "rpm/stable/x86_64/repodata/repomd.xml.asc",
            }
            actual_files = {
                path.relative_to(site).as_posix()
                for path in site.rglob("*")
                if path.is_file()
            }
            self.assertEqual(expected_files, actual_files)
            for path in site.rglob("*"):
                self.assertFalse(path.is_symlink(), path)
                self.assertEqual(0o644 if path.is_file() else 0o755, stat.S_IMODE(path.stat().st_mode), path)
            self.assertEqual((LINUX / "pages-index.html").read_bytes(), (site / "index.html").read_bytes())
            self.assertEqual(self.public_key.read_bytes(), (site / "repository-key.asc").read_bytes())
            published_text = "\n".join(path.relative_to(site).as_posix() for path in site.rglob("*"))
            self.assertNotIn(self.secret_key.name, published_text)
            self.assertNotIn(self.passphrase_file.name, published_text)

            verify_home = root / "verify-home"
            verify_home.mkdir(mode=0o700)
            _run_gpg(verify_home, "--import", os.fspath(site / "repository-key.asc"))
            release = site / "apt/dists/stable/Release"
            _run_gpg(verify_home, "--verify", os.fspath(site / "apt/dists/stable/InRelease"))
            _run_gpg(verify_home, "--verify", os.fspath(site / "apt/dists/stable/Release.gpg"), os.fspath(release))
            repomd = site / "rpm/stable/x86_64/repodata/repomd.xml"
            _run_gpg(verify_home, "--verify", os.fspath(repomd.with_suffix(".xml.asc")), os.fspath(repomd))
            self.assertIn("CLI Origin", release.read_text(encoding="utf-8"))
            self.assertIn("CLI Label", release.read_text(encoding="utf-8"))
            self.assertIn("https://packages.example.invalid/client", release.read_text(encoding="utf-8"))

    def test_rpm_failure_keeps_complete_apt_generation_and_existing_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            site = root / "site"
            site.mkdir()
            old_index = b"previous committed index\n"
            (site / "index.html").write_bytes(old_index)
            result, site, deb, rpm = self._run_repository_cli(root, fail_rpm=True)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(old_index, (site / "index.html").read_bytes())
            self.assertTrue((site / f"apt/pool/main/o/object-storage-client/{deb.name}").is_file())
            self.assertTrue((site / "apt/dists/stable/InRelease").is_file())
            self.assertTrue((site / "apt/dists/stable/Release.gpg").is_file())
            self.assertFalse((site / f"rpm/stable/x86_64/{rpm.name}").exists())
            self.assertNotIn(self.passphrase_file.read_text().strip(), result.stdout + result.stderr)
            self.assertNotIn(self.throwaway_fingerprint, result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_pages_index_is_static_safe_and_complete(self):
        page = (LINUX / "pages-index.html").read_text(encoding="utf-8")
        expected = (
            f"{BASE_URL}/repository-key.asc",
            f"{BASE_URL}/apt stable main",
            f"{BASE_URL}/rpm/stable/x86_64",
            "signed-by=/etc/apt/keyrings/object-storage-client.gpg",
            "gpgcheck=1",
            "repo_gpgcheck=1",
            "https://github.com/devcode-kr/object-storage-client/releases",
            "https://github.com/devcode-kr/object-storage-client/blob/main/PRIVACY.md",
            "https://github.com/devcode-kr/object-storage-client",
            "https://github.com/devcode-kr/object-storage-client/issues",
        )
        for text in expected:
            with self.subTest(text=text):
                self.assertIn(text, page)
        lowered = page.lower()
        self.assertNotIn("<script", lowered)
        self.assertNotIn("javascript:", lowered)
        self.assertNotIn("trusted=yes", lowered)
        self.assertNotIn("--nogpgcheck", lowered)
        self.assertNotIn("curl |", lowered)
        self.assertNotIn("curl|", lowered)
        self.assertNotIn("--no-check-certificate", lowered)
        self.assertNotIn("apt-key", lowered)
        self.assertNotIn("|| true", lowered)
        self.assertNotIn("set +e", lowered)
        self.assertIn("&gt;", page)
        self.assertNotIn(" > ", page)

        apt_block = page[page.index("<h2>APT"):page.index("<h2>DNF")]
        ordered = (
            "set -eu",
            "umask 077",
            "mktemp -d",
            "trap '",
            f"wget -O \"$tmpdir/repository-key.asc\" {BASE_URL}/repository-key.asc",
            "gpg --batch --show-keys --with-colons",
            "fingerprint=",
            f'test "$fingerprint" = "{EXPECTED_FINGERPRINT}"',
            "gpg --batch --dearmor",
            "sudo install -m 0644",
        )
        positions = []
        for text in ordered:
            with self.subTest(order=text):
                self.assertIn(text, apt_block)
                positions.append(apt_block.index(text))
        self.assertEqual(sorted(positions), positions)
        self.assertIn("EXIT HUP INT TERM", apt_block)
        self.assertNotIn("wget -O repository-key.asc", apt_block)
        self.assertNotIn("/etc/apt/keyrings/object-storage-client.gpg\n", apt_block[:positions[-1]])

    def test_apt_and_dnf_bootstraps_independently_pin_exactly_one_public_key(self):
        apt_block, dnf_block = _page_bootstrap_blocks()
        approved = "\n".join(
            (_colon_record("pub"), f"fpr:::::::::{EXPECTED_FINGERPRINT}:")
        )
        two_primary = "\n".join(
            (
                approved,
                _colon_record("pub"),
                f"fpr:::::::::{'B' * 40}:",
            )
        )
        secret = "\n".join(
            (_colon_record("sec"), f"fpr:::::::::{EXPECTED_FINGERPRINT}:")
        )
        for name, block in (("APT", apt_block), ("DNF", dnf_block)):
            with self.subTest(bootstrap=name, case="approved"):
                self.assertEqual(0, _run_page_fingerprint_check(block, approved).returncode)
            for case, key_info in (("two-primary", two_primary), ("secret", secret)):
                with self.subTest(bootstrap=name, case=case):
                    self.assertNotEqual(
                        0, _run_page_fingerprint_check(block, key_info).returncode
                    )

    def test_dnf_bootstrap_verifies_private_download_before_local_key_install(self):
        _, dnf_block = _page_bootstrap_blocks()
        ordered = (
            "set -eu",
            "umask 077",
            "mktemp -d",
            "trap '",
            f'wget -O "$tmpdir/repository-key.asc" {BASE_URL}/repository-key.asc',
            "gpg --batch --show-keys --with-colons",
            "fingerprint=",
            f'test "$fingerprint" = "{EXPECTED_FINGERPRINT}"',
            "sudo install -d -m 0755 /etc/pki/rpm-gpg",
            "sudo install -m 0644",
            "file:///etc/pki/rpm-gpg/RPM-GPG-KEY-object-storage-client",
            "sudo dnf install object-storage-client",
        )
        positions = []
        for text in ordered:
            with self.subTest(order=text):
                self.assertIn(text, dnf_block)
                positions.append(dnf_block.index(text))
        self.assertEqual(sorted(positions), positions)
        self.assertIn("EXIT HUP INT TERM", dnf_block)
        self.assertNotIn(f"gpgkey={BASE_URL}/repository-key.asc", dnf_block)

    def test_repository_public_files_exclude_exact_private_key_identifiers(self):
        private_block = "BEGIN PGP " + "PRIVATE KEY BLOCK"
        secret_names = (
            "LINUX_REPO_GPG_" + "PRIVATE_KEY",
            "LINUX_REPO_GPG_" + "PASSPHRASE",
        )
        passphrase_word = "pass" + "phrase"
        public_files = (
            LINUX / "repository.py",
            LINUX / "pages-index.html",
            LINUX / "repository-key.asc",
        )
        for path in public_files:
            text = path.read_text(encoding="utf-8", errors="strict")
            with self.subTest(path=path.name):
                self.assertNotIn(private_block, text)
                self.assertNotIn(secret_names[0], text)
                self.assertNotIn(secret_names[1], text)
                if path.name != "repository.py":
                    self.assertNotIn(passphrase_word, text.lower())


if __name__ == "__main__":
    unittest.main()
