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
`RequestChecksumCalculation.WHEN_REQUIRED`. **It defaults to `true`** — AWS SDK v4 sends
`x-amz-checksum-*` headers and `aws-chunked` bodies by default, and gateways that do not
implement them answer `NotImplemented` with no further detail, which fails every upload. Amazon
S3 is the only preset that turns checksums back on. Do not "fix" this default to match the SDK.

There is a **second, independent** compatibility hazard: `aws-chunked` upload bodies.
`UseChunkEncoding` exists on `PutObjectRequest` and `UploadPartRequest` but **not** on
`TransferUtilityUploadRequest`, and there is no config-level switch — so as long as uploads go
through `TransferUtility` they always send `Content-Encoding: aws-chunked` and
`x-amz-content-sha256: STREAMING-AWS4-HMAC-SHA256-PAYLOAD`, which the same gateways reject.
That is why `DisableChunkedEncoding` (default `true`) makes `UploadAsync` issue `PutObject`
directly below 16 MiB and hand-roll multipart above it, rather than configuring TransferUtility.
`UploadRequestEncodingTests` captures the real request against a local `HttpListener`, because
no assertion over `AmazonS3Config` can see a per-request decision.

The hand-rolled multipart path uploads parts sequentially and aborts the upload on failure —
abandoned parts are billed. `CalculatePartSize` keeps the part count within S3's 10,000 limit.

`S3ErrorGuidance` maps the bare error codes these gateways return into actionable text, and
`S3ObjectStorageClient` wraps SDK calls so failures surface as `StorageOperationException` with
that text. `FindS3Exception` unwraps `AggregateException` because `TransferUtility` nests
multipart failures; `OperationCanceledException` is deliberately not caught, so the transfer
queue can still distinguish "cancelled" from "failed".

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

### Storage locations and the master password

Both files live in one fixed directory on every platform — `AppPaths.ConfigDirectory`, i.e.
`$HOME/.devcode/object-storage-client/` (`%USERPROFILE%` on Windows). This deliberately ignores
per-platform conventions so the directory can be moved between machines.

| File | Contents |
| --- | --- |
| `sites.json` | Saved connections; credentials encrypted |
| `config.json` | Preferences plus the master-password salt, iteration count and verifier |

`MasterPasswordVault` derives a 32-byte AES key from the master password with PBKDF2-HMAC-SHA256
(600k iterations). The key exists only in memory and the password is never written anywhere, so
`config.json` cannot be used to recover it. `TryUnlock` proves a password by decrypting the
`Verifier` blob — a wrong password fails the GCM tag check, which `AesGcmSecretProtector` reports
as an empty string.

**Startup order matters** and is why `App.OnFrameworkInitializationCompleted` does not build the
container directly: `config.json` must be read, the password taken, and the key derived *before*
`JsonConnectionProfileStore` can be constructed. `StartAsync` therefore runs
`ShutdownMode.OnExplicitShutdown` while the gate window is up (otherwise closing it with no
`MainWindow` would exit the app), then switches to `OnMainWindowClose`. Quitting at the prompt
shuts the app down — there is no usable session without the key.

If the user forgets the password, `MasterPasswordViewModel` offers a reset that creates a new
vault and sets `DiscardedPreviousVault`; startup then deletes `sites.json`, whose secrets are no
longer decryptable. The same path handles a `config.json` whose vault definition is corrupt.

Note `MasterPasswordViewModel.OnPasswordChanged` clears `ErrorMessage`, so any code that both
clears the password box and reports an error must clear the box **first**.

`JsonConnectionProfileStore` must not use `JsonIgnoreCondition.WhenWritingDefault`: it omits
`false` and `0`, while `ForcePathStyle`, `DisableRequestChecksums`, `TimeoutSeconds` and
`MaxConcurrentTransfers` all initialise to `true`/non-zero. An omitted property falls back to the
initialiser on load, so a saved "off" silently reloaded as "on".

**Nothing is written to disk implicitly.** Both files are only saved when the user asks:
`config.json` on first run (to record the new vault) and thereafter from the settings UI's Save;
`sites.json` from the Site Manager's Save and Delete. Exiting saves nothing, and *connecting*
saves nothing — that used to persist the profile, which meant every Quickconnect, built with a
fresh id each time, silently added another saved site. `SiteManagerPersistenceTests` pins this
down.

Both stores verify their own writes: after the rename they read the file back and compare, and
throw if it does not match. That is what catches a save which reports success without the file
holding the new values — a half-written temporary file, or a serializer dropping properties.

Shutdown is **just `provider.DisposeAsync()`**. The container owns the view model, the transfer
queue and the rest, and disposes singletons in reverse registration order. Disposing any of them
explicitly as well disposes them twice — which crashed the app on exit with
`ObjectDisposedException` from the queue's cancellation token source. For the same reason a view
model must only release what it created (its own `TransferQueueViewModel` and the client it built
from the factory), never an injected dependency, and every `DisposeAsync` here is idempotent.

`ShutdownRequested` is a **synchronous** event: an `async` handler returns at its first `await`
and the runtime tears the process down with the work still in flight. `App.ShutdownAsync` is
therefore blocked on — but via
`Task.Run`, **not** awaited directly. `await using` disposals do not carry `ConfigureAwait(false)`,
so `FileStream.DisposeAsync` posts its continuation back to the blocked UI thread and hangs the
app. `Task.Run` clears the synchronization context and fixes the whole class of problem instead of
one await at a time.

The stores are also blocked on from the UI thread, so **every** await in them — including
`await using` disposals, which need the `stream.ConfigureAwait(false)` form — must avoid capturing
the context. `BlockingCallerTests` reproduces the deadlock with a context that cannot pump and
names the offending await in its failure message.

Both stores write through a `.tmp` file and rename. Always open it with
`AppPaths.CreateOwnerOnlyFile`, never `File.Create`: the latter applies the umask (0644 on a
typical Unix box), which would expose the credentials file until a later chmod. That helper sets
the mode twice on purpose — `UnixCreateMode` covers a fresh file, and an explicit chmod covers a
stale temp left by an interrupted save, whose mode `FileMode.Create` would otherwise preserve.

## Conventions specific to this codebase

- Views are `.axaml`; compiled bindings are on by default
  (`AvaloniaUseCompiledBindingsByDefault`), so every view and `DataTemplate` needs `x:DataType`.
- `MainWindowViewModel` implements `ITransferCoordinator`. Uploads need the remote pane's prefix
  and downloads need the local pane's directory, so only the level that owns both panes can
  queue transfers — the panes themselves stay unaware of each other. It also owns the
  post-transfer auto-refresh: completions arrive on worker threads, so the handler marshals to
  the dispatcher, refreshes only the pane whose *current* location the transfer landed in, and
  routes through `RefreshDebouncer` because a folder produces one completion per file.
- Activating a row (`OpenCommand`, bound to double-click) descends into directories and prefixes
  but transfers anything else. Both panes must keep that split in step.
- The master password fields accept printable ASCII only. Three things matter here, all verified
  by `MasterPasswordInputTests` (headless, driving the real input pipeline):
  - **Do not set `InputMethod.IsInputMethodEnabled="False"`.** It looks like the right tool and it
    is not: with the input context off, macOS delivers raw key events mapped through the active
    layout, and under a Korean layout Shift stops producing uppercase. The same keystrokes then
    produce a *different* password depending on the input mode, invisibly, in a masked field —
    which is how a vault ends up created with a password the user cannot reproduce. Let the IME
    run and reject its output instead.
  - The `TextInput` handler must be attached with `RoutingStrategies.Tunnel`, in code-behind.
    `TextInputEvent` routes `Tunnel, Bubble`, and `TextBox.OnTextInput` is a **bubble-stage class
    handler** — so a XAML `TextInput="..."` handler runs *after* the text is already inserted and
    setting `Handled` there does nothing. This is the layer that actually holds.
  - A `TextChanged` correction strips whatever never raised `TextInput` at all (pasting), so what
    the box shows always equals the password that gets used.

  Sanitising only in the view model does **not** work: the coerced value does not propagate back
  to the `TextBox` while the binding is updating from target to source, so the box keeps the
  rejected characters. `MasterPasswordViewModel.RemoveDisallowed` remains the shared rule and the
  backstop for code that sets the property directly. `OnPasswordChanged` clears `ErrorMessage`,
  so the reassign-then-report order there is deliberate.
- Code-behind is limited to view-state plumbing with no MVVM equivalent: `DataGrid.SelectedItems`
  is not a bindable property, so `LocalPaneView`/`RemotePaneView` sync selection into the view
  model, and they handle double-click activation. No business logic belongs there.
  `TransferQueueView` additionally selects the row under a right-click, because Avalonia's
  `DataGrid` does not — without it a context-menu command acts on the previous selection.
- Core's bucket type is `StorageBucket`, not `BucketInfo` — the latter collides with
  `Amazon.S3.Model.BucketInfo`.
- Log colouring is done with style classes (`Classes.command`, `Classes.response`,
  `Classes.error`) driven by `LogLevelConverters`, so the palette stays in `AppStyles.axaml`.
