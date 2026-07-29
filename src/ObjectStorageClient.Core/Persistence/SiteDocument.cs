namespace ObjectStorageClient.Core.Persistence;

/// <summary>
/// Root of <c>sites.json</c>. This is the persistence contract, deliberately separate from
/// <see cref="Models.ConnectionProfile"/> so the shape on disk can change independently of the
/// model the UI binds to — and so nothing reaches the file just by being a public getter.
/// </summary>
internal sealed record SiteDocument
{
    /// <summary>
    /// Still 1: nothing has shipped, so the layout change does not need a new version number.
    /// </summary>
    internal const int CurrentVersion = 1;

    public int Version { get; init; } = CurrentVersion;

    public IReadOnlyList<StoredSite> Sites { get; init; } = [];
}

/// <summary>
/// One saved site. Everything that identifies or reaches the endpoint lives inside
/// <see cref="Connection"/>, encrypted as a single blob; only what the Site Manager needs to
/// list and describe a site is left readable.
/// </summary>
internal sealed record StoredSite
{
    public Guid Id { get; init; }

    public string Name { get; init; } = string.Empty;

    public string ProviderId { get; init; } = string.Empty;

    // Behavioural switches. Not sensitive, and useful to see without unlocking.
    public bool ForcePathStyle { get; init; }

    public bool AllowInsecureCertificates { get; init; }

    public bool DisableRequestChecksums { get; init; }

    public bool DisableChunkedEncoding { get; init; }

    public int TimeoutSeconds { get; init; }

    public int MaxConcurrentTransfers { get; init; }

    public DateTimeOffset CreatedAt { get; init; }

    public DateTimeOffset LastModifiedAt { get; init; }

    public DateTimeOffset? LastUsedAt { get; init; }

    /// <summary>Encrypted <see cref="StoredConnection"/> JSON.</summary>
    public string Connection { get; init; } = string.Empty;
}

/// <summary>
/// The encrypted half. Grouping these means there is no per-field decision about what is secret:
/// everything that describes how to reach the endpoint, credentials included, is inside the blob.
/// </summary>
internal sealed record StoredConnection
{
    public string ServiceUrl { get; init; } = string.Empty;

    public string Region { get; init; } = string.Empty;

    public string AccountId { get; init; } = string.Empty;

    public string AccessKeyId { get; init; } = string.Empty;

    public string SecretAccessKey { get; init; } = string.Empty;

    public string SessionToken { get; init; } = string.Empty;

    public string DefaultBucket { get; init; } = string.Empty;

    public string DefaultPrefix { get; init; } = string.Empty;

    public StoredProxy Proxy { get; init; } = new();
}

internal sealed record StoredProxy
{
    public bool Enabled { get; init; }

    public string Host { get; init; } = string.Empty;

    public int Port { get; init; } = 8080;

    public string Username { get; init; } = string.Empty;

    public string Password { get; init; } = string.Empty;

    public string BypassList { get; init; } = string.Empty;
}

/// <summary>
/// The pre-release layout: the whole profile in the clear, with three separately encrypted
/// secrets beside it.
/// </summary>
/// <remarks>
/// TEMPORARY. This exists only to convert files written before the connection was encrypted as a
/// single blob, which happens automatically the first time such a file is read. Both formats
/// claim version 1 — the layout changed before anything shipped — so they are told apart by shape:
/// a legacy entry has <c>profile</c>, a current one has <c>connection</c>. Delete this record,
/// its siblings and <c>SiteMapper</c>'s legacy overload once no such files remain.
/// </remarks>
internal sealed record LegacySiteDocument
{
    public int Version { get; init; } = SiteDocument.CurrentVersion;

    public IReadOnlyList<LegacyStoredSite> Sites { get; init; } = [];
}

internal sealed record LegacyStoredSite
{
    public LegacyProfile Profile { get; init; } = new();

    public string SecretAccessKey { get; init; } = string.Empty;

    public string SessionToken { get; init; } = string.Empty;

    public string ProxyPassword { get; init; } = string.Empty;
}

internal sealed record LegacyProfile
{
    public Guid Id { get; init; }

    public string Name { get; init; } = string.Empty;

    public string ProviderId { get; init; } = string.Empty;

    public string ServiceUrl { get; init; } = string.Empty;

    public string Region { get; init; } = string.Empty;

    public string AccountId { get; init; } = string.Empty;

    public string AccessKeyId { get; init; } = string.Empty;

    public string DefaultBucket { get; init; } = string.Empty;

    public string DefaultPrefix { get; init; } = string.Empty;

    public bool ForcePathStyle { get; init; } = true;

    public bool AllowInsecureCertificates { get; init; }

    public bool DisableRequestChecksums { get; init; } = true;

    public bool DisableChunkedEncoding { get; init; } = true;

    public int TimeoutSeconds { get; init; } = 100;

    public int MaxConcurrentTransfers { get; init; } = 3;

    public LegacyProxy Proxy { get; init; } = new();

    public DateTimeOffset? LastUsedAt { get; init; }
}

internal sealed record LegacyProxy
{
    public bool Enabled { get; init; }

    public string Host { get; init; } = string.Empty;

    public int Port { get; init; } = 8080;

    public string Username { get; init; } = string.Empty;

    public string BypassList { get; init; } = string.Empty;
}
