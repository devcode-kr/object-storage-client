using ObjectStorageClient.App.ViewModels;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Profiles;
using Xunit;

namespace ObjectStorageClient.App.Tests;

internal sealed class UnusedClientFactory : IObjectStorageClientFactory
{
    public IObjectStorageClient Create(ConnectionProfile profile) =>
        throw new NotSupportedException("These tests never open a connection.");
}

/// <summary>
/// Saving is the Save button's job and nothing else's. Connecting with edited fields is a way to
/// try them out; it must not commit them to disk.
/// </summary>
public sealed class SiteManagerPersistenceTests : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), $"osc-sites-{Guid.NewGuid():N}");
    private readonly string _file;
    private readonly JsonConnectionProfileStore _store;

    public SiteManagerPersistenceTests()
    {
        Directory.CreateDirectory(_directory);
        _file = Path.Combine(_directory, "sites.json");
        _store = new JsonConnectionProfileStore(
            MasterPasswordVault.Create("test-password", iterations: 1_000).Protector,
            _file);
    }

    private SiteManagerViewModel CreateViewModel()
    {
        SiteManagerViewModel viewModel = new(_store, new UnusedClientFactory());

        viewModel.Editor.SelectedProvider = StorageProviderCatalog.Custom;
        viewModel.Editor.Name = "Example";
        viewModel.Editor.ServiceUrl = "https://s3.example.com";
        viewModel.Editor.AccessKeyId = "key";
        viewModel.Editor.SecretAccessKey = "secret";

        return viewModel;
    }

    [Fact]
    public async Task Connect_DoesNotWriteAnythingToDisk()
    {
        SiteManagerViewModel viewModel = CreateViewModel();
        ConnectionProfile? requested = null;
        viewModel.CloseRequested += (_, profile) => requested = profile;

        viewModel.ConnectCommand.Execute(null);

        Assert.False(File.Exists(_file), "Connect wrote the site file.");
        Assert.Empty(await _store.LoadAsync());

        // It still hands the edited values to the main window to connect with.
        Assert.NotNull(requested);
        Assert.Equal("https://s3.example.com", requested!.ServiceUrl);
    }

    [Fact]
    public async Task Save_IsTheOnlyThingThatPersists()
    {
        SiteManagerViewModel viewModel = CreateViewModel();

        await viewModel.SaveCommand.ExecuteAsync(null);

        ConnectionProfile saved = Assert.Single(await _store.LoadAsync());
        Assert.Equal("Example", saved.Name);
        Assert.Equal("secret", saved.SecretAccessKey);
    }

    [Fact]
    public async Task EditingAfterASave_DoesNotPersistUntilSavedAgain()
    {
        SiteManagerViewModel viewModel = CreateViewModel();
        await viewModel.SaveCommand.ExecuteAsync(null);

        viewModel.Editor.Name = "Renamed but not saved";
        viewModel.ConnectCommand.Execute(null);

        Assert.Equal("Example", Assert.Single(await _store.LoadAsync()).Name);
    }

    [Fact]
    public async Task Save_RejectsAnInvalidFormInsteadOfWritingIt()
    {
        SiteManagerViewModel viewModel = CreateViewModel();
        viewModel.Editor.AccessKeyId = string.Empty;

        await viewModel.SaveCommand.ExecuteAsync(null);

        Assert.Empty(await _store.LoadAsync());
        Assert.NotEmpty(viewModel.Editor.ValidationMessage);
    }

    public void Dispose() => Directory.Delete(_directory, recursive: true);
}
