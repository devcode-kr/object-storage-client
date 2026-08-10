using Avalonia.Data.Converters;
using ObjectStorageClient.App.Services;
using ObjectStorageClient.Core.Local;
using ObjectStorageClient.Core.Models;

namespace ObjectStorageClient.App.Converters;

/// <summary>
/// Size column for the two file panes. These bind the whole row rather than its <c>Size</c>,
/// because the value alone cannot tell a zero-byte file from a directory — and the two must not
/// render the same way. See <see cref="ByteSize.Format(long, bool)"/>.
/// </summary>
public static class SizeConverters
{
    public static readonly IValueConverter LocalEntrySize =
        new FuncValueConverter<LocalEntry?, string>(entry =>
            entry is null ? string.Empty : ByteSize.Format(entry.Size, entry.IsDirectory));

    public static readonly IValueConverter RemoteEntrySize =
        new FuncValueConverter<RemoteEntry?, string>(entry =>
            entry is null ? string.Empty : ByteSize.Format(entry.Size, entry.IsFolder));
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
