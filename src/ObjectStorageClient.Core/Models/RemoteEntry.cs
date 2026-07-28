namespace ObjectStorageClient.Core.Models;

/// <summary>One row in the remote pane: either a common prefix ("folder") or an object.</summary>
public sealed record RemoteEntry
{
    public required string Name { get; init; }

    /// <summary>Full object key. Folder entries end with <c>/</c>.</summary>
    public required string Key { get; init; }

    public bool IsFolder { get; init; }

    public long Size { get; init; }

    public DateTimeOffset? LastModified { get; init; }

    public string ETag { get; init; } = string.Empty;

    public string StorageClass { get; init; } = string.Empty;

    public static RemoteEntry Folder(string key, string name) => new()
    {
        Name = name,
        Key = key,
        IsFolder = true,
    };
}

/// <summary>A single page of <see cref="RemoteEntry"/> values plus the token needed to fetch the next one.</summary>
public sealed record ObjectListingPage
{
    public static ObjectListingPage Empty { get; } = new();

    public IReadOnlyList<RemoteEntry> Entries { get; init; } = [];

    /// <summary>Non-null when the listing was truncated.</summary>
    public string? NextContinuationToken { get; init; }

    public bool HasMore => !string.IsNullOrEmpty(NextContinuationToken);
}

/// <summary>A bucket in the remote pane's bucket selector. Named to avoid colliding with the SDK's own type.</summary>
public sealed record StorageBucket
{
    public required string Name { get; init; }

    public DateTimeOffset? CreatedAt { get; init; }
}
