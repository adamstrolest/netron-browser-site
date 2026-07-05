import json
import os
import time
from dataclasses import dataclass, asdict, field

DATA_DIR = os.path.expanduser("~/.config/netron-browser")

def ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def read_json(name):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)

def write_json(name, data):
    ensure_dir()
    path = os.path.join(DATA_DIR, name)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

@dataclass
class Bookmark:
    title: str
    url: str
    created: float = field(default_factory=time.time)

class BookmarkStore:
    def __init__(self):
        self.items: list[Bookmark] = []
        self.load()

    def load(self):
        raw = read_json("bookmarks.json")
        self.items = [Bookmark(**b) for b in raw] if raw else []

    def save(self):
        write_json("bookmarks.json", [asdict(b) for b in self.items])

    def add(self, title, url):
        self.items.append(Bookmark(title, url))
        self.save()

    def remove(self, index):
        if 0 <= index < len(self.items):
            del self.items[index]
            self.save()

    def contains(self, url):
        return any(b.url == url for b in self.items)

@dataclass
class HistoryEntry:
    title: str
    url: str
    visit_time: float = field(default_factory=time.time)

class HistoryStore:
    MAX = 5000

    def __init__(self):
        self.entries: list[HistoryEntry] = []
        self.load()

    def load(self):
        raw = read_json("history.json")
        self.entries = [HistoryEntry(**h) for h in raw] if raw else []

    def save(self):
        write_json("history.json", [asdict(h) for h in self.entries])

    def add(self, title, url):
        self.entries.append(HistoryEntry(title, url, time.time()))
        if len(self.entries) > self.MAX:
            self.entries = self.entries[-self.MAX:]
        self.save()

    def search(self, query=""):
        q = query.lower()
        results = reversed(self.entries[-200:])
        if not q:
            return list(results)
        return [h for h in results if q in h.url.lower() or q in h.title.lower()]

    def clear(self):
        self.entries.clear()
        self.save()

class SessionStore:
    def __init__(self):
        self.tabs: list[str] = []

    def load(self):
        raw = read_json("session.json")
        self.tabs = raw if raw else []

    def save(self, tabs):
        self.tabs = tabs
        write_json("session.json", tabs)

class ZoomStore:
    def __init__(self):
        self._zooms: dict[str, float] = {}
        self.load()

    def load(self):
        raw = read_json("zoom.json")
        self._zooms = raw if raw else {}

    def get(self, domain):
        return self._zooms.get(domain, 1.0)

    def set(self, domain, level):
        self._zooms[domain] = level
        write_json("zoom.json", self._zooms)


class SettingsStore:
    DEFAULTS = {
        # General
        "home_page": "https://www.google.com",
        "search_engine": "https://www.google.com/search?q={}",
        "download_dir": os.path.expanduser("~/Downloads"),
        "confirm_downloads": True,
        "default_zoom": 1.0,

        # Performance
        "javascript_enabled": True,
        "webaudio_enabled": False,
        "media_stream_enabled": False,
        "webgl_enabled": False,
        "webrtc_enabled": False,
        "encrypted_media_enabled": False,
        "smooth_scrolling_enabled": False,
        "plugins_enabled": False,
        "page_cache_enabled": False,
        "dns_prefetching_enabled": False,
        "hardware_acceleration": False,

        # Privacy
        "adblock_enabled": True,
        "youtube_handler_enabled": True,
        "do_not_track": False,
        "cookie_policy": "always",  # always, never, same-site
        "clear_on_exit": False,

        # Security
        "javascript_can_open_windows": True,
        "enable_hyperlink_auditing": False,
        "enable_websecurity": True,
        "enable_fullscreen": True,
        "enable_mediasource": True,

        # New Tab
        "newtab_enabled": True,
        "newtab_heading": "Netron",
        "newtab_search_placeholder": "Search or enter URL...",
        "newtab_background": "#f5f5f5",
        "newtab_bg_image": "",
        "newtab_text_color": "#333",
        "newtab_accent_color": "#4a90d9",
        "newtab_show_quick_links": True,
        "newtab_max_links": 9,
        "newtab_show_search": True,

        # Theme
        "theme": "default",  # default, dark, light
        "theme_accent": "#4a90d9",
        "theme_dark_bg": "#1e1e1e",
        "theme_dark_fg": "#e0e0e0",

        # Default Apps
        "default_browser_registered": False,
        "mailto_handler": "",
        "ftp_handler": "xdg-open",

        # User Agent
        "user_agent_preset": "default",  # default, chrome, firefox, safari, custom
        "user_agent_custom": "",
    }

    UA_PRESETS = {
        "default": "",
        "chrome": "Mozilla/5.0 (X11; Linux i686) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "firefox": "Mozilla/5.0 (X11; Linux i686; rv:125.0) Gecko/20100101 Firefox/125.0",
        "safari": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    }

    def __init__(self):
        self._data = dict(self.DEFAULTS)
        self.load()

    def load(self):
        raw = read_json("settings.json")
        if raw:
            self._data.update(raw)

    def save(self):
        write_json("settings.json", self._data)

    def get(self, key):
        return self._data.get(key, self.DEFAULTS.get(key))

    def get_user_agent(self):
        preset = self.get("user_agent_preset")
        if preset == "custom":
            return self.get("user_agent_custom")
        return self.UA_PRESETS.get(preset, "")

    def set(self, key, value):
        self._data[key] = value
        self.save()
