#!/usr/bin/env bash
#
# Assemble a macOS .app bundle and zip it.
#
#   build/package-macos.sh <rid> <version> <output-dir>
#   build/package-macos.sh osx-arm64 0.0.1 artifacts
#
# `dotnet publish` emits a bare executable, not a bundle, so Finder would not treat the output
# as an application. This wraps the publish output in the Contents/MacOS + Info.plist layout
# that macOS expects, which is also the shape `codesign` and `notarytool` operate on once
# signing is set up.
#
# The zip is produced with `ditto`, not `zip`: ditto preserves the bundle's symlinks and
# resource forks, which is what keeps the signature intact on a signed bundle.

set -euo pipefail

RID="${1:?usage: package-macos.sh <rid> <version> <output-dir>}"
VERSION="${2:?usage: package-macos.sh <rid> <version> <output-dir>}"
OUTPUT_DIR="${3:?usage: package-macos.sh <rid> <version> <output-dir>}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="$REPO_ROOT/src/ObjectStorageClient.App"
ICON="$REPO_ROOT/build/icon/ObjectStorageClient.icns"

APP_NAME="Object Storage Client"
EXECUTABLE="ObjectStorageClient.App"
# Reverse-DNS of devcode.kr. Effectively permanent: macOS keys Gatekeeper decisions, preferences
# and TCC grants off this, so changing it after a release makes macOS treat the app as a new one.
BUNDLE_ID="kr.devcode.object-storage-client"
# .NET 9 does not support anything earlier.
MIN_MACOS="12.0"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

PUBLISH_DIR="$STAGING/publish"
BUNDLE="$STAGING/$APP_NAME.app"

echo "==> Publishing $RID"
dotnet publish "$PROJECT" \
    --configuration Release \
    --runtime "$RID" \
    --self-contained \
    --output "$PUBLISH_DIR" \
    -p:Version="$VERSION" \
    --nologo

echo "==> Assembling $APP_NAME.app"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
cp -R "$PUBLISH_DIR/." "$BUNDLE/Contents/MacOS/"
chmod +x "$BUNDLE/Contents/MacOS/$EXECUTABLE"

if [[ -f "$ICON" ]]; then
    cp "$ICON" "$BUNDLE/Contents/Resources/ObjectStorageClient.icns"
else
    echo "! $ICON missing — bundle will use the generic icon" >&2
fi

cat > "$BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>
    <string>$APP_NAME</string>
    <key>CFBundleExecutable</key>
    <string>$EXECUTABLE</string>
    <key>CFBundleIdentifier</key>
    <string>$BUNDLE_ID</string>
    <key>CFBundleIconFile</key>
    <string>ObjectStorageClient</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundleVersion</key>
    <string>$VERSION</string>
    <key>LSMinimumSystemVersion</key>
    <string>$MIN_MACOS</string>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.utilities</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSHumanReadableCopyright</key>
    <string>Copyright (c) 2026 Astral. MIT License.</string>
</dict>
</plist>
PLIST

mkdir -p "$OUTPUT_DIR"
ARCHIVE="$(cd "$OUTPUT_DIR" && pwd)/ObjectStorageClient-$VERSION-$RID.zip"
rm -f "$ARCHIVE"

echo "==> Writing $ARCHIVE"
ditto -c -k --sequesterRsrc --keepParent "$BUNDLE" "$ARCHIVE"

echo "==> Done"
