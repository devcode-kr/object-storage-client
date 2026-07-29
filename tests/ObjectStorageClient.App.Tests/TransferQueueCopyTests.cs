using ObjectStorageClient.App.Services;
using ObjectStorageClient.App.ViewModels;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Transfers;
using Xunit;

namespace ObjectStorageClient.App.Tests;

/// <summary>Records what would land on the clipboard.</summary>
internal sealed class FakeClipboardService : IClipboardService
{
    internal string? LastText { get; private set; }

    internal int CallCount { get; private set; }

    public Task SetTextAsync(string text)
    {
        LastText = text;
        CallCount++;
        return Task.CompletedTask;
    }
}

/// <summary>
/// Covers the Failed-tab context menu: what each copy command puts on the clipboard, and
/// when the commands are allowed to run at all.
/// </summary>
public sealed class TransferQueueCopyTests
{
    private static (TransferQueueViewModel ViewModel, FakeClipboardService Clipboard) CreateViewModel()
    {
        FakeClipboardService clipboard = new();
        return (new TransferQueueViewModel(new TransferQueue(), clipboard), clipboard);
    }

    /// <summary>Builds a finished transfer directly; an empty <paramref name="error"/> means it succeeded.</summary>
    private static TransferItemViewModel Row(string key, string error)
    {
        TransferItem item = new(new TransferRequest
        {
            Direction = TransferDirection.Upload,
            Bucket = "assets",
            RemoteKey = key,
            LocalPath = $"/home/user/{key}",
            Size = 2048,
        });

        bool failed = !string.IsNullOrEmpty(error);
        item.Status = failed ? TransferStatus.Failed : TransferStatus.Completed;
        item.ErrorMessage = failed ? error : null;

        return new TransferItemViewModel(item);
    }

    [Fact]
    public async Task CopyErrorMessage_PutsOnlyTheReasonOnTheClipboard()
    {
        (TransferQueueViewModel viewModel, FakeClipboardService clipboard) = CreateViewModel();
        viewModel.SelectedItem = Row("photos/cat.png", "Access Denied");

        await viewModel.CopyErrorMessageCommand.ExecuteAsync(null);

        Assert.Equal("Access Denied", clipboard.LastText);
    }

    [Fact]
    public async Task CopyLocalPath_AndCopyRemotePath_CopyThatColumnAlone()
    {
        (TransferQueueViewModel viewModel, FakeClipboardService clipboard) = CreateViewModel();
        viewModel.SelectedItem = Row("photos/cat.png", "Access Denied");

        await viewModel.CopyLocalPathCommand.ExecuteAsync(null);
        Assert.Equal("/home/user/photos/cat.png", clipboard.LastText);

        await viewModel.CopyRemotePathCommand.ExecuteAsync(null);
        Assert.Equal("assets/photos/cat.png", clipboard.LastText);
    }

    [Fact]
    public async Task CopyDetails_IncludesEveryFieldOnItsOwnLine()
    {
        (TransferQueueViewModel viewModel, FakeClipboardService clipboard) = CreateViewModel();
        viewModel.SelectedItem = Row("photos/cat.png", "Access Denied");

        await viewModel.CopyDetailsCommand.ExecuteAsync(null);
        string text = clipboard.LastText!;

        Assert.Contains("Direction: Upload", text, StringComparison.Ordinal);
        Assert.Contains("Local:     /home/user/photos/cat.png", text, StringComparison.Ordinal);
        Assert.Contains("Remote:    assets/photos/cat.png", text, StringComparison.Ordinal);
        Assert.Contains("Reason:    Access Denied", text, StringComparison.Ordinal);
        Assert.DoesNotContain('\t', text);
    }

    [Fact]
    public async Task CopyAllFailed_ProducesATabSeparatedTableWithAHeader()
    {
        (TransferQueueViewModel viewModel, FakeClipboardService clipboard) = CreateViewModel();
        viewModel.Failed.Add(Row("a.bin", "Access Denied"));
        viewModel.Failed.Add(Row("b.bin", "No such bucket"));

        await viewModel.CopyAllFailedCommand.ExecuteAsync(null);
        string[] lines = clipboard.LastText!.Split(Environment.NewLine);

        Assert.Equal(3, lines.Length);
        Assert.StartsWith("Direction\tLocal file\tRemote file", lines[0], StringComparison.Ordinal);
        Assert.Contains("Access Denied", lines[1], StringComparison.Ordinal);
        Assert.Contains("No such bucket", lines[2], StringComparison.Ordinal);
    }

    [Fact]
    public async Task CopyAllFailed_DoesNothingWhenThereAreNoFailures()
    {
        (TransferQueueViewModel viewModel, FakeClipboardService clipboard) = CreateViewModel();

        await viewModel.CopyAllFailedCommand.ExecuteAsync(null);

        Assert.Equal(0, clipboard.CallCount);
    }

    [Fact]
    public void CopyCommands_AreDisabledWithNothingSelected()
    {
        (TransferQueueViewModel viewModel, _) = CreateViewModel();

        Assert.False(viewModel.CopyErrorMessageCommand.CanExecute(null));
        Assert.False(viewModel.CopyDetailsCommand.CanExecute(null));
        Assert.False(viewModel.CopyLocalPathCommand.CanExecute(null));
        Assert.False(viewModel.CopyRemotePathCommand.CanExecute(null));
    }

    [Fact]
    public void SelectingARow_EnablesTheCopyCommands()
    {
        (TransferQueueViewModel viewModel, _) = CreateViewModel();

        viewModel.SelectedItem = Row("photos/cat.png", "Access Denied");

        Assert.True(viewModel.CopyErrorMessageCommand.CanExecute(null));
        Assert.True(viewModel.CopyDetailsCommand.CanExecute(null));
        Assert.True(viewModel.HasSelection);
        Assert.True(viewModel.HasErrorMessage);
    }

    [Fact]
    public void CopyErrorMessage_StaysDisabledForARowWithoutAReason()
    {
        (TransferQueueViewModel viewModel, _) = CreateViewModel();

        // A successful transfer has no error, so only the path/detail commands make sense.
        viewModel.SelectedItem = Row("done.bin", string.Empty);

        Assert.False(viewModel.CopyErrorMessageCommand.CanExecute(null));
        Assert.True(viewModel.CopyDetailsCommand.CanExecute(null));
    }

    [Fact]
    public async Task CopyErrorMessage_DoesNotTouchTheClipboardWithNothingSelected()
    {
        (TransferQueueViewModel viewModel, FakeClipboardService clipboard) = CreateViewModel();

        await viewModel.CopyErrorMessageCommand.ExecuteAsync(null);

        Assert.Equal(0, clipboard.CallCount);
    }
}
