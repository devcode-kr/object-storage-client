# Object Storage Client

A cross-platform desktop client for S3-compatible object storage, with a FileZilla-style
two-pane interface. Built with [Avalonia UI](https://avaloniaui.net) on .NET 9, and runs on
Windows 11, Debian-family Linux, and macOS from one codebase.

## Features

- **Two-pane transfers** — local file system on the left, buckets and prefixes on the right,
  with upload/download through a background queue. Double-click a folder to open it, or a file
  to transfer it; the opposite pane refreshes itself once the transfer finishes.
- **Transfer queue** — queued / failed / successful tabs, per-item progress, cancel and retry.
  Each transfer succeeds or fails on its own; one failure never stalls the rest. Right-click a
  failed transfer to copy its error message, paths, or the whole failure list.
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
- **Master password** — asked for at every launch; credentials are encrypted under a key derived
  from it, and the key is never written to disk.

## Install

Grab a self-contained build for your platform from the
[latest release](https://github.com/devcode-kr/object-storage-client/releases/latest) — no .NET
runtime installation needed. Each release ships `SHA256SUMS.txt` for verification.

**The binaries are not code-signed yet**, so Windows and macOS both object:

- **Windows** — unblock the `.zip` in its Properties dialog before extracting, then answer
  SmartScreen with *More info → Run anyway*.
- **macOS** — the app is reported as *"damaged"*; that is Gatekeeper's message for an unsigned
  quarantined bundle. Clear the attribute after installing:
  `xattr -dr com.apple.quarantine "/Applications/Object Storage Client.app"`
- **Linux** — nothing in the way. A minimal install may still need
  `libx11-6`, `libice6`, `libsm6` and `libfontconfig1`.

The release notes spell each of these out in full.

## Building from source

Requires [.NET SDK 9.0](https://dotnet.microsoft.com/download) or newer. Nothing else — no
workloads, and no Avalonia tooling. The commands are the same on all three platforms:

```bash
git clone <this repo>
cd object-storage-client

dotnet build ObjectStorageClient.sln
dotnet test  ObjectStorageClient.sln
dotnet run --project src/ObjectStorageClient.App
```

`TreatWarningsAsErrors` is on for every project, so the build fails on a warning. The tests run on
Avalonia's headless backend and need no display, which makes them safe to run over SSH or in a
container.

### Linux (Debian / Ubuntu)

Ubuntu 24.04 and later carry the SDK in the archive; on Debian use
[Microsoft's feed](https://learn.microsoft.com/dotnet/core/install/linux-debian) or the
`dotnet-install` script.

```bash
sudo apt install -y dotnet-sdk-9.0
sudo apt install -y libx11-6 libice6 libsm6 libfontconfig1   # Avalonia's runtime dependencies
sudo apt install -y fonts-noto-cjk                           # only if you need CJK text
```

Two things bite on a minimal install. Without the four libraries above the window never appears,
even though the build is self-contained — the .NET runtime is bundled, the X11 and font libraries
are not. And without a CJK font, Korean or Japanese site names and log lines render as boxes;
nothing is broken, the app simply ships no font that covers those ranges.

Avalonia 11 targets X11 directly, so on a Wayland desktop the app runs through XWayland — which
Ubuntu installs by default. Both session types work; testing under each is still worthwhile,
since window sizing and DPI go through different paths.

```bash
dotnet run --project src/ObjectStorageClient.App

# or a self-contained build, which is what a release ships
dotnet publish src/ObjectStorageClient.App -c Release -r linux-x64 --self-contained
./src/ObjectStorageClient.App/bin/Release/net9.0/linux-x64/publish/ObjectStorageClient.App
```

Your sites and settings land in `~/.devcode/object-storage-client/`, created with `0600`
permissions. `stat -c %a ~/.devcode/object-storage-client/sites.json` is the quickest way to
confirm a build has not regressed that.

### Windows 11

```powershell
winget install Microsoft.DotNet.SDK.9

dotnet build ObjectStorageClient.sln
dotnet test  ObjectStorageClient.sln
dotnet run --project src\ObjectStorageClient.App
```

Avalonia talks to Win32 directly, so there is nothing to install beyond the SDK.

```powershell
dotnet publish src\ObjectStorageClient.App -c Release -r win-x64 --self-contained
.\src\ObjectStorageClient.App\bin\Release\net9.0\win-x64\publish\ObjectStorageClient.App.exe
```

Sites and settings go to `%USERPROFILE%\.devcode\object-storage-client\` — the same layout as the
other platforms rather than `%APPDATA%`, so the directory can be carried between machines. Windows
has no owner-only file mode to set, so that step is skipped there.

A locally built `.exe` runs without complaint; SmartScreen only stands in the way of a binary that
arrived over the network, which is what the [Install](#install) section covers.

### A gateway to test against

MinIO in Docker is enough to exercise uploads, downloads and the queue:

```bash
docker run --rm -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \
  quay.io/minio/minio server /data --console-address :9001
```

Create a bucket at <http://localhost:9001>, then connect with the settings below. Pointing all
three platforms at one endpoint is what makes their results comparable.

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

**Disable request checksums** and **Disable chunked upload encoding** are both on by default for
every provider except Amazon S3. The AWS SDK otherwise sends `x-amz-checksum-*` headers and
`aws-chunked` request bodies, which many S3-compatible gateways do not implement — uploads then
fail with a bare `NotImplemented`. All of these toggles live under *Advanced* in the Site Manager.

## Packaging

```bash
dotnet publish src/ObjectStorageClient.App -c Release -r win-x64   --self-contained
dotnet publish src/ObjectStorageClient.App -c Release -r linux-x64 --self-contained
```

On macOS the publish output is a bare executable rather than something Finder treats as an
application, so it goes through a script that wraps it in a `.app` bundle and zips it:

```bash
build/package-macos.sh osx-arm64 0.0.1 artifacts
```

Releases are built by [`.github/workflows/release.yml`](.github/workflows/release.yml) when a
`v*` tag is pushed: it checks that the tag matches `<Version>` in `Directory.Build.props`, runs
the tests on all three operating systems, packages all four targets, and attaches them with
`SHA256SUMS.txt`. Each packaged build is then launched to confirm it starts — the Linux one
inside a bare Debian image carrying only the packages listed above, so that an error in that
list fails the release rather than reaching users.
Running the workflow manually builds the same artifacts without publishing a release, which is
the way to check packaging changes before tagging.

The application icon is drawn once in `build/icon/appicon.svg`; `build/generate-icon.py`
rasterises it into the `.png`, `.ico` and `.icns` variants each platform wants. It looks for
`rsvg-convert`, ImageMagick, `cairosvg` or headless Chrome and uses whichever it finds. The
generated files are committed because the Linux and Windows release runners have none of those,
nor `iconutil`.

## Master password

On first launch the app asks you to choose a master password; every launch after that asks for it
again to decrypt your saved sites. The password is never stored — only a salt, an iteration count
and a verifier blob are — so **there is no way to recover it.** If you forget it, the unlock
screen offers to start over, which discards the saved sites along with the old key.

Quitting at the password prompt closes the app: there is no usable session without the key.

The password fields accept English letters, digits and symbols only, so an input method left in a
composing mode cannot put unexpected characters into your master password — and neither can a
paste.

## Where your data is stored

Both files live in the same directory on every platform (`%USERPROFILE%` stands in for `$HOME`
on Windows):

| File | Contents |
| --- | --- |
| `$HOME/.devcode/object-storage-client/sites.json` | Saved connections from the Site Manager |
| `$HOME/.devcode/object-storage-client/config.json` | Preferences and master-password parameters |

For each saved site, the entire connection — endpoint, region, access key, secret key, session
token, bucket and proxy settings — is encrypted as a single block with AES-256-GCM, under a key
derived from your master password using PBKDF2-HMAC-SHA256 (600,000 iterations). Only the site
name, the provider and a few non-sensitive switches stay readable, so the list can be shown before
you unlock. Both files are written with owner-only permissions where the OS supports it. Because
the key never touches the disk, copying these files to another machine does not expose anything.

## Project layout

```
src/ObjectStorageClient.Core   domain models, S3 access, transfer queue, profile storage
src/ObjectStorageClient.App    Avalonia views and view models
tests/                         unit tests for both
```

See [CLAUDE.md](CLAUDE.md) for the architecture notes and the constraints worth knowing before
changing things.

## License

[MIT](LICENSE). Copyright (c) 2026 Astral.
