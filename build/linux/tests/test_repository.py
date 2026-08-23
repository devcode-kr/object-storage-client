from __future__ import annotations

import dataclasses
import datetime as dt
import os
import pathlib
import stat
import subprocess
import tempfile
import unittest

from build.linux.repository import (
    AptPaths,
    PublicKeyInfo,
    RpmPaths,
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
        self.assertIn("&gt;", page)
        self.assertNotIn(" > ", page)

    def test_committed_public_files_do_not_contain_private_material(self):
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
