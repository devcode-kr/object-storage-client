using System.Runtime.InteropServices;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Profiles;
using Xunit;

namespace ObjectStorageClient.Core.Tests;

/// <summary>
/// Both stores write through a temporary file, and one of them holds encrypted credentials.
/// The temporary file must never be readable by other users, not even briefly.
/// </summary>
public sealed class FilePermissionTests : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), $"osc-perm-{Guid.NewGuid():N}");

    public FilePermissionTests() => Directory.CreateDirectory(_directory);

    private static bool SupportsUnixModes => !RuntimeInformation.IsOSPlatform(OSPlatform.Windows);

    private static void AssertOwnerOnly(string path)
    {
        UnixFileMode mode = File.GetUnixFileMode(path);

        Assert.Equal(UnixFileMode.UserRead | UnixFileMode.UserWrite, mode);
    }

    [Fact]
    public void CreateOwnerOnlyFile_AppliesTheModeAtCreationNotAfterwards()
    {
        if (!SupportsUnixModes)
        {
            return;
        }

        string path = Path.Combine(_directory, "probe.json");

        using (FileStream stream = AppPaths.CreateOwnerOnlyFile(path))
        {
            // Checked while the handle is still open: a chmod issued after writing would
            // leave this assertion failing, which is exactly the regression being guarded.
            AssertOwnerOnly(path);
            stream.WriteByte(0x7B);
        }

        AssertOwnerOnly(path);
    }

    [Fact]
    public void CreateOwnerOnlyFile_TruncatesAnExistingWorldReadableFile()
    {
        if (!SupportsUnixModes)
        {
            return;
        }

        string path = Path.Combine(_directory, "stale.json");
        File.WriteAllText(path, "leftover from an interrupted save");
        File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.OtherRead);

        using (AppPaths.CreateOwnerOnlyFile(path))
        {
        }

        Assert.Empty(File.ReadAllText(path));
        AssertOwnerOnly(path);
    }

    [Fact]
    public async Task SavedProfilesAreOwnerOnly()
    {
        if (!SupportsUnixModes)
        {
            return;
        }

        string file = Path.Combine(_directory, "sites.json");
        JsonConnectionProfileStore store = new(
            MasterPasswordVault.Create("test-password", iterations: 1_000).Protector,
            file);

        await store.SaveAsync(new ConnectionProfile
        {
            Name = "Site",
            ServiceUrl = "https://s3.example.com",
            AccessKeyId = "key",
            SecretAccessKey = "secret",
        });

        AssertOwnerOnly(file);
        Assert.False(File.Exists(file + ".tmp"));
    }

    [Fact]
    public async Task SavedSettingsAreOwnerOnly()
    {
        if (!SupportsUnixModes)
        {
            return;
        }

        string file = Path.Combine(_directory, "config.json");
        JsonAppSettingsStore store = new(file);

        await store.SaveAsync(new AppSettings { ShowHiddenFiles = true });

        AssertOwnerOnly(file);
        Assert.False(File.Exists(file + ".tmp"));
    }

    public void Dispose() => Directory.Delete(_directory, recursive: true);
}
