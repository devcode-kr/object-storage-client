namespace ObjectStorageClient.Core.Models;

/// <summary>
/// Key-derivation parameters for the master password, persisted in <c>config.json</c>.
/// </summary>
/// <remarks>
/// None of these values are secret — they are the salt, the cost factor, and a verifier blob
/// used to tell a correct password from a wrong one. The master password itself is never
/// written anywhere, so losing it means losing the stored credentials.
/// </remarks>
public sealed record MasterPasswordSettings
{
    /// <summary>True once a master password has been set up on this machine.</summary>
    public bool IsConfigured { get; init; }

    /// <summary>Base64 PBKDF2 salt.</summary>
    public string Salt { get; init; } = string.Empty;

    /// <summary>PBKDF2 iteration count, recorded so the cost can be raised for new vaults.</summary>
    public int Iterations { get; init; }

    /// <summary>A known token encrypted with the derived key; decrypting it proves the password.</summary>
    public string Verifier { get; init; } = string.Empty;
}

/// <summary>
/// Application settings stored in <c>$HOME/.devcode/object-storage-client/config.json</c>.
/// Holds only non-secret preferences plus the master-password parameters.
/// </summary>
public sealed record AppSettings
{
    /// <summary>Schema version, so future changes can migrate rather than discard the file.</summary>
    public int Version { get; init; } = 1;

    public MasterPasswordSettings MasterPassword { get; init; } = new();

    /// <summary>Directory the local pane opens on. Empty means the user's home directory.</summary>
    public string LastLocalDirectory { get; init; } = string.Empty;

    public bool ShowHiddenFiles { get; init; }

    /// <summary>Site selected the last time the Site Manager was used.</summary>
    public Guid? LastSiteId { get; init; }
}
