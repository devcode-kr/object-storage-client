using System.Collections.Concurrent;
using System.Threading.Channels;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using ObjectStorageClient.Core.Abstractions;

namespace ObjectStorageClient.Core.Transfers;

/// <summary>
/// Channel-backed transfer engine with a fixed worker pool.
/// Every transfer is independent: one failure never stops the rest of the queue, which is what
/// lets the UI show per-item success/failure the way FileZilla does.
/// </summary>
public sealed class TransferQueue : ITransferQueue
{
    /// <summary>Minimum gap between progress notifications for one item, to keep the UI cheap.</summary>
    private static readonly TimeSpan ProgressInterval = TimeSpan.FromMilliseconds(200);

    private readonly Channel<TransferItem> _channel = Channel.CreateUnbounded<TransferItem>(
        new UnboundedChannelOptions { SingleReader = true, SingleWriter = false });

    private readonly ConcurrentDictionary<Guid, CancellationTokenSource> _cancellations = new();
    private readonly ConcurrentDictionary<Guid, long> _lastProgressTicks = new();
    private readonly List<TransferItem> _items = [];
    private readonly Lock _itemsLock = new();
    private readonly CancellationTokenSource _shutdown = new();
    private readonly ILogger<TransferQueue> _logger;

    private IObjectStorageClient? _client;
    private SemaphoreSlim _slots = new(3, 3);
    private Task? _dispatcher;

    public TransferQueue(ILogger<TransferQueue>? logger = null) =>
        _logger = logger ?? NullLogger<TransferQueue>.Instance;

    public int MaxConcurrency { get; private set; } = 3;

    public event EventHandler<TransferItem>? ItemAdded;

    public event EventHandler<TransferItem>? ItemUpdated;

    public void Attach(IObjectStorageClient? client, int maxConcurrency = 3)
    {
        _client = client;

        int clamped = Math.Clamp(maxConcurrency, 1, 16);
        if (clamped != MaxConcurrency)
        {
            MaxConcurrency = clamped;
            SemaphoreSlim previous = _slots;
            _slots = new SemaphoreSlim(clamped, clamped);
            previous.Dispose();
        }

        _dispatcher ??= Task.Run(DispatchLoopAsync);
    }

    public TransferItem Enqueue(TransferRequest request)
    {
        TransferItem item = new(request);

        lock (_itemsLock)
        {
            _items.Add(item);
        }

        _cancellations[item.Id] = CancellationTokenSource.CreateLinkedTokenSource(_shutdown.Token);
        ItemAdded?.Invoke(this, item);

        if (!_channel.Writer.TryWrite(item))
        {
            Fail(item, "Transfer queue is closed.");
        }

        return item;
    }

    public void Cancel(Guid id)
    {
        if (_cancellations.TryGetValue(id, out CancellationTokenSource? cts))
        {
            cts.Cancel();
        }
    }

    public void CancelAll()
    {
        foreach (CancellationTokenSource cts in _cancellations.Values)
        {
            cts.Cancel();
        }
    }

    public void ClearFinished()
    {
        lock (_itemsLock)
        {
            _items.RemoveAll(item => item.IsTerminal);
        }
    }

    public TransferItem? Retry(Guid id)
    {
        TransferItem? original;
        lock (_itemsLock)
        {
            original = _items.FirstOrDefault(item => item.Id == id);
        }

        if (original is null || original.Status is TransferStatus.Queued or TransferStatus.Running)
        {
            return null;
        }

        lock (_itemsLock)
        {
            _items.Remove(original);
        }

        return Enqueue(new TransferRequest
        {
            Direction = original.Direction,
            Bucket = original.Bucket,
            RemoteKey = original.RemoteKey,
            LocalPath = original.LocalPath,
            Size = original.TotalBytes,
        });
    }

    public IReadOnlyList<TransferItem> Snapshot()
    {
        lock (_itemsLock)
        {
            return [.. _items];
        }
    }

    private async Task DispatchLoopAsync()
    {
        try
        {
            while (await _channel.Reader.WaitToReadAsync(_shutdown.Token).ConfigureAwait(false))
            {
                while (_channel.Reader.TryRead(out TransferItem? item))
                {
                    SemaphoreSlim slots = _slots;
                    await slots.WaitAsync(_shutdown.Token).ConfigureAwait(false);

                    _ = Task.Run(async () =>
                    {
                        try
                        {
                            await ProcessAsync(item).ConfigureAwait(false);
                        }
                        finally
                        {
                            try
                            {
                                slots.Release();
                            }
                            catch (ObjectDisposedException)
                            {
                                // Concurrency was reconfigured while this transfer ran; the old
                                // semaphore is gone and its slot no longer matters.
                            }
                        }
                    });
                }
            }
        }
        catch (OperationCanceledException)
        {
            // Normal shutdown.
        }
    }

    private async Task ProcessAsync(TransferItem item)
    {
        IObjectStorageClient? client = _client;
        if (client is null)
        {
            Fail(item, "Not connected.");
            return;
        }

        if (!_cancellations.TryGetValue(item.Id, out CancellationTokenSource? cts))
        {
            Fail(item, "Transfer was discarded.");
            return;
        }

        if (cts.IsCancellationRequested)
        {
            Finish(item, TransferStatus.Cancelled, "Cancelled before start.");
            return;
        }

        item.Status = TransferStatus.Running;
        item.StartedAt = DateTimeOffset.Now;
        ItemUpdated?.Invoke(this, item);

        Progress<TransferProgress> progress = new(report =>
        {
            item.SetTransferred(report.TransferredBytes);
            if (report.TotalBytes > 0)
            {
                item.TotalBytes = report.TotalBytes;
            }

            if (ShouldReportProgress(item.Id))
            {
                ItemUpdated?.Invoke(this, item);
            }
        });

        try
        {
            if (item.Direction == TransferDirection.Upload)
            {
                await client.UploadAsync(item.Bucket, item.RemoteKey, item.LocalPath, progress, cts.Token)
                    .ConfigureAwait(false);
            }
            else
            {
                await client.DownloadAsync(item.Bucket, item.RemoteKey, item.LocalPath, progress, cts.Token)
                    .ConfigureAwait(false);
            }

            item.SetTransferred(item.TotalBytes);
            Finish(item, TransferStatus.Completed, error: null);
        }
        catch (OperationCanceledException)
        {
            Finish(item, TransferStatus.Cancelled, "Cancelled.");
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Transfer failed: {Direction} {Key}", item.Direction, item.RemoteKey);
            Finish(item, TransferStatus.Failed, ex.Message);
        }
        finally
        {
            _lastProgressTicks.TryRemove(item.Id, out _);
        }
    }

    /// <summary>Rate-limits progress events so a fast transfer cannot flood the UI thread.</summary>
    private bool ShouldReportProgress(Guid id)
    {
        long now = Environment.TickCount64;
        long previous = _lastProgressTicks.GetOrAdd(id, 0);

        if (now - previous < ProgressInterval.TotalMilliseconds)
        {
            return false;
        }

        _lastProgressTicks[id] = now;
        return true;
    }

    private void Fail(TransferItem item, string message) => Finish(item, TransferStatus.Failed, message);

    private void Finish(TransferItem item, TransferStatus status, string? error)
    {
        item.Status = status;
        item.ErrorMessage = error;
        item.FinishedAt = DateTimeOffset.Now;
        ItemUpdated?.Invoke(this, item);
    }

    public async ValueTask DisposeAsync()
    {
        await _shutdown.CancelAsync().ConfigureAwait(false);
        _channel.Writer.TryComplete();

        if (_dispatcher is not null)
        {
            try
            {
                await _dispatcher.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                // Expected during shutdown.
            }
        }

        foreach (CancellationTokenSource cts in _cancellations.Values)
        {
            cts.Dispose();
        }

        _cancellations.Clear();
        _slots.Dispose();
        _shutdown.Dispose();
    }
}
