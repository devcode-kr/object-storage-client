from __future__ import annotations

import dataclasses
import datetime as dt
import html
import os
import pathlib
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from build.linux.repository import (
    AptPaths,
    PublicKeyInfo,
    RpmPaths,
    SigningKeyRecord,
    apt_paths,
    build_parser,
    inspect_public_key,
    normalize_fingerprint,
    rpm_paths,
    verify_public_key_fingerprint,
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
        _run_gpg(
            cls.gnupg_home,
            "--passphrase",
            "",
            "--quick-generate-key",
            "Repository Test <repository-test@example.invalid>",
            "rsa2048",
            "sign",
            "3y",
        )
        listing = _run_gpg(cls.gnupg_home, "--with-colons", "--list-keys").stdout
        fingerprints = [
            fields[9]
            for line in listing.splitlines()
            if (fields := line.split(":"))[0] == "fpr"
        ]
        if len(fingerprints) != 1:
            raise RuntimeError("throwaway key did not have exactly one fingerprint")
        cls.throwaway_fingerprint = fingerprints[0]
        cls.public_key.write_text(
            _run_gpg(
                cls.gnupg_home, "--armor", "--export", cls.throwaway_fingerprint
            ).stdout,
            encoding="ascii",
        )
        cls.secret_key.write_text(
            _run_gpg(
                cls.gnupg_home,
                "--armor",
                "--export-secret-keys",
                cls.throwaway_fingerprint,
            ).stdout,
            encoding="ascii",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._keys.cleanup()

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
        self.assertIn("s", info.capabilities.lower())
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
