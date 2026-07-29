using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Profiles;
using Xunit;

namespace ObjectStorageClient.Core.Tests;

/// <summary>
/// Stands in for a UI thread that is blocked waiting on the store: continuations posted to it
/// never run, exactly as they would not while the thread sits in <c>GetAwaiter().GetResult()</c>.
/// </summary>
internal sealed class BlockedSynchronizationContext : SynchronizationContext
{
    public override void Post(SendOrPostCallback d, object? state) => Interlocked.Increment(ref _posted);

    public override void Send(SendOrPostCallback d, object? state) => Interlocked.Increment(ref _posted);

    private int _posted;

    internal int PostedContinuations => Volatile.Read(ref _posted);
}

/// <summary>
/// The app blocks on these stores while shutting down, from the UI thread. Any await that captures
/// the caller's <see cref="SynchronizationContext"/> deadlocks there — which is what happened when
/// <c>await using</c> was left unconfigured: the file was written but never renamed, so the app
/// hung with a stray <c>.tmp</c> on disk.
/// </summary>
public sealed class BlockingCallerTests : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), $"osc-block-{Guid.NewGuid():N}");

    public BlockingCallerTests() => Directory.CreateDirectory(_directory);

    /// <summary>Runs <paramref name="blockingCall"/> on a thread whose context cannot pump.</summary>
    private static void RunBlockedOnUiLikeThread(Action blockingCall, string what)
    {
        Exception? failure = null;
        BlockedSynchronizationContext context = new();

        Thread thread = new(() =>
        {
            SynchronizationContext.SetSynchronizationContext(context);
            try
            {
                blockingCall();
            }
            catch (Exception ex)
            {
                failure = ex;
            }
        })
        {
            IsBackground = true,
        };

        thread.Start();

        Assert.True(
            thread.Join(TimeSpan.FromSeconds(15)),
            $"{what} deadlocked: {context.PostedContinuations} continuation(s) were posted back to the "
            + "blocked thread, so an await is missing ConfigureAwait(false).");

        Assert.Null(failure);
    }

    [Fact]
    public void SettingsStore_SaveThenLoad_SurvivesABlockingCaller()
    {
        JsonAppSettingsStore store = new(Path.Combine(_directory, "config.json"));

        RunBlockedOnUiLikeThread(
            () => store.SaveAsync(new AppSettings { ShowHiddenFiles = true }).GetAwaiter().GetResult(),
            "JsonAppSettingsStore.SaveAsync");

        RunBlockedOnUiLikeThread(
            () => Assert.True(store.LoadAsync().GetAwaiter().GetResult().ShowHiddenFiles),
            "JsonAppSettingsStore.LoadAsync");
    }

    [Fact]
    public void SettingsStore_LeavesNoTemporaryFileWhenBlockedOn()
    {
        string file = Path.Combine(_directory, "config.json");
        JsonAppSettingsStore store = new(file);

        RunBlockedOnUiLikeThread(
            () => store.SaveAsync(new AppSettings { ShowHiddenFiles = true }).GetAwaiter().GetResult(),
            "JsonAppSettingsStore.SaveAsync");

        // The hang left the file written but unrenamed; completing the call must rename it.
        Assert.True(File.Exists(file));
        Assert.False(File.Exists(file + ".tmp"));
    }

    [Fact]
    public void ProfileStore_SaveThenLoad_SurvivesABlockingCaller()
    {
        string file = Path.Combine(_directory, "sites.json");
        JsonConnectionProfileStore store = new(
            MasterPasswordVault.Create("test-password", iterations: 1_000).Protector,
            file);

        ConnectionProfile profile = new()
        {
            Name = "Site",
            ServiceUrl = "https://s3.example.com",
            AccessKeyId = "key",
            SecretAccessKey = "secret",
        };

        RunBlockedOnUiLikeThread(
            () => store.SaveAsync(profile).GetAwaiter().GetResult(),
            "JsonConnectionProfileStore.SaveAsync");

        RunBlockedOnUiLikeThread(
            () => Assert.Single(store.LoadAsync().GetAwaiter().GetResult()),
            "JsonConnectionProfileStore.LoadAsync");

        Assert.False(File.Exists(file + ".tmp"));
    }

    public void Dispose() => Directory.Delete(_directory, recursive: true);
}
