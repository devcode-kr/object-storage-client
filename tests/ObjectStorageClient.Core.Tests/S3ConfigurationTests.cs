using System.Net;
using Amazon.Runtime;
using Amazon.S3;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Storage;
using Xunit;

namespace ObjectStorageClient.Core.Tests;

/// <summary>
/// Guards the profile → SDK-config mapping. This is the layer that makes non-AWS endpoints,
/// provider quirks and proxies work, and it has no coverage from any UI test.
/// </summary>
public sealed class S3ConfigurationTests
{
    private static ConnectionProfile BaseProfile() => new()
    {
        Name = "Test",
        ServiceUrl = "https://storage.example.com:9000",
        Region = "kr-standard",
        AccessKeyId = "key",
        SecretAccessKey = "secret",
        ForcePathStyle = true,
        TimeoutSeconds = 42,
    };

    [Fact]
    public void BuildConfig_MapsEndpointRegionPathStyleAndTimeout()
    {
        AmazonS3Config config = S3ObjectStorageClient.BuildConfig(BaseProfile());

        // The SDK normalises ServiceURL by appending a trailing slash.
        Assert.Equal("https://storage.example.com:9000/", config.ServiceURL);
        Assert.True(config.ForcePathStyle);
        Assert.Equal("kr-standard", config.AuthenticationRegion);
        Assert.Equal(TimeSpan.FromSeconds(42), config.Timeout);
    }

    [Fact]
    public void BuildConfig_DefaultsTheRegionWhenTheProfileLeavesItBlank()
    {
        AmazonS3Config config = S3ObjectStorageClient.BuildConfig(BaseProfile() with { Region = "  " });

        Assert.Equal("us-east-1", config.AuthenticationRegion);
    }

    [Fact]
    public void BuildConfig_ClampsAnAbsurdTimeout()
    {
        AmazonS3Config config = S3ObjectStorageClient.BuildConfig(BaseProfile() with { TimeoutSeconds = 1 });

        Assert.Equal(TimeSpan.FromSeconds(5), config.Timeout);
    }

    [Fact]
    public void BuildConfig_LeavesChecksumsAtTheSdkDefaultUnlessTheProfileOptsOut()
    {
        AmazonS3Config config = S3ObjectStorageClient.BuildConfig(BaseProfile());

        Assert.NotEqual(RequestChecksumCalculation.WHEN_REQUIRED, config.RequestChecksumCalculation);
    }

    [Fact]
    public void BuildConfig_DisablesChecksumsForGatewaysThatRejectThem()
    {
        AmazonS3Config config = S3ObjectStorageClient.BuildConfig(BaseProfile() with { DisableRequestChecksums = true });

        Assert.Equal(RequestChecksumCalculation.WHEN_REQUIRED, config.RequestChecksumCalculation);
        Assert.Equal(ResponseChecksumValidation.WHEN_REQUIRED, config.ResponseChecksumValidation);
    }

    [Fact]
    public void BuildConfig_UsesTheStockHttpClientWhenNoProxyOrTlsOverrideIsNeeded()
    {
        AmazonS3Config config = S3ObjectStorageClient.BuildConfig(BaseProfile());

        Assert.Null(config.HttpClientFactory);
    }

    [Fact]
    public void BuildConfig_InstallsACustomHttpClientFactoryWhenAProxyIsEnabled()
    {
        ConnectionProfile profile = BaseProfile() with
        {
            Proxy = new ProxySettings { Enabled = true, Host = "proxy.example.com", Port = 3128 },
        };

        Assert.NotNull(S3ObjectStorageClient.BuildConfig(profile).HttpClientFactory);
    }

    [Fact]
    public void BuildConfig_InstallsACustomHttpClientFactoryForInsecureCertificates()
    {
        ConnectionProfile profile = BaseProfile() with { AllowInsecureCertificates = true };

        Assert.NotNull(S3ObjectStorageClient.BuildConfig(profile).HttpClientFactory);
    }

    [Fact]
    public void BuildConfig_IgnoresAProxyThatIsConfiguredButSwitchedOff()
    {
        ConnectionProfile profile = BaseProfile() with
        {
            Proxy = new ProxySettings { Enabled = false, Host = "proxy.example.com", Port = 3128 },
        };

        Assert.Null(S3ObjectStorageClient.BuildConfig(profile).HttpClientFactory);
    }
}

public sealed class S3HttpClientFactoryTests
{
    [Theory]
    [InlineData("localhost", "^localhost$")]
    [InlineData("*.internal", "^.*\\.internal$")]
    [InlineData("10.0.0.?", "^10\\.0\\.0\\..$")]
    public void GlobToRegex_TranslatesWildcardsAndEscapesTheRest(string pattern, string expected) =>
        Assert.Equal(expected, S3HttpClientFactory.GlobToRegex(pattern));

    [Fact]
    public void BuildWebProxy_AppliesTheBypassListAndCredentials()
    {
        ProxySettings settings = new()
        {
            Enabled = true,
            Host = "proxy.example.com",
            Port = 3128,
            Username = "user",
            Password = "pass",
            BypassList = "localhost;*.internal",
        };

        WebProxy proxy = S3HttpClientFactory.BuildWebProxy(settings);

        Assert.Equal(new Uri("http://proxy.example.com:3128"), proxy.Address);
        Assert.True(proxy.BypassProxyOnLocal);
        Assert.Equal(2, proxy.BypassList.Length);
        Assert.NotNull(proxy.Credentials);
    }

    [Fact]
    public void BuildWebProxy_OmitsCredentialsForAnUnauthenticatedProxy()
    {
        ProxySettings settings = new() { Enabled = true, Host = "proxy", Port = 8080 };

        Assert.Null(S3HttpClientFactory.BuildWebProxy(settings).Credentials);
    }
}
