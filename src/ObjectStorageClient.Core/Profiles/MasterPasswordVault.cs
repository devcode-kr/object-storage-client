using System.Security.Cryptography;
using System.Text;
using ObjectStorageClient.Core.Abstractions;
using ObjectStorageClient.Core.Models;

namespace ObjectStorageClient.Core.Profiles;

/// <summary>
/// Turns a master password into the AES key that protects stored credentials.
/// </summary>
/// <remarks>
/// The key is derived with PBKDF2-HMAC-SHA256 and held in memory only, so the credentials in
/// <c>sites.json</c> cannot be read without the password — unlike a key file, which an attacker
/// with filesystem access would simply read alongside the ciphertext.
/// <para>
/// The trade-off is that the password is unrecoverable: there is no escrow, and forgetting it
/// means the saved secrets are gone. <see cref="Reset"/> exists so the user can start over.
/// </para>
/// </remarks>
public static class MasterPasswordVault
{
    /// <summary>OWASP's 2023 floor for PBKDF2-HMAC-SHA256. Recorded per vault so it can be raised later.</summary>
    public const int DefaultIterations = 600_000;

    private const int KeySize = 32;
    private const int SaltSize = 16;

    /// <summary>Plaintext sealed into <see cref="MasterPasswordSettings.Verifier"/> to validate a password.</summary>
    private const string VerifierToken = "object-storage-client.master-password.v1";

    /// <summary>Result of setting up or unlocking a vault.</summary>
    /// <param name="Protector">Encrypts and decrypts credentials with the derived key.</param>
    /// <param name="Settings">Parameters to persist in <c>config.json</c>.</param>
    public sealed record UnlockedVault(ISecretProtector Protector, MasterPasswordSettings Settings);

    /// <summary>
    /// Creates a brand-new vault for <paramref name="password"/>.
    /// Any credentials encrypted under a previous master password become unreadable.
    /// </summary>
    public static UnlockedVault Create(string password, int iterations = DefaultIterations)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(password);

        byte[] salt = RandomNumberGenerator.GetBytes(SaltSize);
        byte[] key = DeriveKey(password, salt, iterations);
        AesGcmSecretProtector protector = new(key);

        return new UnlockedVault(
            protector,
            new MasterPasswordSettings
            {
                IsConfigured = true,
                Salt = Convert.ToBase64String(salt),
                Iterations = iterations,
                Verifier = protector.Protect(VerifierToken),
            });
    }

    /// <summary>
    /// Attempts to unlock an existing vault.
    /// Returns <c>null</c> when the password is wrong, which is the only way this fails —
    /// a malformed or truncated <c>config.json</c> is reported through <paramref name="isUsable"/>.
    /// </summary>
    public static UnlockedVault? TryUnlock(string password, MasterPasswordSettings settings, out bool isUsable)
    {
        isUsable = IsUsable(settings);

        if (!isUsable || string.IsNullOrEmpty(password))
        {
            return null;
        }

        byte[] salt;
        try
        {
            salt = Convert.FromBase64String(settings.Salt);
        }
        catch (FormatException)
        {
            isUsable = false;
            return null;
        }

        byte[] key = DeriveKey(password, salt, settings.Iterations);
        AesGcmSecretProtector protector = new(key);

        // A wrong key makes the GCM tag check fail, which the protector reports as an empty string.
        return protector.Unprotect(settings.Verifier) == VerifierToken
            ? new UnlockedVault(protector, settings)
            : null;
    }

    /// <summary>True when the settings carry a complete, parseable vault definition.</summary>
    public static bool IsUsable(MasterPasswordSettings settings) =>
        settings.IsConfigured
        && settings.Iterations > 0
        && !string.IsNullOrEmpty(settings.Salt)
        && !string.IsNullOrEmpty(settings.Verifier);

    /// <summary>
    /// Clears the vault definition. The caller is responsible for also discarding
    /// <c>sites.json</c>, whose secrets can no longer be decrypted.
    /// </summary>
    public static MasterPasswordSettings Reset() => new();

    private static byte[] DeriveKey(string password, byte[] salt, int iterations) =>
        Rfc2898DeriveBytes.Pbkdf2(
            Encoding.UTF8.GetBytes(password),
            salt,
            Math.Max(iterations, 1),
            HashAlgorithmName.SHA256,
            KeySize);
}
