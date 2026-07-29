using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using ObjectStorageClient.App.ViewModels;

namespace ObjectStorageClient.App.Views;

/// <summary>
/// Shown before the main window. Closing it by any route resolves the view model's
/// <c>Completion</c> task, so startup never hangs waiting on a dismissed dialog.
/// </summary>
public partial class MasterPasswordWindow : Window
{
    public MasterPasswordWindow()
    {
        InitializeComponent();
        DataContextChanged += OnDataContextChanged;
    }

    protected override void OnLoaded(RoutedEventArgs e)
    {
        base.OnLoaded(e);
        PasswordBox.Focus();
    }

    protected override void OnClosing(WindowClosingEventArgs e)
    {
        base.OnClosing(e);

        // Covers the window-chrome close button, which bypasses the Quit command.
        if (DataContext is MasterPasswordViewModel viewModel && !viewModel.Completion.IsCompleted)
        {
            viewModel.CancelCommand.Execute(null);
        }
    }

    private void OnDataContextChanged(object? sender, EventArgs e)
    {
        if (DataContext is MasterPasswordViewModel viewModel)
        {
            viewModel.CloseRequested += (_, _) => Close();
        }
    }

    /// <summary>
    /// Rejects non-ASCII before it reaches the box, so an IME-composed character never appears.
    /// The view model sanitises as well, which is what covers pasting.
    /// </summary>
    private void OnPasswordTextInput(object? sender, TextInputEventArgs e)
    {
        if (e.Text is { Length: > 0 } text && !text.All(MasterPasswordViewModel.IsAllowed))
        {
            e.Handled = true;
        }
    }

    private void OnPasswordKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && DataContext is MasterPasswordViewModel viewModel)
        {
            viewModel.SubmitCommand.Execute(null);
            e.Handled = true;
        }
    }
}
