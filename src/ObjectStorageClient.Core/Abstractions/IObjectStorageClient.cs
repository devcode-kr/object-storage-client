using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Transfers;

namespace ObjectStorageClient.Core.Abstractions;

/// <summary>
/// Storage operations the UI depends on, expressed without any vendor types.
/// The S3 implementation lives in <c>Storage/S3ObjectStorageClient</c>; tests substitute a fake.
/// </summary>
public interface IObjectStorageClient : IAsyncDisposable
{
    /// <summary>Profile this client was created from.</summary>
    ConnectionProfile Profile { get; }

    /// <summary>Cheap round-trip used by "Test connection" and by quick-connect before opening a session.</summary>
    Task TestConnectionAsync(CancellationToken cancellationToken = default);

    Task<IReadOnlyList<StorageBucket>> ListBucketsAsync(CancellationToken cancellationToken = default);

    /// <summary>
    /// Lists one page of a single prefix level: immediate child folders plus objects.
    /// Pass the previous page's <see cref="ObjectListingPage.NextContinuationToken"/> to continue.
    /// </summary>
    Task<ObjectListingPage> ListAsync(
        string bucket,
        string prefix,
        string? continuationToken = null,
        CancellationToken cancellationToken = default);

    Task DownloadAsync(
        string bucket,
        string key,
        string destinationPath,
        IProgress<TransferProgress>? progress = null,
        CancellationToken cancellationToken = default);

    Task UploadAsync(
        string bucket,
        string key,
        string sourcePath,
        IProgress<TransferProgress>? progress = null,
        CancellationToken cancellationToken = default);

    Task DeleteObjectAsync(string bucket, string key, CancellationToken cancellationToken = default);

    /// <summary>Creates a zero-byte marker object so an empty folder shows up in listings.</summary>
    Task CreateFolderAsync(string bucket, string prefix, CancellationToken cancellationToken = default);

    /// <summary>Enumerates every object under a prefix, following continuation tokens.</summary>
    IAsyncEnumerable<RemoteEntry> EnumerateAllAsync(
        string bucket,
        string prefix,
        CancellationToken cancellationToken = default);
}

/// <summary>Creates <see cref="IObjectStorageClient"/> instances; the seam for swapping in a fake backend.</summary>
public interface IObjectStorageClientFactory
{
    IObjectStorageClient Create(ConnectionProfile profile);
}
