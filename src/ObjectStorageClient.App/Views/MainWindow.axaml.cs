using System.Collections.Specialized;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Threading;
using ObjectStorageClient.App.ViewModels;

namespace ObjectStorageClient.App.Views;

public partial class MainWindow : Window
{
    private INotifyCollectionChanged? _logEntries;

    public MainWindow()
    {
        InitializeComponent();
        DataContextChanged += OnDataContextChanged;
    }

    private void OnDataContextChanged(object? sender, EventArgs e)
    {
        if (_logEntries is not null)
        {
            _logEntries.CollectionChanged -= OnLogChanged;
            _logEntries = null;
        }

        if (DataContext is MainWindowViewModel viewModel)
        {
            _logEntries = viewModel.Log.Entries;
            _logEntries.CollectionChanged += OnLogChanged;
        }
    }

    /// <summary>Keeps the message log pinned to the newest line, like a terminal.</summary>
    private void OnLogChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (e.Action == NotifyCollectionChangedAction.Add)
        {
            Dispatcher.UIThread.Post(LogScroller.ScrollToEnd, DispatcherPriority.Background);
        }
    }

    protected override void OnUnloaded(RoutedEventArgs e)
    {
        base.OnUnloaded(e);

        if (_logEntries is not null)
        {
            _logEntries.CollectionChanged -= OnLogChanged;
            _logEntries = null;
        }
    }
}
