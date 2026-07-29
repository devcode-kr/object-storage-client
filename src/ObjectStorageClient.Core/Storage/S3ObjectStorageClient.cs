using System.Runtime.CompilerServices;
using Amazon;
using Amazon.Runtime;
using Amazon.S3;
using Amazon.S3.Model;
using Amazon.S3.Transfer;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Transfers;

namespace ObjectStorageClient.Core.Storage;

/// <summary>
/// <see cref="IObjectStorageClient"/> backed by AWSSDK.S3, configured for arbitrary
/// S3-compatible endpoints rather than AWS alone.
/// </summary>
public sealed class S3ObjectStorageClient : IObjectStorageClient
{
    private readonly AmazonS3Client _client;
    private readonly TransferUtility _transferUtility;

    public S3ObjectStorageClient(ConnectionProfile profile)
    {
        Profile = profile;
        _client = new AmazonS3Client(BuildCredentials(profile), BuildConfig(profile));
        _transferUtility = new TransferUtility(_client);
    }

    public ConnectionProfile Profile { get; }

    /// <summary>
    /// Translates a profile into an <see cref="AmazonS3Config"/>. Kept internal-but-testable
    /// because the endpoint/path-style/proxy mapping is the part most likely to regress.
    /// </summary>
    internal static AmazonS3Config BuildConfig(ConnectionProfile profile)
    {
        string endpoint = profile.ResolveEndpoint();

        AmazonS3Config config = new()
        {
            ServiceURL = endpoint,
            ForcePathStyle = profile.ForcePathStyle,
            // Non-AWS endpoints have no RegionEndpoint; the region only needs to reach SigV4.
            AuthenticationRegion = string.IsNullOrWhiteSpace(profile.Region) ? "us-east-1" : profile.Region.Trim(),
            Timeout = TimeSpan.FromSeconds(Math.Clamp(profile.TimeoutSeconds, 5, 3600)),
        };

        if (profile.DisableRequestChecksums)
        {
            // AWS SDK v4 sends x-amz-checksum-* by default; several gateways reject it.
            config.RequestChecksumCalculation = RequestChecksumCalculation.WHEN_REQUIRED;
            config.ResponseChecksumValidation = ResponseChecksumValidation.WHEN_REQUIRED;
        }

        // Proxying and TLS relaxation are handled on the HttpClient handler: SDK v4 no longer
        // exposes bypass-list settings on the config object.
        if (S3HttpClientFactory.IsRequiredFor(profile))
        {
            config.HttpClientFactory = new S3HttpClientFactory(profile);
        }

        return config;
    }

    /// <summary>
    /// Runs an SDK call, replacing an <see cref="AmazonS3Exception"/> with a
    /// <see cref="StorageOperationException"/> carrying an actionable message. Cancellation is
    /// deliberately left alone so the transfer queue can still tell "cancelled" from "failed".
    /// </summary>
    private static async Task<T> InvokeAsync<T>(Func<Task<T>> operation)
    {
        try
        {
            return await operation().ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is not OperationCanceledException && FindS3Exception(ex) is not null)
        {
            throw Translate(ex);
        }
    }

    private static async Task InvokeAsync(Func<Task> operation)
    {
        try
        {
            await operation().ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is not OperationCanceledException && FindS3Exception(ex) is not null)
        {
            throw Translate(ex);
        }
    }

    private static StorageOperationException Translate(Exception exception)
    {
        AmazonS3Exception s3Exception = FindS3Exception(exception)!;

        return new StorageOperationException(S3ErrorGuidance.Describe(s3Exception), exception)
        {
            ErrorCode = s3Exception.ErrorCode ?? string.Empty,
        };
    }

    /// <summary>TransferUtility wraps multipart failures, so the S3 exception may be nested.</summary>
    private static AmazonS3Exception? FindS3Exception(Exception? exception)
    {
        while (exception is not null)
        {
            if (exception is AmazonS3Exception s3Exception)
            {
                return s3Exception;
            }

            if (exception is AggregateException aggregate)
            {
                foreach (Exception inner in aggregate.InnerExceptions)
                {
                    if (FindS3Exception(inner) is { } found)
                    {
                        return found;
                    }
                }

                return null;
            }

            exception = exception.InnerException;
        }

        return null;
    }

    private static AWSCredentials BuildCredentials(ConnectionProfile profile) =>
        string.IsNullOrWhiteSpace(profile.SessionToken)
            ? new BasicAWSCredentials(profile.AccessKeyId, profile.SecretAccessKey)
            : new SessionAWSCredentials(profile.AccessKeyId, profile.SecretAccessKey, profile.SessionToken);

    public async Task TestConnectionAsync(CancellationToken cancellationToken = default)
    {
        // Prefer the configured bucket: many keys are scoped to one bucket and cannot ListBuckets.
        if (!string.IsNullOrWhiteSpace(Profile.DefaultBucket))
        {
            await InvokeAsync(() => _client.ListObjectsV2Async(
                new ListObjectsV2Request
                {
                    BucketName = Profile.DefaultBucket,
                    MaxKeys = 1,
                    Delimiter = "/",
                },
                cancellationToken)).ConfigureAwait(false);
            return;
        }

        await InvokeAsync(() => _client.ListBucketsAsync(new ListBucketsRequest(), cancellationToken))
            .ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<StorageBucket>> ListBucketsAsync(CancellationToken cancellationToken = default)
    {
        ListBucketsResponse response = await _client
            .ListBucketsAsync(new ListBucketsRequest(), cancellationToken)
            .ConfigureAwait(false);

        if (response.Buckets is null)
        {
            return [];
        }

        return [.. response.Buckets.Select(bucket => new StorageBucket
        {
            Name = bucket.BucketName,
            CreatedAt = bucket.CreationDate,
        })];
    }

    public async Task<ObjectListingPage> ListAsync(
        string bucket,
        string prefix,
        string? continuationToken = null,
        CancellationToken cancellationToken = default)
    {
        string normalizedPrefix = ObjectKey.NormalizePrefix(prefix);

        ListObjectsV2Response response = await InvokeAsync(() => _client.ListObjectsV2Async(
            new ListObjectsV2Request
            {
                BucketName = bucket,
                Prefix = normalizedPrefix,
                Delimiter = ObjectKey.Separator.ToString(),
                ContinuationToken = continuationToken,
                MaxKeys = 1000,
            },
            cancellationToken)).ConfigureAwait(false);

        List<RemoteEntry> entries = [];

        foreach (string commonPrefix in response.CommonPrefixes ?? [])
        {
            entries.Add(RemoteEntry.Folder(commonPrefix, ObjectKey.GetName(commonPrefix)));
        }

        foreach (S3Object s3Object in response.S3Objects ?? [])
        {
            // The zero-byte marker representing the prefix itself is not a child.
            if (string.Equals(s3Object.Key, normalizedPrefix, StringComparison.Ordinal))
            {
                continue;
            }

            entries.Add(new RemoteEntry
            {
                Name = ObjectKey.GetName(s3Object.Key),
                Key = s3Object.Key,
                IsFolder = false,
                Size = s3Object.Size ?? 0,
                LastModified = s3Object.LastModified,
                ETag = s3Object.ETag ?? string.Empty,
                StorageClass = s3Object.StorageClass?.Value ?? string.Empty,
            });
        }

        return new ObjectListingPage
        {
            Entries = entries,
            NextContinuationToken = response.IsTruncated == true ? response.NextContinuationToken : null,
        };
    }

    public async IAsyncEnumerable<RemoteEntry> EnumerateAllAsync(
        string bucket,
        string prefix,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        string normalizedPrefix = ObjectKey.NormalizePrefix(prefix);
        string? token = null;

        do
        {
            ListObjectsV2Response response = await InvokeAsync(() => _client.ListObjectsV2Async(
                new ListObjectsV2Request
                {
                    BucketName = bucket,
                    Prefix = normalizedPrefix,
                    ContinuationToken = token,
                    MaxKeys = 1000,
                },
                cancellationToken)).ConfigureAwait(false);

            foreach (S3Object s3Object in response.S3Objects ?? [])
            {
                if (s3Object.Key.EndsWith(ObjectKey.Separator))
                {
                    continue;
                }

                yield return new RemoteEntry
                {
                    Name = ObjectKey.GetName(s3Object.Key),
                    Key = s3Object.Key,
                    Size = s3Object.Size ?? 0,
                    LastModified = s3Object.LastModified,
                    ETag = s3Object.ETag ?? string.Empty,
                    StorageClass = s3Object.StorageClass?.Value ?? string.Empty,
                };
            }

            token = response.IsTruncated == true ? response.NextContinuationToken : null;
        }
        while (!string.IsNullOrEmpty(token));
    }

    public async Task DownloadAsync(
        string bucket,
        string key,
        string destinationPath,
        IProgress<TransferProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        string? directory = Path.GetDirectoryName(destinationPath);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        TransferUtilityDownloadRequest request = new()
        {
            BucketName = bucket,
            Key = ObjectKey.Normalize(key),
            FilePath = destinationPath,
        };

        if (progress is not null)
        {
            request.WriteObjectProgressEvent += (_, args) =>
                progress.Report(new TransferProgress(args.TransferredBytes, args.TotalBytes));
        }

        await InvokeAsync(() => _transferUtility.DownloadAsync(request, cancellationToken)).ConfigureAwait(false);
    }

    public async Task UploadAsync(
        string bucket,
        string key,
        string sourcePath,
        IProgress<TransferProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        TransferUtilityUploadRequest request = new()
        {
            BucketName = bucket,
            Key = ObjectKey.Normalize(key),
            FilePath = sourcePath,
        };

        if (progress is not null)
        {
            request.UploadProgressEvent += (_, args) =>
                progress.Report(new TransferProgress(args.TransferredBytes, args.TotalBytes));
        }

        await InvokeAsync(() => _transferUtility.UploadAsync(request, cancellationToken)).ConfigureAwait(false);
    }

    public async Task DeleteObjectAsync(string bucket, string key, CancellationToken cancellationToken = default) =>
        await InvokeAsync(() => _client.DeleteObjectAsync(
            new DeleteObjectRequest { BucketName = bucket, Key = ObjectKey.Normalize(key) },
            cancellationToken)).ConfigureAwait(false);

    public async Task CreateFolderAsync(string bucket, string prefix, CancellationToken cancellationToken = default)
    {
        string folderKey = ObjectKey.NormalizePrefix(prefix);
        if (folderKey.Length == 0)
        {
            throw new ArgumentException("Folder prefix must not be empty.", nameof(prefix));
        }

        await InvokeAsync(() => _client.PutObjectAsync(
            new PutObjectRequest
            {
                BucketName = bucket,
                Key = folderKey,
                ContentBody = string.Empty,
            },
            cancellationToken)).ConfigureAwait(false);
    }

    public ValueTask DisposeAsync()
    {
        _transferUtility.Dispose();
        _client.Dispose();
        return ValueTask.CompletedTask;
    }
}

/// <summary>Default factory; registered in DI so the UI never constructs an SDK client directly.</summary>
public sealed class S3ObjectStorageClientFactory : IObjectStorageClientFactory
{
    public IObjectStorageClient Create(ConnectionProfile profile) => new S3ObjectStorageClient(profile);
}
