using System.Collections.ObjectModel;
using Avalonia.Threading;

namespace ObjectStorageClient.App.ViewModels;

public enum LogLevel
{
    Info,
    Command,
    Response,
    Error,
}

/// <summary>One line in the message log pane.</summary>
public sealed record LogEntry(DateTimeOffset Timestamp, LogLevel Level, string Message)
{
    public string TimeText => Timestamp.ToString("HH:mm:ss");

    /// <summary>Style class applied to the row, so colours live in XAML rather than here.</summary>
    public string LevelClass => Level.ToString().ToLowerInvariant();
}

/// <summary>
/// FileZilla-style message log. Capped so a long session cannot grow without bound.
/// Safe to call from any thread — appends are marshalled to the UI thread.
/// </summary>
public sealed class LogViewModel : ViewModelBase
{
    private const int MaxEntries = 2000;

    public ObservableCollection<LogEntry> Entries { get; } = [];

    public void Info(string message) => Append(LogLevel.Info, message);

    public void Command(string message) => Append(LogLevel.Command, message);

    public void Response(string message) => Append(LogLevel.Response, message);

    public void Error(string message) => Append(LogLevel.Error, message);

    public void Error(string message, Exception exception) => Append(LogLevel.Error, $"{message}: {exception.Message}");

    public void Clear()
    {
        if (Dispatcher.UIThread.CheckAccess())
        {
            Entries.Clear();
        }
        else
        {
            Dispatcher.UIThread.Post(Entries.Clear);
        }
    }

    private void Append(LogLevel level, string message)
    {
        LogEntry entry = new(DateTimeOffset.Now, level, message);

        if (Dispatcher.UIThread.CheckAccess())
        {
            AppendCore(entry);
        }
        else
        {
            Dispatcher.UIThread.Post(() => AppendCore(entry));
        }
    }

    private void AppendCore(LogEntry entry)
    {
        Entries.Add(entry);

        while (Entries.Count > MaxEntries)
        {
            Entries.RemoveAt(0);
        }
    }
}
