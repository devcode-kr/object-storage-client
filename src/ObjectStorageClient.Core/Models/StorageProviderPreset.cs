namespace ObjectStorageClient.Core.Models;

/// <summary>
/// A ready-made configuration for a known S3-compatible service.
/// Presets only seed the connection form — every field they populate stays editable,
/// and <see cref="StorageProviderCatalog.Custom"/> leaves everything to the user.
/// </summary>
public sealed record StorageProviderPreset
{
    /// <summary>Stable identifier persisted in <see cref="ConnectionProfile.ProviderId"/>.</summary>
    public required string Id { get; init; }

    /// <summary>Human-readable name shown in the provider drop-down.</summary>
    public required string DisplayName { get; init; }

    /// <summary>
    /// Endpoint template. Supports the <c>{region}</c> and <c>{account}</c> placeholders.
    /// Empty for providers whose endpoint must be typed by hand (MinIO, Ceph, custom).
    /// </summary>
    public string EndpointTemplate { get; init; } = string.Empty;

    /// <summary>Suggested regions. The region field remains free-text so unlisted regions still work.</summary>
    public IReadOnlyList<string> Regions { get; init; } = [];

    public string DefaultRegion { get; init; } = "us-east-1";

    /// <summary>
    /// Path-style addressing (<c>host/bucket/key</c>) instead of virtual-host style
    /// (<c>bucket.host/key</c>). Required by MinIO/Ceph and most self-hosted gateways.
    /// </summary>
    public bool ForcePathStyle { get; init; }

    /// <summary>True when <see cref="ConnectionProfile.AccountId"/> is part of the endpoint (Cloudflare R2).</summary>
    public bool RequiresAccountId { get; init; }

    /// <summary>
    /// Suppress the SDK's opportunistic request checksums. AWS SDK v4 sends
    /// <c>x-amz-checksum-*</c> and <c>aws-chunked</c> bodies by default, and gateways that do not
    /// implement them answer <c>NotImplemented</c> — which is why this defaults to <c>true</c>
    /// and only Amazon S3 itself opts back in.
    /// </summary>
    public bool DisableRequestChecksums { get; init; } = true;

    /// <summary>True for the free-form entry that pre-fills nothing.</summary>
    public bool IsCustom { get; init; }

    /// <summary>Short hint rendered under the endpoint field.</summary>
    public string Hint { get; init; } = string.Empty;

    /// <summary>
    /// Resolves <see cref="EndpointTemplate"/> against the supplied region and account id.
    /// Returns an empty string when the provider has no template (fully manual endpoint).
    /// </summary>
    public string BuildEndpoint(string? region, string? accountId)
    {
        if (string.IsNullOrWhiteSpace(EndpointTemplate))
        {
            return string.Empty;
        }

        return EndpointTemplate
            .Replace("{region}", (region ?? DefaultRegion).Trim(), StringComparison.Ordinal)
            .Replace("{account}", (accountId ?? string.Empty).Trim(), StringComparison.Ordinal);
    }
}
