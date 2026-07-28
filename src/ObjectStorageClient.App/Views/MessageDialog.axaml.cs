using Avalonia.Controls;
using Avalonia.Interactivity;
using ObjectStorageClient.App.ViewModels;

namespace ObjectStorageClient.App.Views;

public partial class MessageDialog : Window
{
    public MessageDialog()
    {
        InitializeComponent();
        DataContextChanged += OnDataContextChanged;
    }

    protected override void OnLoaded(RoutedEventArgs e)
    {
        base.OnLoaded(e);

        // Put the caret where the user is about to type.
        if (DataContext is MessageDialogViewModel { ShowInput: true })
        {
            InputBox.Focus();
            InputBox.SelectAll();
        }
    }

    private void OnDataContextChanged(object? sender, EventArgs e)
    {
        if (DataContext is MessageDialogViewModel viewModel)
        {
            viewModel.CloseRequested += (_, _) => Close();
        }
    }
}
