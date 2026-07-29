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

        foreach (TextBox box in new[] { PasswordBox, ConfirmPasswordBox })
        {
            // Tunnel, not bubble: TextBox.OnTextInput is a class handler on the bubble stage, so
            // a bubbling handler only runs once the text has already been inserted. Attaching in
            // XAML gives a bubbling handler, which is why this is wired up here.
            box.AddHandler(InputElement.TextInputEvent, OnPasswordTextInput, RoutingStrategies.Tunnel);

            // Catches routes that never raise TextInput at all, notably paste.
            box.TextChanged += OnPasswordTextChanged;
        }
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
    /// Drops text input containing non-ASCII before the box receives it.
    /// </summary>
    /// <remarks>
    /// This is the only mechanism used. <c>InputMethod.IsInputMethodEnabled="False"</c> looks like
    /// the obvious alternative but is actively dangerous here: with the input context switched off,
    /// macOS delivers raw key events mapped through the current layout, and under a Korean layout
    /// Shift stops producing uppercase. The same keystrokes then yield a *different* password
    /// depending on the input mode — silently, because the field is masked — which is how a vault
    /// gets created with a password the user cannot reproduce. Letting the IME run and rejecting
    /// its output here keeps input predictable and tells the user what happened.
    /// </remarks>
    private void OnPasswordTextInput(object? sender, TextInputEventArgs e)
    {
        if (e.Text is { Length: > 0 } text && !text.All(MasterPasswordViewModel.IsAllowed))
        {
            e.Handled = true;
            ReportRejectedInput();
        }
    }

    /// <summary>
    /// Last line of defence: strips anything that reached the box without raising
    /// <c>TextInput</c> — pasting, drag-and-drop, or a platform quirk — so what is displayed
    /// always matches the password that will actually be used.
    /// </summary>
    private void OnPasswordTextChanged(object? sender, TextChangedEventArgs e)
    {
        if (sender is not TextBox box || box.Text is not { } text)
        {
            return;
        }

        string allowed = MasterPasswordViewModel.RemoveDisallowed(text);
        if (string.Equals(allowed, text, StringComparison.Ordinal))
        {
            return;
        }

        int caret = box.CaretIndex;
        box.Text = allowed;
        box.CaretIndex = Math.Clamp(caret, 0, allowed.Length);

        // Assigning the text propagates through the binding and clears ErrorMessage, so the
        // rejection has to be reported after it, not before.
        ReportRejectedInput();
    }

    private void ReportRejectedInput() =>
        (DataContext as MasterPasswordViewModel)?.ReportNonAsciiRejected();

    private void OnPasswordKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && DataContext is MasterPasswordViewModel viewModel)
        {
            viewModel.SubmitCommand.Execute(null);
            e.Handled = true;
        }
    }
}
