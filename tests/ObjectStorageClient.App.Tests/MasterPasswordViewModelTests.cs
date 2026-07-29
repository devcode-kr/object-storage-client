using ObjectStorageClient.App.ViewModels;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Profiles;
using Xunit;

namespace ObjectStorageClient.App.Tests;

/// <summary>
/// The startup gate decides whether the user is creating a vault or unlocking one, and it is
/// the only thing standing between a wrong password and an unreadable site list.
/// </summary>
public sealed class MasterPasswordViewModelTests
{
    private const int TestIterations = 1_000;

    private static AppSettings ConfiguredSettings(string password) => new()
    {
        MasterPassword = MasterPasswordVault.Create(password, TestIterations).Settings,
    };

    private static MasterPasswordViewModel Create(AppSettings settings) => new(settings, "/tmp/config");

    [Fact]
    public void FirstRun_StartsInCreateMode()
    {
        MasterPasswordViewModel gate = Create(new AppSettings());

        Assert.True(gate.IsCreating);
        Assert.False(gate.IsUnlocking);
        Assert.Equal("Create", gate.AcceptText);
    }

    [Fact]
    public void ExistingVault_StartsInUnlockMode()
    {
        MasterPasswordViewModel gate = Create(ConfiguredSettings("correct horse"));

        Assert.False(gate.IsCreating);
        Assert.True(gate.IsUnlocking);
        Assert.Equal("Unlock", gate.AcceptText);
    }

    [Fact]
    public async Task Submit_RejectsAnEmptyPassword()
    {
        MasterPasswordViewModel gate = Create(new AppSettings());

        await gate.SubmitCommand.ExecuteAsync(null);

        Assert.Equal("Enter a password.", gate.ErrorMessage);
        Assert.False(gate.Completion.IsCompleted);
    }

    [Fact]
    public async Task Create_RejectsAShortPassword()
    {
        MasterPasswordViewModel gate = Create(new AppSettings());
        gate.Password = "short";
        gate.ConfirmPassword = "short";

        await gate.SubmitCommand.ExecuteAsync(null);

        Assert.Contains("8 characters", gate.ErrorMessage, StringComparison.Ordinal);
        Assert.False(gate.Completion.IsCompleted);
    }

    [Fact]
    public async Task Create_RejectsMismatchedConfirmation()
    {
        MasterPasswordViewModel gate = Create(new AppSettings());
        gate.Password = "correct horse";
        gate.ConfirmPassword = "battery staple";

        await gate.SubmitCommand.ExecuteAsync(null);

        Assert.Contains("do not match", gate.ErrorMessage, StringComparison.Ordinal);
        Assert.False(gate.Completion.IsCompleted);
    }

    [Fact]
    public async Task Create_CompletesWithAVaultThatCanBeUnlockedAgain()
    {
        MasterPasswordViewModel gate = Create(new AppSettings());
        gate.Password = "correct horse";
        gate.ConfirmPassword = "correct horse";

        await gate.SubmitCommand.ExecuteAsync(null);
        MasterPasswordVault.UnlockedVault? vault = await gate.Completion;

        Assert.NotNull(vault);
        Assert.True(MasterPasswordVault.IsUsable(vault!.Settings));
        Assert.NotNull(MasterPasswordVault.TryUnlock("correct horse", vault.Settings, out _));
    }

    [Fact]
    public async Task Unlock_SucceedsWithTheCorrectPassword()
    {
        MasterPasswordViewModel gate = Create(ConfiguredSettings("correct horse"));
        gate.Password = "correct horse";

        await gate.SubmitCommand.ExecuteAsync(null);

        Assert.True(gate.Completion.IsCompleted);
        Assert.NotNull(await gate.Completion);
        Assert.False(gate.DiscardedPreviousVault);
    }

    [Fact]
    public async Task Unlock_ReportsAWrongPasswordAndOffersAReset()
    {
        MasterPasswordViewModel gate = Create(ConfiguredSettings("correct horse"));
        gate.Password = "battery staple";

        await gate.SubmitCommand.ExecuteAsync(null);

        Assert.Equal("Incorrect master password.", gate.ErrorMessage);
        Assert.True(gate.CanReset);
        Assert.Empty(gate.Password);
        Assert.False(gate.Completion.IsCompleted);
    }

    [Fact]
    public async Task Unlock_AllowsRetryingAfterAWrongPassword()
    {
        MasterPasswordViewModel gate = Create(ConfiguredSettings("correct horse"));

        gate.Password = "battery staple";
        await gate.SubmitCommand.ExecuteAsync(null);

        gate.Password = "correct horse";
        await gate.SubmitCommand.ExecuteAsync(null);

        Assert.NotNull(await gate.Completion);
    }

    [Fact]
    public async Task Unlock_FallsBackToCreateModeWhenTheVaultDefinitionIsUnreadable()
    {
        AppSettings broken = new()
        {
            MasterPassword = ConfiguredSettings("correct horse").MasterPassword with { Salt = "not-base64!" },
        };

        MasterPasswordViewModel gate = Create(broken);
        gate.Password = "correct horse";

        await gate.SubmitCommand.ExecuteAsync(null);

        Assert.True(gate.IsCreating);
        Assert.True(gate.DiscardedPreviousVault);
        Assert.False(gate.Completion.IsCompleted);
    }

    [Fact]
    public void ResetVault_SwitchesToCreateModeAndFlagsTheOldSitesForRemoval()
    {
        MasterPasswordViewModel gate = Create(ConfiguredSettings("correct horse"));

        gate.ResetVaultCommand.Execute(null);

        Assert.True(gate.IsCreating);
        Assert.True(gate.DiscardedPreviousVault);
        Assert.Empty(gate.Password);
    }

    [Fact]
    public async Task ResetVault_ThenCreate_ProducesANewUsableVault()
    {
        MasterPasswordViewModel gate = Create(ConfiguredSettings("forgotten"));
        gate.ResetVaultCommand.Execute(null);

        gate.Password = "a-brand-new-password";
        gate.ConfirmPassword = "a-brand-new-password";
        await gate.SubmitCommand.ExecuteAsync(null);

        MasterPasswordVault.UnlockedVault? vault = await gate.Completion;

        Assert.NotNull(vault);
        Assert.True(gate.DiscardedPreviousVault);
        Assert.Null(MasterPasswordVault.TryUnlock("forgotten", vault!.Settings, out _));
    }

    [Fact]
    public async Task Cancel_CompletesWithNullSoStartupCanShutDown()
    {
        MasterPasswordViewModel gate = Create(ConfiguredSettings("correct horse"));

        gate.CancelCommand.Execute(null);

        Assert.Null(await gate.Completion);
    }

    [Fact]
    public void HangulInput_IsRejectedAndReported()
    {
        MasterPasswordViewModel gate = Create(new AppSettings());

        gate.Password = "비밀번호";

        Assert.Empty(gate.Password);
        Assert.Equal(MasterPasswordViewModel.NonAsciiRejectedMessage, gate.ErrorMessage);
    }

    [Fact]
    public void MixedInput_KeepsOnlyTheAsciiCharacters()
    {
        MasterPasswordViewModel gate = Create(new AppSettings());

        gate.Password = "pass비밀word123";

        Assert.Equal("password123", gate.Password);
    }

    [Theory]
    [InlineData("correct horse battery staple")]
    [InlineData("P@ssw0rd!#$%^&*()")]
    [InlineData("abcXYZ0189~`{}[]|\\:;\"'<>,.?/")]
    public void PrintableAsciiPasswords_PassThroughUnchanged(string password)
    {
        MasterPasswordViewModel gate = Create(new AppSettings());

        gate.Password = password;

        Assert.Equal(password, gate.Password);
        Assert.Empty(gate.ErrorMessage);
    }

    [Fact]
    public void ConfirmationField_IsFilteredTheSameWay()
    {
        MasterPasswordViewModel gate = Create(new AppSettings());

        gate.ConfirmPassword = "테스트pw";

        Assert.Equal("pw", gate.ConfirmPassword);
        Assert.Equal(MasterPasswordViewModel.NonAsciiRejectedMessage, gate.ErrorMessage);
    }

    [Fact]
    public async Task AVaultCreatedThroughTheFilteredFields_UnlocksWithTheSameTypedText()
    {
        MasterPasswordViewModel gate = Create(new AppSettings());

        // What the user typed with an IME active, and what should actually be stored.
        gate.Password = "secret비밀123";
        gate.ConfirmPassword = "secret비밀123";
        await gate.SubmitCommand.ExecuteAsync(null);

        MasterPasswordVault.UnlockedVault? vault = await gate.Completion;

        Assert.NotNull(vault);
        Assert.NotNull(MasterPasswordVault.TryUnlock("secret123", vault!.Settings, out _));
    }

    [Fact]
    public async Task TypingAgain_ClearsThePreviousErrorMessage()
    {
        MasterPasswordViewModel gate = Create(ConfiguredSettings("correct horse"));
        gate.Password = "wrong";
        await gate.SubmitCommand.ExecuteAsync(null);
        Assert.NotEmpty(gate.ErrorMessage);

        gate.Password = "c";

        Assert.Empty(gate.ErrorMessage);
    }
}
