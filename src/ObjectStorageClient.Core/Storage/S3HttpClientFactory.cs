using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using Amazon.Runtime;
using ObjectStorageClient.Core.Models;

namespace ObjectStorageClient.Core.Storage;

/// <summary>
/// Supplies the <see cref="HttpClient"/> used by the S3 client when a profile needs an outbound
/// proxy or relaxed TLS validation. AWS SDK v4 dropped the proxy bypass-list properties from
/// <c>ClientConfig</c>, so both concerns are handled here on the handler instead.
/// </summary>
internal sealed class S3HttpClientFactory : HttpClientFactory
{
    private readonly ProxySettings _proxy;
    private readonly bool _allowInsecureCertificates;
    private readonly TimeSpan _timeout;

    internal S3HttpClientFactory(ConnectionProfile profile)
    {
        _proxy = profile.Proxy;
        _allowInsecureCertificates = profile.AllowInsecureCertificates;
        _timeout = TimeSpan.FromSeconds(Math.Clamp(profile.TimeoutSeconds, 5, 3600));
    }

    /// <summary>True when a profile needs anything the SDK's stock client cannot provide.</summary>
    internal static bool IsRequiredFor(ConnectionProfile profile) =>
        profile.AllowInsecureCertificates || profile.Proxy.IsUsable;

    public override HttpClient CreateHttpClient(IClientConfig clientConfig)
    {
        HttpClientHandler handler = new();

        if (_proxy.IsUsable)
        {
            handler.Proxy = BuildWebProxy(_proxy);
            handler.UseProxy = true;
        }

        if (_allowInsecureCertificates)
        {
            // Opt-in per profile, for self-signed development endpoints only.
            handler.ServerCertificateCustomValidationCallback =
                HttpClientHandler.DangerousAcceptAnyServerCertificateValidator;
        }

        return new HttpClient(handler) { Timeout = _timeout };
    }

    internal static WebProxy BuildWebProxy(ProxySettings proxy)
    {
        WebProxy webProxy = new(proxy.Host.Trim(), proxy.Port);

        IReadOnlyList<string> bypass = proxy.ParseBypassList();
        if (bypass.Count > 0)
        {
            webProxy.BypassProxyOnLocal = true;
            webProxy.BypassList = [.. bypass.Select(GlobToRegex)];
        }

        if (proxy.HasCredentials)
        {
            webProxy.Credentials = new NetworkCredential(proxy.Username, proxy.Password);
        }

        return webProxy;
    }

    /// <summary>
    /// <see cref="WebProxy.BypassList"/> takes regular expressions, but users write shell-style
    /// host patterns such as <c>*.internal</c>. Translate the two wildcards and escape the rest.
    /// </summary>
    internal static string GlobToRegex(string pattern)
    {
        StringBuilder builder = new("^");

        foreach (char character in pattern)
        {
            builder.Append(character switch
            {
                '*' => ".*",
                '?' => ".",
                _ => Regex.Escape(character.ToString()),
            });
        }

        return builder.Append('$').ToString();
    }
}
