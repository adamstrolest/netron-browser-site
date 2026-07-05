# Netron Browser

A lightweight WebKitGTK browser for low-end 32-bit machines. Uses yt-dlp + mpv for YouTube (5% CPU instead of 100%).

## Features

- Tabbed browsing with session restore
- YouTube-to-mpv redirection via yt-dlp
- Ad blocking (built-in filter list)
- Bookmark manager with Chrome/Firefox HTML import
- History with search and autocomplete
- Per-site zoom levels
- Custom themes and new tab pages
- Private / ephemeral browsing mode
- Download shelf (Chrome-style bottom bar)
- Fullscreen, Print to PDF, Screenshot
- Cookie policies (Always, Never, Same-site only)
- User Agent switching
- Privacy controls (JS, WebGL, WebAudio, media stream)

## Quick Start

```bash
sudo apt install python3-gi gir1.2-webkit2-4.1 gir1.2-gtk-3.0 gir1.2-pango-1.0 gir1.2-gdkpixbuf-2.0 gir1.2-notify-0.7 yt-dlp mpv
git clone https://github.com/adamstrolest/netron-browser-site.git
cd netron-browser-site/src
python3 netron.py
```

## Install via APT

```bash
echo "deb [signed-by=/usr/share/keyrings/netron-browser.gpg] https://adamstrolest.github.io/netron-browser-apt stable main" | sudo tee /etc/apt/sources.list.d/netron-browser.list
sudo apt update && sudo apt install netron-browser
```

## License

GNU General Public License v3.0
