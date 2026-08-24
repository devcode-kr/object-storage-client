# Code signing policy

*[한국어](CODE_SIGNING_POLICY.md) · English*

How each platform's builds are signed, and what a signature does and does not tell you. Anyone
running a signed program deserves to know what stands behind the signature.

## Where things stand

| Platform | Distribution | Signature |
| --- | --- | --- |
| Windows | Microsoft Store planned; listing/certification pending | Microsoft signing begins after Store certification |
| macOS | GitHub release `.zip` | Current archives are unsigned and not notarised; `SHA256SUMS.txt` only |
| Native Linux packages | GitHub Pages APT/DNF scheduled for the first native release | Will be **signed with the project GPG key** |
| Portable Linux tar.gz | GitHub releases | None; `SHA256SUMS.txt` only |

### Windows

The Windows signing path is separate from Linux. The developer account is approved, while the
Store listing and certification are still pending. Once a submitted MSIX passes certification,
**the Microsoft Store re-signs it with a Microsoft certificate** and handles updates. The project
GPG key is not used for Windows, and no `.exe` or `.msi` is distributed directly. Historical Windows
ZIPs in GitHub releases are unsigned legacy test artifacts, not the current official Store channel.

### macOS

The macOS `.zip` archive has no Apple developer signature or notarisation. `SHA256SUMS.txt` can
show that the downloaded bytes match the release record; it cannot establish who produced them.
Gatekeeper may block these builds; the README recommends building from source or waiting for a
signed and notarised distribution instead of weakening Gatekeeper.

### Linux

The signed repository becomes available with the **first native Linux package release**. Until its
tag and GitHub Pages deployment complete, repository URLs may return **404**; the unsigned release
tar.gz remains the manual fallback meanwhile. The signature behavior below describes the repository
once it has been published, not a claim that the pre-release URLs are currently usable.

APT and DNF verify different, complementary layers:

| Signature | What it verifies | Role of checksums |
| --- | --- | --- |
| APT `InRelease` / `Release.gpg` | The repository `Release` metadata was signed by the project key and has not changed | The signed `Release` hashes the `Packages` index, which hashes each `.deb` |
| RPM package signatures | The signer and integrity of each RPM package | Per-file package checksums can also detect damage after installation |
| DNF `repomd.xml.asc` | The `repomd.xml` repository metadata was signed by the project key and has not changed | Checksums in signed repodata bind its indexes and RPM files |

DNF therefore checks both RPM package signatures and repository metadata signatures. APT follows
the checksum chain from signed metadata to each package. Unlike the unsigned macOS and tar.gz
archives, these signatures also establish which project key produced the artifact.
`SHA256SUMS.txt` remains useful for detecting archive transfer errors; it does not replace a GPG
signature.

## Linux public key

- URL: <https://devcode-kr.github.io/object-storage-client/repository-key.asc>
- Full fingerprint: `843B0BB9F1A4488C8C7B60133F8AC712C8C56B90`
- Expiry: `2029-08-22` (**3 years** from creation)

The installation procedure checks the full fingerprint and key structure before installing a
local keyring. APT binds that keyring only to this repository with `signed-by`; DNF uses a local key
file with both package and metadata verification enabled.

The private key is kept in exactly two places: **GitHub Secrets** for automated publication, and an
encrypted recovery export plus passphrase in the restricted
`/workspace/hermes_home/secure/object-storage-client-linux-repository/` recovery store. No key
material or passphrase from that store belongs in this repository, build artifacts, logs, or
documentation.

## Key rotation

Before changing signers, publish the **old and new public keys** at separate URLs and keep an
**overlap** period. Update user keyrings and installation instructions to trust both keys, publish
the new fingerprint and expiry, and only then switch the APT metadata, RPM package, and DNF metadata
signers. Retain old packages and their original signatures; do not delete or re-sign them when the
overlap ends.

## Build and publication

Official Linux repository signing runs only from a `v*` **tag** in this repository. A **PR** cannot
access the production private key; it exercises the same package and repository verification path
with a **throwaway key**. A missing key, wrong fingerprint, expired key, signing error, or verification
error stops publication, with **no unsigned fallback**. Only the verified repository goes through
the official GitHub Pages deployment. There is no route for publishing a repository built on a
developer machine.

The Windows MSIX may be built from the same tag, but Partner Center and Microsoft Store
certification/signing are a separate path. The Linux GPG private key never signs the MSIX.

## Team roles

One person maintains the project, so that person holds every role. This is stated plainly rather
than dressed up as a separation of duties that does not exist.

| Role | Held by | Responsibility |
| --- | --- | --- |
| Author | Astral (maintainer) | Writes and commits the source |
| Reviewer | Astral (maintainer) | Reviews changes before they reach `main` |
| Approver | Astral (maintainer) | Approves releases and Store submissions |

Should the project gain maintainers, this table changes in the commit that grants them access.
Every account with access to the source repository or Partner Center uses multi-factor
authentication.

## What a signature means

A signature means that the file or metadata passed through the named signer and has not been
altered since. It is not a warranty of fitness or security; see the disclaimer in [LICENSE](LICENSE).

## Privacy and reporting

See the [privacy policy](PRIVACY.en.md). In short: nothing is collected. Suspected malicious
behaviour, or a file that does not match this policy, should be reported through the repository's
issue tracker. Reports are investigated and the cause published. Installation and removal are in
the [README](README.en.md#install).
