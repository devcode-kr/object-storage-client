using ObjectStorageClient.Core.Transfers;
using Xunit;

namespace ObjectStorageClient.Core.Tests;

public sealed class TransferQueueTests
{
    private static TransferRequest Upload(string key) => new()
    {
        Direction = TransferDirection.Upload,
        Bucket = "bucket",
        RemoteKey = key,
        LocalPath = Path.Combine(Path.GetTempPath(), key),
        Size = 100,
    };

    /// <summary>Waits for an item to reach a terminal state, so tests never depend on timing.</summary>
    private static async Task<TransferItem> WaitForTerminalAsync(TransferItem item, TimeSpan? timeout = null)
    {
        using CancellationTokenSource cts = new(timeout ?? TimeSpan.FromSeconds(10));

        while (!item.IsTerminal)
        {
            cts.Token.ThrowIfCancellationRequested();
            await Task.Delay(15, cts.Token);
        }

        return item;
    }

    [Fact]
    public async Task Enqueue_RunsTheTransferAndMarksItCompleted()
    {
        FakeObjectStorageClient client = new();
        await using TransferQueue queue = new();
        queue.Attach(client);

        TransferItem item = queue.Enqueue(Upload("photos/cat.png"));
        await WaitForTerminalAsync(item);

        Assert.Equal(TransferStatus.Completed, item.Status);
        Assert.Contains("photos/cat.png", client.UploadedKeys);
        Assert.Equal(100, item.Percentage);
    }

    [Fact]
    public async Task Enqueue_RecordsTheFailureReasonWithoutStoppingTheQueue()
    {
        FakeObjectStorageClient client = new();
        client.FailingKeys.Add("bad.bin");

        await using TransferQueue queue = new();
        queue.Attach(client);

        TransferItem failing = queue.Enqueue(Upload("bad.bin"));
        TransferItem healthy = queue.Enqueue(Upload("good.bin"));

        await WaitForTerminalAsync(failing);
        await WaitForTerminalAsync(healthy);

        Assert.Equal(TransferStatus.Failed, failing.Status);
        Assert.Contains("Simulated failure", failing.ErrorMessage ?? string.Empty, StringComparison.Ordinal);
        Assert.Equal(TransferStatus.Completed, healthy.Status);
    }

    [Fact]
    public async Task Enqueue_FailsImmediatelyWhenNoClientIsAttached()
    {
        await using TransferQueue queue = new();
        queue.Attach(null);

        TransferItem item = queue.Enqueue(Upload("orphan.bin"));
        await WaitForTerminalAsync(item);

        Assert.Equal(TransferStatus.Failed, item.Status);
        Assert.Equal("Not connected.", item.ErrorMessage);
    }

    [Fact]
    public async Task Cancel_StopsAnInFlightTransfer()
    {
        FakeObjectStorageClient client = new() { TransferDelay = TimeSpan.FromSeconds(5) };
        await using TransferQueue queue = new();
        queue.Attach(client);

        TransferItem item = queue.Enqueue(Upload("slow.bin"));
        queue.Cancel(item.Id);

        await WaitForTerminalAsync(item);

        Assert.Equal(TransferStatus.Cancelled, item.Status);
    }

    [Fact]
    public async Task Retry_ReQueuesAFailedItemAsANewTransfer()
    {
        FakeObjectStorageClient client = new();
        client.FailingKeys.Add("flaky.bin");

        await using TransferQueue queue = new();
        queue.Attach(client);

        TransferItem first = queue.Enqueue(Upload("flaky.bin"));
        await WaitForTerminalAsync(first);
        Assert.Equal(TransferStatus.Failed, first.Status);

        // The next attempt should succeed now that the simulated fault is cleared.
        client.FailingKeys.Clear();
        TransferItem? retried = queue.Retry(first.Id);

        Assert.NotNull(retried);
        Assert.NotEqual(first.Id, retried!.Id);

        await WaitForTerminalAsync(retried);
        Assert.Equal(TransferStatus.Completed, retried.Status);
    }

    [Fact]
    public async Task Retry_IgnoresItemsThatAreStillRunning()
    {
        FakeObjectStorageClient client = new() { TransferDelay = TimeSpan.FromSeconds(2) };
        await using TransferQueue queue = new();
        queue.Attach(client);

        TransferItem item = queue.Enqueue(Upload("running.bin"));

        Assert.Null(queue.Retry(item.Id));

        queue.CancelAll();
        await WaitForTerminalAsync(item);
    }

    [Fact]
    public async Task ClearFinished_RemovesOnlyTerminalItems()
    {
        FakeObjectStorageClient client = new();
        await using TransferQueue queue = new();
        queue.Attach(client);

        TransferItem item = queue.Enqueue(Upload("done.bin"));
        await WaitForTerminalAsync(item);

        queue.ClearFinished();

        Assert.Empty(queue.Snapshot());
    }

    [Fact]
    public async Task Attach_ClampsConcurrencyIntoTheSupportedRange()
    {
        FakeObjectStorageClient client = new();
        await using TransferQueue queue = new();

        queue.Attach(client, maxConcurrency: 500);

        Assert.Equal(16, queue.MaxConcurrency);
    }

    /// <summary>
    /// The queue is a DI singleton, so the container disposes it as well as anything that already
    /// disposed it. A second call used to throw ObjectDisposedException from the cancellation
    /// token source and crash the app on exit.
    /// </summary>
    [Fact]
    public async Task DisposeAsync_IsIdempotent()
    {
        FakeObjectStorageClient client = new();
        TransferQueue queue = new();
        queue.Attach(client);

        TransferItem item = queue.Enqueue(Upload("done.bin"));
        await WaitForTerminalAsync(item);

        await queue.DisposeAsync();
        await queue.DisposeAsync();
        await queue.DisposeAsync();
    }

    [Fact]
    public async Task DisposeAsync_IsIdempotentEvenWithoutAClient()
    {
        TransferQueue queue = new();

        await queue.DisposeAsync();
        await queue.DisposeAsync();
    }

    [Fact]
    public async Task ItemAdded_AndItemUpdated_ReportEveryLifecycleChange()
    {
        FakeObjectStorageClient client = new();
        await using TransferQueue queue = new();
        queue.Attach(client);

        int added = 0;
        int updated = 0;
        queue.ItemAdded += (_, _) => Interlocked.Increment(ref added);
        queue.ItemUpdated += (_, _) => Interlocked.Increment(ref updated);

        TransferItem item = queue.Enqueue(Upload("events.bin"));
        await WaitForTerminalAsync(item);

        Assert.Equal(1, added);
        Assert.True(updated >= 2, $"expected at least a running and a terminal update, saw {updated}");
    }
}
