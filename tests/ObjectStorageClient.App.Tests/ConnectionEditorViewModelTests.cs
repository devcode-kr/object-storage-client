using ObjectStorageClient.App.ViewModels;
using ObjectStorageClient.Core.Models;
using Xunit;

namespace ObjectStorageClient.App.Tests;

/// <summary>
/// Covers the rule the connection form is built around: a preset only <i>seeds</i> the fields,
/// and anything the user types afterwards must survive.
/// </summary>
public sealed class ConnectionEditorViewModelTests
{
    private static StorageProviderPreset Preset(string id) => StorageProviderCatalog.Resolve(id);

    [Fact]
    public void SelectingAPreset_SeedsEndpointRegionAndProviderQuirks()
    {
        ConnectionEditorViewModel editor = new()
        {
            SelectedProvider = Preset("aws"),
        };

        Assert.Equal("https://s3.us-east-1.amazonaws.com", editor.ServiceUrl);
        Assert.Equal("us-east-1", editor.Region);
        Assert.False(editor.ForcePathStyle);
    }

    [Fact]
    public void SelectingAManualProvider_LeavesTheEndpointBlankForTheUserToType()
    {
        ConnectionEditorViewModel editor = new()
        {
            SelectedProvider = Preset("minio"),
        };

        Assert.Empty(editor.ServiceUrl);
        Assert.True(editor.ForcePathStyle);
    }

    [Fact]
    public void ChangingTheRegion_UpdatesEndpointsThatEmbedIt()
    {
        ConnectionEditorViewModel editor = new() { SelectedProvider = Preset("aws") };

        editor.Region = "ap-northeast-2";

        Assert.Equal("https://s3.ap-northeast-2.amazonaws.com", editor.ServiceUrl);
    }

    [Fact]
    public void ChangingTheRegion_DoesNotTouchAManuallyTypedEndpoint()
    {
        ConnectionEditorViewModel editor = new() { SelectedProvider = Preset("minio") };
        editor.ServiceUrl = "http://localhost:9000";

        editor.Region = "kr-standard";

        Assert.Equal("http://localhost:9000", editor.ServiceUrl);
    }

    [Fact]
    public void ChangingTheAccountId_RebuildsEndpointsThatEmbedIt()
    {
        ConnectionEditorViewModel editor = new() { SelectedProvider = Preset("r2") };

        editor.AccountId = "abc123";

        Assert.Equal("https://abc123.r2.cloudflarestorage.com", editor.ServiceUrl);
        Assert.True(editor.ShowAccountId);
    }

    [Fact]
    public void ShowAccountId_IsFalseForProvidersThatDoNotNeedOne()
    {
        ConnectionEditorViewModel editor = new() { SelectedProvider = Preset("aws") };

        Assert.False(editor.ShowAccountId);
    }

    [Fact]
    public void ToProfile_CarriesEveryManuallyEnteredFieldIncludingTheProxy()
    {
        ConnectionEditorViewModel editor = new()
        {
            SelectedProvider = Preset("minio"),
            Name = "Dev MinIO",
            ServiceUrl = "http://localhost:9000",
            Region = "us-east-1",
            AccessKeyId = "minioadmin",
            SecretAccessKey = "minioadmin",
            DefaultBucket = "assets",
            DefaultPrefix = "images/",
            MaxConcurrentTransfers = 6,
            ProxyEnabled = true,
            ProxyHost = "proxy.example.com",
            ProxyPort = 3128,
            ProxyUsername = "user",
            ProxyPassword = "pass",
            ProxyBypassList = "localhost;*.internal",
        };

        ConnectionProfile profile = editor.ToProfile();

        Assert.Equal("Dev MinIO", profile.Name);
        Assert.Equal("minio", profile.ProviderId);
        Assert.Equal("http://localhost:9000", profile.ServiceUrl);
        Assert.Equal("assets", profile.DefaultBucket);
        Assert.Equal(6, profile.MaxConcurrentTransfers);
        Assert.True(profile.Proxy.IsUsable);
        Assert.Equal(3128, profile.Proxy.Port);
        Assert.Equal("pass", profile.Proxy.Password);
        Assert.Empty(profile.Validate());
    }

    [Fact]
    public void LoadFrom_RestoresAProfileWithoutTheProviderPresetOverwritingIt()
    {
        ConnectionProfile saved = new()
        {
            Name = "Scoped AWS",
            ProviderId = "aws",
            // Deliberately different from what the "aws" preset would generate.
            ServiceUrl = "https://s3-accelerate.amazonaws.com",
            Region = "eu-west-1",
            AccessKeyId = "key",
            SecretAccessKey = "secret",
        };

        ConnectionEditorViewModel editor = new();
        editor.LoadFrom(saved);

        Assert.Equal("https://s3-accelerate.amazonaws.com", editor.ServiceUrl);
        Assert.Equal("eu-west-1", editor.Region);
        Assert.Equal("aws", editor.SelectedProvider.Id);
    }

    [Fact]
    public void Validate_PublishesTheProblemsToTheMessageShownInTheDialog()
    {
        ConnectionEditorViewModel editor = new() { SelectedProvider = Preset("minio") };

        Assert.False(editor.Validate());
        Assert.Contains("Endpoint", editor.ValidationMessage, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void AssignNewId_MakesDuplicateSaveAsANewSiteRatherThanOverwriting()
    {
        ConnectionEditorViewModel editor = new();
        editor.LoadFrom(new ConnectionProfile { Name = "Original" });
        Guid originalId = editor.ToProfile().Id;

        editor.AssignNewId();

        Assert.NotEqual(originalId, editor.ToProfile().Id);
    }

    [Fact]
    public void Reset_ClearsCredentialsFromThePreviouslyEditedSite()
    {
        ConnectionEditorViewModel editor = new();
        editor.LoadFrom(new ConnectionProfile
        {
            Name = "Old",
            AccessKeyId = "key",
            SecretAccessKey = "secret",
            DefaultBucket = "bucket",
        });

        editor.Reset(StorageProviderCatalog.Custom);

        Assert.Empty(editor.AccessKeyId);
        Assert.Empty(editor.SecretAccessKey);
        Assert.Empty(editor.DefaultBucket);
    }
}
