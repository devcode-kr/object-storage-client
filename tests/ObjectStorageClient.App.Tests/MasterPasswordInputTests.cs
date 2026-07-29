using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Input;
using Avalonia.Headless.XUnit;
using ObjectStorageClient.App.ViewModels;
using ObjectStorageClient.App.Views;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Profiles;
using Xunit;

namespace ObjectStorageClient.App.Tests;

/// <summary>
/// Drives the real window through Avalonia's input pipeline, because the question here — does a
/// non-ASCII character actually reach the password box — cannot be answered by testing the view
/// model alone. <c>InputMethod.IsInputMethodEnabled</c> is ignored by the macOS backend, so the
/// <c>TextInput</c> handler is what has to hold.
/// </summary>
public sealed class MasterPasswordInputTests
{
    /// <summary>
    /// Both startup dialogs are the same window in different modes: "Set a master password" on
    /// first run, "Unlock" on every run after. Anything input-related must hold in both, so the
    /// core cases are run against each.
    /// </summary>
    public static TheoryData<bool> BothModes => new() { false, true };

    private static (MasterPasswordWindow Window, MasterPasswordViewModel ViewModel, TextBox Box) Open(
        bool unlocking = false)
    {
        AppSettings settings = unlocking
            ? new AppSettings { MasterPassword = MasterPasswordVault.Create("existing-pw", 1_000).Settings }
            : new AppSettings();

        MasterPasswordViewModel viewModel = new(settings, "/tmp/config");
        MasterPasswordWindow window = new() { DataContext = viewModel };

        window.Show();

        // Guard the fixture itself: a mode mix-up would quietly make the theory test one mode twice.
        Assert.Equal(unlocking, viewModel.IsUnlocking);

        TextBox box = window.GetControl<TextBox>("PasswordBox");
        box.Focus();

        return (window, viewModel, box);
    }

    [AvaloniaTheory]
    [MemberData(nameof(BothModes))]
    public void HangulTextInput_NeverReachesTheBoxOrTheViewModel(bool unlocking)
    {
        (MasterPasswordWindow window, MasterPasswordViewModel viewModel, TextBox box) = Open(unlocking);

        window.KeyTextInput("비밀번호");

        Assert.True(string.IsNullOrEmpty(box.Text), $"box contained '{box.Text}'");
        Assert.Empty(viewModel.Password);
    }

    [AvaloniaTheory]
    [MemberData(nameof(BothModes))]
    public void AsciiTextInput_IsAccepted(bool unlocking)
    {
        (MasterPasswordWindow window, MasterPasswordViewModel viewModel, TextBox box) = Open(unlocking);

        window.KeyTextInput("Passw0rd!");

        Assert.Equal("Passw0rd!", box.Text);
        Assert.Equal("Passw0rd!", viewModel.Password);
    }

    [AvaloniaFact]
    public void AsciiTypedAroundHangul_KeepsOnlyTheAscii()
    {
        (MasterPasswordWindow window, MasterPasswordViewModel viewModel, TextBox box) = Open();

        window.KeyTextInput("pass");
        window.KeyTextInput("비밀");
        window.KeyTextInput("word");

        Assert.Equal("password", box.Text);
        Assert.Equal("password", viewModel.Password);
    }

    [AvaloniaFact]
    public void AMixedCommit_IsRejectedWholesaleRatherThanPartially()
    {
        (MasterPasswordWindow window, MasterPasswordViewModel viewModel, TextBox box) = Open();

        // An IME commits its composition in one go; a chunk containing Hangul is dropped whole.
        window.KeyTextInput("ab비밀cd");

        Assert.True(string.IsNullOrEmpty(box.Text), $"box contained '{box.Text}'");
        Assert.Empty(viewModel.Password);
    }

    /// <summary>
    /// Pasting never raises <c>TextInput</c>; it puts the text straight into the box, which is
    /// what the <c>TextChanged</c> correction is there to catch.
    /// </summary>
    [AvaloniaFact]
    public void TextArrivingWithoutATextInputEvent_IsStrippedFromTheBox()
    {
        (_, MasterPasswordViewModel viewModel, TextBox box) = Open();

        box.Text = "pa비밀ss";

        Assert.Equal("pass", box.Text);
        Assert.Equal("pass", viewModel.Password);
    }

    [AvaloniaFact]
    public void WhatTheBoxShows_AlwaysMatchesThePasswordThatWillBeUsed()
    {
        (MasterPasswordWindow window, MasterPasswordViewModel viewModel, TextBox box) = Open();

        window.KeyTextInput("abc");
        box.Text += "한글";
        window.KeyTextInput("123");

        // A mismatch here would mean the user sets a different password than the one displayed.
        Assert.Equal(box.Text, viewModel.Password);
        Assert.Equal("abc123", viewModel.Password);
    }

    /// <summary>
    /// The view blocks the characters before they reach the bound property, so the warning has
    /// to be raised explicitly — otherwise the user's typing just silently disappears.
    /// </summary>
    [AvaloniaFact]
    public void RejectedTyping_TellsTheUserWhyNothingAppeared()
    {
        (MasterPasswordWindow window, MasterPasswordViewModel viewModel, _) = Open();

        window.KeyTextInput("비밀번호");

        Assert.Equal(MasterPasswordViewModel.NonAsciiRejectedMessage, viewModel.ErrorMessage);
    }

    /// <summary>
    /// Asserts what the user actually sees, not just the view-model state: the red warning
    /// TextBlock has to become visible and carry the message.
    /// </summary>
    [AvaloniaTheory]
    [MemberData(nameof(BothModes))]
    public void TheWarningTextBlock_ShowsTheMessage(bool unlocking)
    {
        (MasterPasswordWindow window, _, _) = Open(unlocking);
        TextBlock warning = window.GetControl<TextBlock>("ErrorText");

        Assert.True(string.IsNullOrEmpty(warning.Text));

        window.KeyTextInput("비밀번호");

        Assert.Equal(MasterPasswordViewModel.NonAsciiRejectedMessage, warning.Text);
        Assert.True(warning.IsVisible);
    }

    /// <summary>
    /// The warning slot is reserved rather than collapsed, so showing a message must not change
    /// the window's height: macOS does not re-apply SizeToContent once the window is shown, and a
    /// window that cannot resize would simply clip the extra content.
    /// </summary>
    [AvaloniaFact]
    public void ShowingTheWarning_DoesNotChangeTheWindowHeight()
    {
        (MasterPasswordWindow window, _, _) = Open();
        window.UpdateLayout();
        double before = window.Bounds.Height;

        window.KeyTextInput("비밀번호");
        window.UpdateLayout();

        Assert.Equal(before, window.Bounds.Height);
    }

    /// <summary>
    /// The confirmation field only exists on first run, but it must be filtered too — otherwise
    /// a vault could be created from a confirmation the user never actually matched.
    /// </summary>
    [AvaloniaFact]
    public void TheConfirmationField_IsFilteredAsWell()
    {
        (MasterPasswordWindow window, MasterPasswordViewModel viewModel, _) = Open();
        TextBox password = window.GetControl<TextBox>("PasswordBox");
        TextBox confirm = window.GetControl<TextBox>("ConfirmPasswordBox");

        // Tab across the way a user would: calling Focus() alone does not move the headless
        // input root's keyboard focus, so the text would still land in the password box.
        window.KeyPressQwerty(PhysicalKey.Tab, RawInputModifiers.None);

        // Typing, then an IME committing its composition: two separate input events.
        window.KeyTextInput("pw");
        window.KeyTextInput("비밀");

        Assert.True(
            confirm.Text == "pw",
            $"confirm='{confirm.Text}' password='{password.Text}'");
        Assert.Equal("pw", viewModel.ConfirmPassword);
        Assert.Empty(viewModel.Password);
    }

    [AvaloniaFact]
    public void TheConfirmationField_StripsPastedText()
    {
        (MasterPasswordWindow window, MasterPasswordViewModel viewModel, _) = Open();
        TextBox confirm = window.GetControl<TextBox>("ConfirmPasswordBox");

        confirm.Text = "pw비밀";

        Assert.Equal("pw", confirm.Text);
        Assert.Equal("pw", viewModel.ConfirmPassword);
    }

    [AvaloniaFact]
    public void TheWarningTextBlock_ClearsAgainOnValidInput()
    {
        (MasterPasswordWindow window, _, _) = Open();
        TextBlock warning = window.GetControl<TextBlock>("ErrorText");

        window.KeyTextInput("비밀");
        Assert.NotEmpty(warning.Text!);

        window.KeyTextInput("a");

        Assert.True(string.IsNullOrEmpty(warning.Text));
    }

    /// <summary>
    /// A real IME does not deliver one tidy commit: it churns the box while composing, and each
    /// of those changes flows through the binding. The warning has to survive that, otherwise it
    /// is set and wiped again before the user can read it.
    /// </summary>
    [AvaloniaFact]
    public void TheWarning_SurvivesAFollowUpTextChange()
    {
        (MasterPasswordWindow window, MasterPasswordViewModel viewModel, TextBox box) = Open();

        window.KeyTextInput("비밀");
        Assert.NotEmpty(viewModel.ErrorMessage);

        box.Text = string.Empty;

        Assert.Equal(MasterPasswordViewModel.NonAsciiRejectedMessage, viewModel.ErrorMessage);
    }

    [AvaloniaFact]
    public void RejectedPaste_AlsoWarns()
    {
        (_, MasterPasswordViewModel viewModel, TextBox box) = Open();

        box.Text = "pa비밀ss";

        Assert.Equal(MasterPasswordViewModel.NonAsciiRejectedMessage, viewModel.ErrorMessage);
    }

    [AvaloniaFact]
    public void TypingSomethingValidAfterwards_ClearsTheWarning()
    {
        (MasterPasswordWindow window, MasterPasswordViewModel viewModel, _) = Open();

        window.KeyTextInput("비밀");
        Assert.NotEmpty(viewModel.ErrorMessage);

        window.KeyTextInput("a");

        Assert.Empty(viewModel.ErrorMessage);
    }

    [AvaloniaFact]
    public void ValidTyping_NeverWarns()
    {
        (MasterPasswordWindow window, MasterPasswordViewModel viewModel, _) = Open();

        window.KeyTextInput("Passw0rd!");

        Assert.Empty(viewModel.ErrorMessage);
    }

    [AvaloniaFact]
    public void TheInputMethodIsAlsoTurnedOffForPlatformsThatHonourIt()
    {
        (_, _, TextBox box) = Open();

        Assert.False(Avalonia.Input.InputMethod.GetIsInputMethodEnabled(box));
    }
}
