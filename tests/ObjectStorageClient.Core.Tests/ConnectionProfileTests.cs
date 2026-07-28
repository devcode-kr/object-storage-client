using ObjectStorageClient.Core.Models;
using Xunit;

namespace ObjectStorageClient.Core.Tests;

public sealed class ConnectionProfileTests
{
    private static ConnectionProfile ValidProfile() => new()
    {
        Name = "Test",
        ServiceUrl = "https://s3.example.com",
        Region = "us-east-1",
        AccessKeyId = "AKIA_TEST",
        SecretAccessKey = "secret",
    };

    [Fact]
    public void Validate_AcceptsAFullyManualProfile() => Assert.Empty(ValidProfile().Validate());

    [Fact]
    public void Validate_RequiresEndpointAccessKeyAndSecret()
    {
        IReadOnlyList<string> errors = new ConnectionProfile { Name = "Empty" }.Validate();

        Assert.Contains(errors, error => error.Contains("Endpoint", StringComparison.OrdinalIgnoreCase));
        Assert.Contains(errors, error => error.Contains("Access key", StringComparison.OrdinalIgnoreCase));
        Assert.Contains(errors, error => error.Contains("Secret", StringComparison.OrdinalIgnoreCase));
    }

    [Theory]
    [InlineData("ftp://example.com")]
    [InlineData("not a url")]
    public void Validate_RejectsNonHttpEndpoints(string endpoint)
    {
        IReadOnlyList<string> errors = (ValidProfile() with { ServiceUrl = endpoint }).Validate();

        Assert.Contains(errors, error => error.Contains("valid http", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void Validate_RejectsAnEnabledProxyWithoutAHost()
    {
        ConnectionProfile profile = ValidProfile() with
        {
            Proxy = new ProxySettings { Enabled = true, Host = "", Port = 8080 },
        };

        Assert.Contains(profile.Validate(), error => error.Contains("Proxy", StringComparison.Ordinal));
    }

    [Fact]
    public void Validate_RejectsOutOfRangeConcurrency()
    {
        ConnectionProfile profile = ValidProfile() with { MaxConcurrentTransfers = 99 };

        Assert.Contains(profile.Validate(), error => error.Contains("Concurrent", StringComparison.Ordinal));
    }

    [Fact]
    public void ResolveEndpoint_PrefersTheExplicitServiceUrlOverThePresetTemplate()
    {
        ConnectionProfile profile = ConnectionProfile.FromPreset(StorageProviderCatalog.Resolve("aws")) with
        {
            ServiceUrl = "https://my-gateway.internal:9000",
        };

        Assert.Equal("https://my-gateway.internal:9000", profile.ResolveEndpoint());
    }

    [Fact]
    public void ResolveEndpoint_FallsBackToThePresetTemplateWhenNoUrlIsSet()
    {
        ConnectionProfile profile = new()
        {
            ProviderId = "aws",
            Region = "eu-west-1",
            ServiceUrl = string.Empty,
        };

        Assert.Equal("https://s3.eu-west-1.amazonaws.com", profile.ResolveEndpoint());
    }

    [Fact]
    public void FromPreset_CopiesTheProviderQuirksButLeavesCredentialsEmpty()
    {
        ConnectionProfile profile = ConnectionProfile.FromPreset(StorageProviderCatalog.Resolve("r2"));

        Assert.Equal("r2", profile.ProviderId);
        Assert.True(profile.DisableRequestChecksums);
        Assert.Equal("auto", profile.Region);
        Assert.Empty(profile.AccessKeyId);
        Assert.Empty(profile.SecretAccessKey);
    }

    [Fact]
    public void Validate_RequiresAnAccountIdForProvidersThatEmbedItAndHaveNoManualUrl()
    {
        ConnectionProfile profile = ValidProfile() with
        {
            ProviderId = "r2",
            ServiceUrl = string.Empty,
            AccountId = string.Empty,
        };

        Assert.Contains(profile.Validate(), error => error.Contains("account ID", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void WithoutSecrets_ClearsEverySecretIncludingTheProxyPassword()
    {
        ConnectionProfile profile = ValidProfile() with
        {
            SessionToken = "token",
            Proxy = new ProxySettings { Enabled = true, Host = "proxy", Password = "hunter2" },
        };

        ConnectionProfile stripped = profile.WithoutSecrets();

        Assert.Empty(stripped.SecretAccessKey);
        Assert.Empty(stripped.SessionToken);
        Assert.Empty(stripped.Proxy.Password);
        Assert.Equal("proxy", stripped.Proxy.Host);
    }
}

public sealed class StorageProviderCatalogTests
{
    [Fact]
    public void Resolve_FallsBackToCustomForUnknownIds() =>
        Assert.True(StorageProviderCatalog.Resolve("nope").IsCustom);

    [Fact]
    public void Resolve_IsCaseInsensitive() =>
        Assert.Equal("aws", StorageProviderCatalog.Resolve("AWS").Id);

    [Fact]
    public void BuildEndpoint_SubstitutesRegionAndAccountPlaceholders()
    {
        StorageProviderPreset r2 = StorageProviderCatalog.Resolve("r2");

        Assert.Equal("https://abc123.r2.cloudflarestorage.com", r2.BuildEndpoint("auto", "abc123"));
    }

    [Fact]
    public void BuildEndpoint_ReturnsEmptyForManualOnlyProviders() =>
        Assert.Empty(StorageProviderCatalog.Resolve("minio").BuildEndpoint("us-east-1", null));

    [Fact]
    public void Catalog_AlwaysOffersTheCustomEntryLast() =>
        Assert.True(StorageProviderCatalog.All[^1].IsCustom);
}

public sealed class ProxySettingsTests
{
    [Theory]
    [InlineData(false, "proxy", 8080, false)]
    [InlineData(true, "", 8080, false)]
    [InlineData(true, "proxy", 0, false)]
    [InlineData(true, "proxy", 8080, true)]
    public void IsUsable_RequiresEnabledPlusHostAndPort(bool enabled, string host, int port, bool expected)
    {
        ProxySettings proxy = new() { Enabled = enabled, Host = host, Port = port };

        Assert.Equal(expected, proxy.IsUsable);
    }

    [Fact]
    public void ParseBypassList_SplitsOnSemicolonsAndCommasAndTrims()
    {
        ProxySettings proxy = new() { BypassList = "localhost; 127.0.0.1 ,*.internal" };

        Assert.Equal(["localhost", "127.0.0.1", "*.internal"], proxy.ParseBypassList());
    }
}
