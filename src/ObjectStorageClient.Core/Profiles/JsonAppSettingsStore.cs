using System.Runtime.CompilerServices;
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
            return await ReadAsync(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _fileLock.Release();
        }
    }

    private async Task<AppSettings> ReadAsync(CancellationToken cancellationToken)
    {
        try
        {
            if (!File.Exists(_filePath))
            {
                return new AppSettings();
            }

            // ConfigureAwait(false) on the disposal too: `await using` alone captures the caller's
            // SynchronizationContext, which deadlocks anyone blocking on this from a UI thread.
            FileStream stream = File.OpenRead(_filePath);
            await using ConfiguredAsyncDisposable _ = stream.ConfigureAwait(false);

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

            FileStream stream = AppPaths.CreateOwnerOnlyFile(temporaryPath);
            await using (stream.ConfigureAwait(false))
            {
                await JsonSerializer.SerializeAsync(stream, settings, SerializerOptions, cancellationToken)
                    .ConfigureAwait(false);
            }

            File.Move(temporaryPath, _filePath, overwrite: true);

            // Read it back and compare: a save that reports success without the file actually
            // holding the new values is the failure mode worth catching here — it is how a
            // half-written temporary file, or a serializer that drops properties, goes unnoticed.
            AppSettings written = await ReadAsync(cancellationToken).ConfigureAwait(false);
            if (written != settings)
            {
                throw new IOException(
                    $"Settings were written to '{_filePath}' but did not read back identical.");
            }
        }
        finally
        {
            _fileLock.Release();
        }
    }
}
