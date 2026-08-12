# Privacy policy

*[한국어](PRIVACY.md) · English*

Last updated: 2026-08-11

Object Storage Client **collects no personal data.** What follows is what that means concretely.

## What is not collected

- Names, email addresses, account details, or anything else identifying you
- Usage data, analytics, telemetry, or crash reports
- Advertising identifiers
- File names, file contents, or a record of the storage you connect to

There is no server operated by this project, no account, and no registration.

## What leaves your machine

The application talks only to **the endpoints you enter yourself**:

- the S3-compatible storage endpoint you configure
- the HTTP proxy you configure, if you configure one

Uploads, downloads and listings go there. Nothing is sent anywhere else. The application does not
check for updates or fetch remote configuration.

If you installed from the Microsoft Store, whatever the Store itself collects is covered by the
[Microsoft privacy statement](https://privacy.microsoft.com/privacystatement). That is outside
this application.

## What is stored on your machine

Two files, kept locally and never transmitted:

| File | Contents |
| --- | --- |
| `sites.json` | Saved connections; credentials encrypted |
| `config.json` | Preferences and master-password parameters |

They live in `$HOME/.devcode/object-storage-client/`, or under `%USERPROFILE%` on Windows. A Store
installation uses the same location.

For each connection, the endpoint, region, access key, secret key, session token, bucket and proxy
settings are encrypted together as one block with AES-256-GCM. The key comes from your master
password via PBKDF2-HMAC-SHA256 at 600,000 iterations, and the password itself is never written
anywhere. Files are created with owner-only permissions where the operating system supports it.

**If you forget the master password there is no recovery**, because no copy of it is kept.

## Deleting your data

Removing the application leaves those two files behind so that reinstalling does not lose your
settings. Delete the directory yourself to be rid of them:

```
Windows:        %USERPROFILE%\.devcode\object-storage-client\
macOS / Linux:  ~/.devcode/object-storage-client/
```

## Children

The application is not directed at children, and collects nothing from anyone, children included.

## Changes to this policy

This document is edited and the date above updated. It lives in the repository, so every change
is recorded as a commit.

## Contact

Open an issue: <https://github.com/devcode-kr/object-storage-client/issues>
