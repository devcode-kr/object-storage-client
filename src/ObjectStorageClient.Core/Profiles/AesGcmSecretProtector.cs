using System.Security.Cryptography;
using System.Text;
using ObjectStorageClient.Core.Abstractions;

namespace ObjectStorageClient.Core.Profiles;

/// <summary>
/// Encrypts secrets with AES-256-GCM using a key file kept beside the profile store.
/// </summary>
/// <remarks>
/// This protects credentials from casual disclosure (backups, screen sharing, sync folders).
/// It is <b>not</b> protection against an attacker who can already read the user's home
/// directory, because the key lives there too. Swap in an OS keychain implementation of
/// <see cref="ISecretProtector"/> when that threat model matters.
/// </remarks>
public sealed class AesGcmSecretProtector : ISecretProtector
{
    private const int KeySize = 32;
    private const int NonceSize = 12;
    private const int TagSize = 16;

    private readonly Lazy<byte[]> _key;

    public AesGcmSecretProtector(string? keyFilePath = null)
    {
        string path = keyFilePath ?? AppPaths.KeyFile;
        _key = new Lazy<byte[]>(() => LoadOrCreateKey(path), LazyThreadSafetyMode.ExecutionAndPublication);
    }

    public string Protect(string plaintext)
    {
        if (string.IsNullOrEmpty(plaintext))
        {
            return string.Empty;
        }

        byte[] nonce = RandomNumberGenerator.GetBytes(NonceSize);
        byte[] plainBytes = Encoding.UTF8.GetBytes(plaintext);
        byte[] cipher = new byte[plainBytes.Length];
        byte[] tag = new byte[TagSize];

        using AesGcm aes = new(_key.Value, TagSize);
        aes.Encrypt(nonce, plainBytes, cipher, tag);

        // Layout: nonce | tag | ciphertext
        byte[] payload = new byte[NonceSize + TagSize + cipher.Length];
        nonce.CopyTo(payload, 0);
        tag.CopyTo(payload, NonceSize);
        cipher.CopyTo(payload, NonceSize + TagSize);

        return Convert.ToBase64String(payload);
    }

    public string Unprotect(string protectedValue)
    {
        if (string.IsNullOrEmpty(protectedValue))
        {
            return string.Empty;
        }

        try
        {
            byte[] payload = Convert.FromBase64String(protectedValue);
            if (payload.Length <= NonceSize + TagSize)
            {
                return string.Empty;
            }

            byte[] nonce = payload[..NonceSize];
            byte[] tag = payload[NonceSize..(NonceSize + TagSize)];
            byte[] cipher = payload[(NonceSize + TagSize)..];
            byte[] plain = new byte[cipher.Length];

            using AesGcm aes = new(_key.Value, TagSize);
            aes.Decrypt(nonce, cipher, tag, plain);

            return Encoding.UTF8.GetString(plain);
        }
        catch (Exception ex) when (ex is FormatException or CryptographicException)
        {
            // Key rotated, file copied between machines, or value corrupted: treat as "no secret
            // stored" so the user is prompted again instead of the app failing to start.
            return string.Empty;
        }
    }

    private static byte[] LoadOrCreateKey(string path)
    {
        AppPaths.EnsureConfigDirectory();

        if (File.Exists(path))
        {
            byte[] existing = File.ReadAllBytes(path);
            if (existing.Length == KeySize)
            {
                return existing;
            }
        }

        byte[] key = RandomNumberGenerator.GetBytes(KeySize);
        File.WriteAllBytes(path, key);
        AppPaths.TryRestrictToOwner(path, UnixFileMode.UserRead | UnixFileMode.UserWrite);
        return key;
    }
}
