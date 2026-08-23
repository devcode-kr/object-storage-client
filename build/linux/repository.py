from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
from dataclasses import dataclass
from email.utils import format_datetime, parsedate_to_datetime
import fcntl
import gzip
import hashlib
import os
import pathlib
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

_DEFAULT_BASE_URL = "https://devcode-kr.github.io/object-storage-client"
_ASCII_WHITESPACE = " \t\n\r\v\f"
_FINGERPRINT = re.compile(r"[0-9A-F]{40}")
_KEY_CAPABILITIES = re.compile(r"[escaESCAD]+")
_UNUSABLE_VALIDITY = frozenset({"r", "d", "i", "e", "n"})
_APT_METADATA_LIFETIME = dt.timedelta(days=7)


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
class SigningKeyRecord:
    record_type: str
    validity: str
    capabilities: str
    created: dt.datetime
    expires: dt.datetime | None


@dataclass(frozen=True)
class PublicKeyInfo:
    fingerprint: str
    created: dt.datetime
    expires: dt.datetime | None
    capabilities: str
    validity: str
    signing_keys: tuple[SigningKeyRecord, ...]


def _path(value: os.PathLike[str] | str) -> pathlib.Path:
    if not isinstance(value, (str, os.PathLike)):
        raise TypeError("site root must be a path")
    if not os.fspath(value):
        raise ValueError("site root must name a directory below a filesystem root")
    root = pathlib.Path(value)
    if root.is_absolute() and root == pathlib.Path(root.anchor):
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
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+", value) is None:
        raise RuntimeError(f"public key has an invalid {field} timestamp")
    try:
        timestamp = int(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"public key has an invalid {field} timestamp") from error
    try:
        return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise RuntimeError(f"public key has an invalid {field} timestamp") from error


def _signing_key_record(fields: list[str]) -> SigningKeyRecord:
    if len(fields) <= 11 or fields[0] not in {"pub", "sub"}:
        raise RuntimeError("public key has a malformed signing key record")
    capabilities = fields[11]
    if _KEY_CAPABILITIES.fullmatch(capabilities) is None:
        raise RuntimeError(
            f"public key {fields[0]} record has malformed capabilities"
        )
    return SigningKeyRecord(
        record_type=fields[0],
        validity=fields[1],
        capabilities=capabilities,
        created=_utc_timestamp(fields[5], f"{fields[0]} creation"),
        expires=(
            _utc_timestamp(fields[6], f"{fields[0]} expiry")
            if fields[6]
            else None
        ),
    )


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
    subkey_records: list[list[str]] = []
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
            subkey_records.append(fields)
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
    signing_keys = tuple(
        _signing_key_record(signing_record)
        for signing_record in [record, *subkey_records]
    )
    primary = signing_keys[0]
    fingerprint = normalize_fingerprint(primary_fingerprints[0])
    if primary.validity.lower() in _UNUSABLE_VALIDITY:
        raise RuntimeError(
            f"public key has an unusable primary validity state: {primary.validity}"
        )
    return PublicKeyInfo(
        fingerprint=fingerprint,
        created=primary.created,
        expires=primary.expires,
        capabilities=primary.capabilities,
        validity=primary.validity,
        signing_keys=signing_keys,
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
    if instant < info.created:
        raise RuntimeError(
            f"public key is not valid before {info.created.isoformat()}"
        )
    if info.expires is not None and instant >= info.expires:
        raise RuntimeError(
            f"public key expired at {info.expires.isoformat()}"
        )
    if not any(
        "s" in key.capabilities.lower()
        and "d" not in key.capabilities.lower()
        and key.validity.lower() not in _UNUSABLE_VALIDITY
        and key.created <= instant
        and (key.expires is None or instant < key.expires)
        for key in info.signing_keys
    ):
        raise RuntimeError("public key does not have a usable signing key at this time")
    return info


_SAFE_DEB_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_~-]*\.deb")
_SAFE_RPM_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_~-]*\.rpm")
_RELEASE_FIELDS = {
    "Origin": None,
    "Label": None,
    "Suite": "stable",
    "Codename": "stable",
    "Architectures": "amd64",
    "Components": "main",
}
_RELEASE_HASH_SECTIONS = ("MD5Sum", "SHA1", "SHA256", "SHA512")
_HASH_ALGORITHMS = {
    "MD5Sum": "md5",
    "SHA1": "sha1",
    "SHA256": "sha256",
    "SHA512": "sha512",
}
_PACKAGE_HASH_FIELDS = {
    "MD5sum": "md5",
    "SHA1": "sha1",
    "SHA256": "sha256",
    "SHA512": "sha512",
}
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")


def _require_regular_file(path: pathlib.Path, description: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise RuntimeError(f"{description} path does not exist: {path}") from error
    except OSError as error:
        raise RuntimeError(f"cannot inspect {description} path: {path}") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise RuntimeError(f"{description} path must not be a symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"{description} path must be a regular file")


def _reject_symlink_components(path: pathlib.Path, description: str) -> None:
    absolute = path.absolute()
    current = pathlib.Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise RuntimeError(f"cannot inspect {description} path component: {current}") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeError(f"{description} path must not contain symlink components: {current}")


def _is_relative_to(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_digest(path: pathlib.Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _snapshot_regular_file(
    source: pathlib.Path,
    destination: pathlib.Path,
    description: str,
    *,
    mode: int,
) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as error:
        raise RuntimeError(f"cannot open {description} without following symlinks: {source}") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(f"{description} path must be a regular file")
        try:
            with os.fdopen(descriptor, "rb", closefd=False) as input_stream, destination.open("xb") as output:
                shutil.copyfileobj(input_stream, output)
                output.flush()
                os.fsync(output.fileno())
            destination.chmod(mode)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    finally:
        os.close(descriptor)


def _check_immutable_destination(source: pathlib.Path, destination: pathlib.Path) -> bool:
    try:
        metadata = destination.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"immutable destination collision is not a regular file: {destination}")
    if _sha256(source) != _sha256(destination):
        raise RuntimeError(f"immutable destination collision has different bytes: {destination}")
    return True


def _mkdir_mode(path: pathlib.Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"repository directory collision: {path}")
    path.chmod(0o755)


def _mkdir_repository_tree(site: pathlib.Path, destination: pathlib.Path) -> None:
    _mkdir_mode(site)
    current = site
    for component in destination.relative_to(site).parts:
        current /= component
        _mkdir_mode(current)


def _site_lock_path(site: pathlib.Path) -> pathlib.Path:
    resolved = site.absolute().resolve(strict=False)
    identity = hashlib.sha256(os.fsencode(resolved)).hexdigest()[:32]
    return resolved.parent / f".osc-apt-{identity}.lock"


@contextmanager
def _exclusive_site_lock(site: pathlib.Path):
    _reject_symlink_components(site, "site repository")
    resolved = site.absolute().resolve(strict=False)
    _reject_symlink_components(resolved.parent, "site lock parent")
    _mkdir_mode(resolved.parent)
    _reject_symlink_components(site, "site repository")
    lock_path = _site_lock_path(resolved)
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise RuntimeError(
            f"site lock must be a regular non-symlink file: {lock_path}"
        ) from error
    locked = False
    try:
        os.fchmod(descriptor, 0o600)
        opened = os.fstat(descriptor)
        try:
            named = lock_path.lstat()
        except OSError as error:
            raise RuntimeError(f"cannot inspect site lock file: {lock_path}") from error
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_ISLNK(named.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            or stat.S_IMODE(opened.st_mode) != 0o600
        ):
            raise RuntimeError(
                f"site lock must be the named regular non-symlink 0600 file: {lock_path}"
            )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        locked = True
        named_after_lock = lock_path.lstat()
        if (
            stat.S_ISLNK(named_after_lock.st_mode)
            or not stat.S_ISREG(named_after_lock.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (named_after_lock.st_dev, named_after_lock.st_ino)
        ):
            raise RuntimeError(f"site lock path changed while acquiring lock: {lock_path}")
        yield
    finally:
        try:
            if locked:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _copy_immutable(source: pathlib.Path, destination: pathlib.Path) -> None:
    if _check_immutable_destination(source, destination):
        destination.chmod(0o644)
        return
    _mkdir_mode(destination.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_stream:
            shutil.copyfileobj(input_stream, output)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o644)
        try:
            os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError:
            if not _check_immutable_destination(source, destination):
                raise RuntimeError(f"could not publish immutable file: {destination}")
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _run_command(
    command: list[str],
    *,
    description: str,
    cwd: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
            shell=False,
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"{description} is not available: {command[0]}") from error
    except OSError as error:
        raise RuntimeError(f"could not execute {description}: {command[0]}") from error
    if result.returncode != 0:
        raise RuntimeError(f"{description} failed with exit status {result.returncode}")
    return result


def _gpg_environment(home: pathlib.Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["GNUPGHOME"] = os.fspath(home)
    return environment


def _parse_secret_key_listing(output: str, expected: str, now: dt.datetime) -> None:
    primary_fingerprints: list[str] = []
    signing_records: list[SigningKeyRecord] = []
    secret_primary_records = 0
    secret_records = 0
    fingerprinted_records = 0
    current: list[str] | None = None
    current_type: str | None = None
    for line in output.splitlines():
        fields = line.split(":")
        record_type = fields[0] if fields else ""
        if record_type in {"sec", "ssb"}:
            secret_records += 1
            if record_type == "sec":
                secret_primary_records += 1
            current = fields
            current_type = record_type
            signing_records.append(
                _signing_key_record(["pub" if record_type == "sec" else "sub", *fields[1:]])
            )
        elif record_type == "fpr" and current is not None:
            if len(fields) <= 9:
                raise RuntimeError("private key has a malformed fingerprint")
            if current_type == "sec":
                primary_fingerprints.append(normalize_fingerprint(fields[9]))
            else:
                normalize_fingerprint(fields[9])
            fingerprinted_records += 1
            current = None
            current_type = None
    if secret_primary_records != 1 or len(primary_fingerprints) != 1:
        raise RuntimeError("private key must contain exactly one secret primary fingerprint")
    if fingerprinted_records != secret_records:
        raise RuntimeError("private key has a secret key record without a fingerprint")
    if primary_fingerprints[0] != expected:
        raise RuntimeError(
            f"private key fingerprint mismatch: expected {expected}, got {primary_fingerprints[0]}"
        )
    if not any(
        "s" in record.capabilities.lower()
        and "d" not in record.capabilities.lower()
        and record.validity.lower() not in _UNUSABLE_VALIDITY
        and record.created <= now
        and (record.expires is None or now < record.expires)
        for record in signing_records
    ):
        raise RuntimeError("private key does not have a usable signing key")


def _parse_package_stanzas(text: str, description: str) -> list[dict[str, str]]:
    if _CONTROL_CHARACTER.search(text.replace("\n", "")):
        raise RuntimeError(f"{description} contains control characters")
    stanzas = [stanza for stanza in re.split(r"\n[ \t]*\n", text.strip()) if stanza.strip()]
    if not stanzas:
        raise RuntimeError(f"{description} must contain one or more package stanzas")
    parsed: list[dict[str, str]] = []
    for stanza in stanzas:
        values: dict[str, str] = {}
        for line in stanza.splitlines():
            if not line or line.startswith((" ", "\t")) or ":" not in line:
                continue
            name, value = line.split(":", 1)
            if name in values:
                raise RuntimeError(f"{description} contains duplicate {name} fields")
            values[name] = value.strip()
        parsed.append(values)
    return parsed


def _validate_packages(text: str, packages: dict[str, pathlib.Path]) -> None:
    description = "apt-ftparchive Packages output"
    stanzas = _parse_package_stanzas(text, description)
    indexed: dict[str, dict[str, str]] = {}
    for values in stanzas:
        filename = values.get("Filename", "")
        if filename in indexed:
            raise RuntimeError(f"{description} contains duplicate Filename fields")
        indexed[filename] = values
    if set(indexed) != set(packages):
        raise RuntimeError(
            f"{description} Filename set does not exactly match the staged package pool"
        )
    for filename, package in packages.items():
        values = indexed[filename]
        if values.get("Size") != str(package.stat().st_size):
            raise RuntimeError(f"{description} has an invalid Size field for {filename}")
        for field, algorithm in _PACKAGE_HASH_FIELDS.items():
            if values.get(field, "").lower() != _file_digest(package, algorithm):
                raise RuntimeError(f"{description} has an invalid {field} hash for {filename}")


def _stage_apt_pool(
    existing_pool: pathlib.Path,
    temporary_pool: pathlib.Path,
    package: pathlib.Path,
) -> dict[str, pathlib.Path]:
    if existing_pool.exists():
        metadata = existing_pool.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError(f"existing APT package pool is not a regular directory: {existing_pool}")
        for existing in existing_pool.iterdir():
            entry = existing.lstat()
            if _SAFE_DEB_NAME.fullmatch(existing.name) is None:
                raise RuntimeError(f"existing APT package pool contains an unsafe entry: {existing}")
            if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode):
                raise RuntimeError(
                    f"existing APT package pool entry is not a regular non-symlink file: {existing}"
                )
            _snapshot_regular_file(
                existing,
                temporary_pool / existing.name,
                "existing APT package",
                mode=0o644,
            )
    staged_package = temporary_pool / package.name
    if _check_immutable_destination(package, staged_package):
        staged_package.chmod(0o644)
    else:
        _snapshot_regular_file(package, staged_package, "deb package", mode=0o644)
    prefix = "pool/main/o/object-storage-client"
    return {
        f"{prefix}/{staged.name}": staged
        for staged in sorted(temporary_pool.iterdir(), key=lambda path: path.name)
    }


def _validate_release(
    text: str,
    origin: str,
    label: str,
    description: str,
    release_root: pathlib.Path,
    build_instant: dt.datetime,
    expected_date: dt.datetime,
    expected_valid_until: dt.datetime,
) -> None:
    if _CONTROL_CHARACTER.search(text.replace("\n", "")):
        raise RuntimeError("apt-ftparchive Release output contains control characters")
    expected = {**_RELEASE_FIELDS, "Origin": origin, "Label": label, "Description": description}
    lines = text.splitlines()
    values: dict[str, str] = {}
    for line in lines:
        if ":" in line and not line.startswith((" ", "\t")):
            name, value = line.split(":", 1)
            if name in values:
                raise RuntimeError(f"apt-ftparchive Release output contains duplicate {name} fields")
            values[name] = value.strip()
    parsed_dates: dict[str, dt.datetime] = {}
    for field in ("Date", "Valid-Until"):
        value = values.get(field)
        if not value:
            raise RuntimeError(
                f"apt-ftparchive Release output has an invalid or missing {field} field"
            )
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                f"apt-ftparchive Release output has a malformed {field} field"
            ) from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError(
                f"apt-ftparchive Release output has a timezone-naive {field} field"
            )
        parsed_dates[field] = parsed.astimezone(dt.timezone.utc)
    if parsed_dates["Valid-Until"] <= parsed_dates["Date"]:
        raise RuntimeError("apt-ftparchive Release output has invalid Date and Valid-Until ordering")
    if parsed_dates["Valid-Until"] - parsed_dates["Date"] != _APT_METADATA_LIFETIME:
        raise RuntimeError("apt-ftparchive Release output freshness window is not exactly seven days")
    if parsed_dates["Valid-Until"] <= build_instant:
        raise RuntimeError("apt-ftparchive Release output is already expired at the build instant")
    if parsed_dates["Date"] != expected_date:
        raise RuntimeError("apt-ftparchive Release output Date does not match the build instant")
    if parsed_dates["Valid-Until"] != expected_valid_until:
        raise RuntimeError("apt-ftparchive Release output Valid-Until is not exactly seven days after Date")
    for name, value in expected.items():
        if values.get(name) != value:
            raise RuntimeError(f"apt-ftparchive Release output has an invalid or missing {name} field")
    required_paths = {
        "main/binary-amd64/Packages": release_root / "main/binary-amd64/Packages",
        "main/binary-amd64/Packages.gz": release_root / "main/binary-amd64/Packages.gz",
    }
    for section in _RELEASE_HASH_SECTIONS:
        marker = f"{section}:"
        try:
            index = lines.index(marker)
        except ValueError as error:
            raise RuntimeError(f"apt-ftparchive Release output is missing {section} hash section") from error
        entries: dict[str, tuple[str, str]] = {}
        for line in lines[index + 1 :]:
            if not line.startswith((" ", "\t")):
                break
            fields = line.split()
            if len(fields) != 3 or not fields[1].isdigit():
                raise RuntimeError(f"apt-ftparchive Release output has a malformed {section} hash entry")
            digest, size, relative = fields
            if relative in entries:
                raise RuntimeError(f"apt-ftparchive Release output has a duplicate {section} hash entry")
            entries[relative] = (digest.lower(), size)
        for relative, path in required_paths.items():
            expected_entry = (_file_digest(path, _HASH_ALGORITHMS[section]), str(path.stat().st_size))
            if entries.get(relative) != expected_entry:
                raise RuntimeError(
                    f"apt-ftparchive Release output has an invalid or missing {section} hash for {relative}"
                )


def _validsig_primary_fingerprints(status: str) -> list[str]:
    fingerprints: list[str] = []
    for line in status.splitlines():
        fields = line.split()
        if len(fields) == 12 and fields[0] == "[GNUPG:]" and fields[1] == "VALIDSIG":
            signing = fields[2].upper()
            primary = fields[11].upper()
            if _FINGERPRINT.fullmatch(signing) and _FINGERPRINT.fullmatch(primary):
                fingerprints.append(primary)
    return fingerprints


def _verify_repository_signatures(
    *,
    gpg: str,
    public_key: pathlib.Path,
    release: pathlib.Path,
    inrelease: pathlib.Path,
    detached: pathlib.Path,
    expected: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="osc-apt-verify-") as temporary:
        home = pathlib.Path(temporary)
        home.chmod(0o700)
        environment = _gpg_environment(home)
        base = [gpg, "--batch", "--no-tty", "--homedir", os.fspath(home)]
        _run_command(
            [*base, "--import", os.fspath(public_key)],
            description="gpg public key import for signature verification",
            env=environment,
        )
        checks = (
            ("InRelease", [os.fspath(inrelease)]),
            ("Release.gpg", [os.fspath(detached), os.fspath(release)]),
        )
        for name, arguments in checks:
            result = _run_command(
                [*base, "--status-fd", "1", "--verify", *arguments],
                description=f"gpg {name} signature verification",
                env=environment,
            )
            if expected not in _validsig_primary_fingerprints(result.stdout):
                raise RuntimeError(f"gpg {name} signature verification did not produce the expected VALIDSIG")


def _validate_release_value(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if _CONTROL_CHARACTER.search(value):
        raise ValueError(f"{name} must not contain control characters")
    return value


def _stage_publication(source: pathlib.Path, destination: pathlib.Path) -> pathlib.Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.publish-", dir=destination.parent
    )
    staged = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_stream:
            shutil.copyfileobj(input_stream, output)
            output.flush()
            os.fsync(output.fileno())
        staged.chmod(0o644)
        return staged
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def _fsync_directories(directories: list[pathlib.Path]) -> None:
    seen: set[pathlib.Path] = set()
    for directory in directories:
        if directory in seen:
            continue
        seen.add(directory)
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        fsync_error: BaseException | None = None
        try:
            os.fsync(descriptor)
        except BaseException as error:
            fsync_error = error
        try:
            os.close(descriptor)
        except BaseException:
            if fsync_error is None:
                raise
        if fsync_error is not None:
            raise fsync_error


def _fsync_repodata_tree(root: pathlib.Path) -> None:
    def fsync_path(path: pathlib.Path, *, directory: bool) -> None:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        if directory:
            flags |= os.O_DIRECTORY
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            expected_type = stat.S_ISDIR if directory else stat.S_ISREG
            if not expected_type(metadata.st_mode):
                raise RuntimeError(f"staged repodata entry has an unsafe file type: {path}")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def visit(directory: pathlib.Path) -> None:
        metadata = directory.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError(f"staged repodata entry is not a regular directory: {directory}")
        entries = sorted(directory.iterdir(), key=lambda path: path.name)
        for entry in entries:
            entry_metadata = entry.lstat()
            if stat.S_ISLNK(entry_metadata.st_mode):
                raise RuntimeError(f"staged repodata entry must not be a symlink: {entry}")
            if stat.S_ISDIR(entry_metadata.st_mode):
                visit(entry)
            elif stat.S_ISREG(entry_metadata.st_mode):
                fsync_path(entry, directory=False)
            else:
                raise RuntimeError(f"staged repodata entry has an unsafe file type: {entry}")
        fsync_path(directory, directory=True)

    visit(root)


def _chmod_repodata_tree(root: pathlib.Path) -> None:
    def visit(directory: pathlib.Path) -> None:
        metadata = directory.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError(f"staged repodata entry is not a regular directory: {directory}")
        for entry in sorted(directory.iterdir(), key=lambda path: path.name):
            entry_metadata = entry.lstat()
            if stat.S_ISLNK(entry_metadata.st_mode):
                raise RuntimeError(f"staged repodata entry must not be a symlink: {entry}")
            if stat.S_ISDIR(entry_metadata.st_mode):
                visit(entry)
            elif stat.S_ISREG(entry_metadata.st_mode):
                entry.chmod(0o644)
            else:
                raise RuntimeError(f"staged repodata entry has an unsafe file type: {entry}")
        directory.chmod(0o755)

    visit(root)


def _publish_metadata(publications: tuple[tuple[pathlib.Path, pathlib.Path], ...]) -> None:
    staged: list[tuple[pathlib.Path, pathlib.Path]] = []
    backups: dict[pathlib.Path, pathlib.Path | None] = {}
    published: list[pathlib.Path] = []
    cleanup_backups = True
    try:
        for source, destination in publications:
            staged.append((destination, _stage_publication(source, destination)))
        for destination, _ in staged:
            try:
                metadata = destination.lstat()
            except FileNotFoundError:
                backups[destination] = None
                continue
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError(
                    f"metadata destination collision is not a regular file: {destination}"
                )
            descriptor, backup_name = tempfile.mkstemp(
                prefix=f".{destination.name}.rollback-", dir=destination.parent
            )
            os.close(descriptor)
            backup = pathlib.Path(backup_name)
            backup.unlink()
            _snapshot_regular_file(
                destination, backup, "existing repository metadata", mode=0o644
            )
            backups[destination] = backup
        try:
            for destination, staged_path in staged:
                published.append(destination)
                os.replace(staged_path, destination)
            _fsync_directories([destination.parent for destination, _ in staged])
        except BaseException as publication_error:
            rollback_errors: list[BaseException] = []
            for destination in reversed(published):
                backup = backups[destination]
                try:
                    if backup is None:
                        destination.unlink(missing_ok=True)
                    else:
                        os.replace(backup, destination)
                except BaseException as rollback_error:
                    rollback_errors.append(rollback_error)
            try:
                _fsync_directories([destination.parent for destination in published])
            except BaseException as rollback_error:
                rollback_errors.append(rollback_error)
            if rollback_errors:
                cleanup_backups = False
                raise RuntimeError(
                    "metadata publication failed and rollback was incomplete"
                ) from publication_error
            raise
    finally:
        for _, staged_path in staged:
            staged_path.unlink(missing_ok=True)
        if cleanup_backups:
            for backup in backups.values():
                if backup is not None:
                    backup.unlink(missing_ok=True)


def _stage_rpm_packages(existing: pathlib.Path, staged: pathlib.Path, package: pathlib.Path) -> pathlib.Path:
    if existing.exists():
        metadata = existing.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError(f"existing RPM package directory is not a regular directory: {existing}")
        for entry in existing.iterdir():
            entry_metadata = entry.lstat()
            if entry.name == "repodata":
                if stat.S_ISLNK(entry_metadata.st_mode) or not stat.S_ISDIR(entry_metadata.st_mode):
                    raise RuntimeError("existing RPM repodata is not a regular directory")
                for metadata_file in entry.iterdir():
                    file_metadata = metadata_file.lstat()
                    if (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", metadata_file.name) is None
                            or stat.S_ISLNK(file_metadata.st_mode)
                            or not stat.S_ISREG(file_metadata.st_mode)):
                        raise RuntimeError(
                            f"existing RPM repodata entry is unsafe or not a regular non-symlink file: {metadata_file}"
                        )
                continue
            if _SAFE_RPM_NAME.fullmatch(entry.name) is None:
                raise RuntimeError(f"existing RPM package directory contains an unsafe unexpected entry: {entry}")
            if stat.S_ISLNK(entry_metadata.st_mode) or not stat.S_ISREG(entry_metadata.st_mode):
                raise RuntimeError(f"existing RPM package is not a regular non-symlink file: {entry}")
            _snapshot_regular_file(entry, staged / entry.name, "existing RPM package", mode=0o644)
    destination = staged / package.name
    if destination.exists():
        candidate_directory = staged.parent / ".new-rpm"
        _mkdir_mode(candidate_directory)
        candidate = candidate_directory / package.name
        _snapshot_regular_file(package, candidate, "rpm package", mode=0o644)
        return candidate
    _snapshot_regular_file(package, destination, "rpm package", mode=0o644)
    return destination


def _validate_repodata(
    repodata: pathlib.Path, *, require_signature: bool = False
) -> pathlib.Path:
    try:
        metadata = repodata.lstat()
    except FileNotFoundError as error:
        raise RuntimeError("createrepo_c did not create repodata") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError("createrepo_c repodata must be a regular directory")
    repomd = repodata / "repomd.xml"
    _require_regular_file(repomd, "createrepo_c repomd.xml")
    try:
        root = ET.parse(repomd).getroot()
    except (ET.ParseError, OSError) as error:
        raise RuntimeError("createrepo_c produced malformed repomd.xml") from error
    locations: dict[str, str] = {}
    for data in root.findall("{*}data"):
        kind = data.get("type", "")
        location = data.find("{*}location")
        href = location.get("href", "") if location is not None else ""
        if kind in locations:
            raise RuntimeError(f"repomd.xml contains duplicate {kind} metadata")
        locations[kind] = href
    if not {"primary", "filelists", "other"}.issubset(locations):
        raise RuntimeError("repomd.xml is missing expected primary, filelists, or other metadata")
    expected = {"repomd.xml"}
    for kind, href in locations.items():
        pure = pathlib.PurePosixPath(href)
        if pure.parent != pathlib.PurePosixPath("repodata") or _CONTROL_CHARACTER.search(href):
            raise RuntimeError(f"repomd.xml contains an unsafe {kind} metadata path")
        path = repodata / pure.name
        _require_regular_file(path, f"createrepo_c {kind} metadata")
        data_element = next(item for item in root.findall("{*}data") if item.get("type", "") == kind)
        checksum = data_element.find("{*}checksum")
        algorithm = checksum.get("type", "") if checksum is not None else ""
        if (checksum is None or algorithm not in hashlib.algorithms_available
                or (checksum.text or "").lower() != _file_digest(path, algorithm)):
            raise RuntimeError(f"repomd.xml has an invalid checksum for {kind} metadata")
        expected.add(path.name)
    if require_signature:
        _require_regular_file(repodata / "repomd.xml.asc", "rollback repomd.xml signature")
        expected.add("repomd.xml.asc")
    actual = {entry.name for entry in repodata.iterdir()}
    if actual != expected:
        raise RuntimeError("createrepo_c repodata contains unexpected or unreferenced entries")
    return repomd


def _recover_repodata_rollback(destination: pathlib.Path) -> None:
    parent = destination.parent
    try:
        parent_metadata = parent.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
        raise RuntimeError("RPM package directory is not a regular directory")
    backups = sorted(
        (entry for entry in parent.iterdir() if entry.name.startswith(".repodata.rollback-")),
        key=lambda path: path.name,
    )
    if not backups:
        return
    try:
        destination.lstat()
    except FileNotFoundError:
        live_exists = False
    else:
        live_exists = True
    if live_exists or len(backups) != 1:
        raise RuntimeError(
            "ambiguous repodata rollback state: expected one backup and no live repodata"
        )
    backup = backups[0]
    metadata = backup.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"unsafe repodata rollback backup: {backup}")
    try:
        _validate_repodata(backup, require_signature=True)
    except RuntimeError as error:
        raise RuntimeError(f"unsafe or invalid repodata rollback backup: {backup}") from error
    os.replace(backup, destination)
    _fsync_directories([parent])


def _verify_rpm_packages(rpm_tool: str, public_key: pathlib.Path, packages: list[pathlib.Path], expected: str) -> None:
    with tempfile.TemporaryDirectory(prefix="osc-rpmdb-verify-") as temporary:
        database = pathlib.Path(temporary)
        database.chmod(0o700)
        base = [rpm_tool, "--dbpath", os.fspath(database)]
        _run_command([*base, "--import", os.fspath(public_key)], description="rpm public key import")
        for package in packages:
            result = _run_command([*base, "--checksig", os.fspath(package)], description="rpm package verification")
            conclusions = [line for line in result.stdout.splitlines() if line.strip()]
            prefix = f"{package}:"
            if (
                len(conclusions) != 1
                or not conclusions[0].startswith(prefix)
                or conclusions[0][len(prefix):].split() != ["digests", "signatures", "OK"]
            ):
                raise RuntimeError(
                    f"rpm package verification did not return the expected OK conclusion: {package.name}"
                )


def _publish_repodata(source: pathlib.Path, destination: pathlib.Path) -> None:
    parent = destination.parent
    staged = pathlib.Path(tempfile.mkdtemp(prefix=".repodata.publish-", dir=parent))
    backup = pathlib.Path(tempfile.mkdtemp(prefix=".repodata.rollback-", dir=parent))
    backup.rmdir()
    had_existing = False
    try:
        staged.rmdir()
        shutil.copytree(source, staged, symlinks=True)
        _chmod_repodata_tree(staged)
        _fsync_repodata_tree(staged)
        if destination.exists():
            metadata = destination.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError("repodata destination collision is not a regular directory")
            had_existing = True
        try:
            if had_existing:
                os.replace(destination, backup)
            os.replace(staged, destination)
            _fsync_directories([parent])
        except BaseException as publication_error:
            try:
                destination_metadata = destination.lstat()
            except FileNotFoundError:
                destination_metadata = None
            try:
                backup.lstat()
            except FileNotFoundError:
                backup_exists = False
            else:
                backup_exists = True

            if had_existing and backup_exists:
                if destination_metadata is not None:
                    try:
                        if (
                            stat.S_ISDIR(destination_metadata.st_mode)
                            and not stat.S_ISLNK(destination_metadata.st_mode)
                        ):
                            shutil.rmtree(destination)
                        else:
                            destination.unlink()
                    except OSError as cleanup_error:
                        publication_error.add_note(
                            f"Could not remove failed repodata destination {destination}: {cleanup_error}"
                        )
                try:
                    os.replace(backup, destination)
                except BaseException as restore_error:
                    rollback_error = RuntimeError(
                        "repodata publication failed and rollback is incomplete; "
                        f"preserved rollback backup for recovery at {backup}"
                    )
                    rollback_error.add_note(f"Original publication error: {publication_error!r}")
                    raise rollback_error from restore_error
            elif had_existing:
                if destination_metadata is None:
                    raise RuntimeError(
                        "repodata publication failed and rollback is incomplete; "
                        "live repodata and rollback backup are both missing"
                    ) from publication_error
                # The backup rename failed before mutating the live destination.
            elif destination_metadata is not None:
                try:
                    if (
                        stat.S_ISDIR(destination_metadata.st_mode)
                        and not stat.S_ISLNK(destination_metadata.st_mode)
                    ):
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                except OSError as cleanup_error:
                    publication_error.add_note(
                        f"Could not remove failed repodata destination {destination}: {cleanup_error}"
                    )
                    raise RuntimeError(
                        "repodata publication failed and rollback is incomplete"
                    ) from publication_error
            _fsync_directories([parent])
            raise
        if had_existing:
            shutil.rmtree(backup)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
        if backup.exists() and not had_existing:
            shutil.rmtree(backup)


def build_rpm_repository(
    *,
    site_dir: os.PathLike[str] | str,
    rpm_package: os.PathLike[str] | str,
    public_key: os.PathLike[str] | str,
    expected_fingerprint: str,
    private_key: os.PathLike[str] | str,
    passphrase_file: os.PathLike[str] | str,
    createrepo_c: str = "createrepo_c",
    rpmsign: str = "rpmsign",
    rpm: str = "rpm",
    gpg: str = "gpg",
    now: dt.datetime | None = None,
) -> RpmPaths:
    site = _path(site_dir)
    _reject_symlink_components(site, "site repository")
    with _exclusive_site_lock(site):
        package = pathlib.Path(rpm_package)
        public = pathlib.Path(public_key)
        private = pathlib.Path(private_key)
        passphrase = pathlib.Path(passphrase_file)
        if _SAFE_RPM_NAME.fullmatch(package.name) is None:
            if package.suffix != ".rpm":
                raise ValueError("package filename must end in .rpm")
            raise ValueError("package must have a safe RPM filename")
        for path, description in ((package, "rpm package"), (public, "public key"),
                                  (private, "private key"), (passphrase, "passphrase file")):
            _require_regular_file(path, description)
            _reject_symlink_components(path, description)
        site_absolute = site.absolute().resolve(strict=False)
        for path in (package, public, private, passphrase):
            absolute = path.absolute().resolve(strict=False)
            if absolute == site_absolute or _is_relative_to(absolute, site_absolute):
                raise ValueError(f"site repository must not overlap input file: {path}")
        paths = rpm_paths(site)
        for path in (site / "rpm", paths.packages, paths.repodata):
            _reject_symlink_components(path, "site repository")
        tools = {}
        for name, command in (("createrepo_c", createrepo_c), ("rpmsign", rpmsign), ("rpm", rpm)):
            resolved = shutil.which(command)
            if resolved is None:
                raise RuntimeError(f"{name} is not available: {command}")
            tools[name] = resolved
        expected = normalize_fingerprint(expected_fingerprint)
        instant = now if now is not None else dt.datetime.now(tz=dt.timezone.utc)
        if not isinstance(instant, dt.datetime):
            raise TypeError("now must be a datetime")
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        instant = instant.astimezone(dt.timezone.utc).replace(microsecond=0)
        _recover_repodata_rollback(paths.repodata)
        with tempfile.TemporaryDirectory(prefix="osc-rpm-build-") as temporary:
            root = pathlib.Path(temporary)
            staged_public, staged_private, staged_passphrase = root / "repository-key.asc", root / "private.asc", root / "passphrase"
            _snapshot_regular_file(public, staged_public, "public key", mode=0o644)
            _snapshot_regular_file(private, staged_private, "private key", mode=0o600)
            _snapshot_regular_file(passphrase, staged_passphrase, "passphrase file", mode=0o600)
            info = verify_public_key_fingerprint(staged_public, expected, now=instant, gpg=gpg)
            packages = root / "rpm/stable/x86_64"
            _mkdir_mode(packages)
            staged_package = _stage_rpm_packages(paths.packages, packages, package)
            with tempfile.TemporaryDirectory(prefix="osc-rpm-sign-") as signing_temporary:
                home = pathlib.Path(signing_temporary); home.chmod(0o700)
                environment = _gpg_environment(home)
                base = [gpg, "--batch", "--no-tty", "--homedir", os.fspath(home)]
                _run_command([*base, "--pinentry-mode", "loopback", "--passphrase-file", os.fspath(staged_passphrase),
                              "--import", os.fspath(staged_private)], description="gpg private key import", env=environment)
                listing = _run_command([*base, "--with-colons", "--fingerprint", "--list-secret-keys"],
                                       description="gpg private key inspection", env=environment)
                _parse_secret_key_listing(listing.stdout, expected, instant)
                signing_created = min(key.created for key in info.signing_keys if "s" in key.capabilities.lower()
                                      and key.created <= instant and (key.expires is None or instant < key.expires))
                extra_args = (
                    "--batch --no-tty --pinentry-mode loopback "
                    f"--passphrase-file {shlex.quote(os.fspath(staged_passphrase))} "
                    f"--faked-system-time {int(signing_created.timestamp())}!"
                )
                _run_command([tools["rpmsign"], "--define", f"_gpg_name {expected}",
                              "--define", "_openpgp_sign gpg",
                              "--define", f"_openpgp_sign_id {expected}", "--define", f"_gpg_path {home}",
                              "--define", f"_gpg_sign_cmd_extra_args {extra_args}",
                              "--addsign", os.fspath(staged_package)],
                             description="rpmsign package signing", cwd=packages, env=environment)
            staged_package.chmod(0o644)
            package_in_tree = packages / package.name
            if staged_package != package_in_tree:
                if not _check_immutable_destination(staged_package, package_in_tree):
                    raise RuntimeError(f"immutable destination collision has different bytes: {package_in_tree}")
                staged_package.unlink()
                staged_package = package_in_tree
            staged_rpms = sorted(packages.glob("*.rpm"), key=lambda path: path.name)
            _verify_rpm_packages(tools["rpm"], staged_public, staged_rpms, expected)
            _run_command([tools["createrepo_c"], "--update", os.fspath(packages)],
                         description="createrepo_c repository metadata", cwd=packages.parent)
            repomd = _validate_repodata(packages / "repodata")
            signature = repomd.parent / "repomd.xml.asc"
            with tempfile.TemporaryDirectory(prefix="osc-rpm-metadata-sign-") as signing_temporary:
                home = pathlib.Path(signing_temporary); home.chmod(0o700); environment = _gpg_environment(home)
                base = [gpg, "--batch", "--no-tty", "--homedir", os.fspath(home)]
                _run_command([*base, "--pinentry-mode", "loopback", "--passphrase-file", os.fspath(staged_passphrase),
                              "--import", os.fspath(staged_private)], description="gpg private key import", env=environment)
                _run_command([*base, "--yes", "--armor", "--pinentry-mode", "loopback", "--passphrase-file",
                              os.fspath(staged_passphrase), "--local-user", expected, "--output", os.fspath(signature),
                              "--detach-sign", os.fspath(repomd)], description="gpg repomd.xml signing", env=environment)
            signature.chmod(0o644)
            with tempfile.TemporaryDirectory(prefix="osc-rpm-metadata-verify-") as verify_temporary:
                home = pathlib.Path(verify_temporary); home.chmod(0o700); environment = _gpg_environment(home)
                base = [gpg, "--batch", "--no-tty", "--homedir", os.fspath(home)]
                _run_command([*base, "--import", os.fspath(staged_public)], description="gpg public key import for signature verification", env=environment)
                result = _run_command([*base, "--status-fd", "1", "--verify", os.fspath(signature), os.fspath(repomd)],
                                      description="gpg repomd.xml signature verification", env=environment)
                if expected not in _validsig_primary_fingerprints(result.stdout):
                    raise RuntimeError("gpg repomd.xml signature verification did not produce expected VALIDSIG")
            _mkdir_repository_tree(site, paths.packages)
            _copy_immutable(staged_package, paths.packages / package.name)
            _copy_immutable(staged_public, site / "repository-key.asc")
            _publish_repodata(packages / "repodata", paths.repodata)
        return paths


def build_apt_repository(
    *,
    site_dir: os.PathLike[str] | str,
    deb: os.PathLike[str] | str,
    public_key: os.PathLike[str] | str,
    expected_fingerprint: str,
    private_key: os.PathLike[str] | str,
    passphrase_file: os.PathLike[str] | str,
    origin: str = "Object Storage Client",
    label: str = "Object Storage Client",
    base_url: str = _DEFAULT_BASE_URL,
    apt_ftparchive: str = "apt-ftparchive",
    gpg: str = "gpg",
    now: dt.datetime | None = None,
) -> AptPaths:
    site = _path(site_dir)
    _reject_symlink_components(site, "site repository")
    with _exclusive_site_lock(site):
        return _build_apt_repository_locked(
            site_dir=site,
            deb=deb,
            public_key=public_key,
            expected_fingerprint=expected_fingerprint,
            private_key=private_key,
            passphrase_file=passphrase_file,
            origin=origin,
            label=label,
            base_url=base_url,
            apt_ftparchive=apt_ftparchive,
            gpg=gpg,
            now=now,
        )


def _build_apt_repository_locked(
    *,
    site_dir: os.PathLike[str] | str,
    deb: os.PathLike[str] | str,
    public_key: os.PathLike[str] | str,
    expected_fingerprint: str,
    private_key: os.PathLike[str] | str,
    passphrase_file: os.PathLike[str] | str,
    origin: str = "Object Storage Client",
    label: str = "Object Storage Client",
    base_url: str = _DEFAULT_BASE_URL,
    apt_ftparchive: str = "apt-ftparchive",
    gpg: str = "gpg",
    now: dt.datetime | None = None,
) -> AptPaths:
    site = _path(site_dir)
    package = pathlib.Path(deb)
    public = pathlib.Path(public_key)
    private = pathlib.Path(private_key)
    passphrase = pathlib.Path(passphrase_file)
    if _SAFE_DEB_NAME.fullmatch(package.name) is None:
        if package.suffix != ".deb":
            raise ValueError("package filename must end in .deb")
        raise ValueError("package must have a safe Debian filename")
    for path, description in (
        (package, "deb package"),
        (public, "public key"),
        (private, "private key"),
        (passphrase, "passphrase file"),
    ):
        _require_regular_file(path, description)
        _reject_symlink_components(path, description)
    paths = apt_paths(site)
    _reject_symlink_components(site, "site repository")
    site_absolute = site.absolute().resolve(strict=False)
    for path in (package, public, private, passphrase):
        input_absolute = path.absolute().resolve(strict=False)
        if input_absolute == site_absolute or _is_relative_to(input_absolute, site_absolute):
            raise ValueError(f"site repository must not overlap input file: {path}")
    for path in (site / "apt", paths.pool, paths.binary, paths.release):
        _reject_symlink_components(path, "site repository")
    if site.exists() and not site.is_dir():
        raise RuntimeError("site repository root must be a directory")
    origin = _validate_release_value("origin", origin)
    label = _validate_release_value("label", label)
    base_url = _validate_release_value("base_url", base_url)
    expected = normalize_fingerprint(expected_fingerprint)
    instant = now if now is not None else dt.datetime.now(tz=dt.timezone.utc)
    if not isinstance(instant, dt.datetime):
        raise TypeError("now must be a datetime")
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    instant = instant.astimezone(dt.timezone.utc).replace(microsecond=0)

    package_destination = paths.pool / package.name
    key_destination = site / "repository-key.asc"
    apt_tool = shutil.which(apt_ftparchive)
    if apt_tool is None:
        raise RuntimeError(f"apt-ftparchive is not available: {apt_ftparchive}")

    with tempfile.TemporaryDirectory(prefix="osc-apt-build-") as temporary:
        temporary_root = pathlib.Path(temporary)
        staged_public = temporary_root / "repository-key.asc"
        staged_private = temporary_root / "private-key.asc"
        staged_passphrase = temporary_root / "passphrase"
        _snapshot_regular_file(public, staged_public, "public key", mode=0o644)
        _snapshot_regular_file(private, staged_private, "private key", mode=0o600)
        _snapshot_regular_file(passphrase, staged_passphrase, "passphrase file", mode=0o600)
        verify_public_key_fingerprint(staged_public, expected, now=instant, gpg=gpg)

        build_root = temporary_root / "apt"
        temporary_pool = build_root / "pool/main/o/object-storage-client"
        temporary_binary = build_root / "dists/stable/main/binary-amd64"
        temporary_release = build_root / "dists/stable"
        for directory in (temporary_pool, temporary_binary):
            _mkdir_mode(directory)
        staged_packages = _stage_apt_pool(paths.pool, temporary_pool, package)
        temporary_package = temporary_pool / package.name
        packages_result = _run_command(
            [apt_tool, "packages", "pool/main/o/object-storage-client"],
            description="apt-ftparchive packages",
            cwd=build_root,
        )
        _validate_packages(packages_result.stdout, staged_packages)
        packages_path = temporary_binary / "Packages"
        packages_path.write_text(packages_result.stdout, encoding="utf-8", newline="\n")
        packages_path.chmod(0o644)
        os.utime(packages_path, (0, 0))
        packages_gzip = temporary_binary / "Packages.gz"
        with packages_path.open("rb") as source, packages_gzip.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                shutil.copyfileobj(source, compressed)
        packages_gzip.chmod(0o644)
        os.utime(packages_gzip, (0, 0))

        description = f"Object Storage Client APT repository at {base_url}"
        valid_until = instant + _APT_METADATA_LIFETIME
        options = {
            "Origin": origin,
            "Label": label,
            "Suite": "stable",
            "Codename": "stable",
            "Architectures": "amd64",
            "Components": "main",
            "Description": description,
            "Date": format_datetime(instant, usegmt=True),
            "Valid-Until": format_datetime(valid_until, usegmt=True),
        }
        release_command = [apt_tool]
        for name, value in options.items():
            release_command.extend(("-o", f"APT::FTPArchive::Release::{name}={value}"))
        release_command.extend(("release", "dists/stable"))
        release_result = _run_command(
            release_command,
            description="apt-ftparchive release",
            cwd=build_root,
        )
        _validate_release(
            release_result.stdout,
            origin,
            label,
            description,
            temporary_release,
            instant,
            instant,
            valid_until,
        )
        release_path = temporary_release / "Release"
        release_path.write_text(release_result.stdout, encoding="utf-8", newline="\n")
        release_path.chmod(0o644)

        with tempfile.TemporaryDirectory(prefix="osc-apt-sign-") as signing_temporary:
            signing_home = pathlib.Path(signing_temporary)
            signing_home.chmod(0o700)
            environment = _gpg_environment(signing_home)
            base = [gpg, "--batch", "--no-tty", "--homedir", os.fspath(signing_home)]
            _run_command(
                [
                    *base,
                    "--pinentry-mode",
                    "loopback",
                    "--passphrase-file",
                    os.fspath(staged_passphrase),
                    "--import",
                    os.fspath(staged_private),
                ],
                description="gpg private key import",
                env=environment,
            )
            listing = _run_command(
                [*base, "--with-colons", "--fingerprint", "--list-secret-keys"],
                description="gpg private key inspection",
                env=environment,
            )
            _parse_secret_key_listing(listing.stdout, expected, instant)
            inrelease = temporary_release / "InRelease"
            detached = temporary_release / "Release.gpg"
            signing_options = [
                *base,
                "--yes",
                "--armor",
                "--pinentry-mode",
                "loopback",
                "--passphrase-file",
                os.fspath(staged_passphrase),
                "--local-user",
                expected,
            ]
            _run_command(
                [*signing_options, "--output", os.fspath(inrelease), "--clearsign", os.fspath(release_path)],
                description="gpg InRelease signing",
                env=environment,
            )
            _run_command(
                [*signing_options, "--output", os.fspath(detached), "--detach-sign", os.fspath(release_path)],
                description="gpg Release.gpg signing",
                env=environment,
            )
        for signed in (inrelease, detached):
            signed.chmod(0o644)
        _verify_repository_signatures(
            gpg=gpg,
            public_key=staged_public,
            release=release_path,
            inrelease=inrelease,
            detached=detached,
            expected=expected,
        )

        _mkdir_repository_tree(site, paths.pool)
        _mkdir_repository_tree(site, paths.binary)
        _copy_immutable(temporary_package, package_destination)
        _copy_immutable(staged_public, key_destination)
        for directory in (paths.binary, paths.release):
            _mkdir_repository_tree(site, directory)
        publications = (
            (packages_path, paths.binary / "Packages"),
            (packages_gzip, paths.binary / "Packages.gz"),
            (release_path, paths.release / "Release"),
            (inrelease, paths.release / "InRelease"),
            (detached, paths.release / "Release.gpg"),
        )
        _publish_metadata(publications)
    return paths


def _open_path_nofollow(
    path: pathlib.Path,
    *,
    final_flags: int,
    final_kind: str,
) -> int:
    """Open path components without ever re-resolving an opened parent."""
    if not os.fspath(path) or ".." in path.parts:
        raise ValueError("path must not be empty or contain parent-directory components")
    absolute = path.is_absolute()
    components = path.parts[1:] if absolute else path.parts
    if not components:
        raise ValueError("path must name an entry below a filesystem root")
    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(path.anchor if absolute else ".", directory_flags)
    try:
        for component in components[:-1]:
            child = os.open(component, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        opened = os.open(
            components[-1],
            final_flags | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=descriptor,
        )
    finally:
        os.close(descriptor)
    try:
        metadata = os.fstat(opened)
    except BaseException:
        os.close(opened)
        raise
    expected = stat.S_ISREG if final_kind == "regular" else stat.S_ISDIR
    if not expected(metadata.st_mode):
        os.close(opened)
        raise RuntimeError(f"path must name a non-symlink {final_kind} file")
    return opened


def _unlink_index_name(directory_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=directory_fd)
    except FileNotFoundError:
        pass


def _copy_index_source(source_fd: int, destination_fd: int) -> None:
    os.lseek(source_fd, 0, os.SEEK_SET)
    while True:
        block = os.read(source_fd, 1024 * 1024)
        if not block:
            break
        view = memoryview(block)
        while view:
            written = os.write(destination_fd, view)
            if written <= 0:
                raise OSError("short write while publishing site index")
            view = view[written:]
    os.fchmod(destination_fd, 0o644)
    os.fsync(destination_fd)


def _publish_index_at(site_fd: int, source_fd: int) -> None:
    index_name = "index.html"
    token = uuid.uuid4().hex
    temporary_name = f".index.html.tmp-{token}"
    backup_name = f".index.html.backup-{token}"
    temporary_fd: int | None = None
    backup_exists = False
    old_index_exists = False
    replaced = False
    try:
        try:
            old_metadata = os.stat(index_name, dir_fd=site_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(old_metadata.st_mode):
                raise RuntimeError("existing site index must be a regular non-symlink file")
            old_index_exists = True
            os.link(
                index_name,
                backup_name,
                src_dir_fd=site_fd,
                dst_dir_fd=site_fd,
                follow_symlinks=False,
            )
            backup_exists = True

        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=site_fd,
        )
        _copy_index_source(source_fd, temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None
        replaced = True
        os.replace(
            temporary_name,
            index_name,
            src_dir_fd=site_fd,
            dst_dir_fd=site_fd,
        )
        os.fsync(site_fd)
        metadata = os.stat(index_name, dir_fd=site_fd, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o644:
            raise RuntimeError("published site index must be a regular non-symlink 0644 file")
        if backup_exists:
            os.unlink(backup_name, dir_fd=site_fd)
            backup_exists = False
    except BaseException:
        if temporary_fd is not None:
            os.close(temporary_fd)
            temporary_fd = None
        if replaced:
            if old_index_exists and backup_exists:
                os.replace(
                    backup_name,
                    index_name,
                    src_dir_fd=site_fd,
                    dst_dir_fd=site_fd,
                )
                _unlink_index_name(site_fd, backup_name)
                backup_exists = False
            elif not old_index_exists:
                _unlink_index_name(site_fd, index_name)
            os.fsync(site_fd)
        raise
    finally:
        if temporary_fd is not None:
            os.close(temporary_fd)
        _unlink_index_name(site_fd, temporary_name)
        if backup_exists:
            _unlink_index_name(site_fd, backup_name)


def _publish_site_index(
    site_dir: os.PathLike[str] | str,
    source_page: os.PathLike[str] | str,
) -> pathlib.Path:
    site = _path(site_dir)
    source = pathlib.Path(source_page)
    destination = site / "index.html"
    try:
        source_fd = _open_path_nofollow(
            source, final_flags=os.O_RDONLY, final_kind="regular"
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise RuntimeError("could not safely open non-symlink site index source") from error
    try:
        with _exclusive_site_lock(site):
            try:
                site_fd = _open_path_nofollow(
                    site,
                    final_flags=os.O_RDONLY | os.O_DIRECTORY,
                    final_kind="directory",
                )
            except (OSError, RuntimeError, ValueError) as error:
                raise RuntimeError("could not safely open site repository") from error
            try:
                _publish_index_at(site_fd, source_fd)
            except (OSError, RuntimeError, ValueError) as error:
                raise RuntimeError("could not publish site index") from error
            finally:
                os.close(site_fd)
    finally:
        os.close(source_fd)
    return destination


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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    options = parser.parse_args(argv)
    common = {
        "site_dir": options.site_dir,
        "public_key": options.public_key,
        "expected_fingerprint": options.expected_fingerprint,
        "private_key": options.private_key,
        "passphrase_file": options.passphrase_file,
    }
    try:
        build_apt_repository(
            deb=options.deb,
            origin=options.origin,
            label=options.label,
            base_url=options.base_url,
            **common,
        )
    except (RuntimeError, ValueError, OSError):
        print("APT repository build failed", file=sys.stderr)
        return 1
    try:
        build_rpm_repository(rpm_package=options.rpm, **common)
    except (RuntimeError, ValueError, OSError):
        print("RPM repository build failed", file=sys.stderr)
        return 1
    source_page = pathlib.Path(__file__).with_name("pages-index.html")
    try:
        _publish_site_index(options.site_dir, source_page)
    except (RuntimeError, ValueError, OSError):
        print("site index publication failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
