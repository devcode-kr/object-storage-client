using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Profiles;
using Xunit;

namespace ObjectStorageClient.Core.Tests;

public sealed class JsonAppSettingsStoreTests : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), $"osc-config-{Guid.NewGuid():N}");
    private readonly string _file;

    public JsonAppSettingsStoreTests()
    {
        Directory.CreateDirectory(_directory);
        _file = Path.Combine(_directory, "config.json");
    }

    private JsonAppSettingsStore CreateStore() => new(_file);

    [Fact]
    public async Task LoadAsync_ReturnsDefaultsWhenTheFileDoesNotExist()
    {
        AppSettings settings = await CreateStore().LoadAsync();

        Assert.False(settings.MasterPassword.IsConfigured);
        Assert.Empty(settings.LastLocalDirectory);
        Assert.Null(settings.LastSiteId);
    }

    [Fact]
    public async Task SaveAsync_ThenLoadAsync_RoundTripsPreferencesAndVaultParameters()
    {
        Guid siteId = Guid.NewGuid();
        MasterPasswordVault.UnlockedVault vault = MasterPasswordVault.Create("pw", iterations: 1_000);

        AppSettings saved = new()
        {
            MasterPassword = vault.Settings,
            LastLocalDirectory = _directory,
            ShowHiddenFiles = true,
            LastSiteId = siteId,
        };

        JsonAppSettingsStore store = CreateStore();
        await store.SaveAsync(saved);
        AppSettings loaded = await store.LoadAsync();

        Assert.True(loaded.ShowHiddenFiles);
        Assert.Equal(_directory, loaded.LastLocalDirectory);
        Assert.Equal(siteId, loaded.LastSiteId);
        Assert.Equal(vault.Settings.Salt, loaded.MasterPassword.Salt);
        Assert.Equal(vault.Settings.Iterations, loaded.MasterPassword.Iterations);
        Assert.True(MasterPasswordVault.IsUsable(loaded.MasterPassword));
    }

    [Fact]
    public async Task SaveAsync_ThenUnlock_WorksAcrossAProcessRestart()
    {
        // The whole point of config.json: the vault must survive being written and read back.
        MasterPasswordVault.UnlockedVault created = MasterPasswordVault.Create("correct horse", 1_000);
        string ciphertext = created.Protector.Protect("secret-value");

        await CreateStore().SaveAsync(new AppSettings { MasterPassword = created.Settings });
        AppSettings reloaded = await CreateStore().LoadAsync();

        MasterPasswordVault.UnlockedVault? unlocked =
            MasterPasswordVault.TryUnlock("correct horse", reloaded.MasterPassword, out bool isUsable);

        Assert.True(isUsable);
        Assert.NotNull(unlocked);
        Assert.Equal("secret-value", unlocked!.Protector.Unprotect(ciphertext));
    }

    [Fact]
    public async Task LoadAsync_ReturnsDefaultsForACorruptedFileInsteadOfThrowing()
    {
        await File.WriteAllTextAsync(_file, "{ not json at all");

        AppSettings settings = await CreateStore().LoadAsync();

        Assert.False(settings.MasterPassword.IsConfigured);
    }

    [Fact]
    public async Task SaveAsync_DoesNotLeaveATemporaryFileBehind()
    {
        await CreateStore().SaveAsync(new AppSettings { ShowHiddenFiles = true });

        Assert.True(File.Exists(_file));
        Assert.False(File.Exists(_file + ".tmp"));
    }

    public void Dispose() => Directory.Delete(_directory, recursive: true);
}

public sealed class AppPathsTests
{
    [Fact]
    public void ConfigDirectory_IsTheFixedDevcodeFolderUnderTheUserHome()
    {
        string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);

        Assert.Equal(Path.Combine(home, ".devcode", "object-storage-client"), AppPaths.ConfigDirectory);
    }

    [Fact]
    public void ProfilesFile_IsSitesJsonInsideTheConfigDirectory() =>
        Assert.Equal(Path.Combine(AppPaths.ConfigDirectory, "sites.json"), AppPaths.ProfilesFile);

    [Fact]
    public void SettingsFile_IsConfigJsonInsideTheConfigDirectory() =>
        Assert.Equal(Path.Combine(AppPaths.ConfigDirectory, "config.json"), AppPaths.SettingsFile);
}
