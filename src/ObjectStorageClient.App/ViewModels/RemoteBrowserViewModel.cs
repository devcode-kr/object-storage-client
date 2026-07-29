using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ObjectStorageClient.App.Services;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Storage;

namespace ObjectStorageClient.App.ViewModels;

/// <summary>
/// Right half of the window: the object storage side. Navigation is prefix-based —
/// each "folder" is a common prefix returned by a delimited listing.
/// </summary>
public sealed partial class RemoteBrowserViewModel : ViewModelBase
{
    private readonly LogViewModel _log;
    private readonly IDialogService _dialogs;

    private IObjectStorageClient? _client;
    private CancellationTokenSource? _listingCancellation;

    public RemoteBrowserViewModel(LogViewModel log, IDialogService dialogs, ITransferCoordinator coordinator)
    {
        _log = log;
        _dialogs = dialogs;
        Coordinator = coordinator;
    }

    public ITransferCoordinator Coordinator { get; }

    public ObservableCollection<StorageBucket> Buckets { get; } = [];

    public ObservableCollection<RemoteEntry> Entries { get; } = [];

    /// <summary>Kept in sync by the view's selection handler; drives download and delete.</summary>
    public ObservableCollection<RemoteEntry> SelectedEntries { get; } = [];

    /// <summary>Breadcrumb segments of <see cref="CurrentPrefix"/>, for the path display.</summary>
    public ObservableCollection<string> PathSegments { get; } = [];

    [ObservableProperty]
    private StorageBucket? _selectedBucket;

    [ObservableProperty]
    private string _currentPrefix = string.Empty;

    [ObservableProperty]
    private bool _isBusy;

    [ObservableProperty]
    private bool _isConnected;

    [ObservableProperty]
    private string _statusText = "Not connected";

    /// <summary>Bucket currently open, or an empty string when disconnected.</summary>
    public string CurrentBucket => SelectedBucket?.Name ?? string.Empty;

    partial void OnSelectedBucketChanged(StorageBucket? value)
    {
        if (value is null)
        {
            return;
        }

        CurrentPrefix = string.Empty;
        _ = RefreshAsync();
    }

    partial void OnCurrentPrefixChanged(string value)
    {
        PathSegments.Clear();
        foreach (string segment in ObjectKey.Segments(value))
        {
            PathSegments.Add(segment);
        }
    }

    /// <summary>Binds the pane to a live connection and loads the initial bucket and prefix.</summary>
    public async Task ConnectAsync(IObjectStorageClient client, CancellationToken cancellationToken = default)
    {
        _client = client;
        IsConnected = true;

        Buckets.Clear();
        Entries.Clear();
        SelectedEntries.Clear();

        ConnectionProfile profile = client.Profile;

        try
        {
            _log.Command("ListBuckets");
            IReadOnlyList<StorageBucket> buckets = await client.ListBucketsAsync(cancellationToken).ConfigureAwait(true);

            foreach (StorageBucket bucket in buckets)
            {
                Buckets.Add(bucket);
            }

            _log.Response($"{buckets.Count} bucket(s) listed.");
        }
        catch (Exception ex)
        {
            // Many scoped keys cannot list buckets but can still read the one they are scoped to.
            _log.Error("ListBuckets failed; falling back to the configured bucket", ex);
        }

        if (!string.IsNullOrWhiteSpace(profile.DefaultBucket))
        {
            StorageBucket bucket = Buckets.FirstOrDefault(candidate =>
                string.Equals(candidate.Name, profile.DefaultBucket, StringComparison.Ordinal))
                ?? new StorageBucket { Name = profile.DefaultBucket };

            if (!Buckets.Contains(bucket))
            {
                Buckets.Add(bucket);
            }

            CurrentPrefix = ObjectKey.NormalizePrefix(profile.DefaultPrefix);
            SelectedBucket = bucket;
        }
        else
        {
            SelectedBucket = Buckets.FirstOrDefault();
            StatusText = Buckets.Count == 0 ? "No buckets available" : StatusText;
        }
    }

    public void Disconnect()
    {
        _listingCancellation?.Cancel();
        _client = null;
        IsConnected = false;
        SelectedBucket = null;
        Buckets.Clear();
        Entries.Clear();
        SelectedEntries.Clear();
        CurrentPrefix = string.Empty;
        StatusText = "Not connected";
    }

    [RelayCommand]
    private async Task RefreshAsync()
    {
        if (_client is null || SelectedBucket is null)
        {
            return;
        }

        await _listingCancellation.CancelAndDisposeAsync().ConfigureAwait(true);
        _listingCancellation = new CancellationTokenSource();
        CancellationToken token = _listingCancellation.Token;

        IsBusy = true;
        string bucket = SelectedBucket.Name;
        string prefix = ObjectKey.NormalizePrefix(CurrentPrefix);

        try
        {
            Entries.Clear();
            SelectedEntries.Clear();

            _log.Command($"ListObjectsV2 {bucket}/{prefix}");

            string? continuationToken = null;
            int folders = 0;
            int objects = 0;

            do
            {
                ObjectListingPage page = await _client
                    .ListAsync(bucket, prefix, continuationToken, token)
                    .ConfigureAwait(true);

                foreach (RemoteEntry entry in page.Entries)
                {
                    Entries.Add(entry);
                    if (entry.IsFolder)
                    {
                        folders++;
                    }
                    else
                    {
                        objects++;
                    }
                }

                continuationToken = page.NextContinuationToken;
            }
            while (!string.IsNullOrEmpty(continuationToken) && !token.IsCancellationRequested);

            StatusText = $"{folders} folders, {objects} objects";
            _log.Response($"Listed {folders} folder(s) and {objects} object(s).");
        }
        catch (OperationCanceledException)
        {
            // Superseded by a newer listing.
        }
        catch (Exception ex)
        {
            StatusText = "Listing failed";
            _log.Error($"Failed to list '{bucket}/{prefix}'", ex);
        }
        finally
        {
            IsBusy = false;
        }
    }

    [RelayCommand]
    private async Task NavigateUpAsync()
    {
        if (CurrentPrefix.Length == 0)
        {
            return;
        }

        CurrentPrefix = ObjectKey.GetParentPrefix(CurrentPrefix);
        await RefreshAsync().ConfigureAwait(true);
    }

    /// <summary>Navigates to a breadcrumb segment, counted from the bucket root.</summary>
    [RelayCommand]
    private async Task NavigateToSegmentAsync(string? segment)
    {
        if (segment is null)
        {
            return;
        }

        int index = PathSegments.IndexOf(segment);
        if (index < 0)
        {
            return;
        }

        CurrentPrefix = ObjectKey.NormalizePrefix(string.Join(ObjectKey.Separator, PathSegments.Take(index + 1)));
        await RefreshAsync().ConfigureAwait(true);
    }

    /// <summary>
    /// Double-click / Enter: descend into a prefix, or queue an object for download.
    /// Mirrors <c>LocalBrowserViewModel.Open</c> so both panes behave the same way.
    /// </summary>
    [RelayCommand]
    private async Task OpenAsync(RemoteEntry? entry)
    {
        if (entry is null)
        {
            return;
        }

        if (!entry.IsFolder)
        {
            Coordinator.QueueDownload([entry]);
            return;
        }

        CurrentPrefix = ObjectKey.NormalizePrefix(entry.Key);
        await RefreshAsync().ConfigureAwait(true);
    }

    [RelayCommand]
    private async Task CreateFolderAsync()
    {
        if (_client is null || SelectedBucket is null)
        {
            return;
        }

        string? name = await _dialogs.PromptAsync("Create directory", "New remote directory name:").ConfigureAwait(true);
        if (string.IsNullOrWhiteSpace(name))
        {
            return;
        }

        string key = ObjectKey.NormalizePrefix(ObjectKey.Combine(CurrentPrefix, name.Trim()));

        try
        {
            _log.Command($"PutObject {SelectedBucket.Name}/{key}");
            await _client.CreateFolderAsync(SelectedBucket.Name, key).ConfigureAwait(true);
            _log.Response($"Created '{key}'.");
            await RefreshAsync().ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            await _dialogs.ShowErrorAsync("Create directory", ex.Message).ConfigureAwait(true);
            _log.Error($"Failed to create '{key}'", ex);
        }
    }

    [RelayCommand]
    private async Task DeleteSelectedAsync()
    {
        if (_client is null || SelectedBucket is null || SelectedEntries.Count == 0)
        {
            return;
        }

        List<RemoteEntry> targets = [.. SelectedEntries];
        bool confirmed = await _dialogs
            .ConfirmAsync("Delete", $"Delete {targets.Count} remote item(s)? Folders are deleted recursively.")
            .ConfigureAwait(true);

        if (!confirmed)
        {
            return;
        }

        string bucket = SelectedBucket.Name;

        foreach (RemoteEntry entry in targets)
        {
            try
            {
                if (entry.IsFolder)
                {
                    await foreach (RemoteEntry child in _client.EnumerateAllAsync(bucket, entry.Key).ConfigureAwait(true))
                    {
                        await _client.DeleteObjectAsync(bucket, child.Key).ConfigureAwait(true);
                    }

                    // Remove the zero-byte folder marker itself, if one exists.
                    await _client.DeleteObjectAsync(bucket, entry.Key).ConfigureAwait(true);
                }
                else
                {
                    await _client.DeleteObjectAsync(bucket, entry.Key).ConfigureAwait(true);
                }

                _log.Info($"Deleted {bucket}/{entry.Key}");
            }
            catch (Exception ex)
            {
                _log.Error($"Failed to delete '{entry.Key}'", ex);
            }
        }

        await RefreshAsync().ConfigureAwait(true);
    }

    /// <summary>Queues the current selection for download into the local pane's directory.</summary>
    [RelayCommand]
    private void Download()
    {
        if (SelectedEntries.Count == 0)
        {
            return;
        }

        Coordinator.QueueDownload([.. SelectedEntries]);
    }
}

internal static class CancellationTokenSourceExtensions
{
    /// <summary>Cancels and disposes a token source, tolerating one that is already disposed.</summary>
    internal static async Task CancelAndDisposeAsync(this CancellationTokenSource? source)
    {
        if (source is null)
        {
            return;
        }

        try
        {
            await source.CancelAsync().ConfigureAwait(false);
            source.Dispose();
        }
        catch (ObjectDisposedException)
        {
            // Already torn down.
        }
    }
}
