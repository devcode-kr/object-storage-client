using System.Collections.Concurrent;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Transfers;

namespace ObjectStorageClient.Core.Tests;

/// <summary>
/// In-memory <see cref="IObjectStorageClient"/> for exercising the transfer queue without a network.
/// Behaviour is steered by the delegates, so a test can make one specific key fail or hang.
/// </summary>
internal sealed class FakeObjectStorageClient : IObjectStorageClient
{
    /// <summary>Keys that should throw instead of transferring.</summary>
    internal HashSet<string> FailingKeys { get; } = [];

    /// <summary>Delay applied to every transfer, used to keep an item in-flight long enough to cancel it.</summary>
    internal TimeSpan TransferDelay { get; set; } = TimeSpan.Zero;

    internal ConcurrentBag<string> UploadedKeys { get; } = [];

    internal ConcurrentBag<string> DownloadedKeys { get; } = [];

    public ConnectionProfile Profile { get; } = new() { Name = "Fake" };

    public Task TestConnectionAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;

    public Task<IReadOnlyList<StorageBucket>> ListBucketsAsync(CancellationToken cancellationToken = default) =>
        Task.FromResult<IReadOnlyList<StorageBucket>>([new StorageBucket { Name = "bucket" }]);

    public Task<ObjectListingPage> ListAsync(
        string bucket,
        string prefix,
        string? continuationToken = null,
        CancellationToken cancellationToken = default) =>
        Task.FromResult(ObjectListingPage.Empty);

    public async Task DownloadAsync(
        string bucket,
        string key,
        string destinationPath,
        IProgress<TransferProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        await RunTransferAsync(key, progress, cancellationToken).ConfigureAwait(false);
        DownloadedKeys.Add(key);
    }

    public async Task UploadAsync(
        string bucket,
        string key,
        string sourcePath,
        IProgress<TransferProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        await RunTransferAsync(key, progress, cancellationToken).ConfigureAwait(false);
        UploadedKeys.Add(key);
    }

    public Task DeleteObjectAsync(string bucket, string key, CancellationToken cancellationToken = default) =>
        Task.CompletedTask;

    public Task CreateFolderAsync(string bucket, string prefix, CancellationToken cancellationToken = default) =>
        Task.CompletedTask;

    public async IAsyncEnumerable<RemoteEntry> EnumerateAllAsync(
        string bucket,
        string prefix,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        await Task.CompletedTask.ConfigureAwait(false);
        yield break;
    }

    public ValueTask DisposeAsync() => ValueTask.CompletedTask;

    private async Task RunTransferAsync(string key, IProgress<TransferProgress>? progress, CancellationToken cancellationToken)
    {
        if (FailingKeys.Contains(key))
        {
            throw new InvalidOperationException($"Simulated failure for '{key}'.");
        }

        if (TransferDelay > TimeSpan.Zero)
        {
            await Task.Delay(TransferDelay, cancellationToken).ConfigureAwait(false);
        }

        cancellationToken.ThrowIfCancellationRequested();
        progress?.Report(new TransferProgress(100, 100));
    }
}
