using System.Text.Json;
using System.Text.Json.Serialization;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Models;

namespace ObjectStorageClient.Core.Profiles;

/// <summary>
/// Reads and writes <c>config.json</c>. Contains no secrets — only preferences and the
/// master-password key-derivation parameters.
/// </summary>
public sealed class JsonAppSettingsStore : IAppSettingsStore
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };

    private readonly string _filePath;
    private readonly SemaphoreSlim _fileLock = new(1, 1);

    public JsonAppSettingsStore(string? filePath = null) => _filePath = filePath ?? AppPaths.SettingsFile;

    public string FilePath => _filePath;

    public async Task<AppSettings> LoadAsync(CancellationToken cancellationToken = default)
    {
        await _fileLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (!File.Exists(_filePath))
            {
                return new AppSettings();
            }

            await using FileStream stream = File.OpenRead(_filePath);
            AppSettings? settings = await JsonSerializer
                .DeserializeAsync<AppSettings>(stream, SerializerOptions, cancellationToken)
                .ConfigureAwait(false);

            return settings ?? new AppSettings();
        }
        catch (JsonException)
        {
            // A corrupted settings file must not prevent startup. Defaults mean the user is
            // treated as a first-run: they are asked to create a master password again.
            return new AppSettings();
        }
        finally
        {
            _fileLock.Release();
        }
    }

    public async Task SaveAsync(AppSettings settings, CancellationToken cancellationToken = default)
    {
        await _fileLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            AppPaths.EnsureConfigDirectory();

            // Write-then-replace so an interrupted save cannot leave a half-written vault
            // definition, which would lock the user out of their own credentials.
            string temporaryPath = _filePath + ".tmp";

            await using (FileStream stream = File.Create(temporaryPath))
            {
                await JsonSerializer.SerializeAsync(stream, settings, SerializerOptions, cancellationToken)
                    .ConfigureAwait(false);
            }

            AppPaths.TryRestrictToOwner(temporaryPath, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            File.Move(temporaryPath, _filePath, overwrite: true);
        }
        finally
        {
            _fileLock.Release();
        }
    }
}
