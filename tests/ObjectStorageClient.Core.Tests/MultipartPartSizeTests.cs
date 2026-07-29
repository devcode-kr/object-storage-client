using ObjectStorageClient.Core.Storage;
using Xunit;

namespace ObjectStorageClient.Core.Tests;

/// <summary>
/// The non-chunked upload path splits large files itself instead of using TransferUtility,
/// so it owns the S3 constraint of at most 10,000 parts.
/// </summary>
public sealed class MultipartPartSizeTests
{
    private const long Threshold = S3ObjectStorageClient.MultipartThresholdBytes;

    private const int MaxParts = 10_000;

    private static long PartCount(long length) =>
        (length + S3ObjectStorageClient.CalculatePartSize(length) - 1) / S3ObjectStorageClient.CalculatePartSize(length);

    [Theory]
    [InlineData(Threshold)]
    [InlineData(Threshold * 2)]
    [InlineData(100L * 1024 * 1024)]
    public void ModerateFiles_UseTheThresholdSizedParts(long length) =>
        Assert.Equal(Threshold, S3ObjectStorageClient.CalculatePartSize(length));

    [Theory]
    [InlineData(Threshold)]
    [InlineData(1024L * 1024 * 1024)]          // 1 GB
    [InlineData(160L * 1024 * 1024 * 1024)]    // 160 GB — the point where 16 MiB parts run out
    [InlineData(1024L * 1024 * 1024 * 1024)]   // 1 TB
    [InlineData(5L * 1024 * 1024 * 1024 * 1024)] // 5 TB, S3's maximum object size
    public void PartCountNeverExceedsTheS3Limit(long length) =>
        Assert.True(
            PartCount(length) <= MaxParts,
            $"{length:N0} bytes would need {PartCount(length):N0} parts");

    [Fact]
    public void VeryLargeFiles_GrowThePartSizeBeyondTheThreshold()
    {
        long huge = 5L * 1024 * 1024 * 1024 * 1024;

        Assert.True(S3ObjectStorageClient.CalculatePartSize(huge) > Threshold);
    }

    [Fact]
    public void PartSize_IsNeverSmallerThanTheS3Minimum()
    {
        // S3 requires every part except the last to be at least 5 MiB.
        const long minimumPartSize = 5 * 1024 * 1024;

        foreach (long length in new[] { 1L, Threshold, 1024L * 1024 * 1024, 5L * 1024 * 1024 * 1024 * 1024 })
        {
            Assert.True(S3ObjectStorageClient.CalculatePartSize(length) >= minimumPartSize);
        }
    }
}
