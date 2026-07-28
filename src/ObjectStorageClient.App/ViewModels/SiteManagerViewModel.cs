using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Models;

namespace ObjectStorageClient.App.ViewModels;

/// <summary>
/// Site Manager: the saved-connection list plus the full connection form.
/// Raises <see cref="CloseRequested"/> with the profile to connect to, or <c>null</c> on cancel.
/// </summary>
public sealed partial class SiteManagerViewModel : ViewModelBase
{
    private readonly IConnectionProfileStore _store;
    private readonly IObjectStorageClientFactory _clientFactory;

    public SiteManagerViewModel(IConnectionProfileStore store, IObjectStorageClientFactory clientFactory)
    {
        _store = store;
        _clientFactory = clientFactory;
    }

    /// <summary>Raised when the dialog should close. The argument is the profile to connect with, if any.</summary>
    public event EventHandler<ConnectionProfile?>? CloseRequested;

    public ObservableCollection<ConnectionProfile> Sites { get; } = [];

    public ConnectionEditorViewModel Editor { get; } = new();

    [ObservableProperty]
    private ConnectionProfile? _selectedSite;

    [ObservableProperty]
    private bool _isBusy;

    [ObservableProperty]
    private string _testResult = string.Empty;

    [ObservableProperty]
    private bool _testSucceeded;

    partial void OnSelectedSiteChanged(ConnectionProfile? value)
    {
        if (value is not null)
        {
            Editor.LoadFrom(value);
            TestResult = string.Empty;
        }
    }

    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        Sites.Clear();

        IReadOnlyList<ConnectionProfile> profiles = await _store.LoadAsync(cancellationToken).ConfigureAwait(true);
        foreach (ConnectionProfile profile in profiles.OrderBy(profile => profile.Name, StringComparer.OrdinalIgnoreCase))
        {
            Sites.Add(profile);
        }

        SelectedSite = Sites.FirstOrDefault();

        if (SelectedSite is null)
        {
            Editor.Reset(StorageProviderCatalog.Custom);
        }
    }

    [RelayCommand]
    private void NewSite()
    {
        SelectedSite = null;
        Editor.Reset(StorageProviderCatalog.Custom);
        TestResult = string.Empty;
    }

    [RelayCommand]
    private void DuplicateSite()
    {
        if (SelectedSite is null)
        {
            return;
        }

        Editor.LoadFrom(SelectedSite);
        Editor.AssignNewId();
        Editor.Name = $"{SelectedSite.Name} (copy)";
        SelectedSite = null;
    }

    [RelayCommand]
    private async Task DeleteSiteAsync()
    {
        if (SelectedSite is null)
        {
            return;
        }

        Guid id = SelectedSite.Id;
        await _store.DeleteAsync(id).ConfigureAwait(true);
        await LoadAsync().ConfigureAwait(true);
    }

    [RelayCommand]
    private async Task SaveAsync()
    {
        if (!Editor.Validate())
        {
            return;
        }

        ConnectionProfile profile = Editor.ToProfile();
        await _store.SaveAsync(profile).ConfigureAwait(true);
        await LoadAsync().ConfigureAwait(true);

        SelectedSite = Sites.FirstOrDefault(site => site.Id == profile.Id);
    }

    /// <summary>Opens a throwaway connection to confirm the endpoint, credentials and proxy work.</summary>
    [RelayCommand]
    private async Task TestConnectionAsync()
    {
        if (!Editor.Validate())
        {
            TestSucceeded = false;
            TestResult = "Fix the highlighted problems first.";
            return;
        }

        IsBusy = true;
        TestResult = "Connecting…";

        try
        {
            await using IObjectStorageClient client = _clientFactory.Create(Editor.ToProfile());
            using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(30));
            await client.TestConnectionAsync(timeout.Token).ConfigureAwait(true);

            TestSucceeded = true;
            TestResult = "Connection succeeded.";
        }
        catch (Exception ex)
        {
            TestSucceeded = false;
            TestResult = $"Connection failed: {ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>Saves the form, then closes the dialog asking the main window to connect.</summary>
    [RelayCommand]
    private async Task ConnectAsync()
    {
        if (!Editor.Validate())
        {
            return;
        }

        ConnectionProfile profile = Editor.ToProfile() with { LastUsedAt = DateTimeOffset.Now };
        await _store.SaveAsync(profile).ConfigureAwait(true);

        CloseRequested?.Invoke(this, profile);
    }

    [RelayCommand]
    private void Cancel() => CloseRequested?.Invoke(this, null);
}
