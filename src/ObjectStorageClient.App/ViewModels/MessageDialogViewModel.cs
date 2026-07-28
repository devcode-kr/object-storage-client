using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ObjectStorageClient.App.ViewModels;

/// <summary>
/// One dialog view model covering the three modal shapes the app needs:
/// a text prompt, a yes/no confirmation, and a plain message.
/// </summary>
public sealed partial class MessageDialogViewModel : ViewModelBase
{
    private MessageDialogViewModel(string title, string message)
    {
        Title = title;
        Message = message;
    }

    /// <summary>Raised when the dialog window should close.</summary>
    public event EventHandler? CloseRequested;

    public string Title { get; }

    public string Message { get; }

    public bool ShowInput { get; private init; }

    public bool ShowCancel { get; private init; }

    public bool IsError { get; private init; }

    public string AcceptText { get; private init; } = "OK";

    /// <summary>True when the user accepted rather than cancelled or closed the window.</summary>
    public bool Confirmed { get; private set; }

    [ObservableProperty]
    private string _inputText = string.Empty;

    public static MessageDialogViewModel Prompt(string title, string message, string initialValue) =>
        new(title, message)
        {
            ShowInput = true,
            ShowCancel = true,
            AcceptText = "OK",
            InputText = initialValue,
        };

    public static MessageDialogViewModel Confirm(string title, string message) =>
        new(title, message)
        {
            ShowCancel = true,
            AcceptText = "Yes",
        };

    /// <summary>Plain notification with a single dismiss button.</summary>
    public static MessageDialogViewModel Notice(string title, string message, bool isError) =>
        new(title, message)
        {
            IsError = isError,
            AcceptText = "Close",
        };

    [RelayCommand]
    private void Accept()
    {
        Confirmed = true;
        CloseRequested?.Invoke(this, EventArgs.Empty);
    }

    [RelayCommand]
    private void Cancel()
    {
        Confirmed = false;
        CloseRequested?.Invoke(this, EventArgs.Empty);
    }
}
