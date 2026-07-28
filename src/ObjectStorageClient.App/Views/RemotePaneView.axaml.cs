using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using ObjectStorageClient.App.ViewModels;
using ObjectStorageClient.Core.Models;

namespace ObjectStorageClient.App.Views;

/// <summary>See <see cref="LocalPaneView"/> for why selection sync lives in code-behind.</summary>
public partial class RemotePaneView : UserControl
{
    public RemotePaneView() => InitializeComponent();

    private RemoteBrowserViewModel? ViewModel => DataContext as RemoteBrowserViewModel;

    private void OnSelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (ViewModel is not { } viewModel)
        {
            return;
        }

        viewModel.SelectedEntries.Clear();

        foreach (object? item in EntryGrid.SelectedItems)
        {
            if (item is RemoteEntry entry)
            {
                viewModel.SelectedEntries.Add(entry);
            }
        }
    }

    private void OnDoubleTapped(object? sender, TappedEventArgs e)
    {
        if (ViewModel is { } viewModel && EntryGrid.SelectedItem is RemoteEntry entry)
        {
            viewModel.OpenCommand.Execute(entry);
        }
    }

    private void OnPrefixKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && ViewModel is { } viewModel)
        {
            viewModel.RefreshCommand.Execute(null);
            e.Handled = true;
        }
    }

    protected override void OnUnloaded(RoutedEventArgs e)
    {
        base.OnUnloaded(e);
        ViewModel?.SelectedEntries.Clear();
    }
}
