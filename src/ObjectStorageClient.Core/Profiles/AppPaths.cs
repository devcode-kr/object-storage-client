using System.Runtime.InteropServices;

namespace ObjectStorageClient.Core.Profiles;

/// <summary>
/// Per-user configuration locations, following each platform's convention:
/// <c>%APPDATA%</c> on Windows, <c>~/Library/Application Support</c> on macOS,
/// and <c>$XDG_CONFIG_HOME</c> (default <c>~/.config</c>) on Linux.
/// </summary>
public static class AppPaths
{
    public const string ApplicationFolderName = "ObjectStorageClient";

    public static string ConfigDirectory { get; } = ResolveConfigDirectory();

    public static string ProfilesFile => Path.Combine(ConfigDirectory, "sites.json");

    public static string KeyFile => Path.Combine(ConfigDirectory, "secret.key");

    /// <summary>Creates the config directory, restricting it to the current user where the OS allows it.</summary>
    public static string EnsureConfigDirectory()
    {
        Directory.CreateDirectory(ConfigDirectory);

        if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
        {
            TryRestrictToOwner(ConfigDirectory, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        }

        return ConfigDirectory;
    }

    /// <summary>Best-effort chmod 600/700. Silently ignored on filesystems that do not support it.</summary>
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
        if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
        {
            string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            return Path.Combine(home, "Library", "Application Support", ApplicationFolderName);
        }

        if (RuntimeInformation.IsOSPlatform(OSPlatform.Linux))
        {
            string xdg = Environment.GetEnvironmentVariable("XDG_CONFIG_HOME") ?? string.Empty;
            string root = string.IsNullOrWhiteSpace(xdg)
                ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".config")
                : xdg;

            return Path.Combine(root, ApplicationFolderName);
        }

        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            ApplicationFolderName);
    }
}
