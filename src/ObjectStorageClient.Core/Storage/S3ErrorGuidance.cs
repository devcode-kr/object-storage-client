using Amazon.S3;

namespace ObjectStorageClient.Core.Storage;

/// <summary>Raised instead of the raw SDK exception, so failures carry an actionable message.</summary>
public sealed class StorageOperationException : Exception
{
    public StorageOperationException(string message, Exception innerException)
        : base(message, innerException)
    {
    }

    /// <summary>S3 error code, e.g. <c>NotImplemented</c>. Empty when the service sent none.</summary>
    public string ErrorCode { get; init; } = string.Empty;
}

/// <summary>
/// Turns S3 error codes into something a user can act on.
/// </summary>
/// <remarks>
/// Gateways routinely answer with a bare code and no detail — the SDK then reports
/// "No further error information was returned by the service", which tells the user nothing.
/// The common failures against non-AWS endpoints all have a specific, checkable cause.
/// </remarks>
public static class S3ErrorGuidance
{
    /// <summary>Returns the SDK message with a hint appended, when the error code has a known cause.</summary>
    public static string Describe(AmazonS3Exception exception)
    {
        string? hint = HintFor(exception.ErrorCode);

        return hint is null ? exception.Message : $"{exception.Message} — {hint}";
    }

    /// <summary>Actionable explanation for an S3 error code, or <c>null</c> when there is nothing to add.</summary>
    public static string? HintFor(string? errorCode) => errorCode switch
    {
        "NotImplemented" =>
            "The endpoint does not implement something this request used. Most often that is the "
            + "AWS SDK's checksum headers: enable \"Disable request checksums\" in the site's "
            + "Advanced settings. If it persists on large files only, the gateway likely does not "
            + "support multipart uploads.",

        "AccessDenied" =>
            "The credentials are valid but not allowed this operation. Check the key's policy and "
            + "the bucket permissions.",

        "NoSuchBucket" =>
            "The bucket does not exist at this endpoint. Check the bucket name, and whether the "
            + "endpoint and region point at the right account.",

        "InvalidAccessKeyId" =>
            "The endpoint does not recognise this access key ID.",

        "SignatureDoesNotMatch" =>
            "The request signature did not match. Check the secret access key, and that the region "
            + "matches the one the endpoint expects.",

        "RequestTimeTooSkewed" =>
            "The local clock is too far from the server's. Synchronise the system time.",

        "InvalidRequest" or "InvalidArgument" =>
            "The endpoint rejected a request parameter. If the site uses virtual-host addressing, "
            + "try switching on path-style addressing in the Advanced settings.",

        _ => null,
    };
}
