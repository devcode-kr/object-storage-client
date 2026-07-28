using System.Security.Cryptography;
using System.Text;
using ObjectStorageClient.Core.Abstractions;

namespace ObjectStorageClient.Core.Profiles;

/// <summary>
/// Encrypts secrets with AES-256-GCM under a key supplied by the caller.
/// </summary>
/// <remarks>
/// The key comes from <see cref="MasterPasswordVault"/>, derived from the master password the
/// user types at startup, and exists only in memory. Construct this directly only in tests.
/// </remarks>
public sealed class AesGcmSecretProtector : ISecretProtector
{
    internal const int KeySize = 32;

    private const int NonceSize = 12;
    private const int TagSize = 16;

    private readonly byte[] _key;

    /// <param name="key">A 32-byte AES-256 key.</param>
    public AesGcmSecretProtector(byte[] key)
    {
        ArgumentNullException.ThrowIfNull(key);

        if (key.Length != KeySize)
        {
            throw new ArgumentException($"Key must be {KeySize} bytes, got {key.Length}.", nameof(key));
        }

        _key = key;
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

        using AesGcm aes = new(_key, TagSize);
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

            using AesGcm aes = new(_key, TagSize);
            aes.Decrypt(nonce, cipher, tag, plain);

            return Encoding.UTF8.GetString(plain);
        }
        catch (Exception ex) when (ex is FormatException or CryptographicException)
        {
            // Wrong key or a corrupted value. Reported as "no secret stored" so a single bad
            // entry cannot stop the app from starting; the master password check itself is
            // handled by MasterPasswordVault's verifier.
            return string.Empty;
        }
    }
}
