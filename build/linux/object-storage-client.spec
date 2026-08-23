Name: object-storage-client
Version: @VERSION@
Release: @RELEASE@%{?dist}
Summary: Desktop client for S3-compatible object storage
License: MIT
URL: https://github.com/devcode-kr/object-storage-client
Source0: @SOURCE@
BuildArch: x86_64
Requires: libX11
Requires: libICE
Requires: libSM
Requires: fontconfig
Requires: ca-certificates

%description
Browse local files and remote S3-compatible object storage in a two-pane interface.

%prep
%setup -q -c -T
%{__tar} -xzf %{SOURCE0}

%build

%install
rm -rf %{buildroot}
mkdir -p %{buildroot}
cp -a .%{_prefix} %{buildroot}/

%files
%license /usr/share/doc/object-storage-client/LICENSE
%doc /usr/share/doc/object-storage-client/README.md
%doc /usr/share/doc/object-storage-client/PRIVACY.md
/usr/bin/object-storage-client
/usr/lib/object-storage-client/
/usr/share/applications/object-storage-client.desktop
/usr/share/icons/hicolor/256x256/apps/object-storage-client.png
