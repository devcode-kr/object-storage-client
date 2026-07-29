namespace ObjectStorageClient.App.Services;

/// <summary>
/// Collapses a burst of requests into a single deferred call.
/// </summary>
/// <remarks>
/// Queueing a folder produces one completion per file. Refreshing a pane on each of them would
/// hammer the endpoint and make the listing flicker, so requests are coalesced into one refresh
/// once the burst goes quiet.
/// </remarks>
public sealed class RefreshDebouncer
{
    private readonly TimeSpan _delay;
    private readonly Func<Task> _refresh;

    /// <summary>Bumped per request; a scheduled run that is no longer the newest simply drops.</summary>
    private int _generation;

    public RefreshDebouncer(TimeSpan delay, Func<Task> refresh)
    {
        _delay = delay;
        _refresh = refresh;
    }

    /// <summary>Schedules a refresh, superseding any request still waiting out its delay.</summary>
    public void Request()
    {
        int generation = Interlocked.Increment(ref _generation);
        _ = RunAsync(generation);
    }

    private async Task RunAsync(int generation)
    {
        try
        {
            await Task.Delay(_delay).ConfigureAwait(false);

            if (Volatile.Read(ref _generation) != generation)
            {
                return;
            }

            await _refresh().ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is OperationCanceledException or ObjectDisposedException
                                      or InvalidOperationException)
        {
            // The window went away mid-delay. Nothing is left to refresh, and this runs detached,
            // so the exception must not escape as an unobserved task fault.
        }
    }
}
