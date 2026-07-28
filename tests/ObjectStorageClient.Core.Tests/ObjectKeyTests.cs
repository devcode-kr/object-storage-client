using ObjectStorageClient.Core.Storage;
using Xunit;

namespace ObjectStorageClient.Core.Tests;

public sealed class ObjectKeyTests
{
    [Theory]
    [InlineData(null, "")]
    [InlineData("", "")]
    [InlineData("/photos/cat.png", "photos/cat.png")]
    [InlineData("photos//cat.png", "photos/cat.png")]
    [InlineData("photos\\cat.png", "photos/cat.png")]
    public void Normalize_StripsLeadingSlashesAndCollapsesSeparators(string? input, string expected) =>
        Assert.Equal(expected, ObjectKey.Normalize(input));

    [Theory]
    [InlineData("", "")]
    [InlineData("photos", "photos/")]
    [InlineData("photos/", "photos/")]
    [InlineData("/photos/2024", "photos/2024/")]
    public void NormalizePrefix_EnsuresTrailingSeparator(string input, string expected) =>
        Assert.Equal(expected, ObjectKey.NormalizePrefix(input));

    [Theory]
    [InlineData("", "cat.png", "cat.png")]
    [InlineData("photos", "cat.png", "photos/cat.png")]
    [InlineData("photos/", "/cat.png", "photos/cat.png")]
    public void Combine_JoinsPrefixAndChild(string prefix, string child, string expected) =>
        Assert.Equal(expected, ObjectKey.Combine(prefix, child));

    [Theory]
    [InlineData("photos/2024/cat.png", "cat.png")]
    [InlineData("photos/2024/", "2024")]
    [InlineData("cat.png", "cat.png")]
    [InlineData("", "")]
    public void GetName_ReturnsLastSegmentIgnoringTrailingSeparator(string key, string expected) =>
        Assert.Equal(expected, ObjectKey.GetName(key));

    [Theory]
    [InlineData("photos/2024/cat.png", "photos/2024/")]
    [InlineData("photos/2024/", "photos/")]
    [InlineData("cat.png", "")]
    public void GetParentPrefix_WalksUpOneLevel(string key, string expected) =>
        Assert.Equal(expected, ObjectKey.GetParentPrefix(key));

    [Fact]
    public void Segments_SplitsPrefixForBreadcrumbs() =>
        Assert.Equal(["photos", "2024"], ObjectKey.Segments("/photos/2024/"));

    [Fact]
    public void FromLocalPath_UsesFileNameWhenNoBaseDirectoryGiven()
    {
        string localPath = Path.Combine("home", "user", "cat.png");

        Assert.Equal("uploads/cat.png", ObjectKey.FromLocalPath("uploads", localPath));
    }

    [Fact]
    public void FromLocalPath_MirrorsDirectoryStructureRelativeToBase()
    {
        string root = Path.Combine(Path.GetTempPath(), "osc-tests");
        string localPath = Path.Combine(root, "photos", "2024", "cat.png");

        string key = ObjectKey.FromLocalPath("uploads", localPath, root);

        Assert.Equal("uploads/photos/2024/cat.png", key);
    }

    [Fact]
    public void ToLocalPath_StripsThePrefixAndMapsToPlatformSeparators()
    {
        string target = Path.GetTempPath();

        string result = ObjectKey.ToLocalPath(target, "photos/2024/cat.png", "photos/");

        Assert.Equal(Path.Combine(Path.GetFullPath(target), "2024", "cat.png"), result);
    }

    [Fact]
    public void ToLocalPath_RejectsKeysThatEscapeTheTargetDirectory()
    {
        string target = Path.Combine(Path.GetTempPath(), "osc-download-root");

        Assert.Throws<InvalidOperationException>(() =>
            ObjectKey.ToLocalPath(target, "../../etc/passwd"));
    }
}
