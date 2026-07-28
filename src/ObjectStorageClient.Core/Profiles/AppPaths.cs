using System.Runtime.InteropServices;

namespace ObjectStorageClient.Core.Profiles;

/// <summary>
/// On-disk locations for the two files the app owns, both under a single fixed directory:
/// <c>$HOME/.devcode/object-storage-client/</c>.
/// </summary>
/// <remarks>
/// The path is deliberately identical on Windows, Linux and macOS rather than following each
/// platform's convention, so a profile directory can be moved or synced between machines and
/// keep working. <c>$HOME</c> resolves to <c>%USERPROFILE%</c> on Windows.
/// </remarks>
public static class AppPaths
{
    public const string VendorFolderName = ".devcode";

    public const string ApplicationFolderName = "object-storage-client";

    public static string ConfigDirectory { get; } = ResolveConfigDirectory();

    /// <summary>Saved connections shown in the Site Manager.</summary>
    public static string ProfilesFile => Path.Combine(ConfigDirectory, "sites.json");

    /// <summary>Application settings, including the master-password key-derivation parameters.</summary>
    public static string SettingsFile => Path.Combine(ConfigDirectory, "config.json");

    /// <summary>Creates the config directory, restricting it to the current user where the OS allows it.</summary>
    public static string EnsureConfigDirectory()
    {
        Directory.CreateDirectory(ConfigDirectory);

        TryRestrictToOwner(
            ConfigDirectory,
            UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);

        return ConfigDirectory;
    }

    /// <summary>Best-effort chmod 600/700. Silently ignored on Windows and on filesystems without POSIX modes.</summary>
    public static void TryRestrictToOwner(string path, UnixFileMode mode)
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
        {
            return;
        }

        try
        {
            File.SetUnixFileMode(path, mode);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or PlatformNotSupportedException)
        {
            // Permission hardening is advisory; the app still works without it.
        }
    }

    private static string ResolveConfigDirectory()
    {
        string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);

        if (string.IsNullOrEmpty(home))
        {
            // Falls back only in unusual hosts (service accounts, some containers).
            home = Environment.GetEnvironmentVariable("HOME") ?? Directory.GetCurrentDirectory();
        }

        return Path.Combine(home, VendorFolderName, ApplicationFolderName);
    }
}
