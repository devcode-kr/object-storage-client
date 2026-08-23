#!/bin/sh
set -eu

umask 022

PROGRAM=object-storage-client
FIXTURE=/root/.devcode/$PROGRAM/preserve-me
FIXTURE_BYTES=object-storage-client-smoke-preserve-v1
REPOSITORY_URL=${REPOSITORY_URL:-http://repository:8000}
APP_PID=
XVFB_PID=
TEMP_ROOT=

fail() {
    printf 'smoke-package: %s\n' "$*" >&2
    exit 1
}

stop_process() {
    process_pid=$1
    if [ -n "$process_pid" ] && kill -0 "$process_pid" 2>/dev/null; then
        kill "$process_pid" 2>/dev/null || :
        stop_attempt=0
        while kill -0 "$process_pid" 2>/dev/null && [ "$stop_attempt" -lt 20 ]; do
            sleep 1
            stop_attempt=$((stop_attempt + 1))
        done
        if kill -0 "$process_pid" 2>/dev/null; then
            kill -KILL "$process_pid" 2>/dev/null || :
        fi
    fi
    if [ -n "$process_pid" ]; then
        wait "$process_pid" 2>/dev/null || :
    fi
}

cleanup() {
    stop_process "$APP_PID"
    APP_PID=
    stop_process "$XVFB_PID"
    XVFB_PID=
    if [ -n "$TEMP_ROOT" ] && [ -d "$TEMP_ROOT" ] && [ ! -L "$TEMP_ROOT" ]; then
        rm -rf -- "$TEMP_ROOT"
    fi
}

trap cleanup EXIT HUP INT TERM

[ "$#" -eq 3 ] || fail "usage: smoke-package.sh deb|rpm PACKAGE REPOSITORY"
KIND=$1
PACKAGE=$2
REPOSITORY=$3

case "$KIND" in
    deb|rpm) ;;
    *) fail "package kind must be deb or rpm" ;;
esac

[ -f "$PACKAGE" ] && [ ! -L "$PACKAGE" ] || fail "package must be a regular non-symlink file"
[ -d "$REPOSITORY" ] && [ ! -L "$REPOSITORY" ] || fail "repository must be a non-symlink directory"
REPOSITORY_KEY=$REPOSITORY/repository-key.asc
[ -f "$REPOSITORY_KEY" ] && [ ! -L "$REPOSITORY_KEY" ] || fail "repository-key.asc must be a regular non-symlink file"

case "$REPOSITORY_URL" in
    http://?*|https://?*) ;;
    *) fail "REPOSITORY_URL must use http:// or https://" ;;
esac
case "$REPOSITORY_URL" in
    *[!A-Za-z0-9._:/%-]*) fail "REPOSITORY_URL contains unsafe characters" ;;
esac

[ "$(id -u)" -eq 0 ] || fail "root privileges are required"
TEMP_ROOT=$(mktemp -d /tmp/object-storage-client-smoke.XXXXXX)
GPG_HOME=$TEMP_ROOT/gnupg
install -d -m 0700 "$GPG_HOME"

install_dependencies() {
    case "$KIND" in
        deb)
            apt-get update
            DEBIAN_FRONTEND=noninteractive apt-get install -y \
                libx11-6 libice6 libsm6 libfontconfig1 ca-certificates \
                xvfb desktop-file-utils curl gnupg procps x11-utils
            ;;
        rpm)
            dnf -y install \
                libX11 libICE libSM fontconfig ca-certificates \
                xorg-x11-server-Xvfb xorg-x11-utils desktop-file-utils curl gnupg2 procps-ng
            ;;
    esac
}

install_local_package() {
    install -d -m 0755 "$(dirname "$FIXTURE")"
    printf '%s' "$FIXTURE_BYTES" > "$FIXTURE"
    chmod 0644 "$FIXTURE"

    case "$KIND" in
        deb) DEBIAN_FRONTEND=noninteractive apt-get install -y "$PACKAGE" ;;
        rpm) dnf -y install "$PACKAGE" ;;
    esac
}

require_directory() {
    required_directory=$1
    [ -d "$required_directory" ] && [ ! -L "$required_directory" ] || fail "missing package directory: $required_directory"
    [ "$(stat -c '%a' "$required_directory")" = 755 ] || fail "unsafe directory mode: $required_directory"
}

require_file_mode() {
    required_file=$1
    required_mode=$2
    [ -f "$required_file" ] && [ ! -L "$required_file" ] || fail "missing package file: $required_file"
    [ "$(stat -c '%a' "$required_file")" = "$required_mode" ] || fail "unexpected file mode: $required_file"
}

validate_manifest_symlinks() {
    manifest=$TEMP_ROOT/installed-files
    case "$KIND" in
        deb) dpkg-query -L "$PROGRAM" > "$manifest" ;;
        rpm) rpm -ql "$PROGRAM" > "$manifest" ;;
    esac
    while IFS= read -r installed_path; do
        [ ! -L "$installed_path" ] || fail "package-owned symlink is forbidden: $installed_path"
        case "$installed_path" in
            /.|/usr|/usr/bin|/usr/lib|/usr/share|\
            /usr/share/applications|/usr/share/icons|/usr/share/icons/hicolor|\
            /usr/share/icons/hicolor/256x256|/usr/share/icons/hicolor/256x256/apps|\
            /usr/share/doc|/usr/lib/object-storage-client|/usr/lib/object-storage-client/*|\
            /usr/bin/object-storage-client|\
            /usr/share/applications/object-storage-client.desktop|\
            /usr/share/icons/hicolor/256x256/apps/object-storage-client.png|\
            /usr/share/doc/object-storage-client|\
            /usr/share/doc/object-storage-client/README.md|\
            /usr/share/doc/object-storage-client/PRIVACY.md|\
            /usr/share/doc/object-storage-client/LICENSE) ;;
            *) fail "unapproved package path: $installed_path" ;;
        esac
    done < "$manifest"
}

validate_installed_files() {
    require_directory /usr/lib/object-storage-client
    require_directory /usr/share/doc/object-storage-client
    require_file_mode /usr/bin/object-storage-client 755
    require_file_mode /usr/lib/object-storage-client/ObjectStorageClient.App 755
    require_file_mode /usr/share/applications/object-storage-client.desktop 644
    require_file_mode /usr/share/icons/hicolor/256x256/apps/object-storage-client.png 644
    require_file_mode /usr/share/doc/object-storage-client/README.md 644
    require_file_mode /usr/share/doc/object-storage-client/PRIVACY.md 644
    require_file_mode /usr/share/doc/object-storage-client/LICENSE 644
    validate_manifest_symlinks
    desktop-file-validate /usr/share/applications/object-storage-client.desktop
}

print_launch_logs() {
    printf '%s\n' '--- Xvfb log ---' >&2
    if [ -f "$TEMP_ROOT/xvfb.log" ]; then
        sed -n '1,200p' "$TEMP_ROOT/xvfb.log" >&2
    fi
    printf '%s\n' '--- application log ---' >&2
    if [ -f "$TEMP_ROOT/application.log" ]; then
        sed -n '1,200p' "$TEMP_ROOT/application.log" >&2
    fi
}

launch_under_xvfb() {
    Xvfb :99 -screen 0 1024x768x24 > "$TEMP_ROOT/xvfb.log" 2>&1 &
    XVFB_PID=$!

    display_attempt=0
    while ! xdpyinfo -display :99 >/dev/null 2>&1; do
        if ! kill -0 "$XVFB_PID" 2>/dev/null || [ "$display_attempt" -ge 30 ]; then
            print_launch_logs
            fail "Xvfb did not become ready"
        fi
        sleep 1
        display_attempt=$((display_attempt + 1))
    done

    DISPLAY=:99 /usr/bin/object-storage-client > "$TEMP_ROOT/application.log" 2>&1 &
    APP_PID=$!
    SMOKE_SECONDS=15
    elapsed=0
    while [ "$elapsed" -lt "$SMOKE_SECONDS" ]; do
        if ! kill -0 "$APP_PID" 2>/dev/null; then
            wait "$APP_PID" 2>/dev/null || :
            APP_PID=
            print_launch_logs
            fail "application exited before 15 seconds"
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    if ! kill -0 "$APP_PID" 2>/dev/null; then
        wait "$APP_PID" 2>/dev/null || :
        APP_PID=
        print_launch_logs
        fail "application did not remain alive for 15 seconds"
    fi

    stop_process "$APP_PID"
    APP_PID=
    stop_process "$XVFB_PID"
    XVFB_PID=
}

preserve_user_fixture_on_remove() {
    case "$KIND" in
        deb) DEBIAN_FRONTEND=noninteractive apt-get remove -y object-storage-client ;;
        rpm) dnf -y remove object-storage-client ;;
    esac

    for removed_path in \
        /usr/bin/object-storage-client \
        /usr/lib/object-storage-client \
        /usr/share/applications/object-storage-client.desktop \
        /usr/share/icons/hicolor/256x256/apps/object-storage-client.png \
        /usr/share/doc/object-storage-client
    do
        [ ! -e "$removed_path" ] && [ ! -L "$removed_path" ] || fail "package path remains after removal: $removed_path"
    done
    [ -f "$FIXTURE" ] && [ ! -L "$FIXTURE" ] || fail "user fixture was removed"
    [ "$(cat "$FIXTURE")" = "$FIXTURE_BYTES" ] || fail "user fixture bytes changed"
}

validate_repository_key() {
    key_listing=$TEMP_ROOT/repository-key.colons
    GNUPGHOME=$GPG_HOME gpg --batch --show-keys --with-colons "$REPOSITORY_KEY" > "$key_listing" 2>/dev/null || fail "repository key is invalid"
    public_primary_count=$(awk -F: '$1 == "pub" { count += 1 } END { print count + 0 }' "$key_listing")
    secret_record_count=$(awk -F: '$1 == "sec" || $1 == "ssb" { count += 1 } END { print count + 0 }' "$key_listing")
    [ "$public_primary_count" -eq 1 ] || fail "repository key must contain exactly one public primary key"
    [ "$secret_record_count" -eq 0 ] || fail "repository key must not contain secret key material"
}

install_from_repository() {
    validate_repository_key
    case "$KIND" in
        deb)
            install -d -m 0755 /etc/apt/keyrings
            rm -f /etc/apt/keyrings/object-storage-client.gpg
            GNUPGHOME=$GPG_HOME gpg --batch --yes --dearmor --output /etc/apt/keyrings/object-storage-client.gpg "$REPOSITORY_KEY"
            chmod 0644 /etc/apt/keyrings/object-storage-client.gpg
            printf 'deb [arch=amd64 signed-by=/etc/apt/keyrings/object-storage-client.gpg] %s stable main\n' \
                "$REPOSITORY_URL/apt" > /etc/apt/sources.list.d/object-storage-client.list
            chmod 0644 /etc/apt/sources.list.d/object-storage-client.list
            apt-get update
            DEBIAN_FRONTEND=noninteractive apt-get install -y object-storage-client
            ;;
        rpm)
            install -d -m 0755 /etc/pki/rpm-gpg /etc/yum.repos.d
            install -m 0644 "$REPOSITORY_KEY" /etc/pki/rpm-gpg/object-storage-client.asc
            {
                printf '%s\n' '[object-storage-client]'
                printf '%s\n' 'name=Object Storage Client'
                printf 'baseurl=%s\n' "$REPOSITORY_URL/rpm/stable/x86_64"
                printf '%s\n' 'enabled=1'
                printf '%s\n' 'gpgcheck=1'
                printf '%s\n' 'repo_gpgcheck=1'
                printf '%s\n' 'gpgkey=file:///etc/pki/rpm-gpg/object-storage-client.asc'
            } > /etc/yum.repos.d/object-storage-client.repo
            chmod 0644 /etc/yum.repos.d/object-storage-client.repo
            dnf -y clean metadata
            dnf -y makecache
            dnf -y install object-storage-client
            ;;
    esac
}

print_installed_identity() {
    case "$KIND" in
        deb) dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\n' object-storage-client ;;
        rpm) rpm -q --qf '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n' object-storage-client ;;
    esac
}

install_dependencies
install_local_package
validate_installed_files
launch_under_xvfb
preserve_user_fixture_on_remove
install_from_repository
validate_installed_files
print_installed_identity
