using Avalonia.Controls;

namespace ObjectStorageClient.App.Views;

/// <summary>
/// Closing is driven by <c>SiteManagerViewModel.CloseRequested</c>, which the dialog service
/// subscribes to so it can also capture the profile the user chose to connect with.
/// </summary>
public partial class SiteManagerWindow : Window
{
    public SiteManagerWindow() => InitializeComponent();
}
