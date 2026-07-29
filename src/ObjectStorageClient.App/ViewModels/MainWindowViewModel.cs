using System.Collections.ObjectModel;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ObjectStorageClient.App.Services;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Local;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Storage;
using ObjectStorageClient.Core.Transfers;

namespace ObjectStorageClient.App.ViewModels;

/// <summary>
/// Owns the whole FileZilla-style shell: quick-connect bar, both file panes, the message log
/// and the transfer queue. Also acts as the <see cref="ITransferCoordinator"/> the panes use,
/// because only this level knows both the local directory and the remote prefix.
/// </summary>
public sealed partial class MainWindowViewModel : ViewModelBase, ITransferCoordinator, IAsyncDisposable
{
    private readonly IObjectStorageClientFactory _clientFactory;
    private readonly ITransferQueue _queue;
    private readonly IDialogService _dialogs;

    /// <summary>Long enough to swallow a folder's worth of completions, short enough to feel instant.</summary>
    private static readonly TimeSpan RefreshDelay = TimeSpan.FromMilliseconds(400);

    private readonly RefreshDebouncer _remotePaneRefresh;
    private readonly RefreshDebouncer _localPaneRefresh;

    private IObjectStorageClient? _client;
    private int _disposed;

    public MainWindowViewModel(
        IObjectStorageClientFactory clientFactory,
        ITransferQueue queue,
        IDialogService dialogs,
        IClipboardService clipboard,
        LogViewModel log)
    {
        _clientFactory = clientFactory;
        _queue = queue;
        _dialogs = dialogs;

        Log = log;
        Transfers = new TransferQueueViewModel(queue, clipboard);
        Local = new LocalBrowserViewModel(log, dialogs, this);
        Remote = new RemoteBrowserViewModel(log, dialogs, this);

        foreach (StorageProviderPreset preset in StorageProviderCatalog.All)
        {
            Providers.Add(preset);
        }

        _selectedProvider = StorageProviderCatalog.Custom;

        _remotePaneRefresh = new RefreshDebouncer(
            RefreshDelay,
            () => Dispatcher.UIThread.InvokeAsync(() => Remote.RefreshCommand.Execute(null)).GetTask());

        _localPaneRefresh = new RefreshDebouncer(
            RefreshDelay,
            () => Dispatcher.UIThread.InvokeAsync(() => Local.RefreshCommand.Execute(null)).GetTask());

        _queue.ItemUpdated += OnTransferUpdated;

        Log.Info("Object Storage Client ready. Use Quickconnect or the Site Manager to connect.");
    }

    public LogViewModel Log { get; }

    public LocalBrowserViewModel Local { get; }

    public RemoteBrowserViewModel Remote { get; }

    public TransferQueueViewModel Transfers { get; }

    /// <summary>Provider presets offered in the quick-connect bar. "Custom" leaves every field manual.</summary>
    public ObservableCollection<StorageProviderPreset> Providers { get; } = [];

    [ObservableProperty]
    private StorageProviderPreset _selectedProvider;

    [ObservableProperty]
    private string _quickEndpoint = string.Empty;

    [ObservableProperty]
    private string _quickRegion = "us-east-1";

    [ObservableProperty]
    private string _quickAccessKey = string.Empty;

    [ObservableProperty]
    private string _quickSecretKey = string.Empty;

    [ObservableProperty]
    private string _quickBucket = string.Empty;

    [ObservableProperty]
    private bool _isConnected;

    [ObservableProperty]
    private bool _isConnecting;

    [ObservableProperty]
    private string _connectionTitle = "Not connected";

    [ObservableProperty]
    private string _statusText = "Ready";

    bool ITransferCoordinator.IsConnected => IsConnected;

    partial void OnSelectedProviderChanged(StorageProviderPreset value)
    {
        // Seed the quick-connect fields; the user can overwrite any of them.
        QuickRegion = value.DefaultRegion;
        QuickEndpoint = value.BuildEndpoint(value.DefaultRegion, accountId: null);
    }

    /// <summary>
    /// Refreshes the pane a finished transfer landed in, so the new object or file appears
    /// without the user hitting Refresh.
    /// </summary>
    /// <remarks>
    /// The queue raises this from worker threads, so the whole decision is marshalled onto the UI
    /// thread — it reads pane state. Only the destination the user is actually looking at is
    /// refreshed: a transfer into some other bucket, prefix or directory changes nothing on screen.
    /// </remarks>
    private void OnTransferUpdated(object? sender, TransferItem item)
    {
        if (item.Status != TransferStatus.Completed)
        {
            return;
        }

        Dispatcher.UIThread.Post(() =>
        {
            if (item.Direction == TransferDirection.Upload)
            {
                if (IsShowingUploadDestination(item))
                {
                    _remotePaneRefresh.Request();
                }
            }
            else if (IsShowingDownloadDestination(item))
            {
                _localPaneRefresh.Request();
            }
        });
    }

    private bool IsShowingUploadDestination(TransferItem item) =>
        string.Equals(item.Bucket, Remote.CurrentBucket, StringComparison.Ordinal)
        && string.Equals(
            ObjectKey.GetParentPrefix(item.RemoteKey),
            ObjectKey.NormalizePrefix(Remote.CurrentPrefix),
            StringComparison.Ordinal);

    private bool IsShowingDownloadDestination(TransferItem item) =>
        Path.GetDirectoryName(item.LocalPath) is { } directory
        && IsSamePath(directory, Local.CurrentPath);

    /// <summary>Compares directories ignoring case and a trailing separator, as Windows and macOS do.</summary>
    private static bool IsSamePath(string left, string right)
    {
        if (string.IsNullOrEmpty(left) || string.IsNullOrEmpty(right))
        {
            return false;
        }

        try
        {
            return string.Equals(
                Path.TrimEndingDirectorySeparator(Path.GetFullPath(left)),
                Path.TrimEndingDirectorySeparator(Path.GetFullPath(right)),
                StringComparison.OrdinalIgnoreCase);
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            return false;
        }
    }

    /// <summary>Applies persisted preferences from <c>config.json</c> at startup.</summary>
    public Task ApplySettingsAsync(AppSettings settings)
    {
        Local.ShowHiddenFiles = settings.ShowHiddenFiles;

        if (!string.IsNullOrWhiteSpace(settings.LastLocalDirectory) &&
            Directory.Exists(settings.LastLocalDirectory))
        {
            Local.Navigate(settings.LastLocalDirectory);
        }

        return Task.CompletedTask;
    }

    [RelayCommand]
    private async Task QuickConnectAsync()
    {
        ConnectionProfile profile = new()
        {
            Name = string.IsNullOrWhiteSpace(QuickEndpoint) ? "Quickconnect" : QuickEndpoint,
            ProviderId = SelectedProvider.Id,
            ServiceUrl = QuickEndpoint.Trim(),
            Region = QuickRegion.Trim(),
            AccessKeyId = QuickAccessKey.Trim(),
            SecretAccessKey = QuickSecretKey,
            DefaultBucket = QuickBucket.Trim(),
            ForcePathStyle = SelectedProvider.ForcePathStyle,
            DisableRequestChecksums = SelectedProvider.DisableRequestChecksums,
        };

        IReadOnlyList<string> errors = profile.Validate();
        if (errors.Count > 0)
        {
            await _dialogs.ShowErrorAsync("Quickconnect", string.Join(Environment.NewLine, errors)).ConfigureAwait(true);
            return;
        }

        await ConnectAsync(profile).ConfigureAwait(true);
    }

    [RelayCommand]
    private async Task OpenSiteManagerAsync()
    {
        ConnectionProfile? profile = await _dialogs.ShowSiteManagerAsync().ConfigureAwait(true);
        if (profile is not null)
        {
            await ConnectAsync(profile).ConfigureAwait(true);
        }
    }

    /// <summary>Opens a session and hands the live client to the remote pane and the transfer queue.</summary>
    public async Task ConnectAsync(ConnectionProfile profile)
    {
        await DisconnectAsync().ConfigureAwait(true);

        IsConnecting = true;
        StatusText = $"Connecting to {profile.ResolveEndpoint()}…";
        Log.Command($"Connecting to {profile.ResolveEndpoint()} (region {profile.Region})");

        try
        {
            IObjectStorageClient client = _clientFactory.Create(profile);
            using (CancellationTokenSource timeout = new(TimeSpan.FromSeconds(profile.TimeoutSeconds)))
            {
                await client.TestConnectionAsync(timeout.Token).ConfigureAwait(true);
            }

            _client = client;
            _queue.Attach(client, profile.MaxConcurrentTransfers);

            IsConnected = true;
            ConnectionTitle = $"{profile.Name} — {profile.ResolveEndpoint()}";
            StatusText = "Connected";
            Log.Response("Connection established.");

            // No implicit save. Connecting used to persist the profile, which meant every
            // Quickconnect — built with a fresh id each time — added another saved site.
            await Remote.ConnectAsync(client).ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            IsConnected = false;
            StatusText = "Connection failed";
            ConnectionTitle = "Not connected";
            Log.Error("Connection failed", ex);
            await _dialogs.ShowErrorAsync("Connection failed", ex.Message).ConfigureAwait(true);
        }
        finally
        {
            IsConnecting = false;
        }
    }

    [RelayCommand]
    private async Task DisconnectAsync()
    {
        if (_client is null)
        {
            return;
        }

        _queue.Attach(null);
        Remote.Disconnect();

        await _client.DisposeAsync().ConfigureAwait(true);
        _client = null;

        IsConnected = false;
        ConnectionTitle = "Not connected";
        StatusText = "Disconnected";
        Log.Info("Disconnected.");
    }

    [RelayCommand]
    private void ClearLog() => Log.Clear();

    [RelayCommand]
    private static void Exit() =>
        (Avalonia.Application.Current?.ApplicationLifetime
            as Avalonia.Controls.ApplicationLifetimes.IClassicDesktopStyleApplicationLifetime)?.Shutdown();

    /// <inheritdoc />
    public void QueueUpload(IReadOnlyList<LocalEntry> entries)
    {
        if (!IsConnected || Remote.SelectedBucket is null)
        {
            Log.Error("Cannot upload: not connected to a bucket.");
            return;
        }

        string bucket = Remote.SelectedBucket.Name;
        string prefix = ObjectKey.NormalizePrefix(Remote.CurrentPrefix);
        int queued = 0;

        foreach (LocalEntry entry in entries)
        {
            if (entry.IsDirectory)
            {
                // Walk the tree so the object keys mirror the local folder structure.
                string parent = Path.GetDirectoryName(entry.FullPath.TrimEnd(Path.DirectorySeparatorChar)) ?? entry.FullPath;

                foreach (string file in LocalFileSystem.EnumerateFilesRecursively(entry.FullPath))
                {
                    queued += EnqueueUpload(bucket, ObjectKey.FromLocalPath(prefix, file, parent), file);
                }
            }
            else
            {
                queued += EnqueueUpload(bucket, ObjectKey.Combine(prefix, entry.Name), entry.FullPath);
            }
        }

        Log.Info($"Queued {queued} file(s) for upload to {bucket}/{prefix}");
    }

    /// <inheritdoc />
    public void QueueDownload(IReadOnlyList<RemoteEntry> entries)
    {
        if (!IsConnected || _client is null || Remote.SelectedBucket is null)
        {
            Log.Error("Cannot download: not connected to a bucket.");
            return;
        }

        string bucket = Remote.SelectedBucket.Name;
        string localDirectory = Local.CurrentPath;

        foreach (RemoteEntry entry in entries)
        {
            if (entry.IsFolder)
            {
                // Enumerating a prefix is a network call, so fan it out in the background.
                _ = QueueFolderDownloadAsync(bucket, entry, localDirectory);
            }
            else
            {
                string destination = Path.Combine(localDirectory, entry.Name);
                EnqueueDownload(bucket, entry.Key, destination, entry.Size);
            }
        }
    }

    private async Task QueueFolderDownloadAsync(string bucket, RemoteEntry folder, string localDirectory)
    {
        if (_client is null)
        {
            return;
        }

        // Recreate the folder itself under the local directory, then mirror its contents.
        string strippedPrefix = ObjectKey.GetParentPrefix(folder.Key);
        int queued = 0;

        try
        {
            await foreach (RemoteEntry child in _client.EnumerateAllAsync(bucket, folder.Key).ConfigureAwait(true))
            {
                string destination = ObjectKey.ToLocalPath(localDirectory, child.Key, strippedPrefix);
                EnqueueDownload(bucket, child.Key, destination, child.Size);
                queued++;
            }

            Log.Info($"Queued {queued} file(s) from {bucket}/{folder.Key}");
        }
        catch (Exception ex)
        {
            Log.Error($"Failed to enumerate '{folder.Key}'", ex);
        }
    }

    private int EnqueueUpload(string bucket, string key, string localPath)
    {
        long size = 0;
        try
        {
            size = new FileInfo(localPath).Length;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // Size is cosmetic; the transfer still runs.
        }

        _queue.Enqueue(new TransferRequest
        {
            Direction = TransferDirection.Upload,
            Bucket = bucket,
            RemoteKey = key,
            LocalPath = localPath,
            Size = size,
        });

        return 1;
    }

    private void EnqueueDownload(string bucket, string key, string destination, long size) =>
        _queue.Enqueue(new TransferRequest
        {
            Direction = TransferDirection.Download,
            Bucket = bucket,
            RemoteKey = key,
            LocalPath = destination,
            Size = size,
        });

    /// <summary>
    /// Releases only what this view model owns. The transfer queue is a container singleton, so
    /// the container disposes it — after this, since it is registered earlier and singletons are
    /// disposed in reverse. Disposing it here as well is what crashed shutdown.
    /// </summary>
    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) == 1)
        {
            return;
        }

        _queue.ItemUpdated -= OnTransferUpdated;
        Transfers.Dispose();

        if (_client is not null)
        {
            await _client.DisposeAsync().ConfigureAwait(false);
            _client = null;
        }
    }
}
