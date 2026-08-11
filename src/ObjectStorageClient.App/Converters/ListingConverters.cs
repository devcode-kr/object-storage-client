using System.Globalization;
using Avalonia.Data.Converters;
using Avalonia.Media;
using ObjectStorageClient.App.Services;
using ObjectStorageClient.Core.Local;
using ObjectStorageClient.Core.Models;

namespace ObjectStorageClient.App.Converters;

/// <summary>Everything the two file panes need to turn a row into cell content.</summary>
public static class ListingConverters
{
    /// <summary>
    /// Row icons, drawn rather than typed. These used to be the 📁 and 📄 emoji, which look fine
    /// on Windows and macOS and break on Linux: the app bundles Inter, Inter has no emoji, and a
    /// machine without an emoji font substitutes whatever fontconfig picks — in practice a
    /// striped box that reads as a rendering fault. A self-contained build should not depend on
    /// the host having a particular font any more than it should depend on a system library.
    /// </summary>
    /// <remarks>
    /// Both are authored in the same 16×16 box and drawn with <c>Stretch="None"</c>, so the file
    /// stays optically smaller than the folder instead of each being scaled to fill the cell.
    /// </remarks>
    private static readonly Geometry FolderIcon = StreamGeometry.Parse(
        "M1.6 4.2 a1.1 1.1 0 0 1 1.1 -1.1 h3.3 a1 1 0 0 1 0.78 0.37 l0.86 1.03 " +
        "H13.3 a1.1 1.1 0 0 1 1.1 1.1 v6.6 a1.1 1.1 0 0 1 -1.1 1.1 " +
        "H2.7 a1.1 1.1 0 0 1 -1.1 -1.1 z");

    /// <summary>F0 selects the even-odd fill rule, which is what punches out the folded corner.</summary>
    private static readonly Geometry FileIcon = StreamGeometry.Parse(
        "F0 M3.6 2.3 a0.9 0.9 0 0 1 0.9 -0.9 h4.35 L12.4 5 v7.8 " +
        "a0.9 0.9 0 0 1 -0.9 0.9 H4.5 a0.9 0.9 0 0 1 -0.9 -0.9 z " +
        "M9.3 2.6 v2.1 a0.6 0.6 0 0 0 0.6 0.6 h2 z");

    public static readonly IValueConverter EntryIcon =
        new FuncValueConverter<bool, Geometry>(isContainer => isContainer ? FolderIcon : FileIcon);

    /// <summary>
    /// Size for a local row. Bound to the row rather than to <c>Size</c>, because the value alone
    /// cannot tell a zero-byte file from a directory — see <see cref="ByteSize.Format(long, bool)"/>.
    /// </summary>
    public static readonly IValueConverter LocalEntrySize =
        new FuncValueConverter<LocalEntry?, string>(entry =>
            entry is null ? string.Empty : ByteSize.Format(entry.Size, entry.IsDirectory));

    /// <summary>Size for a remote row; folder prefixes are containers.</summary>
    public static readonly IValueConverter RemoteEntrySize =
        new FuncValueConverter<RemoteEntry?, string>(entry =>
            entry is null ? string.Empty : ByteSize.Format(entry.Size, entry.IsFolder));

    /// <summary>
    /// Modified column. A key prefix has no modification time of its own and neither does the
    /// ".." row, so the value is null — which a <c>StringFormat</c> binding renders as
    /// <c>0001-01-01 00:00</c>, the default of the underlying value type. Show nothing instead.
    /// </summary>
    public static readonly IValueConverter Timestamp =
        new FuncValueConverter<DateTimeOffset?, string>(value =>
            value is { } moment
                ? moment.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture)
                : string.Empty);
}
