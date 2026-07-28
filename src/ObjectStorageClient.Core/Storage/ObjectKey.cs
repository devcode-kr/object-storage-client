namespace ObjectStorageClient.Core.Storage;

/// <summary>
/// Helpers for the flat, forward-slash object namespace S3 exposes.
/// Object keys are not file paths: they never start with <c>/</c>, always use <c>/</c> as the
/// separator on every OS, and a trailing <c>/</c> is what marks a "folder" prefix.
/// </summary>
public static class ObjectKey
{
    public const char Separator = '/';

    /// <summary>Strips leading slashes and collapses the key into its canonical form.</summary>
    public static string Normalize(string? key)
    {
        if (string.IsNullOrWhiteSpace(key))
        {
            return string.Empty;
        }

        string normalized = key.Replace('\\', Separator).TrimStart(Separator);
        while (normalized.Contains("//", StringComparison.Ordinal))
        {
            normalized = normalized.Replace("//", "/", StringComparison.Ordinal);
        }

        return normalized;
    }

    /// <summary>Normalizes a prefix and guarantees the trailing separator that marks a folder.</summary>
    public static string NormalizePrefix(string? prefix)
    {
        string normalized = Normalize(prefix);
        if (normalized.Length == 0)
        {
            return string.Empty;
        }

        return normalized.EndsWith(Separator) ? normalized : normalized + Separator;
    }

    /// <summary>Appends <paramref name="child"/> to <paramref name="prefix"/>.</summary>
    public static string Combine(string? prefix, string child)
    {
        string basePrefix = NormalizePrefix(prefix);
        string tail = Normalize(child);
        return basePrefix + tail;
    }

    /// <summary>Last path segment; for folder keys the trailing separator is ignored.</summary>
    public static string GetName(string? key)
    {
        string normalized = Normalize(key).TrimEnd(Separator);
        if (normalized.Length == 0)
        {
            return string.Empty;
        }

        int index = normalized.LastIndexOf(Separator);
        return index < 0 ? normalized : normalized[(index + 1)..];
    }

    /// <summary>Prefix containing <paramref name="key"/>, or an empty string at the bucket root.</summary>
    public static string GetParentPrefix(string? key)
    {
        string normalized = Normalize(key).TrimEnd(Separator);
        int index = normalized.LastIndexOf(Separator);
        return index < 0 ? string.Empty : normalized[..(index + 1)];
    }

    /// <summary>Breadcrumb segments for a prefix, in order from the bucket root.</summary>
    public static IReadOnlyList<string> Segments(string? prefix) =>
        Normalize(prefix).Split(Separator, StringSplitOptions.RemoveEmptyEntries);

    /// <summary>
    /// Maps a local file path to an object key underneath <paramref name="targetPrefix"/>,
    /// converting the platform separator to <c>/</c>.
    /// </summary>
    public static string FromLocalPath(string targetPrefix, string localPath, string? relativeToDirectory = null)
    {
        string relative = relativeToDirectory is null
            ? Path.GetFileName(localPath)
            : Path.GetRelativePath(relativeToDirectory, localPath);

        return Combine(targetPrefix, relative.Replace(Path.DirectorySeparatorChar, Separator)
                                             .Replace(Path.AltDirectorySeparatorChar, Separator));
    }

    /// <summary>
    /// Maps an object key to a destination path under <paramref name="targetDirectory"/>.
    /// Rejects keys that would escape the directory (<c>..</c> traversal or absolute segments).
    /// </summary>
    public static string ToLocalPath(string targetDirectory, string key, string? strippedPrefix = null)
    {
        string relativeKey = Normalize(key);
        string prefix = NormalizePrefix(strippedPrefix);
        if (prefix.Length > 0 && relativeKey.StartsWith(prefix, StringComparison.Ordinal))
        {
            relativeKey = relativeKey[prefix.Length..];
        }

        string relativePath = relativeKey.Replace(Separator, Path.DirectorySeparatorChar);
        string root = Path.GetFullPath(targetDirectory);
        string combined = Path.GetFullPath(Path.Combine(root, relativePath));

        string rootWithSeparator = root.EndsWith(Path.DirectorySeparatorChar)
            ? root
            : root + Path.DirectorySeparatorChar;

        if (!combined.StartsWith(rootWithSeparator, StringComparison.Ordinal))
        {
            throw new InvalidOperationException($"Object key '{key}' resolves outside of '{targetDirectory}'.");
        }

        return combined;
    }
}
