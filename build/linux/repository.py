from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
import os
import pathlib
import re
import stat
import subprocess
import tempfile

_DEFAULT_BASE_URL = "https://devcode-kr.github.io/object-storage-client"
_ASCII_WHITESPACE = " \t\n\r\v\f"
_FINGERPRINT = re.compile(r"[0-9A-F]{40}")


@dataclass(frozen=True)
class AptPaths:
    pool: pathlib.Path
    binary: pathlib.Path
    release: pathlib.Path


@dataclass(frozen=True)
class RpmPaths:
    packages: pathlib.Path
    repodata: pathlib.Path


@dataclass(frozen=True)
class PublicKeyInfo:
    fingerprint: str
    created: dt.datetime
    expires: dt.datetime | None
    capabilities: str


def _path(value: os.PathLike[str] | str) -> pathlib.Path:
    if not isinstance(value, (str, os.PathLike)):
        raise TypeError("site root must be a path")
    root = pathlib.Path(value)
    if not os.fspath(root) or root == pathlib.Path(root.anchor):
        raise ValueError("site root must name a directory below a filesystem root")
    if ".." in root.parts:
        raise ValueError("site root must not contain a parent-directory component")
    return root


def apt_paths(site_root: os.PathLike[str] | str) -> AptPaths:
    root = _path(site_root)
    return AptPaths(
        pool=root / "apt" / "pool" / "main" / "o" / "object-storage-client",
        binary=root / "apt" / "dists" / "stable" / "main" / "binary-amd64",
        release=root / "apt" / "dists" / "stable",
    )


def rpm_paths(site_root: os.PathLike[str] | str) -> RpmPaths:
    root = _path(site_root)
    packages = root / "rpm" / "stable" / "x86_64"
    return RpmPaths(packages=packages, repodata=packages / "repodata")


def normalize_fingerprint(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("fingerprint must be a string")
    normalized = value.translate({ord(character): None for character in _ASCII_WHITESPACE})
    normalized = normalized.upper()
    if _FINGERPRINT.fullmatch(normalized) is None:
        raise ValueError("fingerprint must contain exactly 40 hexadecimal characters")
    return normalized


def _utc_timestamp(value: str, field: str) -> dt.datetime:
    try:
        timestamp = int(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"public key has an invalid {field} timestamp") from error
    try:
        return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise RuntimeError(f"public key has an invalid {field} timestamp") from error


def _regular_non_symlink(path: pathlib.Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise RuntimeError(f"public key path does not exist: {path}") from error
    except OSError as error:
        raise RuntimeError(f"cannot inspect public key path: {path}") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise RuntimeError("public key path must not be a symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("public key path must be a regular file")


def inspect_public_key(
    public_key: os.PathLike[str] | str,
    *,
    gpg: str = "gpg",
) -> PublicKeyInfo:
    path = pathlib.Path(public_key)
    _regular_non_symlink(path)

    with tempfile.TemporaryDirectory(prefix="osc-repository-gpg-") as temporary:
        home = pathlib.Path(temporary)
        home.chmod(0o700)
        environment = os.environ.copy()
        environment["GNUPGHOME"] = os.fspath(home)
        command = [
            gpg,
            "--batch",
            "--no-tty",
            "--homedir",
            os.fspath(home),
            "--with-colons",
            "--import-options",
            "show-only",
            "--import",
            os.fspath(path),
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                shell=False,
            )
        except FileNotFoundError as error:
            raise RuntimeError(f"gpg is not available: {gpg}") from error
        except OSError as error:
            raise RuntimeError(f"could not execute gpg: {gpg}") from error

    if result.returncode != 0:
        raise RuntimeError("malformed public key or gpg could not inspect it")

    public_records: list[list[str]] = []
    primary_fingerprints: list[str] = []
    secret_records = 0
    current_key_record: str | None = None
    for line in result.stdout.splitlines():
        fields = line.split(":")
        record = fields[0] if fields else ""
        if record in {"sec", "ssb"}:
            secret_records += 1
            current_key_record = record
        elif record == "pub":
            public_records.append(fields)
            current_key_record = record
        elif record == "sub":
            current_key_record = record
        elif record == "fpr" and current_key_record == "pub":
            if len(fields) <= 9:
                raise RuntimeError("public key has a malformed primary fingerprint")
            primary_fingerprints.append(fields[9])

    if secret_records:
        raise RuntimeError("secret key input is not accepted; provide a public key export")
    if len(public_records) != 1 or len(primary_fingerprints) != 1:
        raise RuntimeError("public key must contain exactly one primary public key and fingerprint")

    record = public_records[0]
    if len(record) <= 11:
        raise RuntimeError("public key record is malformed")
    fingerprint = normalize_fingerprint(primary_fingerprints[0])
    created = _utc_timestamp(record[5], "creation")
    expires = _utc_timestamp(record[6], "expiry") if record[6] else None
    capabilities = record[11]
    if "s" not in capabilities.lower():
        raise RuntimeError("public key does not have signing capability")
    return PublicKeyInfo(
        fingerprint=fingerprint,
        created=created,
        expires=expires,
        capabilities=capabilities,
    )


def verify_public_key_fingerprint(
    public_key: os.PathLike[str] | str,
    expected_fingerprint: str,
    *,
    now: dt.datetime | None = None,
    gpg: str = "gpg",
) -> PublicKeyInfo:
    expected = normalize_fingerprint(expected_fingerprint)
    info = inspect_public_key(public_key, gpg=gpg)
    if info.fingerprint != expected:
        raise RuntimeError(
            f"public key fingerprint mismatch: expected {expected}, got {info.fingerprint}"
        )
    instant = now if now is not None else dt.datetime.now(tz=dt.timezone.utc)
    if not isinstance(instant, dt.datetime):
        raise TypeError("now must be a datetime")
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if info.expires is not None and instant >= info.expires:
        raise RuntimeError(
            f"public key expired at {info.expires.isoformat()}"
        )
    return info


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build signed Object Storage Client Linux repositories"
    )
    parser.add_argument("--site-dir", type=pathlib.Path, required=True)
    parser.add_argument("--deb", type=pathlib.Path, required=True)
    parser.add_argument("--rpm", type=pathlib.Path, required=True)
    parser.add_argument("--public-key", type=pathlib.Path, required=True)
    parser.add_argument("--expected-fingerprint", required=True)
    parser.add_argument("--private-key", type=pathlib.Path, required=True)
    parser.add_argument("--passphrase-file", type=pathlib.Path, required=True)
    parser.add_argument("--origin", default="Object Storage Client")
    parser.add_argument("--label", default="Object Storage Client")
    parser.add_argument("--base-url", default=_DEFAULT_BASE_URL)
    return parser
