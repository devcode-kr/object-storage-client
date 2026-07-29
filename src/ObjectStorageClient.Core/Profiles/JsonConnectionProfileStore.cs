using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Serialization;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Models;

namespace ObjectStorageClient.Core.Profiles;

/// <summary>
/// Saved sites persisted as JSON in the per-user config directory.
/// Secrets are written through <see cref="ISecretProtector"/> and never appear in plaintext on disk.
/// </summary>
public sealed class JsonConnectionProfileStore : IConnectionProfileStore
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        WriteIndented = true,
        // Must not be WhenWritingDefault: that omits `false` and `0`, while several profile
        // properties initialise to `true`/non-zero. An omitted property falls back to the
        // initialiser on load, so writing ForcePathStyle=false would silently reload as true.
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };

    private readonly ISecretProtector _protector;
    private readonly string _filePath;
    private readonly SemaphoreSlim _fileLock = new(1, 1);

    public JsonConnectionProfileStore(ISecretProtector protector, string? filePath = null)
    {
        _protector = protector;
        _filePath = filePath ?? AppPaths.ProfilesFile;
    }

    public async Task<IReadOnlyList<ConnectionProfile>> LoadAsync(CancellationToken cancellationToken = default)
    {
        await _fileLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            return await LoadUnsynchronizedAsync(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _fileLock.Release();
        }
    }

    public async Task SaveAsync(ConnectionProfile profile, CancellationToken cancellationToken = default)
    {
        await _fileLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            List<ConnectionProfile> profiles = [.. await LoadUnsynchronizedAsync(cancellationToken).ConfigureAwait(false)];
            int index = profiles.FindIndex(existing => existing.Id == profile.Id);

            if (index >= 0)
            {
                profiles[index] = profile;
            }
            else
            {
                profiles.Add(profile);
            }

            await WriteAsync(profiles, cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _fileLock.Release();
        }
    }

    public async Task DeleteAsync(Guid id, CancellationToken cancellationToken = default)
    {
        await _fileLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            List<ConnectionProfile> profiles = [.. await LoadUnsynchronizedAsync(cancellationToken).ConfigureAwait(false)];
            if (profiles.RemoveAll(profile => profile.Id == id) > 0)
            {
                await WriteAsync(profiles, cancellationToken).ConfigureAwait(false);
            }
        }
        finally
        {
            _fileLock.Release();
        }
    }

    private async Task<IReadOnlyList<ConnectionProfile>> LoadUnsynchronizedAsync(CancellationToken cancellationToken)
    {
        if (!File.Exists(_filePath))
        {
            return [];
        }

        // ConfigureAwait(false) on the disposal too: `await using` alone captures the caller's
        // SynchronizationContext, which deadlocks anyone blocking on this from a UI thread.
        FileStream stream = File.OpenRead(_filePath);
        await using ConfiguredAsyncDisposable _ = stream.ConfigureAwait(false);

        ProfileDocument? document;

        try
        {
            document = await JsonSerializer
                .DeserializeAsync<ProfileDocument>(stream, SerializerOptions, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (JsonException)
        {
            // A corrupted file must not prevent the app from starting.
            return [];
        }

        if (document?.Sites is null)
        {
            return [];
        }

        return [.. document.Sites.Select(Decrypt)];
    }

    private async Task WriteAsync(IReadOnlyList<ConnectionProfile> profiles, CancellationToken cancellationToken)
    {
        AppPaths.EnsureConfigDirectory();

        ProfileDocument document = new()
        {
            Version = 1,
            Sites = [.. profiles.Select(Encrypt)],
        };

        // Write-then-replace so an interrupted save cannot truncate the existing site list.
        string temporaryPath = _filePath + ".tmp";

        FileStream stream = AppPaths.CreateOwnerOnlyFile(temporaryPath);
        await using (stream.ConfigureAwait(false))
        {
            await JsonSerializer.SerializeAsync(stream, document, SerializerOptions, cancellationToken)
                .ConfigureAwait(false);
        }

        File.Move(temporaryPath, _filePath, overwrite: true);
    }

    private StoredProfile Encrypt(ConnectionProfile profile) => new()
    {
        Profile = profile.WithoutSecrets(),
        SecretAccessKey = _protector.Protect(profile.SecretAccessKey),
        SessionToken = _protector.Protect(profile.SessionToken),
        ProxyPassword = _protector.Protect(profile.Proxy.Password),
    };

    private ConnectionProfile Decrypt(StoredProfile stored) => stored.Profile with
    {
        SecretAccessKey = _protector.Unprotect(stored.SecretAccessKey),
        SessionToken = _protector.Unprotect(stored.SessionToken),
        Proxy = stored.Profile.Proxy with { Password = _protector.Unprotect(stored.ProxyPassword) },
    };

    private sealed record ProfileDocument
    {
        public int Version { get; init; } = 1;

        public IReadOnlyList<StoredProfile> Sites { get; init; } = [];
    }

    /// <summary>On-disk shape: the profile minus secrets, plus the encrypted secret blobs.</summary>
    private sealed record StoredProfile
    {
        public ConnectionProfile Profile { get; init; } = new();

        public string SecretAccessKey { get; init; } = string.Empty;

        public string SessionToken { get; init; } = string.Empty;

        public string ProxyPassword { get; init; } = string.Empty;
    }
}
