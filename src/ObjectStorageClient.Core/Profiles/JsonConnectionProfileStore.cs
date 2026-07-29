using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Serialization;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Persistence;

namespace ObjectStorageClient.Core.Profiles;

/// <summary>
/// Saved sites persisted as JSON in the per-user config directory.
/// </summary>
/// <remarks>
/// The file layout is <see cref="SiteDocument"/>, kept separate from
/// <see cref="ConnectionProfile"/> and reached only through <see cref="SiteMapper"/>. Everything
/// describing how to reach an endpoint — URL, region, credentials, bucket, proxy — is encrypted
/// together as one blob, so nothing sensitive can appear in the clear by being added to the model.
/// </remarks>
public sealed class JsonConnectionProfileStore : IConnectionProfileStore
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        WriteIndented = true,
        // Not WhenWritingDefault: that omits `false` and `0`, and several settings default to
        // `true`/non-zero, so an omitted property would reload as the opposite of what was saved.
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
            return await ReadAsync(cancellationToken).ConfigureAwait(false);
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
            List<ConnectionProfile> profiles = [.. await ReadAsync(cancellationToken).ConfigureAwait(false)];
            int index = profiles.FindIndex(existing => existing.Id == profile.Id);

            // The store owns the timestamps: created once, modified on every save.
            DateTimeOffset now = DateTimeOffset.Now;
            ConnectionProfile stamped = profile with
            {
                CreatedAt = index >= 0 ? profiles[index].CreatedAt : now,
                LastModifiedAt = now,
            };

            if (index >= 0)
            {
                profiles[index] = stamped;
            }
            else
            {
                profiles.Add(stamped);
            }

            await WriteAsync(profiles, cancellationToken).ConfigureAwait(false);

            // Read it back and compare, secrets included. This is what catches a save that
            // reports success without the file actually holding the new values.
            IReadOnlyList<ConnectionProfile> written = await ReadAsync(cancellationToken).ConfigureAwait(false);

            if (written.FirstOrDefault(saved => saved.Id == stamped.Id) != stamped)
            {
                throw new IOException(
                    $"Site '{stamped.Name}' was written to '{_filePath}' but did not read back identical.");
            }
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
            List<ConnectionProfile> profiles = [.. await ReadAsync(cancellationToken).ConfigureAwait(false)];
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

    private async Task<IReadOnlyList<ConnectionProfile>> ReadAsync(CancellationToken cancellationToken)
    {
        if (!File.Exists(_filePath))
        {
            return [];
        }

        try
        {
            // ConfigureAwait(false) on the disposal too: `await using` alone captures the caller's
            // SynchronizationContext, which deadlocks anyone blocking on this from a UI thread.
            FileStream stream = File.OpenRead(_filePath);
            await using ConfiguredAsyncDisposable _ = stream.ConfigureAwait(false);

            using JsonDocument document = await JsonDocument
                .ParseAsync(stream, cancellationToken: cancellationToken)
                .ConfigureAwait(false);

            return ReadDocument(document.RootElement);
        }
        catch (JsonException)
        {
            // A corrupted file must not prevent the app from starting.
            return [];
        }
    }

    private IReadOnlyList<ConnectionProfile> ReadDocument(JsonElement root)
    {
        int version = root.TryGetProperty("version", out JsonElement versionElement)
            && versionElement.TryGetInt32(out int parsed)
                ? parsed
                : SiteDocument.Version1;

        if (version >= SiteDocument.CurrentVersion)
        {
            SiteDocument? document = root.Deserialize<SiteDocument>(SerializerOptions);
            return document?.Sites is null
                ? []
                : [.. document.Sites.Select(site => SiteMapper.ToProfile(site, _protector))];
        }

        // Version 1 is rewritten in the current layout the next time the site is saved.
        LegacySiteDocument? legacy = root.Deserialize<LegacySiteDocument>(SerializerOptions);
        if (legacy?.Sites is null)
        {
            return [];
        }

        DateTimeOffset migratedAt = DateTimeOffset.Now;
        return [.. legacy.Sites.Select(site => SiteMapper.ToProfile(site, _protector, migratedAt))];
    }

    private async Task WriteAsync(IReadOnlyList<ConnectionProfile> profiles, CancellationToken cancellationToken)
    {
        AppPaths.EnsureConfigDirectory();

        SiteDocument document = new()
        {
            Sites = [.. profiles.Select(profile => SiteMapper.ToStored(profile, _protector))],
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
}
