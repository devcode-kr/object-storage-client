using System.Globalization;
using Avalonia.Data.Converters;
using ObjectStorageClient.App.Services;

namespace ObjectStorageClient.App.Converters;

/// <summary>Renders a <see cref="long"/> byte count as "1.5 MB".</summary>
public sealed class ByteSizeConverter : IValueConverter
{
    public object? Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is long bytes ? ByteSize.Format(bytes) : string.Empty;

    public object? ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}

/// <summary>Ready-made converters exposed as static fields so XAML can use <c>{x:Static}</c>.</summary>
public static class GlyphConverters
{
    /// <summary>Folder or file glyph for a boolean "is directory" flag.</summary>
    public static readonly IValueConverter DirectoryGlyph =
        new FuncValueConverter<bool, string>(isDirectory => isDirectory ? "📁" : "📄");

    /// <summary>Folder or object glyph for a remote entry.</summary>
    public static readonly IValueConverter RemoteGlyph =
        new FuncValueConverter<bool, string>(isFolder => isFolder ? "📁" : "📄");
}
