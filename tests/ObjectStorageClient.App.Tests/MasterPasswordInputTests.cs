using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Headless.XUnit;
using ObjectStorageClient.App.ViewModels;
using ObjectStorageClient.App.Views;
using ObjectStorageClient.Core.Models;
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
    private static (MasterPasswordWindow Window, MasterPasswordViewModel ViewModel, TextBox Box) Open()
    {
        MasterPasswordViewModel viewModel = new(new AppSettings(), "/tmp/config");
        MasterPasswordWindow window = new() { DataContext = viewModel };

        window.Show();

        TextBox box = window.GetControl<TextBox>("PasswordBox");
        box.Focus();

        return (window, viewModel, box);
    }

    [AvaloniaFact]
    public void HangulTextInput_NeverReachesTheBoxOrTheViewModel()
    {
        (MasterPasswordWindow window, MasterPasswordViewModel viewModel, TextBox box) = Open();

        window.KeyTextInput("비밀번호");

        Assert.True(string.IsNullOrEmpty(box.Text), $"box contained '{box.Text}'");
        Assert.Empty(viewModel.Password);
    }

    [AvaloniaFact]
    public void AsciiTextInput_IsAccepted()
    {
        (MasterPasswordWindow window, MasterPasswordViewModel viewModel, TextBox box) = Open();

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
    [AvaloniaFact]
    public void TheWarningTextBlock_BecomesVisibleWithTheMessage()
    {
        (MasterPasswordWindow window, _, _) = Open();
        TextBlock warning = window.GetControl<TextBlock>("ErrorText");

        Assert.False(warning.IsVisible);

        window.KeyTextInput("비밀번호");

        Assert.True(warning.IsVisible);
        Assert.Equal(MasterPasswordViewModel.NonAsciiRejectedMessage, warning.Text);
    }

    [AvaloniaFact]
    public void TheWarningTextBlock_HidesAgainOnValidInput()
    {
        (MasterPasswordWindow window, _, _) = Open();
        TextBlock warning = window.GetControl<TextBlock>("ErrorText");

        window.KeyTextInput("비밀");
        Assert.True(warning.IsVisible);

        window.KeyTextInput("a");

        Assert.False(warning.IsVisible);
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
