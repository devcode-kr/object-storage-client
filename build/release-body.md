A cross-platform desktop client for S3-compatible object storage, with a FileZilla-style
two-pane interface.

## Downloads

| Platform | File |
| --- | --- |
| Windows 11 (x64) | `ObjectStorageClient-@VERSION@-win-x64.zip` |
| Linux (x64, Debian family) | `ObjectStorageClient-@VERSION@-linux-x64.tar.gz` |
| macOS (Apple Silicon) | `ObjectStorageClient-@VERSION@-osx-arm64.zip` |
| macOS (Intel) | `ObjectStorageClient-@VERSION@-osx-x64.zip` |

Every build is self-contained — no .NET runtime installation is required.

## These builds are not code-signed

Signing certificates cost money that this project has not spent yet, so both Windows and macOS
will warn you. The steps below are how you get past that. Verify the checksums first if you
would rather not take that on faith.

### Windows

1. Right-click the downloaded `.zip` → **Properties** → tick **Unblock** → **OK**, then extract.
   (Skipping this propagates the download mark to every extracted file.)
2. Run `ObjectStorageClient.App.exe`. SmartScreen shows *"Windows protected your PC"* —
   choose **More info** → **Run anyway**.

### macOS

macOS reports unsigned apps as *"damaged and can't be opened"*. The app is not damaged; that is
the Gatekeeper message for a quarantined bundle without a signature. Remove the quarantine
attribute after moving the app into place:

```sh
xattr -dr com.apple.quarantine "/Applications/Object Storage Client.app"
```

### Linux

No signature checks stand in the way. On a minimal install you may need the libraries Avalonia
depends on:

```sh
sudo apt install libice6 libsm6 libfontconfig1
tar -xzf ObjectStorageClient-@VERSION@-linux-x64.tar.gz
./ObjectStorageClient-@VERSION@-linux-x64/ObjectStorageClient.App
```

## Verifying your download

`SHA256SUMS.txt` covers every asset in this release.

```sh
sha256sum -c SHA256SUMS.txt --ignore-missing    # Linux
shasum -a 256 -c SHA256SUMS.txt --ignore-missing # macOS
```

```powershell
Get-FileHash .\ObjectStorageClient-@VERSION@-win-x64.zip -Algorithm SHA256  # Windows
```

## Where your data is stored

`$HOME/.devcode/object-storage-client/` (`%USERPROFILE%` on Windows) holds `sites.json` and
`config.json`. Saved credentials are encrypted with AES-256-GCM under a key derived from your
master password, which is never written to disk — **if you forget it, there is no recovery.**

## License

MIT.
