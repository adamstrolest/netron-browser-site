%global pkgname netron-browser
%global pkgver 1.7.0

Name:           %{pkgname}
Version:        %{pkgver}
Release:        1%{?dist}
Summary:        Lightweight WebKitGTK browser with yt-dlp YouTube integration

License:        GPLv3
URL:            https://adamstrolest.github.io/netron-browser-site/
Source0:        https://github.com/adamstrolest/netron-browser-site/archive/v%{version}/%{pkgname}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  librsvg2-tools

Requires:       python3-gobject
Requires:       webkit2gtk4.1
Requires:       gtk3
Requires:       python3
Requires:       python3-cairo
Requires:       yt-dlp
Requires:       mpv
Requires:       xdg-utils

%description
A minimal WebKitGTK browser designed for low-end 32-bit machines.
Features ad blocking, tabbed browsing, bookmarks, history,
session restore, per-site zoom, theme support, and YouTube
redirection to yt-dlp + mpv for low-CPU playback.

%prep
%setup -q -n %{pkgname}-%{version}

%build
# Pure Python — nothing to build

%install
# Python sources
install -Dpm 0644 src/browser.py        %{buildroot}%{_datadir}/%{pkgname}/browser.py
install -Dpm 0644 src/dialogs.py        %{buildroot}%{_datadir}/%{pkgname}/dialogs.py
install -Dpm 0644 src/interceptors.py   %{buildroot}%{_datadir}/%{pkgname}/interceptors.py
install -Dpm 0644 src/netron.py         %{buildroot}%{_datadir}/%{pkgname}/netron.py
install -Dpm 0644 src/persistence.py    %{buildroot}%{_datadir}/%{pkgname}/persistence.py
install -Dpm 0755 src/run.sh            %{buildroot}%{_datadir}/%{pkgname}/run.sh

# Wrapper script
install -Dpm 0755 /dev/stdin %{buildroot}%{_bindir}/%{pkgname} <<'WRAPPER'
#!/bin/sh
exec /usr/bin/python3 %{_datadir}/%{pkgname}/netron.py "$@"
WRAPPER

# Desktop file
desktop-file-install --dir=%{buildroot}%{_datadir}/applications \
    packaging/common/netron-browser.desktop

# SVG icon
install -Dpm 0644 packaging/common/netron-browser.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/%{pkgname}.svg

# PNG fallback
install -Dpm 0644 packaging/common/netron-browser.png \
    %{buildroot}%{_datadir}/pixmaps/%{pkgname}.png

# Generate PNG icons from SVG
for size in 16 22 24 32 48 64 96 128 256; do
    dir="%{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps"
    mkdir -p "$dir"
    rsvg-convert -w "$size" -h "$size" packaging/common/netron-browser.svg \
        -o "$dir/%{pkgname}.png"
done

%files
%{_datadir}/%{pkgname}/
%{_bindir}/%{pkgname}
%{_datadir}/applications/%{pkgname}.desktop
%{_datadir}/icons/hicolor/*/apps/%{pkgname}.png
%{_datadir}/icons/hicolor/scalable/apps/%{pkgname}.svg
%{_datadir}/pixmaps/%{pkgname}.png

%changelog
* Sun Jul 05 2026 Adam <adam@example.com> - 1.7.0-1
- Initial Fedora package
