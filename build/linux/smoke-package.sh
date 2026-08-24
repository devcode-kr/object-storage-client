#!/bin/sh
set -eu

umask 022

PROGRAM=object-storage-client
FIXTURE=/root/.devcode/$PROGRAM/preserve-me
FIXTURE_BYTES=object-storage-client-smoke-preserve-v1
REPOSITORY_URL=${REPOSITORY_URL:-http://repository:8000}
OS_RELEASE_FILE=${OS_RELEASE_FILE:-/etc/os-release}
SMOKE_ROOT=${SMOKE_ROOT:-}
PACKAGE_MANAGER_TIMEOUT_SECONDS=300
GPG_TIMEOUT_SECONDS=30
DESKTOP_VALIDATE_TIMEOUT_SECONDS=30
APP_PID=
XVFB_PID=
ACTIVE_COMMAND_PID=
TEMP_ROOT=
GPG_HOME=
PACKAGE=
REPOSITORY_KEY=
PACKAGE_SNAPSHOT=
REPOSITORY_KEY_SNAPSHOT=
CLEANED=0

fail() {
    printf 'smoke-package: %s\n' "$*" >&2
    exit 1
}

run_with_timeout() {
    timeout_seconds=$1
    shift
    timeout --kill-after=10s "$timeout_seconds" "$@" &
    ACTIVE_COMMAND_PID=$!
    if wait "$ACTIVE_COMMAND_PID"; then
        timeout_status=0
    else
        timeout_status=$?
    fi
    ACTIVE_COMMAND_PID=
    return "$timeout_status"
}

stop_active_command() {
    active_pid=$1
    case "$active_pid" in
        ''|*[!0-9]*) return 0 ;;
    esac
    [ "$active_pid" -gt 1 ] || return 0
    [ "$active_pid" != "$$" ] || return 0

    if ! kill -TERM "-$active_pid" 2>/dev/null; then
        kill -TERM "$active_pid" 2>/dev/null || :
    fi

    active_stop_attempt=0
    while [ "$active_stop_attempt" -lt 20 ]; do
        if ! kill -0 "-$active_pid" 2>/dev/null && ! kill -0 "$active_pid" 2>/dev/null; then
            break
        fi
        sleep 0.1
        active_stop_attempt=$((active_stop_attempt + 1))
    done

    if kill -0 "-$active_pid" 2>/dev/null || kill -0 "$active_pid" 2>/dev/null; then
        if ! kill -KILL "-$active_pid" 2>/dev/null; then
            kill -KILL "$active_pid" 2>/dev/null || :
        fi
    fi
    wait "$active_pid" 2>/dev/null || :
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
    [ "$CLEANED" -eq 0 ] || return 0
    CLEANED=1
    stop_active_command "$ACTIVE_COMMAND_PID"
    ACTIVE_COMMAND_PID=
    stop_process "$APP_PID"
    APP_PID=
    stop_process "$XVFB_PID"
    XVFB_PID=
    if [ -n "$TEMP_ROOT" ] && [ -d "$TEMP_ROOT" ] && [ ! -L "$TEMP_ROOT" ]; then
        rm -rf -- "$TEMP_ROOT"
    fi
}

handle_hup() {
    trap - HUP
    cleanup
    exit 129
}

handle_int() {
    trap - INT
    cleanup
    exit 130
}

handle_term() {
    trap - TERM
    cleanup
    exit 143
}

select_xdpyinfo_package() {
    if [ ! -f "$OS_RELEASE_FILE" ]; then
        fail "os-release must resolve to a regular file"
    fi
    os_id=$(awk -F= '
        $1 == "ID" {
            value = substr($0, index($0, "=") + 1)
            gsub(/^"|"$/, "", value)
            print value
            exit
        }
    ' "$OS_RELEASE_FILE")
    case "$os_id" in
        fedora) printf '%s\n' xdpyinfo ;;
        rocky|almalinux|rhel) printf '%s\n' xorg-x11-utils ;;
        *) fail "unsupported RPM distribution ID: ${os_id:-missing}" ;;
    esac
}

snapshot_inputs() {
    case "$KIND" in
        deb) snapshot_suffix=.deb ;;
        rpm) snapshot_suffix=.rpm ;;
        *) fail "package kind must be deb or rpm" ;;
    esac
    PACKAGE_SNAPSHOT=$TEMP_ROOT/package$snapshot_suffix
    REPOSITORY_KEY_SNAPSHOT=$TEMP_ROOT/repository-key.asc
    install -m 0444 "$PACKAGE" "$PACKAGE_SNAPSHOT"
    if [ ! -f "$PACKAGE" ] || [ -L "$PACKAGE" ]; then
        fail "package source changed while snapshotting"
    fi
    if [ ! -f "$PACKAGE_SNAPSHOT" ] || [ -L "$PACKAGE_SNAPSHOT" ]; then
        fail "package snapshot is not a regular file"
    fi
    install -m 0600 "$REPOSITORY_KEY" "$REPOSITORY_KEY_SNAPSHOT"
    if [ ! -f "$REPOSITORY_KEY" ] || [ -L "$REPOSITORY_KEY" ]; then
        fail "repository key source changed while snapshotting"
    fi
    if [ ! -f "$REPOSITORY_KEY_SNAPSHOT" ] || [ -L "$REPOSITORY_KEY_SNAPSHOT" ]; then
        fail "repository key snapshot is not a regular file"
    fi
    PACKAGE=$PACKAGE_SNAPSHOT
    REPOSITORY_KEY=$REPOSITORY_KEY_SNAPSHOT
}

install_dependencies() {
    case "$KIND" in
        deb)
            install -d -m 0755 /etc/dpkg/dpkg.cfg.d
            printf '%s\n' 'path-include=/usr/share/doc/object-storage-client/*' \
                > /etc/dpkg/dpkg.cfg.d/99-object-storage-client-smoke
            chmod 0644 /etc/dpkg/dpkg.cfg.d/99-object-storage-client-smoke
            run_with_timeout "$PACKAGE_MANAGER_TIMEOUT_SECONDS" apt-get update
            run_with_timeout "$PACKAGE_MANAGER_TIMEOUT_SECONDS" env DEBIAN_FRONTEND=noninteractive apt-get install -y \
                libx11-6 libice6 libsm6 libfontconfig1 ca-certificates \
                xvfb desktop-file-utils curl gnupg procps x11-utils
            ;;
        rpm)
            xdpyinfo_package=$(select_xdpyinfo_package)
            run_with_timeout "$PACKAGE_MANAGER_TIMEOUT_SECONDS" dnf -y install \
                libX11 libICE libSM fontconfig ca-certificates \
                xorg-x11-server-Xvfb desktop-file-utils curl gnupg2 procps-ng \
                "$xdpyinfo_package"
            ;;
    esac
    command -v xdpyinfo >/dev/null 2>&1 || fail "xdpyinfo is unavailable after dependency installation"
}

install_local_package() {
    install -d -m 0755 "$(dirname "$FIXTURE")"
    printf '%s' "$FIXTURE_BYTES" > "$FIXTURE"
    chmod 0644 "$FIXTURE"

    case "$KIND" in
        deb) run_with_timeout "$PACKAGE_MANAGER_TIMEOUT_SECONDS" env DEBIAN_FRONTEND=noninteractive apt-get install -y "$PACKAGE" ;;
        rpm) run_with_timeout "$PACKAGE_MANAGER_TIMEOUT_SECONDS" dnf -y install "$PACKAGE" ;;
    esac
}

rooted_path() {
    printf '%s%s\n' "$SMOKE_ROOT" "$1"
}

validate_entry_metadata() {
    installed_path=$1
    actual_path=$(rooted_path "$installed_path")
    [ -e "$actual_path" ] || [ -L "$actual_path" ] || fail "package manifest path does not exist: $installed_path"
    [ ! -L "$actual_path" ] || fail "package-owned symlink is forbidden: $installed_path"
    metadata=$(stat -c '%F|%u|%g|%a' "$actual_path") || fail "cannot stat package path: $installed_path"
    entry_type=${metadata%%|*}
    metadata=${metadata#*|}
    entry_uid=${metadata%%|*}
    metadata=${metadata#*|}
    entry_gid=${metadata%%|*}
    entry_mode=${metadata##*|}
    if [ "$entry_uid" != 0 ] || [ "$entry_gid" != 0 ]; then
        fail "package path is not root-owned: $installed_path"
    fi
    case "$entry_type" in
        directory)
            [ "$entry_mode" = 755 ] || fail "unsafe directory mode: $installed_path"
            ;;
        "regular file")
            case "$entry_mode" in
                644|755) ;;
                *) fail "unsafe regular file mode: $installed_path" ;;
            esac
            ;;
        *) fail "unsupported package entry type: $installed_path ($entry_type)" ;;
    esac
}

validate_manifest_entries() {
    manifest=$TEMP_ROOT/installed-files
    case "$KIND" in
        deb) dpkg-query -L "$PROGRAM" > "$manifest" ;;
        rpm) rpm -ql "$PROGRAM" > "$manifest" ;;
        *) fail "package kind must be deb or rpm" ;;
    esac
    manifest_count=0
    while IFS= read -r installed_path; do
        [ -n "$installed_path" ] || fail "package manifest contains an empty path"
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
        validate_entry_metadata "$installed_path"
        manifest_count=$((manifest_count + 1))
    done < "$manifest"
    [ "$manifest_count" -gt 0 ] || fail "package manifest is empty"
}

require_directory() {
    required_path=$1
    required_directory=$(rooted_path "$required_path")
    if [ ! -d "$required_directory" ] || [ -L "$required_directory" ]; then
        fail "missing package directory: $required_path"
    fi
    metadata=$(stat -c '%u|%g|%a' "$required_directory") || fail "cannot stat package directory: $required_path"
    [ "$metadata" = '0|0|755' ] || fail "unexpected directory ownership or mode: $required_path"
}

require_file_mode() {
    required_path=$1
    required_mode=$2
    required_file=$(rooted_path "$required_path")
    if [ ! -f "$required_file" ] || [ -L "$required_file" ]; then
        fail "missing package file: $required_path"
    fi
    metadata=$(stat -c '%u|%g|%a' "$required_file") || fail "cannot stat package file: $required_path"
    [ "$metadata" = "0|0|$required_mode" ] || fail "unexpected file ownership or mode: $required_path"
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
    validate_manifest_entries
    run_with_timeout "$DESKTOP_VALIDATE_TIMEOUT_SECONDS" desktop-file-validate "$(rooted_path /usr/share/applications/object-storage-client.desktop)"
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
        deb) run_with_timeout "$PACKAGE_MANAGER_TIMEOUT_SECONDS" env DEBIAN_FRONTEND=noninteractive apt-get remove -y object-storage-client ;;
        rpm) run_with_timeout "$PACKAGE_MANAGER_TIMEOUT_SECONDS" dnf -y remove object-storage-client ;;
    esac

    for removed_path in \
        /usr/bin/object-storage-client \
        /usr/lib/object-storage-client \
        /usr/share/applications/object-storage-client.desktop \
        /usr/share/icons/hicolor/256x256/apps/object-storage-client.png \
        /usr/share/doc/object-storage-client
    do
        if [ -e "$removed_path" ] || [ -L "$removed_path" ]; then
            fail "package path remains after removal: $removed_path"
        fi
    done
    if [ ! -f "$FIXTURE" ] || [ -L "$FIXTURE" ]; then
        fail "user fixture was removed"
    fi
    [ "$(cat "$FIXTURE")" = "$FIXTURE_BYTES" ] || fail "user fixture bytes changed"
}

validate_repository_key() {
    key_listing=$TEMP_ROOT/repository-key.colons
    run_with_timeout "$GPG_TIMEOUT_SECONDS" env GNUPGHOME="$GPG_HOME" gpg --batch --show-keys --with-colons "$REPOSITORY_KEY" > "$key_listing" 2>/dev/null || fail "repository key is invalid"
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
            run_with_timeout "$GPG_TIMEOUT_SECONDS" env GNUPGHOME="$GPG_HOME" gpg --batch --yes --dearmor --output /etc/apt/keyrings/object-storage-client.gpg "$REPOSITORY_KEY"
            chmod 0644 /etc/apt/keyrings/object-storage-client.gpg
            printf 'deb [arch=amd64 signed-by=/etc/apt/keyrings/object-storage-client.gpg] %s stable main\n' \
                "$REPOSITORY_URL/apt" > /etc/apt/sources.list.d/object-storage-client.list
            chmod 0644 /etc/apt/sources.list.d/object-storage-client.list
            run_with_timeout "$PACKAGE_MANAGER_TIMEOUT_SECONDS" apt-get update
            run_with_timeout "$PACKAGE_MANAGER_TIMEOUT_SECONDS" env DEBIAN_FRONTEND=noninteractive apt-get install -y object-storage-client
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
            run_with_timeout "$PACKAGE_MANAGER_TIMEOUT_SECONDS" dnf -y clean metadata
            run_with_timeout "$PACKAGE_MANAGER_TIMEOUT_SECONDS" dnf -y makecache
            run_with_timeout "$PACKAGE_MANAGER_TIMEOUT_SECONDS" dnf -y install object-storage-client
            ;;
    esac
}

print_installed_identity() {
    case "$KIND" in
        deb) dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\n' object-storage-client ;;
        rpm) rpm -q --qf '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n' object-storage-client ;;
    esac
}

main() {
    [ "$#" -eq 3 ] || fail "usage: smoke-package.sh deb|rpm PACKAGE REPOSITORY"
    KIND=$1
    PACKAGE=$2
    REPOSITORY=$3

    case "$KIND" in
        deb|rpm) ;;
        *) fail "package kind must be deb or rpm" ;;
    esac

    if [ ! -f "$PACKAGE" ] || [ -L "$PACKAGE" ]; then
        fail "package must be a regular non-symlink file"
    fi
    if [ ! -d "$REPOSITORY" ] || [ -L "$REPOSITORY" ]; then
        fail "repository must be a non-symlink directory"
    fi
    REPOSITORY_KEY=$REPOSITORY/repository-key.asc
    if [ ! -f "$REPOSITORY_KEY" ] || [ -L "$REPOSITORY_KEY" ]; then
        fail "repository-key.asc must be a regular non-symlink file"
    fi

    case "$REPOSITORY_URL" in
        http://?*|https://?*) ;;
        *) fail "REPOSITORY_URL must use http:// or https://" ;;
    esac
    case "$REPOSITORY_URL" in
        *[!A-Za-z0-9._:/%-]*) fail "REPOSITORY_URL contains unsafe characters" ;;
    esac

    [ "$(id -u)" -eq 0 ] || fail "root privileges are required"
    command -v timeout >/dev/null 2>&1 || fail "timeout command is required"
    TEMP_ROOT=$(mktemp -d /tmp/object-storage-client-smoke.XXXXXX)
    trap cleanup 0
    trap handle_hup HUP
    trap handle_int INT
    trap handle_term TERM
    GPG_HOME=$TEMP_ROOT/gnupg
    install -d -m 0700 "$GPG_HOME"
    snapshot_inputs

    install_dependencies
    install_local_package
    validate_installed_files
    launch_under_xvfb
    preserve_user_fixture_on_remove
    install_from_repository
    validate_installed_files
    print_installed_identity
}

[ "${SMOKE_PACKAGE_LIBRARY_ONLY:-0}" = 1 ] || main "$@"
