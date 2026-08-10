using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Headless.XUnit;
using Avalonia.Threading;
using Avalonia.VisualTree;
using ObjectStorageClient.App.ViewModels;
using ObjectStorageClient.App.Views;
using ObjectStorageClient.Core.Models;
using Xunit;

namespace ObjectStorageClient.App.Tests;

/// <summary>
/// The Size column renders the whole row rather than its <c>Size</c> value, so that a directory
/// or a key prefix can show "-" instead of the "0 B" that reads as an empty file. That decision
/// lives in the XAML binding, which no view-model test can reach — these render the real panes
/// headlessly and read the cells back.
/// </summary>
public sealed class SizeColumnTests : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), $"osc-size-{Guid.NewGuid():N}");

    public SizeColumnTests()
    {
        Directory.CreateDirectory(Path.Combine(_directory, "child"));
        File.WriteAllText(Path.Combine(_directory, "note.txt"), "hello");
        File.WriteAllText(Path.Combine(_directory, "empty.bin"), string.Empty);
    }

    [AvaloniaFact]
    public void LocalPane_ShowsADashForDirectoriesAndAByteCountForFiles()
    {
        LocalBrowserViewModel pane = new(new LogViewModel(), new StubDialogService(), new FakeTransferCoordinator());
        pane.Navigate(_directory);

        LocalPaneView view = new() { DataContext = pane };
        Dictionary<string, string> sizes = Render(view);

        Assert.Equal("-", sizes[".."]);
        Assert.Equal("-", sizes["child"]);
        Assert.Equal("5 B", sizes["note.txt"]);

        // The case the dash exists to disambiguate: a real zero-byte file still reads as one.
        Assert.Equal("0 B", sizes["empty.bin"]);
    }

    [AvaloniaFact]
    public void RemotePane_ShowsADashForPrefixesAndAByteCountForObjects()
    {
        RemoteBrowserViewModel pane = new(new LogViewModel(), new StubDialogService(), new FakeTransferCoordinator());
        pane.Entries.Add(RemoteEntry.Folder("photos/2024/", "2024"));
        pane.Entries.Add(new RemoteEntry { Name = "cat.png", Key = "photos/cat.png", Size = 2048 });
        pane.Entries.Add(new RemoteEntry { Name = "marker", Key = "photos/marker", Size = 0 });

        RemotePaneView view = new() { DataContext = pane };
        Dictionary<string, string> sizes = Render(view);

        Assert.Equal("-", sizes["2024"]);
        Assert.Equal("2 KB", sizes["cat.png"]);
        Assert.Equal("0 B", sizes["marker"]);
    }

    /// <summary>Shows the pane in a window and returns each row's filename mapped to its Size cell.</summary>
    private static Dictionary<string, string> Render(Control view)
    {
        Window window = new() { Content = view, Width = 800, Height = 600 };
        window.Show();
        Dispatcher.UIThread.RunJobs();
        AvaloniaHeadlessPlatform.ForceRenderTimerTick();

        DataGrid grid = window.GetVisualDescendants().OfType<DataGrid>().Single();
        Dictionary<string, string> sizes = [];

        foreach (DataGridRow row in grid.GetVisualDescendants().OfType<DataGridRow>())
        {
            List<DataGridCell> cells = [.. row.GetVisualDescendants().OfType<DataGridCell>()];
            Assert.True(cells.Count >= 2, $"row rendered {cells.Count} cells");

            // Cell 0 is the filename template (glyph then name); cell 1 is Size.
            string name = CellText(cells[0], last: true);
            sizes[name] = CellText(cells[1], last: false);
        }

        Assert.NotEmpty(sizes);
        return sizes;
    }

    private static string CellText(DataGridCell cell, bool last)
    {
        List<TextBlock> blocks = [.. cell.GetVisualDescendants().OfType<TextBlock>()];
        Assert.NotEmpty(blocks);
        return (last ? blocks[^1].Text : blocks[0].Text) ?? string.Empty;
    }

    public void Dispose() => Directory.Delete(_directory, recursive: true);
}
