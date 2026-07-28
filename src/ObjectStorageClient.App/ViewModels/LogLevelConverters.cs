using Avalonia.Data.Converters;

namespace ObjectStorageClient.App.ViewModels;

/// <summary>
/// Maps a <see cref="LogLevel"/> onto the boolean style classes the log rows toggle.
/// Keeping the colours in XAML and the predicate here avoids a converter per colour.
/// </summary>
public static class LogLevelConverters
{
    public static readonly IValueConverter IsCommand =
        new FuncValueConverter<LogLevel, bool>(level => level == LogLevel.Command);

    public static readonly IValueConverter IsResponse =
        new FuncValueConverter<LogLevel, bool>(level => level == LogLevel.Response);

    public static readonly IValueConverter IsError =
        new FuncValueConverter<LogLevel, bool>(level => level == LogLevel.Error);
}
