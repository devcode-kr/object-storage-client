using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Microsoft.Extensions.DependencyInjection;
using ObjectStorageClient.App.Services;
using ObjectStorageClient.App.ViewModels;
using ObjectStorageClient.App.Views;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Profiles;
using ObjectStorageClient.Core.Storage;
using ObjectStorageClient.Core.Transfers;

namespace ObjectStorageClient.App;

public partial class App : Application
{
    /// <summary>Composition root. Available to views that must resolve a dialog view model.</summary>
    public static IServiceProvider? Services { get; private set; }

    /// <summary>Upper bound on shutdown work, so the window always closes.</summary>
    private static readonly TimeSpan ShutdownTimeout = TimeSpan.FromSeconds(10);

    public override void Initialize() => AvaloniaXamlLoader.Load(this);

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            // The master-password window is shown before MainWindow exists, so the app must not
            // treat "no main window" as a reason to exit while the user is still typing.
            desktop.ShutdownMode = ShutdownMode.OnExplicitShutdown;

            base.OnFrameworkInitializationCompleted();
            _ = StartAsync(desktop);
            return;
        }

        base.OnFrameworkInitializationCompleted();
    }

    /// <summary>
    /// Startup sequence: load <c>config.json</c>, take the master password, derive the key,
    /// and only then build the services that depend on it.
    /// </summary>
    private static async Task StartAsync(IClassicDesktopStyleApplicationLifetime desktop)
    {
        JsonAppSettingsStore settingsStore = new();
        AppSettings settings = await settingsStore.LoadAsync().ConfigureAwait(true);

        MasterPasswordViewModel gate = new(settings, AppPaths.ConfigDirectory);
        MasterPasswordWindow gateWindow = new() { DataContext = gate };
        gateWindow.Show();

        MasterPasswordVault.UnlockedVault? vault = await gate.Completion.ConfigureAwait(true);

        if (vault is null)
        {
            // The user quit at the password prompt; there is nothing to run without the key.
            desktop.Shutdown();
            return;
        }

        if (gate.DiscardedPreviousVault)
        {
            // The old sites.json is encrypted with a key nobody has any more.
            DiscardUnreadableProfiles();
        }

        settings = settings with { MasterPassword = vault.Settings };
        await settingsStore.SaveAsync(settings).ConfigureAwait(true);

        ServiceProvider provider = BuildServices(settingsStore, vault.Protector);
        Services = provider;

        MainWindowViewModel viewModel = provider.GetRequiredService<MainWindowViewModel>();
        await viewModel.ApplySettingsAsync(settings).ConfigureAwait(true);

        MainWindow window = new() { DataContext = viewModel };
        desktop.MainWindow = window;
        desktop.ShutdownMode = ShutdownMode.OnMainWindowClose;
        window.Show();

        // Nothing is persisted on exit: settings are only written when the user asks for it.
        // Shutdown just releases the connection and the transfer queue.
        desktop.ShutdownRequested += (_, _) =>
        {
            // Task.Run so the teardown runs without the UI thread's SynchronizationContext.
            // Awaiting it directly deadlocks: `await using` disposals do not carry
            // ConfigureAwait(false), so FileStream.DisposeAsync posts its continuation back to
            // the very thread this handler is blocking.
            if (!Task.Run(() => ShutdownAsync(provider)).Wait(ShutdownTimeout))
            {
                // Never wedge the app closed.
            }
        };
    }

    /// <summary>
    /// Tears down the connection and the transfer queue before the process exits.
    /// </summary>
    /// <remarks>
    /// <para>
    /// <c>ShutdownRequested</c> is a synchronous event, so an <c>async</c> handler returns at its
    /// first <c>await</c> and the runtime carries on tearing the process down with the work still
    /// in flight — which left a half-written <c>config.json.tmp</c> behind and lost the session's
    /// settings, because the file was written but never renamed.
    /// </para>
    /// <para>
    /// The caller must therefore block, but must not await this directly from the UI thread:
    /// <c>await using</c> disposals do not carry <c>ConfigureAwait(false)</c>, so
    /// <c>FileStream.DisposeAsync</c> posts its continuation back to the blocked thread and hangs
    /// the app. Running it through <c>Task.Run</c> clears the synchronization context, which fixes
    /// the whole class of problem rather than one await at a time.
    /// </para>
    /// </remarks>
    private static async Task ShutdownAsync(ServiceProvider provider) =>
        // Disposing the container is the whole teardown: it owns the view model, the transfer
        // queue and the rest, and disposes singletons in reverse registration order. Disposing
        // any of them here as well would dispose them twice.
        await provider.DisposeAsync().ConfigureAwait(false);

    private static ServiceProvider BuildServices(IAppSettingsStore settingsStore, ISecretProtector protector)
    {
        ServiceCollection services = new();

        services.AddSingleton(settingsStore);
        services.AddSingleton(protector);
        services.AddSingleton<IConnectionProfileStore>(provider =>
            new JsonConnectionProfileStore(provider.GetRequiredService<ISecretProtector>()));

        services.AddSingleton<IObjectStorageClientFactory, S3ObjectStorageClientFactory>();
        services.AddSingleton<ITransferQueue>(_ => new TransferQueue());

        services.AddSingleton<LogViewModel>();
        services.AddSingleton<IDialogService, DialogService>();
        services.AddSingleton<IClipboardService, ClipboardService>();
        services.AddSingleton<MainWindowViewModel>();

        // Transient: the Site Manager gets a fresh editor every time it is opened.
        services.AddTransient<SiteManagerViewModel>();

        return services.BuildServiceProvider();
    }

    private static void DiscardUnreadableProfiles()
    {
        try
        {
            if (File.Exists(AppPaths.ProfilesFile))
            {
                File.Delete(AppPaths.ProfilesFile);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // Leaving the file in place is harmless: its secrets simply decrypt to empty.
        }
    }
}
