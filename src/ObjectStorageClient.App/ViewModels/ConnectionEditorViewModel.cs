using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using ObjectStorageClient.Core.Models;

namespace ObjectStorageClient.App.ViewModels;

/// <summary>
/// Editable form behind one <see cref="ConnectionProfile"/>.
/// Selecting a provider only *seeds* the fields — every value stays editable afterwards, so a
/// fully hand-typed endpoint/key/region/bucket combination is equally valid.
/// </summary>
public sealed partial class ConnectionEditorViewModel : ViewModelBase
{
    /// <summary>Set while a preset or profile is being applied, so field-change handlers do not fight back.</summary>
    private bool _suppressPresetSync;

    private Guid _id = Guid.NewGuid();

    public ConnectionEditorViewModel()
    {
        foreach (StorageProviderPreset preset in StorageProviderCatalog.All)
        {
            Providers.Add(preset);
        }

        _selectedProvider = StorageProviderCatalog.Custom;
        ApplyPreset(StorageProviderCatalog.Custom, seedEndpoint: false);
    }

    public ObservableCollection<StorageProviderPreset> Providers { get; } = [];

    /// <summary>Suggested regions for the selected provider. The region field itself stays free-text.</summary>
    public ObservableCollection<string> SuggestedRegions { get; } = [];

    [ObservableProperty]
    private StorageProviderPreset _selectedProvider;

    [ObservableProperty]
    private string _name = "New Site";

    [ObservableProperty]
    private string _serviceUrl = string.Empty;

    [ObservableProperty]
    private string _region = "us-east-1";

    [ObservableProperty]
    private string _accountId = string.Empty;

    [ObservableProperty]
    private string _accessKeyId = string.Empty;

    [ObservableProperty]
    private string _secretAccessKey = string.Empty;

    [ObservableProperty]
    private string _sessionToken = string.Empty;

    [ObservableProperty]
    private string _defaultBucket = string.Empty;

    [ObservableProperty]
    private string _defaultPrefix = string.Empty;

    [ObservableProperty]
    private bool _forcePathStyle = true;

    [ObservableProperty]
    private bool _allowInsecureCertificates;

    // Both default on: the SDK's checksum headers and aws-chunked bodies are what
    // S3-compatible gateways reject. Only the Amazon S3 preset turns them off.
    [ObservableProperty]
    private bool _disableRequestChecksums = true;

    [ObservableProperty]
    private bool _disableChunkedEncoding = true;

    [ObservableProperty]
    private int _timeoutSeconds = 100;

    [ObservableProperty]
    private int _maxConcurrentTransfers = 3;

    [ObservableProperty]
    private bool _proxyEnabled;

    [ObservableProperty]
    private string _proxyHost = string.Empty;

    [ObservableProperty]
    private int _proxyPort = 8080;

    [ObservableProperty]
    private string _proxyUsername = string.Empty;

    [ObservableProperty]
    private string _proxyPassword = string.Empty;

    [ObservableProperty]
    private string _proxyBypassList = string.Empty;

    [ObservableProperty]
    private string _validationMessage = string.Empty;

    /// <summary>Cloudflare R2 and friends need an account id woven into the endpoint.</summary>
    public bool ShowAccountId => SelectedProvider.RequiresAccountId;

    public string EndpointHint => string.IsNullOrEmpty(SelectedProvider.Hint)
        ? "Full endpoint URL, including scheme and port if non-standard."
        : SelectedProvider.Hint;

    partial void OnSelectedProviderChanged(StorageProviderPreset value)
    {
        OnPropertyChanged(nameof(ShowAccountId));
        OnPropertyChanged(nameof(EndpointHint));

        if (_suppressPresetSync)
        {
            return;
        }

        ApplyPreset(value, seedEndpoint: true);
    }

    partial void OnRegionChanged(string value)
    {
        // Providers whose endpoint embeds the region should follow the region field.
        if (_suppressPresetSync || SelectedProvider.EndpointTemplate.Length == 0)
        {
            return;
        }

        if (!SelectedProvider.EndpointTemplate.Contains("{region}", StringComparison.Ordinal))
        {
            return;
        }

        ServiceUrl = SelectedProvider.BuildEndpoint(value, AccountId);
    }

    partial void OnAccountIdChanged(string value)
    {
        if (_suppressPresetSync || !SelectedProvider.RequiresAccountId)
        {
            return;
        }

        ServiceUrl = SelectedProvider.BuildEndpoint(Region, value);
    }

    /// <summary>Fills the form from an existing profile without triggering preset re-seeding.</summary>
    public void LoadFrom(ConnectionProfile profile)
    {
        _suppressPresetSync = true;

        try
        {
            _id = profile.Id;
            SelectedProvider = StorageProviderCatalog.Resolve(profile.ProviderId);
            RefreshSuggestedRegions(SelectedProvider);

            Name = profile.Name;
            ServiceUrl = profile.ServiceUrl;
            Region = profile.Region;
            AccountId = profile.AccountId;
            AccessKeyId = profile.AccessKeyId;
            SecretAccessKey = profile.SecretAccessKey;
            SessionToken = profile.SessionToken;
            DefaultBucket = profile.DefaultBucket;
            DefaultPrefix = profile.DefaultPrefix;
            ForcePathStyle = profile.ForcePathStyle;
            AllowInsecureCertificates = profile.AllowInsecureCertificates;
            DisableRequestChecksums = profile.DisableRequestChecksums;
            DisableChunkedEncoding = profile.DisableChunkedEncoding;
            TimeoutSeconds = profile.TimeoutSeconds;
            MaxConcurrentTransfers = profile.MaxConcurrentTransfers;

            ProxyEnabled = profile.Proxy.Enabled;
            ProxyHost = profile.Proxy.Host;
            ProxyPort = profile.Proxy.Port;
            ProxyUsername = profile.Proxy.Username;
            ProxyPassword = profile.Proxy.Password;
            ProxyBypassList = profile.Proxy.BypassList;

            ValidationMessage = string.Empty;
        }
        finally
        {
            _suppressPresetSync = false;
        }
    }

    /// <summary>Materialises the form into a profile. Does not validate; call <see cref="Validate"/> first.</summary>
    public ConnectionProfile ToProfile() => new()
    {
        Id = _id,
        Name = Name.Trim(),
        ProviderId = SelectedProvider.Id,
        ServiceUrl = ServiceUrl.Trim(),
        Region = Region.Trim(),
        AccountId = AccountId.Trim(),
        AccessKeyId = AccessKeyId.Trim(),
        SecretAccessKey = SecretAccessKey,
        SessionToken = SessionToken.Trim(),
        DefaultBucket = DefaultBucket.Trim(),
        DefaultPrefix = DefaultPrefix.Trim(),
        ForcePathStyle = ForcePathStyle,
        AllowInsecureCertificates = AllowInsecureCertificates,
        DisableRequestChecksums = DisableRequestChecksums,
        DisableChunkedEncoding = DisableChunkedEncoding,
        TimeoutSeconds = TimeoutSeconds,
        MaxConcurrentTransfers = MaxConcurrentTransfers,
        Proxy = new ProxySettings
        {
            Enabled = ProxyEnabled,
            Host = ProxyHost.Trim(),
            Port = ProxyPort,
            Username = ProxyUsername.Trim(),
            Password = ProxyPassword,
            BypassList = ProxyBypassList.Trim(),
        },
    };

    /// <summary>Runs profile validation and publishes the result to <see cref="ValidationMessage"/>.</summary>
    public bool Validate()
    {
        IReadOnlyList<string> errors = ToProfile().Validate();
        ValidationMessage = string.Join(Environment.NewLine, errors);
        return errors.Count == 0;
    }

    /// <summary>Resets the form to a new, unsaved profile seeded from <paramref name="preset"/>.</summary>
    public void Reset(StorageProviderPreset preset)
    {
        _id = Guid.NewGuid();
        _suppressPresetSync = true;

        try
        {
            SelectedProvider = preset;
            Name = preset.IsCustom ? "New Site" : preset.DisplayName;
            AccountId = string.Empty;
            AccessKeyId = string.Empty;
            SecretAccessKey = string.Empty;
            SessionToken = string.Empty;
            DefaultBucket = string.Empty;
            DefaultPrefix = string.Empty;
            TimeoutSeconds = 100;
            MaxConcurrentTransfers = 3;
            AllowInsecureCertificates = false;
            ProxyEnabled = false;
            ProxyHost = string.Empty;
            ProxyPort = 8080;
            ProxyUsername = string.Empty;
            ProxyPassword = string.Empty;
            ProxyBypassList = string.Empty;
            ValidationMessage = string.Empty;
        }
        finally
        {
            _suppressPresetSync = false;
        }

        ApplyPreset(preset, seedEndpoint: true);
    }

    /// <summary>Gives the edited profile a fresh identity, so "Duplicate" does not overwrite the original.</summary>
    public void AssignNewId() => _id = Guid.NewGuid();

    private void ApplyPreset(StorageProviderPreset preset, bool seedEndpoint)
    {
        _suppressPresetSync = true;

        try
        {
            RefreshSuggestedRegions(preset);

            Region = preset.DefaultRegion;
            ForcePathStyle = preset.ForcePathStyle;
            DisableRequestChecksums = preset.DisableRequestChecksums;
            DisableChunkedEncoding = preset.DisableChunkedEncoding;

            if (seedEndpoint)
            {
                // Empty for manual providers, which is exactly the "type it yourself" case.
                ServiceUrl = preset.BuildEndpoint(preset.DefaultRegion, AccountId);
            }
        }
        finally
        {
            _suppressPresetSync = false;
        }
    }

    private void RefreshSuggestedRegions(StorageProviderPreset preset)
    {
        SuggestedRegions.Clear();
        foreach (string region in preset.Regions)
        {
            SuggestedRegions.Add(region);
        }
    }
}
