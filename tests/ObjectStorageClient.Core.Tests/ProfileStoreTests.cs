using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Profiles;
using Xunit;

namespace ObjectStorageClient.Core.Tests;

public sealed class AesGcmSecretProtectorTests : IDisposable
{
    private readonly string _keyFile = Path.Combine(Path.GetTempPath(), $"osc-key-{Guid.NewGuid():N}.bin");

    [Fact]
    public void ProtectThenUnprotect_RoundTrips()
    {
        AesGcmSecretProtector protector = new(_keyFile);

        string protectedValue = protector.Protect("hunter2");

        Assert.NotEqual("hunter2", protectedValue);
        Assert.Equal("hunter2", protector.Unprotect(protectedValue));
    }

    [Fact]
    public void Protect_ReturnsEmptyForEmptyInput()
    {
        AesGcmSecretProtector protector = new(_keyFile);

        Assert.Empty(protector.Protect(string.Empty));
        Assert.Empty(protector.Unprotect(string.Empty));
    }

    [Fact]
    public void Unprotect_ReturnsEmptyRatherThanThrowingOnCorruptedInput()
    {
        AesGcmSecretProtector protector = new(_keyFile);

        Assert.Empty(protector.Unprotect("not-base64!"));
        Assert.Empty(protector.Unprotect(Convert.ToBase64String([1, 2, 3])));
    }

    [Fact]
    public void Unprotect_ReturnsEmptyWhenTheValueWasEncryptedWithAnotherKey()
    {
        string otherKeyFile = Path.Combine(Path.GetTempPath(), $"osc-key-{Guid.NewGuid():N}.bin");

        try
        {
            string protectedValue = new AesGcmSecretProtector(_keyFile).Protect("hunter2");

            Assert.Empty(new AesGcmSecretProtector(otherKeyFile).Unprotect(protectedValue));
        }
        finally
        {
            File.Delete(otherKeyFile);
        }
    }

    public void Dispose() => File.Delete(_keyFile);
}

public sealed class JsonConnectionProfileStoreTests : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), $"osc-store-{Guid.NewGuid():N}");
    private readonly string _file;
    private readonly ISecretProtector _protector;

    public JsonConnectionProfileStoreTests()
    {
        Directory.CreateDirectory(_directory);
        _file = Path.Combine(_directory, "sites.json");
        _protector = new AesGcmSecretProtector(Path.Combine(_directory, "secret.key"));
    }

    private JsonConnectionProfileStore CreateStore() => new(_protector, _file);

    private static ConnectionProfile SampleProfile() => new()
    {
        Name = "MinIO dev",
        ProviderId = "minio",
        ServiceUrl = "http://localhost:9000",
        Region = "us-east-1",
        AccessKeyId = "minioadmin",
        SecretAccessKey = "s3cr3t-access-key",
        DefaultBucket = "assets",
        Proxy = new ProxySettings { Enabled = true, Host = "proxy", Port = 3128, Password = "proxypass" },
    };

    [Fact]
    public async Task LoadAsync_ReturnsEmptyWhenNothingHasBeenSaved() =>
        Assert.Empty(await CreateStore().LoadAsync());

    [Fact]
    public async Task SaveAsync_ThenLoadAsync_RoundTripsIncludingSecrets()
    {
        JsonConnectionProfileStore store = CreateStore();
        ConnectionProfile profile = SampleProfile();

        await store.SaveAsync(profile);
        IReadOnlyList<ConnectionProfile> loaded = await store.LoadAsync();

        ConnectionProfile actual = Assert.Single(loaded);
        Assert.Equal(profile.Id, actual.Id);
        Assert.Equal("MinIO dev", actual.Name);
        Assert.Equal("s3cr3t-access-key", actual.SecretAccessKey);
        Assert.Equal("proxypass", actual.Proxy.Password);
        Assert.Equal(3128, actual.Proxy.Port);
    }

    [Fact]
    public async Task SaveAsync_NeverWritesSecretsInPlaintext()
    {
        await CreateStore().SaveAsync(SampleProfile());

        string json = await File.ReadAllTextAsync(_file);

        Assert.DoesNotContain("s3cr3t-access-key", json, StringComparison.Ordinal);
        Assert.DoesNotContain("proxypass", json, StringComparison.Ordinal);

        // Non-secret fields stay readable, which is what makes the file diffable and portable.
        Assert.Contains("MinIO dev", json, StringComparison.Ordinal);
        Assert.Contains("minioadmin", json, StringComparison.Ordinal);
    }

    [Fact]
    public async Task SaveAsync_ReplacesAnExistingProfileRatherThanDuplicatingIt()
    {
        JsonConnectionProfileStore store = CreateStore();
        ConnectionProfile profile = SampleProfile();

        await store.SaveAsync(profile);
        await store.SaveAsync(profile with { Name = "Renamed" });

        ConnectionProfile actual = Assert.Single(await store.LoadAsync());
        Assert.Equal("Renamed", actual.Name);
    }

    [Fact]
    public async Task DeleteAsync_RemovesOnlyTheRequestedProfile()
    {
        JsonConnectionProfileStore store = CreateStore();
        ConnectionProfile first = SampleProfile();
        ConnectionProfile second = SampleProfile() with { Id = Guid.NewGuid(), Name = "Second" };

        await store.SaveAsync(first);
        await store.SaveAsync(second);
        await store.DeleteAsync(first.Id);

        ConnectionProfile actual = Assert.Single(await store.LoadAsync());
        Assert.Equal("Second", actual.Name);
    }

    [Fact]
    public async Task LoadAsync_ReturnsEmptyForACorruptedFileInsteadOfThrowing()
    {
        await File.WriteAllTextAsync(_file, "{ this is not json");

        Assert.Empty(await CreateStore().LoadAsync());
    }

    public void Dispose() => Directory.Delete(_directory, recursive: true);
}
