using System.Collections.Immutable;

namespace ObjectStorageClient.Core.Models;

/// <summary>
/// Built-in list of S3-compatible providers offered in the connection dialog.
/// Adding a provider here is the only change required to make it selectable in the UI.
/// </summary>
public static class StorageProviderCatalog
{
    public const string CustomProviderId = "custom";

    /// <summary>Fully manual entry: no endpoint template, nothing pre-filled.</summary>
    public static StorageProviderPreset Custom { get; } = new()
    {
        Id = CustomProviderId,
        DisplayName = "Custom / S3-compatible",
        IsCustom = true,
        ForcePathStyle = true,
        DefaultRegion = "us-east-1",
        Hint = "Enter the full endpoint URL, e.g. https://storage.example.com:9000",
    };

    public static ImmutableArray<StorageProviderPreset> All { get; } =
    [
        new()
        {
            Id = "aws",
            DisplayName = "Amazon S3",
            EndpointTemplate = "https://s3.{region}.amazonaws.com",
            DefaultRegion = "us-east-1",
            Regions =
            [
                "us-east-1", "us-east-2", "us-west-1", "us-west-2",
                "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1", "eu-north-1",
                "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
                "ap-southeast-1", "ap-southeast-2", "ap-south-1",
                "sa-east-1", "ca-central-1",
            ],
        },
        new()
        {
            Id = "minio",
            DisplayName = "MinIO",
            ForcePathStyle = true,
            DefaultRegion = "us-east-1",
            Hint = "Self-hosted endpoint, e.g. http://localhost:9000",
        },
        new()
        {
            Id = "r2",
            DisplayName = "Cloudflare R2",
            EndpointTemplate = "https://{account}.r2.cloudflarestorage.com",
            DefaultRegion = "auto",
            Regions = ["auto"],
            RequiresAccountId = true,
            DisableRequestChecksums = true,
            Hint = "Requires your Cloudflare account ID.",
        },
        new()
        {
            Id = "b2",
            DisplayName = "Backblaze B2",
            EndpointTemplate = "https://s3.{region}.backblazeb2.com",
            DefaultRegion = "us-west-004",
            Regions = ["us-west-000", "us-west-001", "us-west-002", "us-west-004", "eu-central-003"],
            DisableRequestChecksums = true,
        },
        new()
        {
            Id = "wasabi",
            DisplayName = "Wasabi",
            EndpointTemplate = "https://s3.{region}.wasabisys.com",
            DefaultRegion = "us-east-1",
            Regions = ["us-east-1", "us-east-2", "us-central-1", "us-west-1", "eu-central-1", "eu-west-1", "ap-northeast-1", "ap-northeast-2"],
        },
        new()
        {
            Id = "spaces",
            DisplayName = "DigitalOcean Spaces",
            EndpointTemplate = "https://{region}.digitaloceanspaces.com",
            DefaultRegion = "nyc3",
            Regions = ["nyc3", "sfo3", "ams3", "sgp1", "fra1", "syd1"],
        },
        new()
        {
            Id = "gcs",
            DisplayName = "Google Cloud Storage (S3 interop)",
            EndpointTemplate = "https://storage.googleapis.com",
            DefaultRegion = "auto",
            Regions = ["auto"],
            DisableRequestChecksums = true,
            Hint = "Requires an HMAC key from the Cloud Storage interoperability settings.",
        },
        new()
        {
            Id = "ncloud",
            DisplayName = "NAVER Cloud Object Storage",
            EndpointTemplate = "https://kr.object.ncloudstorage.com",
            DefaultRegion = "kr-standard",
            Regions = ["kr-standard"],
            ForcePathStyle = true,
        },
        new()
        {
            Id = "linode",
            DisplayName = "Akamai / Linode Object Storage",
            EndpointTemplate = "https://{region}.linodeobjects.com",
            DefaultRegion = "us-east-1",
            Regions = ["us-east-1", "us-southeast-1", "eu-central-1", "ap-south-1"],
        },
        Custom,
    ];

    /// <summary>Looks a preset up by id, falling back to <see cref="Custom"/> for unknown ids.</summary>
    public static StorageProviderPreset Resolve(string? providerId)
    {
        if (string.IsNullOrWhiteSpace(providerId))
        {
            return Custom;
        }

        foreach (StorageProviderPreset preset in All)
        {
            if (string.Equals(preset.Id, providerId, StringComparison.OrdinalIgnoreCase))
            {
                return preset;
            }
        }

        return Custom;
    }
}
