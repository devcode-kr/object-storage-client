using System.Runtime.InteropServices;

namespace ObjectStorageClient.Core.Local;

/// <summary>A row in the local pane.</summary>
public sealed record LocalEntry
{
    public required string Name { get; init; }

    public required string FullPath { get; init; }

    public bool IsDirectory { get; init; }

    public long Size { get; init; }

    public DateTimeOffset? LastModified { get; init; }

    /// <summary>True for the synthetic ".." row that navigates to the parent directory.</summary>
    public bool IsParentLink { get; init; }
}

/// <summary>
/// Directory listing for the local pane. Entries that cannot be read (permission denied,
/// broken symlink) are skipped rather than aborting the whole listing.
/// </summary>
public static class LocalFileSystem
{
    /// <summary>Drive roots on Windows, or the conventional starting points on Unix.</summary>
    public static IReadOnlyList<LocalEntry> GetRoots()
    {
        List<LocalEntry> roots = [];

        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
        {
            foreach (DriveInfo drive in DriveInfo.GetDrives())
            {
                if (!drive.IsReady)
                {
                    continue;
                }

                roots.Add(new LocalEntry
                {
                    Name = drive.Name,
                    FullPath = drive.RootDirectory.FullName,
                    IsDirectory = true,
                });
            }

            return roots;
        }

        string home = GetHomeDirectory();
        roots.Add(new LocalEntry { Name = "Home", FullPath = home, IsDirectory = true });
        roots.Add(new LocalEntry { Name = "/", FullPath = "/", IsDirectory = true });

        foreach (string candidate in new[] { "/Volumes", "/media", "/mnt" })
        {
            if (Directory.Exists(candidate))
            {
                roots.Add(new LocalEntry { Name = candidate, FullPath = candidate, IsDirectory = true });
            }
        }

        return roots;
    }

    public static string GetHomeDirectory()
    {
        string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        return string.IsNullOrEmpty(home) ? Directory.GetCurrentDirectory() : home;
    }

    /// <summary>
    /// Lists <paramref name="path"/>: directories first, then files, each alphabetically.
    /// Set <paramref name="includeParentLink"/> to prepend the ".." row.
    /// </summary>
    public static IReadOnlyList<LocalEntry> List(string path, bool includeParentLink = true, bool showHidden = false)
    {
        DirectoryInfo directory = new(path);
        List<LocalEntry> entries = [];

        if (includeParentLink && directory.Parent is { } parent)
        {
            entries.Add(new LocalEntry
            {
                Name = "..",
                FullPath = parent.FullName,
                IsDirectory = true,
                IsParentLink = true,
            });
        }

        List<LocalEntry> directories = [];
        List<LocalEntry> files = [];

        foreach (FileSystemInfo info in EnumerateSafely(directory))
        {
            if (!showHidden && IsHidden(info))
            {
                continue;
            }

            if (info is DirectoryInfo dir)
            {
                directories.Add(new LocalEntry
                {
                    Name = dir.Name,
                    FullPath = dir.FullName,
                    IsDirectory = true,
                    LastModified = SafeLastWrite(dir),
                });
            }
            else if (info is FileInfo file)
            {
                files.Add(new LocalEntry
                {
                    Name = file.Name,
                    FullPath = file.FullName,
                    IsDirectory = false,
                    Size = SafeLength(file),
                    LastModified = SafeLastWrite(file),
                });
            }
        }

        entries.AddRange(directories.OrderBy(entry => entry.Name, StringComparer.OrdinalIgnoreCase));
        entries.AddRange(files.OrderBy(entry => entry.Name, StringComparer.OrdinalIgnoreCase));
        return entries;
    }

    /// <summary>Every file underneath <paramref name="directory"/>, recursively, skipping unreadable branches.</summary>
    public static IEnumerable<string> EnumerateFilesRecursively(string directory)
    {
        Stack<string> pending = new();
        pending.Push(directory);

        while (pending.Count > 0)
        {
            string current = pending.Pop();

            string[] files;
            try
            {
                files = Directory.GetFiles(current);
            }
            catch (Exception ex) when (ex is UnauthorizedAccessException or IOException)
            {
                continue;
            }

            foreach (string file in files)
            {
                yield return file;
            }

            try
            {
                foreach (string subdirectory in Directory.GetDirectories(current))
                {
                    pending.Push(subdirectory);
                }
            }
            catch (Exception ex) when (ex is UnauthorizedAccessException or IOException)
            {
                // Skip unreadable subtree.
            }
        }
    }

    private static IEnumerable<FileSystemInfo> EnumerateSafely(DirectoryInfo directory)
    {
        try
        {
            return directory.EnumerateFileSystemInfos();
        }
        catch (Exception ex) when (ex is UnauthorizedAccessException or DirectoryNotFoundException or IOException)
        {
            return [];
        }
    }

    private static bool IsHidden(FileSystemInfo info)
    {
        if (info.Name.StartsWith('.'))
        {
            return true;
        }

        try
        {
            return info.Attributes.HasFlag(FileAttributes.Hidden);
        }
        catch (IOException)
        {
            return false;
        }
    }

    private static long SafeLength(FileInfo file)
    {
        try
        {
            return file.Length;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return 0;
        }
    }

    private static DateTimeOffset? SafeLastWrite(FileSystemInfo info)
    {
        try
        {
            return info.LastWriteTime;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }
}
