using ObjectStorageClient.App.Services;
using ObjectStorageClient.App.ViewModels;
using ObjectStorageClient.Core.Local;
using ObjectStorageClient.Core.Models;
using Xunit;

namespace ObjectStorageClient.App.Tests;

internal sealed class FakeTransferCoordinator : ITransferCoordinator
{
    public bool IsConnected { get; set; } = true;

    internal List<LocalEntry> Uploaded { get; } = [];

    internal List<RemoteEntry> Downloaded { get; } = [];

    public void QueueUpload(IReadOnlyList<LocalEntry> entries) => Uploaded.AddRange(entries);

    public void QueueDownload(IReadOnlyList<RemoteEntry> entries) => Downloaded.AddRange(entries);
}

internal sealed class StubDialogService : IDialogService
{
    public Task<string?> PromptAsync(string title, string message, string initialValue = "") =>
        Task.FromResult<string?>(null);

    public Task<bool> ConfirmAsync(string title, string message) => Task.FromResult(false);

    public Task ShowErrorAsync(string title, string message) => Task.CompletedTask;

    public Task ShowInfoAsync(string title, string message) => Task.CompletedTask;

    public Task<ConnectionProfile?> ShowSiteManagerAsync() => Task.FromResult<ConnectionProfile?>(null);
}

/// <summary>
/// Activating a row (double-click or Enter) descends into containers and transfers everything
/// else, so the two panes must agree on that split.
/// </summary>
public sealed class DoubleClickTransferTests : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), $"osc-dbl-{Guid.NewGuid():N}");
    private readonly FakeTransferCoordinator _coordinator = new();

    public DoubleClickTransferTests()
    {
        Directory.CreateDirectory(Path.Combine(_directory, "child"));
        File.WriteAllText(Path.Combine(_directory, "note.txt"), "hello");
    }

    private LocalBrowserViewModel CreateLocalPane()
    {
        LocalBrowserViewModel pane = new(new LogViewModel(), new StubDialogService(), _coordinator);
        pane.Navigate(_directory);
        return pane;
    }

    private RemoteBrowserViewModel CreateRemotePane() =>
        new(new LogViewModel(), new StubDialogService(), _coordinator);

    [Fact]
    public void LocalPane_ActivatingAFile_QueuesAnUpload()
    {
        LocalBrowserViewModel pane = CreateLocalPane();
        LocalEntry file = pane.Entries.Single(entry => entry.Name == "note.txt");

        pane.OpenCommand.Execute(file);

        Assert.Equal("note.txt", Assert.Single(_coordinator.Uploaded).Name);
        Assert.Equal(_directory, pane.CurrentPath);
    }

    [Fact]
    public void LocalPane_ActivatingADirectory_NavigatesWithoutTransferring()
    {
        LocalBrowserViewModel pane = CreateLocalPane();
        LocalEntry directory = pane.Entries.Single(entry => entry.Name == "child");

        pane.OpenCommand.Execute(directory);

        Assert.Empty(_coordinator.Uploaded);
        Assert.Equal(Path.Combine(_directory, "child"), pane.CurrentPath);
    }

    [Fact]
    public void LocalPane_ActivatingTheParentLink_Navigates()
    {
        LocalBrowserViewModel pane = CreateLocalPane();
        LocalEntry parent = pane.Entries.Single(entry => entry.IsParentLink);

        pane.OpenCommand.Execute(parent);

        Assert.Empty(_coordinator.Uploaded);
        Assert.NotEqual(_directory, pane.CurrentPath);
    }

    [Fact]
    public async Task RemotePane_ActivatingAnObject_QueuesADownload()
    {
        RemoteBrowserViewModel pane = CreateRemotePane();
        RemoteEntry file = new() { Name = "cat.png", Key = "photos/cat.png", Size = 10 };

        await pane.OpenCommand.ExecuteAsync(file);

        Assert.Equal("photos/cat.png", Assert.Single(_coordinator.Downloaded).Key);
        Assert.Empty(pane.CurrentPrefix);
    }

    [Fact]
    public async Task RemotePane_ActivatingAFolder_NavigatesWithoutTransferring()
    {
        RemoteBrowserViewModel pane = CreateRemotePane();
        RemoteEntry folder = RemoteEntry.Folder("photos/2024/", "2024");

        await pane.OpenCommand.ExecuteAsync(folder);

        Assert.Empty(_coordinator.Downloaded);
        Assert.Equal("photos/2024/", pane.CurrentPrefix);
    }

    [Fact]
    public async Task ActivatingNothing_IsIgnoredByBothPanes()
    {
        LocalBrowserViewModel local = CreateLocalPane();
        RemoteBrowserViewModel remote = CreateRemotePane();

        local.OpenCommand.Execute(null);
        await remote.OpenCommand.ExecuteAsync(null);

        Assert.Empty(_coordinator.Uploaded);
        Assert.Empty(_coordinator.Downloaded);
    }

    public void Dispose() => Directory.Delete(_directory, recursive: true);
}
