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
            raise ValueError(
                f"application version must be Major.Minor.Patch: {application!r}"
            )
        if isinstance(package_release, bool) or not isinstance(package_release, int):
            raise ValueError("package release must be an integer")
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
