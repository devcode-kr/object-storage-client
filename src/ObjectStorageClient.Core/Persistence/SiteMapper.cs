using System.Text.Json;
using System.Text.Json.Serialization;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Models;

namespace ObjectStorageClient.Core.Persistence;

/// <summary>
/// Converts between <see cref="ConnectionProfile"/> — the model the UI binds to — and the
/// <see cref="StoredSite"/> layout written to <c>sites.json</c>.
/// </summary>
/// <remarks>
/// This is the only place the two shapes meet. Everything that describes how to reach an endpoint
/// is encrypted together as one blob, so there is no per-field judgement about what counts as
/// secret and no extra field to add when the connection grows a new setting.
/// </remarks>
internal static class SiteMapper
{
    /// <summary>Compact: the result is encrypted, so readability buys nothing.</summary>
    private static readonly JsonSerializerOptions ConnectionOptions = new()
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };

    internal static StoredSite ToStored(ConnectionProfile profile, ISecretProtector protector)
    {
        StoredConnection connection = new()
        {
            ServiceUrl = profile.ServiceUrl,
            Region = profile.Region,
            AccountId = profile.AccountId,
            AccessKeyId = profile.AccessKeyId,
            SecretAccessKey = profile.SecretAccessKey,
            SessionToken = profile.SessionToken,
            DefaultBucket = profile.DefaultBucket,
            DefaultPrefix = profile.DefaultPrefix,
            Proxy = new StoredProxy
            {
                Enabled = profile.Proxy.Enabled,
                Host = profile.Proxy.Host,
                Port = profile.Proxy.Port,
                Username = profile.Proxy.Username,
                Password = profile.Proxy.Password,
                BypassList = profile.Proxy.BypassList,
            },
        };

        return new StoredSite
        {
            Id = profile.Id,
            Name = profile.Name,
            ProviderId = profile.ProviderId,
            ForcePathStyle = profile.ForcePathStyle,
            AllowInsecureCertificates = profile.AllowInsecureCertificates,
            DisableRequestChecksums = profile.DisableRequestChecksums,
            DisableChunkedEncoding = profile.DisableChunkedEncoding,
            TimeoutSeconds = profile.TimeoutSeconds,
            MaxConcurrentTransfers = profile.MaxConcurrentTransfers,
            CreatedAt = profile.CreatedAt,
            LastModifiedAt = profile.LastModifiedAt,
            LastUsedAt = profile.LastUsedAt,
            Connection = protector.Protect(JsonSerializer.Serialize(connection, ConnectionOptions)),
        };
    }

    /// <summary>
    /// Rebuilds the profile. A blob that cannot be decrypted — wrong master password, or a file
    /// copied from another machine — yields a site with its connection fields blank rather than a
    /// missing site, so the user can see what is there and re-enter it.
    /// </summary>
    internal static ConnectionProfile ToProfile(StoredSite stored, ISecretProtector protector)
    {
        StoredConnection connection = ReadConnection(stored.Connection, protector);

        return new ConnectionProfile
        {
            Id = stored.Id,
            Name = stored.Name,
            ProviderId = stored.ProviderId,
            ServiceUrl = connection.ServiceUrl,
            Region = connection.Region,
            AccountId = connection.AccountId,
            AccessKeyId = connection.AccessKeyId,
            SecretAccessKey = connection.SecretAccessKey,
            SessionToken = connection.SessionToken,
            DefaultBucket = connection.DefaultBucket,
            DefaultPrefix = connection.DefaultPrefix,
            ForcePathStyle = stored.ForcePathStyle,
            AllowInsecureCertificates = stored.AllowInsecureCertificates,
            DisableRequestChecksums = stored.DisableRequestChecksums,
            DisableChunkedEncoding = stored.DisableChunkedEncoding,
            TimeoutSeconds = stored.TimeoutSeconds,
            MaxConcurrentTransfers = stored.MaxConcurrentTransfers,
            CreatedAt = stored.CreatedAt,
            LastModifiedAt = stored.LastModifiedAt,
            LastUsedAt = stored.LastUsedAt,
            Proxy = new ProxySettings
            {
                Enabled = connection.Proxy.Enabled,
                Host = connection.Proxy.Host,
                Port = connection.Proxy.Port,
                Username = connection.Proxy.Username,
                Password = connection.Proxy.Password,
                BypassList = connection.Proxy.BypassList,
            },
        };
    }

    /// <summary>
    /// Reads a version 1 entry, where the profile sat in the clear beside three separately
    /// encrypted secrets. Timestamps did not exist then, so they are seeded from the file itself.
    /// </summary>
    internal static ConnectionProfile ToProfile(
        LegacyStoredSite stored,
        ISecretProtector protector,
        DateTimeOffset migratedAt)
    {
        LegacyProfile profile = stored.Profile;

        return new ConnectionProfile
        {
            Id = profile.Id == Guid.Empty ? Guid.NewGuid() : profile.Id,
            Name = profile.Name,
            ProviderId = profile.ProviderId,
            ServiceUrl = profile.ServiceUrl,
            Region = profile.Region,
            AccountId = profile.AccountId,
            AccessKeyId = profile.AccessKeyId,
            SecretAccessKey = protector.Unprotect(stored.SecretAccessKey),
            SessionToken = protector.Unprotect(stored.SessionToken),
            DefaultBucket = profile.DefaultBucket,
            DefaultPrefix = profile.DefaultPrefix,
            ForcePathStyle = profile.ForcePathStyle,
            AllowInsecureCertificates = profile.AllowInsecureCertificates,
            DisableRequestChecksums = profile.DisableRequestChecksums,
            DisableChunkedEncoding = profile.DisableChunkedEncoding,
            TimeoutSeconds = profile.TimeoutSeconds,
            MaxConcurrentTransfers = profile.MaxConcurrentTransfers,
            CreatedAt = migratedAt,
            LastModifiedAt = migratedAt,
            LastUsedAt = profile.LastUsedAt,
            Proxy = new ProxySettings
            {
                Enabled = profile.Proxy.Enabled,
                Host = profile.Proxy.Host,
                Port = profile.Proxy.Port,
                Username = profile.Proxy.Username,
                Password = protector.Unprotect(stored.ProxyPassword),
                BypassList = profile.Proxy.BypassList,
            },
        };
    }

    private static StoredConnection ReadConnection(string encrypted, ISecretProtector protector)
    {
        string json = protector.Unprotect(encrypted);
        if (string.IsNullOrEmpty(json))
        {
            return new StoredConnection();
        }

        try
        {
            return JsonSerializer.Deserialize<StoredConnection>(json, ConnectionOptions)
                ?? new StoredConnection();
        }
        catch (JsonException)
        {
            return new StoredConnection();
        }
    }
}
