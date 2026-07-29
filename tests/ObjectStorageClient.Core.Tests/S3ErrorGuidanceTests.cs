using Amazon.S3;
using ObjectStorageClient.Core.Storage;
using Xunit;

namespace ObjectStorageClient.Core.Tests;

public sealed class S3ErrorGuidanceTests
{
    [Fact]
    public void NotImplemented_PointsAtTheChecksumSetting()
    {
        string? hint = S3ErrorGuidance.HintFor("NotImplemented");

        Assert.NotNull(hint);
        Assert.Contains("Disable request checksums", hint!, StringComparison.Ordinal);
        Assert.Contains("multipart", hint, StringComparison.OrdinalIgnoreCase);
    }

    [Theory]
    [InlineData("AccessDenied")]
    [InlineData("NoSuchBucket")]
    [InlineData("InvalidAccessKeyId")]
    [InlineData("SignatureDoesNotMatch")]
    [InlineData("RequestTimeTooSkewed")]
    [InlineData("InvalidArgument")]
    public void CommonFailures_AllCarryAHint(string errorCode) =>
        Assert.False(string.IsNullOrWhiteSpace(S3ErrorGuidance.HintFor(errorCode)));

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("SomethingUnheardOf")]
    public void UnknownCodes_AddNothing(string? errorCode) =>
        Assert.Null(S3ErrorGuidance.HintFor(errorCode));

    [Fact]
    public void Describe_AppendsTheHintToTheSdkMessage()
    {
        // The message the SDK actually produced for the failing upload.
        AmazonS3Exception exception = new(
            "Error making request with Error Code NotImplemented and Http Status Code NotImplemented. "
            + "No further error information was returned by the service.")
        {
            ErrorCode = "NotImplemented",
        };

        string described = S3ErrorGuidance.Describe(exception);

        Assert.StartsWith("Error making request", described, StringComparison.Ordinal);
        Assert.Contains("Disable request checksums", described, StringComparison.Ordinal);
    }

    [Fact]
    public void Describe_LeavesAnUnrecognisedErrorUntouched()
    {
        AmazonS3Exception exception = new("Some other failure") { ErrorCode = "Whatever" };

        Assert.Equal("Some other failure", S3ErrorGuidance.Describe(exception));
    }
}
