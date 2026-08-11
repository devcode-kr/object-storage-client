using System.Globalization;
using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Headless.XUnit;
using Avalonia.Media;
using Avalonia.Threading;
using Avalonia.VisualTree;
using ObjectStorageClient.App.Converters;
using ObjectStorageClient.App.ViewModels;
using ObjectStorageClient.App.Views;
using ObjectStorageClient.Core.Models;
using Xunit;

// Path is System.IO.Path throughout this file; the shape needs the alias.
using IconPath = Avalonia.Controls.Shapes.Path;

namespace ObjectStorageClient.App.Tests;

/// <summary>
/// What the file panes actually render. Both columns here decide what to show from something the
/// bound value alone does not carry — a directory has no size and a prefix has no timestamp, and
/// the underlying value in each case is a zero that must not be printed as one. That decision
/// lives in the XAML binding, which no view-model test can reach, so these render the real panes
/// headlessly and read the cells back.
/// </summary>
public sealed class FilePaneColumnTests : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), $"osc-cols-{Guid.NewGuid():N}");

    public FilePaneColumnTests()
    {
        Directory.CreateDirectory(Path.Combine(_directory, "child"));
        File.WriteAllText(Path.Combine(_directory, "note.txt"), "hello");
        File.WriteAllText(Path.Combine(_directory, "empty.bin"), string.Empty);
    }

    [AvaloniaFact]
    public void LocalPane_ShowsADashForDirectoriesAndAByteCountForFiles()
    {
        Dictionary<string, Cells> rows = RenderLocalPane();

        Assert.Equal("-", rows[".."].Size);
        Assert.Equal("-", rows["child"].Size);
        Assert.Equal("5 B", rows["note.txt"].Size);

        // The case the dash exists to disambiguate: a real zero-byte file still reads as one.
        Assert.Equal("0 B", rows["empty.bin"].Size);
    }

    [AvaloniaFact]
    public void LocalPane_LeavesTheModifiedCellEmptyWhenThereIsNoTimestamp()
    {
        Dictionary<string, Cells> rows = RenderLocalPane();

        // The ".." row carries no timestamp; it must not render as 0001-01-01.
        Assert.Equal(string.Empty, rows[".."].Modified);
        Assert.Matches(@"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", rows["note.txt"].Modified);
    }

    [AvaloniaFact]
    public void RemotePane_ShowsADashForPrefixesAndAByteCountForObjects()
    {
        Dictionary<string, Cells> rows = RenderRemotePane();

        Assert.Equal("-", rows["2024"].Size);
        Assert.Equal("2 KB", rows["cat.png"].Size);
        Assert.Equal("0 B", rows["marker"].Size);
    }

    [AvaloniaFact]
    public void RemotePane_LeavesTheModifiedCellEmptyForPrefixes()
    {
        Dictionary<string, Cells> rows = RenderRemotePane();

        Assert.Equal(string.Empty, rows["2024"].Modified);
        Assert.Equal("2024-05-04 07:28", rows["cat.png"].Modified);
    }

    [AvaloniaFact]
    public void BothPanes_DrawTheirRowIcons()
    {
        // Emoji glyphs rendered as a substitute box on Linux, so the icons are drawn instead.
        // A row with no geometry would show nothing at all, which no other assertion would catch.
        Assert.All(RenderLocalPane().Values, row => Assert.True(row.HasIcon, "local row has no icon"));
        Assert.All(RenderRemotePane().Values, row => Assert.True(row.HasIcon, "remote row has no icon"));
    }

    [Fact]
    public void RowIcons_AreParseableGeometryWithArea()
    {
        // StreamGeometry.Parse throws on malformed data, and a typo that still parses could
        // silently produce an empty shape.
        foreach (bool isContainer in new[] { true, false })
        {
            object? icon = ListingConverters.EntryIcon.Convert(
                isContainer, typeof(Geometry), null, CultureInfo.InvariantCulture);

            Geometry geometry = Assert.IsAssignableFrom<Geometry>(icon);
            Assert.True(geometry.Bounds.Width > 4, $"icon {isContainer} is {geometry.Bounds.Width} wide");
            Assert.True(geometry.Bounds.Height > 4, $"icon {isContainer} is {geometry.Bounds.Height} tall");
        }
    }

    private Dictionary<string, Cells> RenderLocalPane()
    {
        LocalBrowserViewModel pane = new(new LogViewModel(), new StubDialogService(), new FakeTransferCoordinator());
        pane.Navigate(_directory);
        return Render(new LocalPaneView { DataContext = pane });
    }

    private static Dictionary<string, Cells> RenderRemotePane()
    {
        RemoteBrowserViewModel pane = new(new LogViewModel(), new StubDialogService(), new FakeTransferCoordinator());
        pane.Entries.Add(RemoteEntry.Folder("photos/2024/", "2024"));
        pane.Entries.Add(new RemoteEntry
        {
            Name = "cat.png",
            Key = "photos/cat.png",
            Size = 2048,
            LastModified = new DateTimeOffset(2024, 5, 4, 7, 28, 0, TimeSpan.Zero),
        });
        pane.Entries.Add(new RemoteEntry { Name = "marker", Key = "photos/marker", Size = 0 });

        return Render(new RemotePaneView { DataContext = pane });
    }

    private sealed record Cells(string Size, string Modified, bool HasIcon);

    /// <summary>Shows the pane in a window and returns each row's filename mapped to its cells.</summary>
    private static Dictionary<string, Cells> Render(Control view)
    {
        Window window = new() { Content = view, Width = 900, Height = 600 };
        window.Show();
        Dispatcher.UIThread.RunJobs();
        AvaloniaHeadlessPlatform.ForceRenderTimerTick();

        DataGrid grid = window.GetVisualDescendants().OfType<DataGrid>().Single();
        Dictionary<string, Cells> rows = [];

        foreach (DataGridRow row in grid.GetVisualDescendants().OfType<DataGridRow>())
        {
            List<DataGridCell> cells = [.. row.GetVisualDescendants().OfType<DataGridCell>()];
            Assert.True(cells.Count >= 3, $"row rendered {cells.Count} cells");

            // Cell 0 is the filename template (icon then name); 1 is Size and 2 is Modified.
            string name = Text(cells[0]);

            // Fill matters as much as Data: a theme resource key that does not resolve leaves the
            // geometry painted with nothing, which looks exactly like the missing-glyph bug.
            bool hasIcon = cells[0].GetVisualDescendants().OfType<IconPath>()
                .Any(icon => icon.Data is not null && icon.Fill is not null);

            rows[name] = new Cells(Text(cells[1]), Text(cells[2]), hasIcon);
        }

        Assert.NotEmpty(rows);
        return rows;
    }

    private static string Text(DataGridCell cell)
    {
        TextBlock? block = cell.GetVisualDescendants().OfType<TextBlock>().FirstOrDefault();
        Assert.NotNull(block);
        return block.Text ?? string.Empty;
    }

    public void Dispose() => Directory.Delete(_directory, recursive: true);
}
