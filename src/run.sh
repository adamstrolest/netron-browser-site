#!/bin/sh
cd "$(dirname "$0")"

python3 -c "import gi; gi.require_version('WebKit2', '4.1'); from gi.repository import WebKit2" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Installing dependencies..."
    sudo apt-get update
    sudo apt-get install -y python3-gi python3-gi-cairo gir1.2-webkit2-4.1 yt-dlp mpv xdg-utils
fi

if ! command -v yt-dlp >/dev/null 2>&1; then
    echo "Warning: yt-dlp not found. Install: sudo apt install yt-dlp"
fi
if ! command -v mpv >/dev/null 2>&1; then
    echo "Warning: mpv not found. Install: sudo apt install mpv"
fi

echo "Launching Netron Browser..."
exec python3 netron.py "$@"
