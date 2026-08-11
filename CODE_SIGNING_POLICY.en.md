# Code signing policy

*[한국어](CODE_SIGNING_POLICY.md) · English*

This document describes who may sign releases of Object Storage Client, how signing happens, and
what a signature does and does not tell you. It exists because the
[SignPath Foundation](https://signpath.org) requires projects it signs for to publish one, and
because anyone running a signed binary deserves to know what stands behind the signature.

## Signing provider

Windows releases are to be signed with a free certificate issued by the
[SignPath Foundation](https://signpath.org), using [SignPath.io](https://signpath.io).

**No release is signed yet.** v0.0.1 shipped unsigned, and the application to the Foundation is
pending; the first signed release will be the one that follows approval. Until then this
document states the process that will be followed rather than one already in force, and the
release notes tell you what an unsigned build looks like on first launch.

## Team roles

The project is currently maintained by one person, who therefore holds every role. This is
stated plainly rather than dressed up as a separation of duties that does not exist.

| Role | Held by | Responsibility |
| --- | --- | --- |
| Author | Astral (project maintainer) | Writes and commits the source code |
| Reviewer | Astral (project maintainer) | Reviews changes before they reach `main` |
| Approver | Astral (project maintainer) | Approves a signing request for a tagged release |

Should the project gain maintainers, this table is updated in the same commit that grants them
access, and Approver is separated from Author first.

All accounts with access to the source repository or to SignPath require multi-factor
authentication.

## What gets signed

Only the Windows artifacts published as assets of a
[GitHub release](https://github.com/devcode-kr/object-storage-client/releases), built by
[`.github/workflows/release.yml`](.github/workflows/release.yml) from a `v*` tag in this
repository.

Nothing is signed from a developer machine, and nothing built from a source tree other than this
one is signed. The release workflow is the only path to a signed binary, and it is public: the
build that produced any given asset can be inspected in the Actions log.

Every signed binary carries its product name and version in the assembly metadata, set from
`Directory.Build.props`. The release workflow fails if the tag and that version disagree, so a
signature cannot vouch for a build whose stated version is wrong.

## What the signature means

It means the binary is an automated build of the source in this repository at the tagged commit,
and that it has not been altered since. That is the whole claim. It is not a warranty of
fitness, security or correctness — see the disclaimer in [LICENSE](LICENSE).

Releases also ship `SHA256SUMS.txt`. Verifying a checksum tells you the file arrived intact;
verifying the signature tells you where it came from. They answer different questions.

## Privacy

The application collects no telemetry, no analytics and no usage data. Nothing is transmitted
anywhere except to the S3-compatible storage endpoint you configure, and to the HTTP proxy you
configure if you configure one.

Credentials are encrypted at rest under a key derived from a master password that is never
written to disk, in a directory only the account owner can read. There is no account, no
registration and no server operated by this project. See
[Where your data is stored](README.en.md#where-your-data-is-stored).

## Installation and removal

The application is distributed as an archive; there is no installer, and nothing outside the
extracted folder and one configuration directory is touched. It does not write to the registry,
install services, or modify system configuration.

To remove it, delete the extracted folder and, if you also want your saved sites and settings
gone, `%USERPROFILE%\.devcode\object-storage-client\` on Windows or
`$HOME/.devcode/object-storage-client/` elsewhere. See
[Uninstalling](README.en.md#uninstalling).

## Reporting a problem

Suspected malicious behaviour, or a binary whose signature does not match this policy, should be
reported through the repository's issue tracker. Reports are investigated and the cause
published.
