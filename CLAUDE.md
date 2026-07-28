# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A cross-platform desktop client for S3-compatible object storage, built with Avalonia UI and
laid out like FileZilla: quick-connect bar, message log, side-by-side local/remote file panes,
and a transfer queue with queued/failed/successful tabs. Targets Windows 11, Debian-family
Linux, and macOS from a single codebase.

## Commands

```bash
dotnet build ObjectStorageClient.sln            # build everything
dotnet test  ObjectStorageClient.sln            # run all tests
dotnet run --project src/ObjectStorageClient.App # launch the GUI

# single test / single class
dotnet test tests/ObjectStorageClient.Core.Tests --filter "FullyQualifiedName~TransferQueueTests"
dotnet test tests/ObjectStorageClient.Core.Tests --filter "FullyQualifiedName~ObjectKeyTests.ToLocalPath_RejectsKeysThatEscapeTheTargetDirectory"

# self-contained desktop builds
dotnet publish src/ObjectStorageClient.App -c Release -r win-x64   --self-contained
dotnet publish src/ObjectStorageClient.App -c Release -r linux-x64 --self-contained
dotnet publish src/ObjectStorageClient.App -c Release -r osx-arm64 --self-contained
```

`TreatWarningsAsErrors` is on for every project, so a warning fails the build.

## Version pins that are load-bearing

- **Avalonia is pinned to the 11.3 line, not 12.x.** Avalonia 12's Roslyn analyzers require the
  .NET 10 SDK (compiler 4.14); this repo builds on the .NET 9 SDK. Bumping `AvaloniaVersion` in
  `Directory.Packages.props` without also moving to the .NET 10 SDK fails with `CS9057`.
  A 12.x upgrade also means: `Avalonia.Diagnostics` → `AvaloniaUI.DiagnosticsSupport`, and the
  DataGrid theme include in `App.axaml` changes from `Themes/Fluent.xaml` to `Themes/Fluent.axaml`.
- `Avalonia.Controls.DataGrid` tracks a separate version (`AvaloniaDataGridVersion`) because it
  lags the core packages.
- All package versions live in `Directory.Packages.props` (central package management); csproj
  files carry `<PackageReference Include="..." />` with no `Version` attribute.

## Architecture

Two projects, with a hard dependency rule: **Core never references Avalonia.**

```
src/ObjectStorageClient.Core   domain models, S3 access, transfers, profile storage
src/ObjectStorageClient.App    Avalonia views + view models (MVVM, CommunityToolkit.Mvvm)
```

`IObjectStorageClient` (`Core/Abstractions`) is the seam. `S3ObjectStorageClient` implements it
over AWSSDK.S3; tests substitute `FakeObjectStorageClient`. View models depend on the interface,
never on `Amazon.*` types.

### Provider presets vs. manual entry

`StorageProviderCatalog` holds the built-in providers (AWS, MinIO, R2, B2, Wasabi, Spaces, GCS,
NAVER Cloud, Linode, plus a `custom` entry). **A preset only seeds the form — every field stays
editable, and a fully hand-typed endpoint/key/region/bucket profile is a first-class case.**
`ConnectionEditorViewModel` enforces this: `_suppressPresetSync` guards the field-change handlers
so loading a saved profile never lets the preset overwrite what the user stored. Adding a provider
means adding one entry to `StorageProviderCatalog.All` and nothing else.

`ConnectionProfile.ResolveEndpoint()` is the single place that decides the effective endpoint:
an explicit `ServiceUrl` always wins over the preset's `{region}`/`{account}` template.

### Why proxy and TLS settings live in a custom HttpClientFactory

AWS SDK v4 removed `ProxyBypassList`/`ProxyBypassOnLocal` from `ClientConfig`, so
`S3HttpClientFactory` builds the `HttpClientHandler` instead — it owns proxy credentials, the
glob-to-regex bypass list, and the opt-in "accept any TLS certificate" switch.
`S3ObjectStorageClient.BuildConfig` only installs it when a profile actually needs it
(`S3HttpClientFactory.IsRequiredFor`). That mapping is covered by `S3ConfigurationTests`; it is
the layer most likely to break silently against a non-AWS gateway.

Provider quirks also flow through `BuildConfig`: `DisableRequestChecksums` sets
`RequestChecksumCalculation.WHEN_REQUIRED`, because SDK v4 sends `x-amz-checksum-*` headers by
default and R2/B2/GCS reject them.

### Object keys are not file paths

`ObjectKey` is the only place that converts between the flat `/`-delimited S3 namespace and
platform file paths. Keys never start with `/`, always use `/` regardless of OS, and a trailing
`/` is what marks a folder prefix. `ObjectKey.ToLocalPath` rejects keys that would escape the
download directory — do not bypass it when adding download paths.

### Transfer queue threading contract

`TransferQueue` is channel-backed with a fixed worker pool and raises `ItemAdded`/`ItemUpdated`
**from worker threads**. `TransferQueueViewModel` is responsible for marshalling onto
`Dispatcher.UIThread`; Core deliberately knows nothing about the dispatcher. Progress events are
throttled to ~5/sec per item. Each transfer is independent — one failure never stops the queue,
which is what makes the failed/successful tabs meaningful.

### Credential storage

Profiles are JSON in the per-user config directory (`AppPaths`: `%APPDATA%` / `~/Library/
Application Support` / `$XDG_CONFIG_HOME`). Secrets go through `ISecretProtector`; the default
`AesGcmSecretProtector` encrypts with a machine-local key file. **This protects against casual
disclosure, not against an attacker who can read the user's home directory** — the key lives
there too. Replacing it with an OS-keychain implementation only requires a new `ISecretProtector`.

## Conventions specific to this codebase

- Views are `.axaml`; compiled bindings are on by default
  (`AvaloniaUseCompiledBindingsByDefault`), so every view and `DataTemplate` needs `x:DataType`.
- `MainWindowViewModel` implements `ITransferCoordinator`. Uploads need the remote pane's prefix
  and downloads need the local pane's directory, so only the level that owns both panes can
  queue transfers — the panes themselves stay unaware of each other.
- Code-behind is limited to view-state plumbing with no MVVM equivalent: `DataGrid.SelectedItems`
  is not a bindable property, so `LocalPaneView`/`RemotePaneView` sync selection into the view
  model, and they handle double-click activation. No business logic belongs there.
- Core's bucket type is `StorageBucket`, not `BucketInfo` — the latter collides with
  `Amazon.S3.Model.BucketInfo`.
- Log colouring is done with style classes (`Classes.command`, `Classes.response`,
  `Classes.error`) driven by `LogLevelConverters`, so the palette stays in `AppStyles.axaml`.
