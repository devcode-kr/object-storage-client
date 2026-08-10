using System.Globalization;

namespace ObjectStorageClient.App.Services;

/// <summary>Human-readable byte counts for the file listings and the transfer queue.</summary>
public static class ByteSize
{
    /// <summary>Shown where a row has no size of its own, rather than a misleading "0 B".</summary>
    public const string None = "-";

    private static readonly string[] Units = ["B", "KB", "MB", "GB", "TB", "PB"];

    /// <summary>
    /// Size for one row of a file listing. A directory or a key prefix is a container, not
    /// content: its <c>Size</c> is always zero, and rendering that as "0 B" reads as an empty
    /// file. Containers get <see cref="None"/> instead.
    /// </summary>
    public static string Format(long bytes, bool isContainer) =>
        isContainer ? None : Format(bytes);

    public static string Format(long bytes)
    {
        if (bytes < 0)
        {
            return string.Empty;
        }

        if (bytes < 1024)
        {
            return $"{bytes} B";
        }

        double value = bytes;
        int unit = 0;

        while (value >= 1024 && unit < Units.Length - 1)
        {
            value /= 1024;
            unit++;
        }

        return string.Create(
            CultureInfo.InvariantCulture,
            $"{value:0.##} {Units[unit]}");
    }
}
