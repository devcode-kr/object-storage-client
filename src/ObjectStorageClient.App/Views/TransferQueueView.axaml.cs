using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.VisualTree;
using ObjectStorageClient.App.ViewModels;

namespace ObjectStorageClient.App.Views;

public partial class TransferQueueView : UserControl
{
    public TransferQueueView() => InitializeComponent();

    /// <summary>
    /// Selects the row under a right-click before the context menu opens. Without this the menu
    /// would act on whatever was left-clicked last, so "Copy error message" could silently copy
    /// a different transfer's reason than the one the user aimed at.
    /// </summary>
    private void OnRowPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (sender is not DataGrid grid || e.Source is not Visual source)
        {
            return;
        }

        if (!e.GetCurrentPoint(grid).Properties.IsRightButtonPressed)
        {
            return;
        }

        if (source.FindAncestorOfType<DataGridRow>(includeSelf: true) is { DataContext: TransferItemViewModel item })
        {
            grid.SelectedItem = item;
        }
    }
}
