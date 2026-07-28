namespace ObjectStorageClient.Core.Transfers;

public enum TransferDirection
{
    Upload,
    Download,
}

public enum TransferStatus
{
    Queued,
    Running,
    Completed,
    Failed,
    Cancelled,
}

/// <summary>Byte counter reported by the SDK while a single object moves.</summary>
public readonly record struct TransferProgress(long TransferredBytes, long TotalBytes)
{
    public double Percentage => TotalBytes <= 0 ? 0d : Math.Clamp(TransferredBytes * 100d / TotalBytes, 0d, 100d);
}

/// <summary>A queued transfer as requested by the UI, before the queue assigns it an identity.</summary>
public sealed record TransferRequest
{
    public required TransferDirection Direction { get; init; }

    public required string Bucket { get; init; }

    /// <summary>Object key, without a leading slash.</summary>
    public required string RemoteKey { get; init; }

    /// <summary>Absolute path of the local source (upload) or destination (download).</summary>
    public required string LocalPath { get; init; }

    /// <summary>Known size in bytes, or 0 when unknown at enqueue time.</summary>
    public long Size { get; init; }
}

/// <summary>
/// Live state of one transfer. Owned by <see cref="TransferQueue"/>, which mutates it from worker
/// threads; the UI only reads it on the dispatcher thread after an <c>ItemUpdated</c> notification.
/// </summary>
public sealed class TransferItem
{
    private long _transferredBytes;

    internal TransferItem(TransferRequest request)
    {
        Direction = request.Direction;
        Bucket = request.Bucket;
        RemoteKey = request.RemoteKey;
        LocalPath = request.LocalPath;
        TotalBytes = request.Size;
    }

    public Guid Id { get; } = Guid.NewGuid();

    public TransferDirection Direction { get; }

    public string Bucket { get; }

    public string RemoteKey { get; }

    public string LocalPath { get; }

    public long TotalBytes { get; internal set; }

    public long TransferredBytes => Interlocked.Read(ref _transferredBytes);

    public TransferStatus Status { get; internal set; } = TransferStatus.Queued;

    public string? ErrorMessage { get; internal set; }

    public DateTimeOffset EnqueuedAt { get; } = DateTimeOffset.Now;

    public DateTimeOffset? StartedAt { get; internal set; }

    public DateTimeOffset? FinishedAt { get; internal set; }

    public double Percentage => TotalBytes <= 0
        ? (Status == TransferStatus.Completed ? 100d : 0d)
        : Math.Clamp(TransferredBytes * 100d / TotalBytes, 0d, 100d);

    public bool IsTerminal => Status is TransferStatus.Completed or TransferStatus.Failed or TransferStatus.Cancelled;

    internal void SetTransferred(long value) => Interlocked.Exchange(ref _transferredBytes, value);
}
