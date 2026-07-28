using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using ObjectStorageClient.App.ViewModels;
using ObjectStorageClient.Core.Local;

namespace ObjectStorageClient.App.Views;

/// <summary>
/// Code-behind is limited to view-state plumbing that has no MVVM equivalent in Avalonia:
/// multi-selection sync (<c>DataGrid.SelectedItems</c> is not a bindable property) and
/// double-click / Enter activation.
/// </summary>
public partial class LocalPaneView : UserControl
{
    public LocalPaneView() => InitializeComponent();

    private LocalBrowserViewModel? ViewModel => DataContext as LocalBrowserViewModel;

    private void OnSelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (ViewModel is not { } viewModel)
        {
            return;
        }

        viewModel.SelectedEntries.Clear();

        foreach (object? item in EntryGrid.SelectedItems)
        {
            if (item is LocalEntry entry)
            {
                viewModel.SelectedEntries.Add(entry);
            }
        }
    }

    private void OnDoubleTapped(object? sender, TappedEventArgs e)
    {
        if (ViewModel is { } viewModel && EntryGrid.SelectedItem is LocalEntry entry)
        {
            viewModel.OpenCommand.Execute(entry);
        }
    }

    private void OnRootSelected(object? sender, SelectionChangedEventArgs e)
    {
        if (sender is ComboBox { SelectedItem: LocalEntry root } && ViewModel is { } viewModel)
        {
            viewModel.Navigate(root.FullPath);
        }
    }

    private void OnPathKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && sender is TextBox textBox && ViewModel is { } viewModel)
        {
            viewModel.Navigate(textBox.Text ?? string.Empty);
            e.Handled = true;
        }
    }

    protected override void OnUnloaded(RoutedEventArgs e)
    {
        base.OnUnloaded(e);
        ViewModel?.SelectedEntries.Clear();
    }
}
