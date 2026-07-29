using System.Security.Cryptography;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Profiles;
using Xunit;

namespace ObjectStorageClient.Core.Tests;

public sealed class AesGcmSecretProtectorTests
{
    private static byte[] Key() => RandomNumberGenerator.GetBytes(AesGcmSecretProtector.KeySize);

    [Fact]
    public void ProtectThenUnprotect_RoundTrips()
    {
        AesGcmSecretProtector protector = new(Key());

        string protectedValue = protector.Protect("hunter2");

        Assert.NotEqual("hunter2", protectedValue);
        Assert.Equal("hunter2", protector.Unprotect(protectedValue));
    }

    [Fact]
    public void Protect_ProducesADifferentCiphertextEachTime()
    {
        AesGcmSecretProtector protector = new(Key());

        // A fresh nonce per call: identical secrets must not be recognisable on disk.
        Assert.NotEqual(protector.Protect("same"), protector.Protect("same"));
    }

    [Fact]
    public void Protect_ReturnsEmptyForEmptyInput()
    {
        AesGcmSecretProtector protector = new(Key());

        Assert.Empty(protector.Protect(string.Empty));
        Assert.Empty(protector.Unprotect(string.Empty));
    }

    [Fact]
    public void Unprotect_ReturnsEmptyRatherThanThrowingOnCorruptedInput()
    {
        AesGcmSecretProtector protector = new(Key());

        Assert.Empty(protector.Unprotect("not-base64!"));
        Assert.Empty(protector.Unprotect(Convert.ToBase64String([1, 2, 3])));
    }

    [Fact]
    public void Unprotect_ReturnsEmptyUnderADifferentKey()
    {
        string protectedValue = new AesGcmSecretProtector(Key()).Protect("hunter2");

        Assert.Empty(new AesGcmSecretProtector(Key()).Unprotect(protectedValue));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(16)]
    [InlineData(64)]
    public void Constructor_RejectsKeysThatAreNotAes256(int length) =>
        Assert.Throws<ArgumentException>(() => new AesGcmSecretProtector(new byte[length]));
}

public sealed class MasterPasswordVaultTests
{
    // Real vaults use 600k PBKDF2 iterations; tests use a token count to stay fast.
    private const int TestIterations = 1_000;

    [Fact]
    public void Create_ProducesAUsableVaultDefinition()
    {
        MasterPasswordVault.UnlockedVault vault = MasterPasswordVault.Create("correct horse", TestIterations);

        Assert.True(vault.Settings.IsConfigured);
        Assert.True(MasterPasswordVault.IsUsable(vault.Settings));
        Assert.Equal(TestIterations, vault.Settings.Iterations);
        Assert.NotEmpty(vault.Settings.Salt);
        Assert.NotEmpty(vault.Settings.Verifier);
    }

    [Fact]
    public void Create_NeverStoresThePasswordItself()
    {
        MasterPasswordVault.UnlockedVault vault = MasterPasswordVault.Create("correct horse", TestIterations);

        string serialized = vault.Settings.Salt + vault.Settings.Verifier;
        Assert.DoesNotContain("correct horse", serialized, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Create_UsesAFreshSaltPerVault()
    {
        MasterPasswordVault.UnlockedVault first = MasterPasswordVault.Create("same password", TestIterations);
        MasterPasswordVault.UnlockedVault second = MasterPasswordVault.Create("same password", TestIterations);

        Assert.NotEqual(first.Settings.Salt, second.Settings.Salt);
    }

    [Fact]
    public void TryUnlock_ReturnsAWorkingProtectorForTheCorrectPassword()
    {
        MasterPasswordVault.UnlockedVault created = MasterPasswordVault.Create("correct horse", TestIterations);
        string ciphertext = created.Protector.Protect("my-secret-key");

        MasterPasswordVault.UnlockedVault? unlocked =
            MasterPasswordVault.TryUnlock("correct horse", created.Settings, out bool isUsable);

        Assert.True(isUsable);
        Assert.NotNull(unlocked);
        Assert.Equal("my-secret-key", unlocked!.Protector.Unprotect(ciphertext));
    }

    [Fact]
    public void TryUnlock_ReturnsNullForTheWrongPassword()
    {
        MasterPasswordVault.UnlockedVault created = MasterPasswordVault.Create("correct horse", TestIterations);

        Assert.Null(MasterPasswordVault.TryUnlock("battery staple", created.Settings, out bool isUsable));
        Assert.True(isUsable);
    }

    [Fact]
    public void TryUnlock_ReturnsNullForAnEmptyPassword()
    {
        MasterPasswordVault.UnlockedVault created = MasterPasswordVault.Create("correct horse", TestIterations);

        Assert.Null(MasterPasswordVault.TryUnlock(string.Empty, created.Settings, out _));
    }

    [Fact]
    public void TryUnlock_ReportsAnUnconfiguredVaultAsUnusable()
    {
        Assert.Null(MasterPasswordVault.TryUnlock("anything", new MasterPasswordSettings(), out bool isUsable));
        Assert.False(isUsable);
    }

    [Fact]
    public void TryUnlock_ReportsACorruptedSaltAsUnusableRatherThanThrowing()
    {
        MasterPasswordVault.UnlockedVault created = MasterPasswordVault.Create("correct horse", TestIterations);
        MasterPasswordSettings broken = created.Settings with { Salt = "not-base64!" };

        Assert.Null(MasterPasswordVault.TryUnlock("correct horse", broken, out bool isUsable));
        Assert.False(isUsable);
    }

    [Theory]
    [InlineData("", 1000, "verifier")]
    [InlineData("c2FsdA==", 0, "verifier")]
    [InlineData("c2FsdA==", 1000, "")]
    public void IsUsable_RequiresEveryVaultField(string salt, int iterations, string verifier)
    {
        MasterPasswordSettings settings = new()
        {
            IsConfigured = true,
            Salt = salt,
            Iterations = iterations,
            Verifier = verifier,
        };

        Assert.False(MasterPasswordVault.IsUsable(settings));
    }

    [Fact]
    public void Create_RejectsABlankPassword() =>
        Assert.Throws<ArgumentException>(() => MasterPasswordVault.Create("   ", TestIterations));

    [Fact]
    public void Reset_ClearsTheVaultDefinition() =>
        Assert.False(MasterPasswordVault.IsUsable(MasterPasswordVault.Reset()));
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
        _protector = MasterPasswordVault.Create("test-master-password", iterations: 1_000).Protector;
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
    public async Task LoadAsync_YieldsEmptySecretsUnderADifferentMasterPassword()
    {
        await CreateStore().SaveAsync(SampleProfile());

        ISecretProtector otherProtector = MasterPasswordVault.Create("a-different-password", 1_000).Protector;
        ConnectionProfile actual = Assert.Single(await new JsonConnectionProfileStore(otherProtector, _file).LoadAsync());

        Assert.Empty(actual.SecretAccessKey);
        Assert.Empty(actual.Proxy.Password);
        Assert.Equal("MinIO dev", actual.Name);
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

    /// <summary>
    /// Regression: the serializer used to omit `false` and `0`, while these properties initialise
    /// to `true`/non-zero — so a saved "off" reloaded as "on" and path-style addressing could not
    /// be turned off at all.
    /// </summary>
    [Fact]
    public async Task SaveAsync_PersistsFlagsWhoseValueMatchesTheClrDefault()
    {
        JsonConnectionProfileStore store = CreateStore();

        await store.SaveAsync(SampleProfile() with
        {
            ForcePathStyle = false,
            DisableRequestChecksums = false,
            AllowInsecureCertificates = false,
        });

        ConnectionProfile actual = Assert.Single(await store.LoadAsync());

        Assert.False(actual.ForcePathStyle);
        Assert.False(actual.DisableRequestChecksums);
        Assert.False(actual.AllowInsecureCertificates);
    }

    [Fact]
    public async Task SaveAsync_PersistsAnEnabledFlagJustTheSame()
    {
        JsonConnectionProfileStore store = CreateStore();

        await store.SaveAsync(SampleProfile() with { ForcePathStyle = true, DisableRequestChecksums = true });

        ConnectionProfile actual = Assert.Single(await store.LoadAsync());

        Assert.True(actual.ForcePathStyle);
        Assert.True(actual.DisableRequestChecksums);
    }

    /// <summary>
    /// Profiles written before checksums defaulted to disabled simply omit the property; they
    /// should pick up the safer default rather than keep failing against the same gateway.
    /// </summary>
    [Fact]
    public async Task LoadAsync_TreatsAnAbsentChecksumFlagAsDisabled()
    {
        await File.WriteAllTextAsync(_file, """
            {
              "version": 1,
              "sites": [
                {
                  "profile": {
                    "id": "8a1c1d1e-0000-4000-8000-000000000001",
                    "name": "legacy",
                    "providerId": "custom",
                    "serviceUrl": "https://storage.example.com",
                    "region": "us-east-1",
                    "accessKeyId": "key",
                    "forcePathStyle": true
                  },
                  "secretAccessKey": ""
                }
              ]
            }
            """);

        ConnectionProfile actual = Assert.Single(await CreateStore().LoadAsync());

        Assert.True(actual.DisableRequestChecksums);
        Assert.Equal("legacy", actual.Name);
    }

    [Fact]
    public async Task LoadAsync_ReturnsEmptyForACorruptedFileInsteadOfThrowing()
    {
        await File.WriteAllTextAsync(_file, "{ this is not json");

        Assert.Empty(await CreateStore().LoadAsync());
    }

    public void Dispose() => Directory.Delete(_directory, recursive: true);
}
