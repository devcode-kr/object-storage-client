# Code signing policy

*[한국어](CODE_SIGNING_POLICY.md) · English*

How each platform's builds are signed, and what a signature does and does not tell you. Anyone
running a signed program deserves to know what stands behind the signature.

## Where things stand

| Platform | Distribution | Signature |
| --- | --- | --- |
| Windows | Microsoft Store | **Signed by Microsoft** |
| macOS | GitHub releases | None |
| Linux | GitHub releases | None |

### Windows

Distributed through the Store only. Once a submitted MSIX passes certification, **Microsoft
re-signs it with their own certificate.** No certificate is bought here and nothing is signed
here. For the user there is no warning to click past, and the Store handles updates.

No `.exe` or `.msi` is distributed directly. The Store does not re-sign those, so they would need
a certificate of their own, and that path was not taken.

### macOS and Linux

Unsigned. Signing macOS would mean the Apple Developer Program at $99/yr, which has not been paid
for. So macOS reports *"damaged and can't be opened"* on first launch — the app is not damaged,
that is Gatekeeper's message for an unsigned quarantined bundle. The release notes give the way
past it.

Nothing stands in the way on Linux.

## Team roles

One person maintains the project, so that person holds every role. This is stated plainly rather
than dressed up as a separation of duties that does not exist.

| Role | Held by | Responsibility |
| --- | --- | --- |
| Author | Astral (maintainer) | Writes and commits the source |
| Reviewer | Astral (maintainer) | Reviews changes before they reach `main` |
| Approver | Astral (maintainer) | Approves releases and Store submissions |

Should the project gain maintainers, this table changes in the commit that grants them access.
Every account with access to the source repository or to Partner Center uses multi-factor
authentication.

## What gets built and published

Everything distributed comes from [`.github/workflows/release.yml`](.github/workflows/release.yml),
built from a `v*` tag in this repository. There is no path for publishing something built on a
developer machine. The workflow is public, so the build behind any given file can be read in the
Actions log.

The MSIX submitted to the Store comes from the same workflow. Only the upload to Partner Center
is done by hand.

Binaries carry their product name and version in the assembly metadata, set from
`Directory.Build.props`. The workflow fails if the tag and that version disagree.

## What the signature means

Microsoft's signature on the Windows package means **this package came through the Store and has
not been altered since**. It is not a warranty of fitness or security — see the disclaimer in
[LICENSE](LICENSE).

macOS and Linux releases ship `SHA256SUMS.txt`. A checksum tells you the file arrived intact; it
says nothing about where it came from. The two answer different questions.

## Privacy

See the [privacy policy](PRIVACY.en.md). In short: nothing is collected.

## Installation and removal

Windows installs and uninstalls through the Store. macOS and Linux are archives — delete the
folder you extracted. Neither writes to the registry, installs a service, or changes system
configuration. See [Uninstalling](README.en.md#uninstalling).

## Reporting a problem

Suspected malicious behaviour, or a file that does not match this policy, should be reported
through the repository's issue tracker. Reports are investigated and the cause published.
