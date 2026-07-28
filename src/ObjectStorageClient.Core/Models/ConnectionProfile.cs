namespace ObjectStorageClient.Core.Models;

/// <summary>
/// Everything needed to open a connection to an object storage endpoint.
/// A profile may be seeded from a <see cref="StorageProviderPreset"/>, but every field
/// is independently editable — a fully hand-typed profile is a first-class case.
/// </summary>
public sealed record ConnectionProfile
{
    public Guid Id { get; init; } = Guid.NewGuid();

    public string Name { get; init; } = "New Site";

    /// <summary>Preset this profile was seeded from, or <c>custom</c> for manual entry.</summary>
    public string ProviderId { get; init; } = StorageProviderCatalog.CustomProviderId;

    /// <summary>Absolute endpoint URL. Always wins over the preset template once set.</summary>
    public string ServiceUrl { get; init; } = string.Empty;

    public string Region { get; init; } = "us-east-1";

    /// <summary>Account identifier for providers that embed it in the endpoint (Cloudflare R2).</summary>
    public string AccountId { get; init; } = string.Empty;

    public string AccessKeyId { get; init; } = string.Empty;

    /// <summary>Held in plaintext in memory only; persisted through <c>ISecretProtector</c>.</summary>
    public string SecretAccessKey { get; init; } = string.Empty;

    /// <summary>Optional temporary-credential session token (STS).</summary>
    public string SessionToken { get; init; } = string.Empty;

    /// <summary>Bucket opened right after connecting. Empty means "show the bucket list".</summary>
    public string DefaultBucket { get; init; } = string.Empty;

    /// <summary>Prefix selected right after opening <see cref="DefaultBucket"/>.</summary>
    public string DefaultPrefix { get; init; } = string.Empty;

    public bool ForcePathStyle { get; init; } = true;

    /// <summary>Skip TLS certificate validation. Only for self-signed development endpoints.</summary>
    public bool AllowInsecureCertificates { get; init; }

    /// <summary>See <see cref="StorageProviderPreset.DisableRequestChecksums"/>.</summary>
    public bool DisableRequestChecksums { get; init; }

    public int TimeoutSeconds { get; init; } = 100;

    public int MaxConcurrentTransfers { get; init; } = 3;

    public ProxySettings Proxy { get; init; } = ProxySettings.Disabled;

    public DateTimeOffset? LastUsedAt { get; init; }

    /// <summary>The preset backing <see cref="ProviderId"/>.</summary>
    public StorageProviderPreset Preset => StorageProviderCatalog.Resolve(ProviderId);

    /// <summary>
    /// Effective endpoint: the explicit <see cref="ServiceUrl"/> when present, otherwise the
    /// preset template resolved against <see cref="Region"/> and <see cref="AccountId"/>.
    /// </summary>
    public string ResolveEndpoint() =>
        string.IsNullOrWhiteSpace(ServiceUrl)
            ? Preset.BuildEndpoint(Region, AccountId)
            : ServiceUrl.Trim();

    /// <summary>
    /// Creates a profile pre-filled from a preset. All values remain editable afterwards.
    /// </summary>
    public static ConnectionProfile FromPreset(StorageProviderPreset preset, string? name = null) => new()
    {
        Name = name ?? preset.DisplayName,
        ProviderId = preset.Id,
        Region = preset.DefaultRegion,
        ServiceUrl = preset.BuildEndpoint(preset.DefaultRegion, accountId: null),
        ForcePathStyle = preset.ForcePathStyle,
        DisableRequestChecksums = preset.DisableRequestChecksums,
    };

    /// <summary>
    /// Validates the fields required to open a connection.
    /// Returns an empty list when the profile is ready to connect.
    /// </summary>
    public IReadOnlyList<string> Validate()
    {
        List<string> errors = [];

        if (string.IsNullOrWhiteSpace(Name))
        {
            errors.Add("Site name is required.");
        }

        string endpoint = ResolveEndpoint();
        if (string.IsNullOrWhiteSpace(endpoint))
        {
            errors.Add("Endpoint URL is required.");
        }
        else if (!Uri.TryCreate(endpoint, UriKind.Absolute, out Uri? uri) ||
                 (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
        {
            errors.Add($"Endpoint '{endpoint}' is not a valid http(s) URL.");
        }

        if (Preset.RequiresAccountId && string.IsNullOrWhiteSpace(AccountId) && string.IsNullOrWhiteSpace(ServiceUrl))
        {
            errors.Add($"{Preset.DisplayName} requires an account ID.");
        }

        if (string.IsNullOrWhiteSpace(AccessKeyId))
        {
            errors.Add("Access key ID is required.");
        }

        if (string.IsNullOrWhiteSpace(SecretAccessKey))
        {
            errors.Add("Secret access key is required.");
        }

        if (Proxy.Enabled && !Proxy.IsUsable)
        {
            errors.Add("Proxy is enabled but the host or port is invalid.");
        }

        if (MaxConcurrentTransfers is < 1 or > 16)
        {
            errors.Add("Concurrent transfers must be between 1 and 16.");
        }

        return errors;
    }

    /// <summary>Copy without secret material, for logging and on-disk storage of the non-secret part.</summary>
    public ConnectionProfile WithoutSecrets() => this with
    {
        SecretAccessKey = string.Empty,
        SessionToken = string.Empty,
        Proxy = Proxy with { Password = string.Empty },
    };
}
