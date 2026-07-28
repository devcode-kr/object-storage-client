using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Microsoft.Extensions.DependencyInjection;
using ObjectStorageClient.App.Services;
using ObjectStorageClient.App.ViewModels;
using ObjectStorageClient.App.Views;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Profiles;
using ObjectStorageClient.Core.Storage;
using ObjectStorageClient.Core.Transfers;

namespace ObjectStorageClient.App;

public partial class App : Application
{
    /// <summary>Composition root. Available to views that must resolve a dialog view model.</summary>
    public static IServiceProvider? Services { get; private set; }

    public override void Initialize() => AvaloniaXamlLoader.Load(this);

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            ServiceCollection services = new();
            ConfigureServices(services);
            ServiceProvider provider = services.BuildServiceProvider();
            Services = provider;

            MainWindowViewModel viewModel = provider.GetRequiredService<MainWindowViewModel>();
            desktop.MainWindow = new MainWindow { DataContext = viewModel };

            // Tear the transfer queue and the live connection down before the process exits.
            desktop.ShutdownRequested += async (_, _) =>
            {
                await viewModel.DisposeAsync().ConfigureAwait(false);
                await provider.DisposeAsync().ConfigureAwait(false);
            };
        }

        base.OnFrameworkInitializationCompleted();
    }

    private static void ConfigureServices(IServiceCollection services)
    {
        services.AddSingleton<ISecretProtector>(_ => new AesGcmSecretProtector());
        services.AddSingleton<IConnectionProfileStore>(provider =>
            new JsonConnectionProfileStore(provider.GetRequiredService<ISecretProtector>()));

        services.AddSingleton<IObjectStorageClientFactory, S3ObjectStorageClientFactory>();
        services.AddSingleton<ITransferQueue>(_ => new TransferQueue());

        services.AddSingleton<LogViewModel>();
        services.AddSingleton<IDialogService, DialogService>();
        services.AddSingleton<MainWindowViewModel>();

        // Transient: the Site Manager gets a fresh editor every time it is opened.
        services.AddTransient<SiteManagerViewModel>();
    }
}
