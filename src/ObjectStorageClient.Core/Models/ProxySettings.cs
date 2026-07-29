using System.Text.Json.Serialization;

namespace ObjectStorageClient.Core.Models;

/// <summary>
/// Optional outbound HTTP proxy applied to every request of a connection.
/// Disabled by default; when <see cref="Enabled"/> is false the settings are ignored entirely.
/// </summary>
public sealed record ProxySettings
{
    public static ProxySettings Disabled { get; } = new();

    public bool Enabled { get; init; }

    public string Host { get; init; } = string.Empty;

    public int Port { get; init; } = 8080;

    /// <summary>Optional proxy user. Leave empty for an unauthenticated proxy.</summary>
    public string Username { get; init; } = string.Empty;

    /// <summary>
    /// Optional proxy password. Never serialised here — the profile store writes it encrypted
    /// alongside the profile, same as the storage credentials.
    /// </summary>
    [JsonIgnore]
    public string Password { get; init; } = string.Empty;

    /// <summary>Hosts that bypass the proxy, e.g. <c>localhost;127.0.0.1;*.internal</c>.</summary>
    public string BypassList { get; init; } = string.Empty;

    /// <summary>True when the proxy is switched on and has a usable host/port pair.</summary>
    /// <remarks>Derived; see <see cref="ConnectionProfile.Preset"/> for why these are not serialised.</remarks>
    [JsonIgnore]
    public bool IsUsable => Enabled && !string.IsNullOrWhiteSpace(Host) && Port is > 0 and <= 65535;

    [JsonIgnore]
    public bool HasCredentials => !string.IsNullOrEmpty(Username);

    /// <summary>Splits <see cref="BypassList"/> into individual host patterns.</summary>
    public IReadOnlyList<string> ParseBypassList() =>
        BypassList.Split([';', ','], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
}
