using ObjectStorageClient.App.Services;
using Xunit;

namespace ObjectStorageClient.App.Tests;

/// <summary>
/// Queueing a folder produces one completion per file, so the debouncer is what stops the panes
/// refreshing dozens of times per transfer batch.
/// </summary>
public sealed class RefreshDebouncerTests
{
    private static readonly TimeSpan Delay = TimeSpan.FromMilliseconds(60);

    private static TimeSpan Settle => Delay * 6;

    [Fact]
    public async Task ABurstOfRequests_RefreshesOnce()
    {
        int refreshes = 0;
        RefreshDebouncer debouncer = new(Delay, () =>
        {
            Interlocked.Increment(ref refreshes);
            return Task.CompletedTask;
        });

        for (int i = 0; i < 50; i++)
        {
            debouncer.Request();
        }

        await Task.Delay(Settle);

        Assert.Equal(1, refreshes);
    }

    [Fact]
    public async Task ASingleRequest_StillRefreshes()
    {
        int refreshes = 0;
        RefreshDebouncer debouncer = new(Delay, () =>
        {
            Interlocked.Increment(ref refreshes);
            return Task.CompletedTask;
        });

        debouncer.Request();
        await Task.Delay(Settle);

        Assert.Equal(1, refreshes);
    }

    [Fact]
    public async Task RequestsSeparatedByAQuietPeriod_RefreshEachTime()
    {
        int refreshes = 0;
        RefreshDebouncer debouncer = new(Delay, () =>
        {
            Interlocked.Increment(ref refreshes);
            return Task.CompletedTask;
        });

        debouncer.Request();
        await Task.Delay(Settle);
        debouncer.Request();
        await Task.Delay(Settle);

        Assert.Equal(2, refreshes);
    }

    [Fact]
    public async Task NoRequest_NeverRefreshes()
    {
        int refreshes = 0;
        RefreshDebouncer debouncer = new(Delay, () =>
        {
            Interlocked.Increment(ref refreshes);
            return Task.CompletedTask;
        });

        _ = debouncer;
        await Task.Delay(Settle);

        Assert.Equal(0, refreshes);
    }

    [Fact]
    public async Task ConcurrentRequests_AreStillCoalesced()
    {
        int refreshes = 0;
        RefreshDebouncer debouncer = new(Delay, () =>
        {
            Interlocked.Increment(ref refreshes);
            return Task.CompletedTask;
        });

        await Task.WhenAll(Enumerable.Range(0, 20).Select(_ => Task.Run(debouncer.Request)));
        await Task.Delay(Settle);

        Assert.Equal(1, refreshes);
    }
}
