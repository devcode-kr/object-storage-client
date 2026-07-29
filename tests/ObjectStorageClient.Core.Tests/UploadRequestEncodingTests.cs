using System.Collections.Specialized;
using System.Net;
using ObjectStorageClient.Core.Models;
using ObjectStorageClient.Core.Storage;
using Xunit;

namespace ObjectStorageClient.Core.Tests;

/// <summary>
/// Captures the PUT the SDK actually puts on the wire, against a throwaway local listener.
/// </summary>
/// <remarks>
/// Unit tests over <c>AmazonS3Config</c> cannot see this: chunked upload encoding is decided per
/// request, and <c>TransferUtility</c> — which the upload path used to go through — always turns
/// it on. Gateways that do not implement <c>aws-chunked</c> answer <c>NotImplemented</c>, so the
/// absence of that header is the behaviour worth pinning down.
/// </remarks>
public sealed class UploadRequestEncodingTests : IDisposable
{
    private readonly string _file = Path.Combine(Path.GetTempPath(), $"osc-upload-{Guid.NewGuid():N}.bin");

    public UploadRequestEncodingTests() => File.WriteAllBytes(_file, new byte[64 * 1024]);

    /// <summary>Runs one upload against a local listener and returns the request headers.</summary>
    private async Task<NameValueCollection> CaptureUploadHeadersAsync(bool disableChunkedEncoding)
    {
        using HttpListener listener = new();
        int port = StartOnFreePort(listener);

        NameValueCollection? headers = null;
        using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(30));

        Task serving = Task.Run(
            async () =>
            {
                HttpListenerContext context = await listener.GetContextAsync().ConfigureAwait(false);
                headers = context.Request.Headers;

                context.Response.Headers.Add("ETag", "\"d41d8cd98f00b204e9800998ecf8427e\"");
                context.Response.StatusCode = 200;
                context.Response.Close();
            },
            timeout.Token);

        ConnectionProfile profile = new()
        {
            Name = "capture",
            ServiceUrl = $"http://localhost:{port}",
            Region = "us-east-1",
            AccessKeyId = "test-key",
            SecretAccessKey = "test-secret",
            ForcePathStyle = true,
            DisableChunkedEncoding = disableChunkedEncoding,
        };

        await using (S3ObjectStorageClient client = new(profile))
        {
            // The stub response is deliberately minimal, so the SDK may still fault afterwards.
            // Only the request it emitted matters here.
            try
            {
                await client.UploadAsync("bucket", "folder/upload.bin", _file, null, timeout.Token)
                    .ConfigureAwait(false);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                // Ignored: the assertion is on the captured request.
            }
        }

        await serving.WaitAsync(TimeSpan.FromSeconds(30)).ConfigureAwait(false);
        listener.Stop();

        Assert.NotNull(headers);
        return headers!;
    }

    private static int StartOnFreePort(HttpListener listener)
    {
        for (int attempt = 0; attempt < 10; attempt++)
        {
            int port = Random.Shared.Next(20_000, 40_000);
            listener.Prefixes.Clear();
            listener.Prefixes.Add($"http://localhost:{port}/");

            try
            {
                listener.Start();
                return port;
            }
            catch (HttpListenerException)
            {
                // Port taken; try another.
            }
        }

        throw new InvalidOperationException("No free local port for the capture listener.");
    }

    [Fact]
    public async Task DefaultUpload_SendsAPlainSignedBodyWithNoChunkedEncoding()
    {
        NameValueCollection headers = await CaptureUploadHeadersAsync(disableChunkedEncoding: true);

        Assert.Null(headers["Content-Encoding"]);
        Assert.Null(headers["X-Amz-Decoded-Content-Length"]);

        // A real payload hash rather than the streaming sentinel.
        string? contentSha = headers["X-Amz-Content-SHA256"];
        Assert.NotNull(contentSha);
        Assert.DoesNotContain("STREAMING", contentSha!, StringComparison.Ordinal);
    }

    [Fact]
    public async Task OptingIntoChunkedEncoding_RestoresTheSdkStreamingBody()
    {
        NameValueCollection headers = await CaptureUploadHeadersAsync(disableChunkedEncoding: false);

        Assert.Equal("aws-chunked", headers["Content-Encoding"]);
        Assert.Contains("STREAMING", headers["X-Amz-Content-SHA256"] ?? string.Empty, StringComparison.Ordinal);
    }

    [Fact]
    public async Task UploadKey_IsPercentEncodedSoNonAsciiNamesSurvive()
    {
        // The reported failure involved a Korean filename; confirm it is not the cause.
        using HttpListener listener = new();
        int port = StartOnFreePort(listener);
        string? path = null;

        Task serving = Task.Run(async () =>
        {
            HttpListenerContext context = await listener.GetContextAsync().ConfigureAwait(false);
            path = context.Request.Url?.AbsolutePath;
            context.Response.Headers.Add("ETag", "\"x\"");
            context.Response.StatusCode = 200;
            context.Response.Close();
        });

        ConnectionProfile profile = new()
        {
            Name = "capture",
            ServiceUrl = $"http://localhost:{port}",
            Region = "us-east-1",
            AccessKeyId = "test-key",
            SecretAccessKey = "test-secret",
            ForcePathStyle = true,
        };

        await using (S3ObjectStorageClient client = new(profile))
        {
            try
            {
                await client.UploadAsync("bucket", "test/한글 테스트.jpg", _file);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                // Ignored; only the request line matters.
            }
        }

        await serving.WaitAsync(TimeSpan.FromSeconds(30));
        listener.Stop();

        Assert.Equal("/bucket/test/%ED%95%9C%EA%B8%80%20%ED%85%8C%EC%8A%A4%ED%8A%B8.jpg", path);
    }

    public void Dispose() => File.Delete(_file);
}
