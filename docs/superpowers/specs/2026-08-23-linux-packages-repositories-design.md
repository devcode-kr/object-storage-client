# Linux packages and repositories design

**Date:** 2026-08-23  
**Status:** Approved design pending implementation plan  
**Target release:** 1.0.0 and later

## Goal

Distribute Object Storage Client for x86-64 Linux as native Debian and RPM packages, publish signed stable APT and DNF/YUM repositories through this repository's GitHub Pages site, and let the operating system package manager handle updates.

## Supported systems

The first supported package set covers:

- Debian 12 and newer;
- Ubuntu 22.04 and newer;
- Fedora 44 and Fedora 43 for the initial implementation, updated deliberately in later packaging changes as Fedora releases age out;
- Rocky Linux 9;
- AlmaLinux 9;
- RHEL 9, with final pre-release validation performed manually on a subscribed RHEL system.

Only `amd64`/`x86_64` is supported. The packages require a graphical desktop with X11 or XWayland. Other architectures and distributions are outside this design.

## Non-goals

- The application will not download, install, or prompt for its own updates.
- The packages will not enable `unattended-upgrades`, `dnf-automatic`, or change the host's update policy.
- There will be no testing, nightly, or preview repository channel.
- The first implementation will not publish to Debian, Ubuntu, Fedora, EPEL, or Red Hat's official repositories.
- The packages will not delete `~/.devcode/object-storage-client/` during removal or upgrade.
- RHEL subscription infrastructure will not be placed in public CI.

## Package identity and versions

The package name, command, desktop-file basename, and icon name are all `object-storage-client`.

The application version remains the three-part value from `Directory.Build.props`, such as `1.0.0`. Native package versions add a packaging release number:

- Debian: `1.0.0-1`;
- RPM: `Version: 1.0.0`, `Release: 1`;
- Microsoft Store remains `1.0.0.0`.

A packaging-only correction increments the Debian revision and RPM release without changing the application or Store version. A source release resets the packaging release to `1`.

## Installed layout

Both package formats install the same application payload:

```text
/usr/lib/object-storage-client/
  ObjectStorageClient.App
  ObjectStorageClient.App.dll
  ObjectStorageClient.Core.dll
  remaining self-contained publish output

/usr/bin/object-storage-client
/usr/share/applications/object-storage-client.desktop
/usr/share/icons/hicolor/256x256/apps/object-storage-client.png
/usr/share/doc/object-storage-client/
  README.md
  PRIVACY.md
  LICENSE
```

`/usr/bin/object-storage-client` is a small launcher that executes `/usr/lib/object-storage-client/ObjectStorageClient.App` without depending on the caller's working directory.

The desktop entry uses:

```ini
Name=Object Storage Client
Exec=object-storage-client
Icon=object-storage-client
Type=Application
Categories=Network;FileTransfer;
Terminal=false
```

The icon comes from the existing committed 256×256 RGBA application icon at `src/ObjectStorageClient.App/Assets/appicon.png`.

The application continues to store user-owned state at `~/.devcode/object-storage-client/`. Package install, upgrade, downgrade, and removal scripts must not read, migrate, or delete that directory.

## Native dependencies

The Debian package declares:

```text
libx11-6, libice6, libsm6, libfontconfig1, ca-certificates
```

The RPM package declares:

```text
libX11, libICE, libSM, fontconfig, ca-certificates
```

The application is self-contained and does not depend on a separately installed .NET runtime. CJK fonts and XWayland are documented optional environment dependencies rather than forced package dependencies.

## Build components

Packaging uses distribution-native tools inside containers:

- `dotnet publish` produces one `linux-x64` self-contained payload;
- `dpkg-deb` creates the Debian package;
- `rpmbuild` creates the RPM package;
- `apt-ftparchive` creates APT indexes and Release metadata;
- `createrepo_c` creates DNF/YUM repository metadata;
- GnuPG signs APT and RPM repository metadata;
- `rpmsign` signs the RPM package.

No fpm or nFPM dependency is introduced. Packaging scripts are separated by responsibility: payload staging, Debian metadata, RPM specification, repository indexing, signing, and contract validation.

## Public repository layout

GitHub Pages serves the `gh-pages` branch at:

```text
https://devcode-kr.github.io/object-storage-client/
```

The branch contains:

```text
apt/
  pool/main/o/object-storage-client/*.deb
  dists/stable/main/binary-amd64/Packages
  dists/stable/main/binary-amd64/Packages.gz
  dists/stable/Release
  dists/stable/InRelease
  dists/stable/Release.gpg

rpm/
  stable/x86_64/*.rpm
  stable/x86_64/repodata/
  stable/x86_64/repodata/repomd.xml.asc

repository-key.asc
index.html
```

Old package versions remain available so an existing repository index and explicit downgrade remain reproducible. Repository metadata ranks the newest valid package version normally.

Users configure APT with a `signed-by` keyring and the stable component:

```text
deb [arch=amd64 signed-by=/etc/apt/keyrings/object-storage-client.gpg] https://devcode-kr.github.io/object-storage-client/apt stable main
```

Users configure DNF with `gpgcheck=1`, `repo_gpgcheck=1`, the stable x86-64 base URL, and the published key URL. Installation documentation must not recommend `trusted=yes`, `--nogpgcheck`, or disabling repository metadata verification.

## Signing and key handling

An existing deployment GPG key is reused. Private key material and its passphrase exist only as GitHub Repository Secrets:

```text
LINUX_REPO_GPG_PRIVATE_KEY
LINUX_REPO_GPG_PASSPHRASE
```

The expected full fingerprint is a GitHub Repository Variable:

```text
LINUX_REPO_GPG_FINGERPRINT
```

The matching public key is committed as `build/linux/repository-key.asc` and copied to the Pages root. Release automation imports the private key into an ephemeral GnuPG home, derives its fingerprint, and requires exact agreement with both the configured fingerprint and committed public key before signing.

The workflow must not print the private key, passphrase, secret-bearing commands, or an environment dump. Temporary GnuPG state is removed after signing. A missing key, wrong fingerprint, signing error, or verification failure stops publication; the workflow never falls back to unsigned output.

## Release data flow

A pull request or manual workflow dispatch performs build and validation only:

1. Resolve the application and package release versions.
2. Run the existing test matrix.
3. Publish the `linux-x64` self-contained payload once.
4. Create unsigned test `.deb` and `.rpm` packages.
5. Validate package metadata, paths, desktop entry, icon, and user-state invariants.
6. Generate an ephemeral, throwaway GPG key that exists only for the validation job.
7. Sign test packages and local repository metadata with the throwaway key, then verify them through the package managers.
8. Install and smoke-test the packages in the Linux container matrix.
9. Serve the local APT/DNF repository over HTTP and test package discovery and installation.
10. Upload test artifacts without changing GitHub Releases or Pages. The throwaway private key is never uploaded.

A `v*` tag performs the same checks and then publishes:

1. Sign the RPM package and APT/DNF metadata with the verified GPG key.
2. Verify every signature using only the committed public key.
3. Publish tar.gz, `.deb`, `.rpm`, and checksums in the GitHub Release.
4. Check out the existing `gh-pages` history.
5. Add the new package versions without removing old versions.
6. Regenerate and sign all repository metadata.
7. Push the updated `gh-pages` branch.
8. Fetch the public Pages URLs and verify the version, repository indexes, package signatures, and metadata signatures.

GitHub Release publication occurs before Pages publication. If Pages publication fails, the signed packages remain available from the release and the Pages job can be repaired and rerun without rebuilding source binaries.

## Update behavior

The operating system owns update checks and installation:

```bash
sudo apt update && sudo apt upgrade
sudo dnf upgrade
```

Users may independently enable `unattended-upgrades` or `dnf-automatic`. The Object Storage Client package neither enables those services nor asks for administrator privileges at application runtime.

An update replaces files under `/usr/lib/object-storage-client`, the launcher, desktop entry, icon, and documentation. It preserves all user data. A packaging-only release uses the native package release number so APT and DNF recognize it as newer even when the application assembly version is unchanged.

## Automated validation

### Static contract tests

Tests validate:

- package name, architecture, version, and release mapping;
- exact installed paths and file modes;
- executable launcher and application binary;
- desktop entry syntax and required fields;
- PNG dimensions, format, and icon destination;
- Debian and RPM dependency lists;
- absence of writes or maintainer-script references to the user-state directory;
- absence of private key material and unsigned-publication fallbacks;
- APT and DNF repository paths and stable-channel configuration;
- workflow publication gates for pull requests, manual runs, and tags.

Tests are written before packaging implementation and must fail because the expected package files or metadata do not yet exist.

### Container matrix

CI installs the generated package in:

- Debian 12;
- Ubuntu 22.04;
- Ubuntu 24.04;
- Fedora 44;
- Fedora 43;
- Rocky Linux 9;
- AlmaLinux 9.

Each container test:

1. installs the local package through `apt` or `dnf`;
2. confirms dependency resolution;
3. checks installed application, launcher, desktop entry, icon, and documentation;
4. validates the desktop entry;
5. starts Xvfb and launches the packaged application;
6. requires the process to remain alive for 15 seconds;
7. removes the package and confirms package-owned files disappear;
8. confirms a fixture in the user-state directory remains untouched;
9. configures a temporary HTTP-hosted APT or DNF repository;
10. discovers and installs the package through that repository;
11. verifies repository and package signatures with a throwaway CI key on pull requests and with the configured deployment key on tag releases.

RHEL 9 is manually validated before public release because public CI does not carry a Red Hat subscription. Rocky and Alma provide automated RHEL-compatible coverage but do not replace the final RHEL check.

## Error handling and rollback

- Package construction fails on missing payload files, invalid metadata, wrong architecture, or invalid desktop assets.
- Repository generation fails on duplicate/conflicting versions, missing packages, invalid indexes, or signature errors.
- Pages publication is atomic at the git commit level. The previous `gh-pages` commit remains the rollback target.
- Rolling back repository metadata means reverting `gh-pages` to the last verified commit; published GitHub Release assets are not silently replaced.
- A bad native package is superseded with a higher package release. Existing package files and checksums remain immutable.
- A failed distro container blocks publication unless it is the separately documented manual RHEL gate.

## Documentation

README documentation will include:

- one-time APT and DNF repository setup with `signed-by`/GPG verification;
- package installation, upgrade, removal, and optional user-data deletion;
- supported distributions and x86-64 limitation;
- the distinction between package-manager updates and application-managed updates;
- X11/XWayland and optional CJK font notes;
- tar.gz as a portable fallback;
- manual RHEL validation status.

The Pages root includes concise installation commands and links to the public key, GitHub Release, privacy policy, source, and issue tracker.

## Acceptance criteria

The feature is ready for a pull request when:

1. deterministic `.deb` and `.rpm` packages are generated from the same publish payload;
2. both packages install the documented files and preserve user state on removal;
3. the desktop menu entry and existing icon work from native package installs;
4. all listed public container tests pass, except RHEL which has a documented manual gate;
5. local APT and DNF repositories support signed package discovery and installation;
6. tag-only publication and secret handling tests pass;
7. the existing .NET test suite and platform release builds remain green;
8. no release or Pages state is changed by pull request validation or manual workflow dispatch;
9. a live tag release is not performed until the existing GPG secrets, fingerprint variable, public key, and GitHub Pages source are configured and verified.
