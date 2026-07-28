using ObjectStorageClient.Core.Local;
using ObjectStorageClient.Core.Models;

namespace ObjectStorageClient.App.Services;

/// <summary>
/// Bridges the two file panes: uploads need the remote pane's current bucket and prefix,
/// downloads need the local pane's current directory. <c>MainWindowViewModel</c> owns both
/// panes and implements this, so neither pane has to know about the other.
/// </summary>
public interface ITransferCoordinator
{
    bool IsConnected { get; }

    /// <summary>Queues local files (directories are walked) into the remote pane's current prefix.</summary>
    void QueueUpload(IReadOnlyList<LocalEntry> entries);

    /// <summary>Queues remote objects (prefixes are walked) into the local pane's current directory.</summary>
    void QueueDownload(IReadOnlyList<RemoteEntry> entries);
}
