using Avalonia;
using Avalonia.Headless;
using ObjectStorageClient.App;

[assembly: AvaloniaTestApplication(typeof(ObjectStorageClient.App.Tests.TestAppBuilder))]

namespace ObjectStorageClient.App.Tests;

/// <summary>
/// Hosts the real <see cref="App"/> on the headless backend, so <c>[AvaloniaFact]</c> tests get
/// the application's actual styles and control themes.
/// </summary>
/// <remarks>
/// <see cref="App.OnFrameworkInitializationCompleted"/> only runs the master-password startup
/// flow under a classic desktop lifetime, which the headless session does not install — so the
/// app stays inert here and tests can drive individual windows.
/// </remarks>
public static class TestAppBuilder
{
    public static AppBuilder BuildAvaloniaApp() => AppBuilder
        .Configure<App>()
        .UseHeadless(new AvaloniaHeadlessPlatformOptions());
}
