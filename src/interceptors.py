import json
import re
import threading
import subprocess

import gi
gi.require_version("WebKit2", "4.1")
from gi.repository import WebKit2, GLib, GObject

BLOCKED_DOMAINS = {
    "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "google-analytics.com", "googletagmanager.com", "googletagservices.com",
    "adservice.google.com", "pagead2.googlesyndication.com",
    "partner.googleadservices.com", "ad.doubleclick.net",
    "adsrvr.org", "adsymptotic.com", "adzerk.net", "amazon-adsystem.com",
    "casalemedia.com", "criteo.com", "criteo.net",
    "exponential.com", "facebook.com/tr", "moatads.com",
    "outbrain.com", "pubmatic.com", "quantserve.com",
    "rubiconproject.com", "scorecardresearch.com", "serving-sys.com",
    "sharethis.com", "taboola.com", "tribalfusion.com",
    "yieldmanager.com", "yieldmo.com",
}

TRACKER_DOMAINS = {
    "facebook.com", "twitter.com", "t.co", "instagram.com",
    "linkedin.com", "pinterest.com", "reddit.com",
    "snapchat.com", "tumblr.com", "x.com",
}

YOUTUBE_PATTERNS = [
    re.compile(r"^https?://(www\.)?youtube\.com/watch\?.*v=[\w-]+"),
    re.compile(r"^https?://(www\.)?youtube\.com/v/[\w-]+"),
    re.compile(r"^https?://(www\.)?youtube\.com/embed/[\w-]+"),
    re.compile(r"^https?://(www\.)?youtube\.com/shorts/[\w-]+"),
    re.compile(r"^https?://youtu\.be/[\w-]+"),
    re.compile(r"^https?://m\.youtube\.com/watch\?.*v=[\w-]+"),
]


def is_youtube_url(uri):
    return any(p.match(uri) for p in YOUTUBE_PATTERNS)


def build_adblock_rules():
    rules = []
    for domain in BLOCKED_DOMAINS:
        escaped = re.escape(domain).replace(r"\.", "\\.")
        rules.append({
            "trigger": {
                "url-filter": f".*[.]{escaped}/.*",
                "resource-type": ["image", "script", "stylesheet",
                                  "xmlhttprequest", "font", "media", "other"],
            },
            "action": {"type": "block"},
        })
    for domain in TRACKER_DOMAINS:
        escaped = re.escape(domain).replace(r"\.", "\\.")
        rules.append({
            "trigger": {
                "url-filter": f".*[.]{escaped}/.*",
                "resource-type": ["image", "script", "xmlhttprequest",
                                  "font", "other"],
            },
            "action": {"type": "block"},
        })
    return rules


def init_content_filter_store():
    import os
    cache_dir = os.path.expanduser("~/.cache/netron-browser/ads")
    os.makedirs(cache_dir, exist_ok=True)
    store = WebKit2.UserContentFilterStore.new(cache_dir)
    return store


def get_or_create_filter(store, callback):
    def on_load(store, result):
        try:
            filt = store.load_finish(result)
            if filt:
                callback(filt)
                return
        except GLib.Error:
            pass
        rules = build_adblock_rules()
        rules_json = json.dumps(rules)
        rules_bytes = GLib.Bytes.new(rules_json.encode("utf-8"))
        store.save("adblock", rules_bytes, None,
                   lambda s, r: _on_saved(s, r, callback))

    def _on_saved(store, result, cb):
        try:
            filt = store.save_finish(result)
            if filt:
                cb(filt)
        except GLib.Error:
            cb(None)

    store.load("adblock", None, on_load)


def launch_ytdlp(url, callback=None):
    def _run():
        try:
            yt = subprocess.Popen(
                ["yt-dlp", "--no-playlist", "--no-warnings",
                 "--ignore-errors", "-f", "best[height<=480]",
                 "-o", "-", url],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            subprocess.Popen(
                ["mpv", "--no-video", "--cache=yes", "--cache-secs=60", "-"],
                stdin=yt.stdout, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            yt.stdout.close()
            yt.wait()
        except FileNotFoundError:
            subprocess.Popen(
                ["xterm", "-e", "echo 'yt-dlp or mpv not found'; sleep 3"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        if callback:
            GObject.idle_add(callback)

    threading.Thread(target=_run, daemon=True).start()
