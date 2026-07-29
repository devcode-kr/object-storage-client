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

    /// <summary>Set while reading a pre-release file, so it gets rewritten once. TEMPORARY.</summary>
    private bool _readLegacyLayout;

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
            IReadOnlyList<ConnectionProfile> profiles = await ReadAsync(cancellationToken).ConfigureAwait(false);

            // The one write this store performs without being asked, and only ever once: a file in
            // the pre-release layout is converted the first time it is opened. Re-encrypting the
            // connection needs the master password, so it can only happen here, with the key to
            // hand. TEMPORARY — remove with the legacy records.
            if (_readLegacyLayout)
            {
                _readLegacyLayout = false;
                await WriteAsync(profiles, cancellationToken).ConfigureAwait(false);
            }

            return profiles;
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
        // Told apart by shape, not by version: the layout changed before anything shipped, so both
        // carry version 1. A legacy entry has `profile`; a current one has `connection`.
        if (IsLegacyLayout(root))
        {
            LegacySiteDocument? legacy = root.Deserialize<LegacySiteDocument>(SerializerOptions);
            if (legacy?.Sites is null)
            {
                return [];
            }

            DateTimeOffset migratedAt = DateTimeOffset.Now;
            List<ConnectionProfile> migrated = [];
            bool everySecretRecovered = true;

            foreach (LegacyStoredSite site in legacy.Sites)
            {
                migrated.Add(SiteMapper.ToProfile(site, _protector, migratedAt, out bool recovered));
                everySecretRecovered &= recovered;
            }

            // Only convert when the key actually opened the file. Rewriting after a failed
            // decrypt would re-encrypt the blanks and destroy the credentials for good.
            _readLegacyLayout = everySecretRecovered;
            return migrated;
        }

        SiteDocument? document = root.Deserialize<SiteDocument>(SerializerOptions);
        return document?.Sites is null
            ? []
            : [.. document.Sites.Select(site => SiteMapper.ToProfile(site, _protector))];
    }

    /// <summary>TEMPORARY: remove with the legacy records.</summary>
    private static bool IsLegacyLayout(JsonElement root) =>
        root.TryGetProperty("sites", out JsonElement sites)
        && sites.ValueKind == JsonValueKind.Array
        && sites.EnumerateArray().Any(site => site.TryGetProperty("profile", out _));

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
