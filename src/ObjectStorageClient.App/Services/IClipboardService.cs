using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Input.Platform;

namespace ObjectStorageClient.App.Services;

/// <summary>
/// System clipboard access. Abstracted so view models can offer copy commands without
/// reaching for <c>TopLevel</c>, and so tests can assert on what would be copied.
/// </summary>
public interface IClipboardService
{
    Task SetTextAsync(string text);
}

/// <summary>Clipboard of the main window's top level.</summary>
public sealed class ClipboardService : IClipboardService
{
    public async Task SetTextAsync(string text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return;
        }

        if (GetClipboard() is { } clipboard)
        {
            await clipboard.SetTextAsync(text).ConfigureAwait(true);
        }
    }

    private static IClipboard? GetClipboard()
    {
        Window? mainWindow =
            (Avalonia.Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.MainWindow;

        return TopLevel.GetTopLevel(mainWindow)?.Clipboard;
    }
}
