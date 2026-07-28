using ObjectStorageClient.Core.Transfers;

namespace ObjectStorageClient.Core.Abstractions;

/// <summary>
/// Background transfer engine. Raises events from worker threads — subscribers are responsible
/// for marshalling to their own UI thread.
/// </summary>
public interface ITransferQueue : IAsyncDisposable
{
    /// <summary>Number of transfers running at once. Changes apply to work picked up afterwards.</summary>
    int MaxConcurrency { get; }

    /// <summary>Raised once, right after a request is accepted.</summary>
    event EventHandler<TransferItem>? ItemAdded;

    /// <summary>Raised on progress and on every status change. Progress updates are throttled.</summary>
    event EventHandler<TransferItem>? ItemUpdated;

    /// <summary>
    /// Points the queue at a connected client and sets how many transfers may run at once.
    /// Passing <c>null</c> detaches, so queued work waits for the next connection.
    /// </summary>
    void Attach(IObjectStorageClient? client, int maxConcurrency = 3);

    TransferItem Enqueue(TransferRequest request);

    void Cancel(Guid id);

    void CancelAll();

    /// <summary>Drops finished items from <see cref="Snapshot"/>.</summary>
    void ClearFinished();

    /// <summary>Re-queues a failed or cancelled item.</summary>
    TransferItem? Retry(Guid id);

    IReadOnlyList<TransferItem> Snapshot();
}
