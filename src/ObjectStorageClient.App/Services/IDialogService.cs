namespace ObjectStorageClient.App.Services;

/// <summary>
/// Modal interactions a view model may need. Abstracted so view models stay testable
/// and never reference <c>Window</c> directly.
/// </summary>
public interface IDialogService
{
    /// <summary>Single-line text prompt. Returns <c>null</c> when the user cancels.</summary>
    Task<string?> PromptAsync(string title, string message, string initialValue = "");

    Task<bool> ConfirmAsync(string title, string message);

    Task ShowErrorAsync(string title, string message);

    Task ShowInfoAsync(string title, string message);

    /// <summary>Opens the Site Manager. Returns the profile the user chose to connect with, if any.</summary>
    Task<Core.Models.ConnectionProfile?> ShowSiteManagerAsync();
}
