# Object Storage Client

A cross-platform desktop client for S3-compatible object storage, with a FileZilla-style
two-pane interface. Built with [Avalonia UI](https://avaloniaui.net) on .NET 9, and runs on
Windows 11, Debian-family Linux, and macOS from one codebase.

## Features

- **Two-pane transfers** — local file system on the left, buckets and prefixes on the right,
  with upload/download through a background queue.
- **Transfer queue** — queued / failed / successful tabs, per-item progress, cancel and retry.
  Each transfer succeeds or fails on its own; one failure never stalls the rest.
- **Message log** — colour-coded request/response/error lines, as in an FTP client.
- **Provider presets** — Amazon S3, MinIO, Cloudflare R2, Backblaze B2, Wasabi,
  DigitalOcean Spaces, Google Cloud Storage (S3 interop), NAVER Cloud Object Storage,
  Akamai/Linode, plus a fully custom entry.
- **Everything is still manual** — a preset only pre-fills the form. Endpoint, region, access
  key, secret, bucket and prefix all stay editable, so any S3-compatible gateway works even if
  it is not in the list.
- **Optional HTTP proxy** — per-site host/port, optional credentials, and a bypass list with
  `*` / `?` wildcards.
- **Site Manager** — saved connections with credentials encrypted at rest, plus a
  "Test connection" button.

## Requirements

- [.NET SDK 9.0](https://dotnet.microsoft.com/download) or newer

## Getting started

```bash
git clone <this repo>
cd object-storage-client

dotnet build ObjectStorageClient.sln
dotnet test  ObjectStorageClient.sln
dotnet run --project src/ObjectStorageClient.App
```

### Connecting

Use the **Quickconnect** bar for a one-off session, or **Site Manager** to save a connection.

For a local MinIO instance:

| Field | Value |
| --- | --- |
| Provider | MinIO |
| Endpoint | `http://localhost:9000` |
| Region | `us-east-1` |
| Access key / Secret | your MinIO credentials |
| Bucket | optional — leave blank to browse all buckets |

Path-style addressing is enabled automatically for MinIO and other self-hosted gateways.
For services that reject the AWS SDK's default checksum headers (R2, B2, GCS), the preset also
switches on **Disable request checksums**; both toggles remain available under *Advanced* in the
Site Manager.

## Packaging

```bash
dotnet publish src/ObjectStorageClient.App -c Release -r win-x64   --self-contained
dotnet publish src/ObjectStorageClient.App -c Release -r linux-x64 --self-contained
dotnet publish src/ObjectStorageClient.App -c Release -r osx-arm64 --self-contained
```

## Where your data is stored

Connection profiles live in the per-user configuration directory:

| Platform | Location |
| --- | --- |
| Windows | `%APPDATA%\ObjectStorageClient\sites.json` |
| macOS | `~/Library/Application Support/ObjectStorageClient/sites.json` |
| Linux | `$XDG_CONFIG_HOME/ObjectStorageClient/sites.json` (default `~/.config`) |

Secret keys, session tokens and proxy passwords are encrypted with AES-256-GCM using a key file
stored alongside them, with owner-only permissions where the OS supports it. This keeps
credentials out of plaintext backups and sync folders, but it is **not** protection against an
attacker who can already read your home directory — the key is there too. Integration with the
OS keychain is a natural next step.

## Project layout

```
src/ObjectStorageClient.Core   domain models, S3 access, transfer queue, profile storage
src/ObjectStorageClient.App    Avalonia views and view models
tests/                         unit tests for both
```

See [CLAUDE.md](CLAUDE.md) for the architecture notes and the constraints worth knowing before
changing things.
