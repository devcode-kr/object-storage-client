using ObjectStorageClient.Core.Models;

namespace ObjectStorageClient.Core.Abstractions;

/// <summary>Persistence for saved sites (the Site Manager list).</summary>
public interface IConnectionProfileStore
{
    Task<IReadOnlyList<ConnectionProfile>> LoadAsync(CancellationToken cancellationToken = default);

    /// <summary>Inserts or replaces a profile, matching on <see cref="ConnectionProfile.Id"/>.</summary>
    Task SaveAsync(ConnectionProfile profile, CancellationToken cancellationToken = default);

    Task DeleteAsync(Guid id, CancellationToken cancellationToken = default);
}

/// <summary>Persistence for application settings (<c>config.json</c>).</summary>
public interface IAppSettingsStore
{
    /// <summary>Returns defaults when the file is missing or unreadable, never throws for those cases.</summary>
    Task<AppSettings> LoadAsync(CancellationToken cancellationToken = default);

    Task SaveAsync(AppSettings settings, CancellationToken cancellationToken = default);
}

/// <summary>
/// Encrypts credentials at rest. The default implementation derives its AES-GCM key from the
/// master password; an OS keychain implementation can be substituted without touching the store.
/// </summary>
public interface ISecretProtector
{
    /// <summary>Returns an opaque, storable representation of <paramref name="plaintext"/>.</summary>
    string Protect(string plaintext);

    /// <summary>Reverses <see cref="Protect"/>. Returns an empty string if the value cannot be read.</summary>
    string Unprotect(string protectedValue);
}
