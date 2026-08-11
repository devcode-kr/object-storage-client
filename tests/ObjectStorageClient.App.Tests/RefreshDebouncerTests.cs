using ObjectStorageClient.App.Services;
using Xunit;

namespace ObjectStorageClient.App.Tests;

/// <summary>
/// Queueing a folder produces one completion per file, so the debouncer is what stops the panes
/// refreshing dozens of times per transfer batch.
/// </summary>
/// <remarks>
/// These wait for refreshes to arrive rather than sleeping for a margin and assuming they did.
/// The debouncer's delay is short, but a loaded machine can starve the thread pool and push its
/// continuation past any wall-clock margin a test might pick — which is exactly how the
/// "separated by a quiet period" case failed on a CI runner while passing everywhere else.
/// A fixed wait is only used to assert that no *further* refresh arrives, where being slow
/// cannot produce a false failure.
/// </remarks>
public sealed class RefreshDebouncerTests
{
    private static readonly TimeSpan Delay = TimeSpan.FromMilliseconds(60);

    /// <summary>Long enough that only a genuinely missing refresh trips it.</summary>
    private static readonly TimeSpan Patience = TimeSpan.FromSeconds(10);

    private static TimeSpan Settle => Delay * 6;

    [Fact]
    public async Task ABurstOfRequests_RefreshesOnce()
    {
        Recorder recorder = new();
        RefreshDebouncer debouncer = new(Delay, recorder.RefreshAsync);

        for (int i = 0; i < 50; i++)
        {
            debouncer.Request();
        }

        await recorder.WaitForNextAsync();
        await Task.Delay(Settle);

        Assert.Equal(1, recorder.Count);
    }

    [Fact]
    public async Task ASingleRequest_StillRefreshes()
    {
        Recorder recorder = new();
        RefreshDebouncer debouncer = new(Delay, recorder.RefreshAsync);

        debouncer.Request();

        await recorder.WaitForNextAsync();

        Assert.Equal(1, recorder.Count);
    }

    [Fact]
    public async Task RequestsSeparatedByAQuietPeriod_RefreshEachTime()
    {
        Recorder recorder = new();
        RefreshDebouncer debouncer = new(Delay, recorder.RefreshAsync);

        debouncer.Request();
        await recorder.WaitForNextAsync();

        debouncer.Request();
        await recorder.WaitForNextAsync();

        Assert.Equal(2, recorder.Count);
    }

    [Fact]
    public async Task NoRequest_NeverRefreshes()
    {
        Recorder recorder = new();
        RefreshDebouncer debouncer = new(Delay, recorder.RefreshAsync);

        _ = debouncer;
        await Task.Delay(Settle);

        Assert.Equal(0, recorder.Count);
    }

    [Fact]
    public async Task ConcurrentRequests_AreStillCoalesced()
    {
        Recorder recorder = new();
        RefreshDebouncer debouncer = new(Delay, recorder.RefreshAsync);

        await Task.WhenAll(Enumerable.Range(0, 20).Select(_ => Task.Run(debouncer.Request)));

        await recorder.WaitForNextAsync();
        await Task.Delay(Settle);

        Assert.Equal(1, recorder.Count);
    }

    /// <summary>Counts refreshes and lets a test block until the nth one actually arrives.</summary>
    private sealed class Recorder
    {
        private readonly SemaphoreSlim _arrived = new(0);
        private int _count;

        public int Count => Volatile.Read(ref _count);

        public Task RefreshAsync()
        {
            Interlocked.Increment(ref _count);
            _arrived.Release();
            return Task.CompletedTask;
        }

        /// <summary>Blocks until one more refresh arrives. Each call consumes exactly one.</summary>
        public async Task WaitForNextAsync()
        {
            Assert.True(
                await _arrived.WaitAsync(Patience),
                $"waited {Patience.TotalSeconds:0}s for a refresh; {Count} had arrived");
        }
    }
}
