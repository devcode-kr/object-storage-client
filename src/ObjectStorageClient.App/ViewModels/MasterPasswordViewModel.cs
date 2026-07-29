using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Profiles;

namespace ObjectStorageClient.App.ViewModels;

/// <summary>
/// The startup gate. Runs in one of two modes: creating the vault on first run, or unlocking
/// it on every run after that. Completes with the unlocked vault, or <c>null</c> if the user
/// backs out — in which case the app shuts down rather than running without its credentials.
/// </summary>
public sealed partial class MasterPasswordViewModel : ViewModelBase
{
    private readonly TaskCompletionSource<MasterPasswordVault.UnlockedVault?> _completion =
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    private MasterPasswordSettings _settings;

    public MasterPasswordViewModel(AppSettings settings, string configDirectory)
    {
        _settings = settings.MasterPassword;
        ConfigDirectory = configDirectory;
        IsCreating = !MasterPasswordVault.IsUsable(_settings);
    }

    /// <summary>Resolves once the user unlocks, creates, or cancels.</summary>
    public Task<MasterPasswordVault.UnlockedVault?> Completion => _completion.Task;

    /// <summary>Raised when the window should close.</summary>
    public event EventHandler? CloseRequested;

    /// <summary>True on first run: the user is choosing a password rather than entering one.</summary>
    public bool IsCreating { get; private set; }

    public bool IsUnlocking => !IsCreating;

    public string ConfigDirectory { get; }

    /// <summary>
    /// True when the previous vault was abandoned, either because the user reset it or because
    /// its definition was unreadable. The startup code clears <c>sites.json</c> in that case,
    /// since nothing in it can be decrypted with the new key.
    /// </summary>
    public bool DiscardedPreviousVault { get; private set; }

    public string Title => IsCreating ? "Set a master password" : "Unlock";

    public string Explanation => IsCreating
        ? "Your saved site credentials are encrypted with this password. It is never stored, "
        + "so it cannot be recovered — if you forget it, the saved credentials are lost."
        : "Enter the master password to decrypt your saved sites.";

    public string AcceptText => IsCreating ? "Create" : "Unlock";

    [ObservableProperty]
    private string _password = string.Empty;

    [ObservableProperty]
    private string _confirmPassword = string.Empty;

    [ObservableProperty]
    private string _errorMessage = string.Empty;

    [ObservableProperty]
    private bool _isBusy;

    /// <summary>Shown after a failed unlock, offering to discard the vault and start over.</summary>
    [ObservableProperty]
    private bool _canReset;

    /// <summary>Only printable ASCII is accepted in the master password.</summary>
    /// <remarks>
    /// Enforced in the view (see <c>MasterPasswordWindow</c>) because that is the only place that
    /// can stop the text before <c>TextBox</c> inserts it. This method is the shared rule both
    /// layers apply, and the backstop for anything that sets the property directly.
    /// </remarks>
    public const string NonAsciiRejectedMessage =
        "The master password accepts English letters, digits and symbols only.";

    internal static bool IsAllowed(char character) => character is >= ' ' and <= '~';

    internal static string RemoveDisallowed(string value) =>
        value.All(IsAllowed) ? value : new string([.. value.Where(IsAllowed)]);

    partial void OnPasswordChanged(string value)
    {
        string allowed = RemoveDisallowed(value);

        if (!string.Equals(allowed, value, StringComparison.Ordinal))
        {
            // Re-assigning re-enters this method, which clears ErrorMessage — so report afterwards.
            Password = allowed;
            ErrorMessage = NonAsciiRejectedMessage;
            return;
        }

        ErrorMessage = string.Empty;
    }

    partial void OnConfirmPasswordChanged(string value)
    {
        string allowed = RemoveDisallowed(value);

        if (!string.Equals(allowed, value, StringComparison.Ordinal))
        {
            ConfirmPassword = allowed;
            ErrorMessage = NonAsciiRejectedMessage;
        }
    }

    [RelayCommand]
    private async Task SubmitAsync()
    {
        if (IsBusy)
        {
            return;
        }

        if (string.IsNullOrEmpty(Password))
        {
            ErrorMessage = "Enter a password.";
            return;
        }

        IsBusy = true;

        try
        {
            if (IsCreating)
            {
                await CreateAsync().ConfigureAwait(true);
            }
            else
            {
                await UnlockAsync().ConfigureAwait(true);
            }
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task CreateAsync()
    {
        if (Password.Length < 8)
        {
            ErrorMessage = "Use at least 8 characters.";
            return;
        }

        if (!string.Equals(Password, ConfirmPassword, StringComparison.Ordinal))
        {
            ErrorMessage = "The two passwords do not match.";
            return;
        }

        // Key derivation is deliberately slow; keep it off the UI thread.
        string password = Password;
        MasterPasswordVault.UnlockedVault vault =
            await Task.Run(() => MasterPasswordVault.Create(password)).ConfigureAwait(true);

        Complete(vault);
    }

    private async Task UnlockAsync()
    {
        string password = Password;
        MasterPasswordSettings settings = _settings;

        (MasterPasswordVault.UnlockedVault? vault, bool isUsable) = await Task.Run(() =>
        {
            MasterPasswordVault.UnlockedVault? result = MasterPasswordVault.TryUnlock(password, settings, out bool usable);
            return (result, usable);
        }).ConfigureAwait(true);

        if (!isUsable)
        {
            // config.json lost or corrupted its vault definition: fall back to creating a new one.
            SwitchToCreateMode("The stored password settings are unreadable. Set a new master password.");
            return;
        }

        if (vault is null)
        {
            // Clear the box first: OnPasswordChanged resets ErrorMessage, so assigning the
            // message before emptying the field would wipe it before the user sees it.
            Password = string.Empty;
            ErrorMessage = "Incorrect master password.";
            CanReset = true;
            return;
        }

        Complete(vault);
    }

    /// <summary>
    /// Discards the vault so a forgotten password does not permanently lock the user out.
    /// The saved sites become undecryptable, so the caller also clears <c>sites.json</c>.
    /// </summary>
    [RelayCommand]
    private void ResetVault() =>
        SwitchToCreateMode("Saved sites will be discarded. Set a new master password.");

    [RelayCommand]
    private void Cancel()
    {
        _completion.TrySetResult(null);
        CloseRequested?.Invoke(this, EventArgs.Empty);
    }

    private void SwitchToCreateMode(string message)
    {
        DiscardedPreviousVault = true;
        _settings = MasterPasswordVault.Reset();
        IsCreating = true;
        CanReset = false;
        Password = string.Empty;
        ConfirmPassword = string.Empty;
        ErrorMessage = message;

        OnPropertyChanged(nameof(IsCreating));
        OnPropertyChanged(nameof(IsUnlocking));
        OnPropertyChanged(nameof(Title));
        OnPropertyChanged(nameof(Explanation));
        OnPropertyChanged(nameof(AcceptText));
    }

    private void Complete(MasterPasswordVault.UnlockedVault vault)
    {
        _completion.TrySetResult(vault);
        CloseRequested?.Invoke(this, EventArgs.Empty);
    }
}
