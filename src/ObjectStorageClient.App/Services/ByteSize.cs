using System.Globalization;

namespace ObjectStorageClient.App.Services;

/// <summary>Human-readable byte counts for the file listings and the transfer queue.</summary>
public static class ByteSize
{
    private static readonly string[] Units = ["B", "KB", "MB", "GB", "TB", "PB"];

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
