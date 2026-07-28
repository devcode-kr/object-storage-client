using System.Collections.ObjectModel;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ObjectStorageClient.App.Services;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Transfers;

namespace ObjectStorageClient.App.ViewModels;

/// <summary>UI projection of one <see cref="TransferItem"/>.</summary>
public sealed partial class TransferItemViewModel : ViewModelBase
{
    public TransferItemViewModel(TransferItem model)
    {
        Model = model;
        Refresh();
    }

    public TransferItem Model { get; }

    public Guid Id => Model.Id;

    public string DirectionGlyph => Model.Direction == TransferDirection.Upload ? "▲" : "▼";

    public string DirectionText => Model.Direction.ToString();

    public string LocalPath => Model.LocalPath;

    public string RemotePath => $"{Model.Bucket}/{Model.RemoteKey}";

    [ObservableProperty]
    private string _sizeText = string.Empty;

    [ObservableProperty]
    private double _percentage;

    [ObservableProperty]
    private string _statusText = string.Empty;

    [ObservableProperty]
    private string _errorMessage = string.Empty;

    public TransferStatus Status => Model.Status;

    /// <summary>Re-reads the model. Must be called on the UI thread.</summary>
    public void Refresh()
    {
        SizeText = Model.TotalBytes > 0
            ? $"{ByteSize.Format(Model.TransferredBytes)} / {ByteSize.Format(Model.TotalBytes)}"
            : ByteSize.Format(Model.TransferredBytes);

        Percentage = Model.Percentage;
        StatusText = Model.Status.ToString();
        ErrorMessage = Model.ErrorMessage ?? string.Empty;
        OnPropertyChanged(nameof(Status));
    }
}

/// <summary>
/// Bottom pane: FileZilla's queued / failed / successful transfer tabs.
/// Subscribes to the queue's worker-thread events and marshals them onto the UI thread.
/// </summary>
public sealed partial class TransferQueueViewModel : ViewModelBase, IDisposable
{
    private readonly ITransferQueue _queue;
    private readonly Dictionary<Guid, TransferItemViewModel> _index = [];

    public TransferQueueViewModel(ITransferQueue queue)
    {
        _queue = queue;
        _queue.ItemAdded += OnItemAdded;
        _queue.ItemUpdated += OnItemUpdated;
    }

    /// <summary>Queued and running transfers.</summary>
    public ObservableCollection<TransferItemViewModel> Active { get; } = [];

    public ObservableCollection<TransferItemViewModel> Failed { get; } = [];

    public ObservableCollection<TransferItemViewModel> Successful { get; } = [];

    [ObservableProperty]
    private TransferItemViewModel? _selectedItem;

    public string ActiveHeader => $"Queued files ({Active.Count})";

    public string FailedHeader => $"Failed transfers ({Failed.Count})";

    public string SuccessfulHeader => $"Successful transfers ({Successful.Count})";

    private void OnItemAdded(object? sender, TransferItem item) =>
        Dispatcher.UIThread.Post(() =>
        {
            TransferItemViewModel viewModel = new(item);
            _index[item.Id] = viewModel;
            Active.Add(viewModel);
            RaiseHeaders();
        });

    private void OnItemUpdated(object? sender, TransferItem item) =>
        Dispatcher.UIThread.Post(() =>
        {
            if (!_index.TryGetValue(item.Id, out TransferItemViewModel? viewModel))
            {
                return;
            }

            viewModel.Refresh();

            if (!item.IsTerminal)
            {
                return;
            }

            Active.Remove(viewModel);
            Failed.Remove(viewModel);
            Successful.Remove(viewModel);

            switch (item.Status)
            {
                case TransferStatus.Completed:
                    Successful.Add(viewModel);
                    break;
                case TransferStatus.Failed:
                case TransferStatus.Cancelled:
                    Failed.Add(viewModel);
                    break;
            }

            RaiseHeaders();
        });

    private void RaiseHeaders()
    {
        OnPropertyChanged(nameof(ActiveHeader));
        OnPropertyChanged(nameof(FailedHeader));
        OnPropertyChanged(nameof(SuccessfulHeader));
    }

    [RelayCommand]
    private void CancelSelected()
    {
        if (SelectedItem is not null)
        {
            _queue.Cancel(SelectedItem.Id);
        }
    }

    [RelayCommand]
    private void CancelAll() => _queue.CancelAll();

    [RelayCommand]
    private void RetrySelected()
    {
        if (SelectedItem is null)
        {
            return;
        }

        Guid id = SelectedItem.Id;
        if (_queue.Retry(id) is not null)
        {
            TransferItemViewModel? stale = Failed.FirstOrDefault(item => item.Id == id);
            if (stale is not null)
            {
                Failed.Remove(stale);
                _index.Remove(id);
            }

            RaiseHeaders();
        }
    }

    [RelayCommand]
    private void RetryAllFailed()
    {
        foreach (TransferItemViewModel item in Failed.ToList())
        {
            if (_queue.Retry(item.Id) is not null)
            {
                Failed.Remove(item);
                _index.Remove(item.Id);
            }
        }

        RaiseHeaders();
    }

    [RelayCommand]
    private void ClearFinished()
    {
        _queue.ClearFinished();

        foreach (TransferItemViewModel item in Failed.Concat(Successful))
        {
            _index.Remove(item.Id);
        }

        Failed.Clear();
        Successful.Clear();
        RaiseHeaders();
    }

    public void Dispose()
    {
        _queue.ItemAdded -= OnItemAdded;
        _queue.ItemUpdated -= OnItemUpdated;
    }
}
