using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Microsoft.Extensions.DependencyInjection;
using ObjectStorageClient.App.ViewModels;
using ObjectStorageClient.App.Views;
using ObjectStorageClient.Core.Models;

namespace ObjectStorageClient.App.Services;

/// <summary>
/// Shows modal windows owned by the main window. The only place in the app that view models
/// reach the <c>Window</c> type, keeping the view models themselves platform-free.
/// </summary>
public sealed class DialogService : IDialogService
{
    public async Task<string?> PromptAsync(string title, string message, string initialValue = "")
    {
        Window? owner = GetOwner();
        if (owner is null)
        {
            return null;
        }

        MessageDialogViewModel viewModel = MessageDialogViewModel.Prompt(title, message, initialValue);
        MessageDialog dialog = new() { DataContext = viewModel };

        await dialog.ShowDialog(owner).ConfigureAwait(true);
        return viewModel.Confirmed ? viewModel.InputText : null;
    }

    public async Task<bool> ConfirmAsync(string title, string message)
    {
        Window? owner = GetOwner();
        if (owner is null)
        {
            return false;
        }

        MessageDialogViewModel viewModel = MessageDialogViewModel.Confirm(title, message);
        MessageDialog dialog = new() { DataContext = viewModel };

        await dialog.ShowDialog(owner).ConfigureAwait(true);
        return viewModel.Confirmed;
    }

    public Task ShowErrorAsync(string title, string message) => ShowMessageAsync(title, message, isError: true);

    public Task ShowInfoAsync(string title, string message) => ShowMessageAsync(title, message, isError: false);

    public async Task<ConnectionProfile?> ShowSiteManagerAsync()
    {
        Window? owner = GetOwner();
        if (owner is null || App.Services is null)
        {
            return null;
        }

        SiteManagerViewModel viewModel = App.Services.GetRequiredService<SiteManagerViewModel>();
        SiteManagerWindow window = new() { DataContext = viewModel };

        ConnectionProfile? result = null;
        viewModel.CloseRequested += (_, profile) =>
        {
            result = profile;
            window.Close();
        };

        await viewModel.LoadAsync().ConfigureAwait(true);
        await window.ShowDialog(owner).ConfigureAwait(true);

        return result;
    }

    private static async Task ShowMessageAsync(string title, string message, bool isError)
    {
        Window? owner = GetOwner();
        if (owner is null)
        {
            return;
        }

        MessageDialog dialog = new()
        {
            DataContext = MessageDialogViewModel.Notice(title, message, isError),
        };

        await dialog.ShowDialog(owner).ConfigureAwait(true);
    }

    private static Window? GetOwner() =>
        (Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.MainWindow;
}
