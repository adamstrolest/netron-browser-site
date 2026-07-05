import os
import subprocess
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _rw(entry):
    """Make an entry read-write for code size."""
    pass


def _cb(label, active):
    c = Gtk.CheckButton(label=label)
    c.set_active(active)
    return c


class SettingsDialog(Gtk.Dialog):
    def __init__(self, settings, parent=None):
        super().__init__(title="Settings", parent=parent, flags=0)
        self._settings = settings
        self.set_default_size(560, 450)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Save", Gtk.ResponseType.OK)

        nb = Gtk.Notebook()
        self.get_content_area().pack_start(nb, True, True, 0)

        # ---------- General ----------
        general = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        general.set_border_width(12)

        general.pack_start(Gtk.Label("Home page:", xalign=0), False, False, 0)
        self._home = Gtk.Entry()
        self._home.set_text(settings.get("home_page"))
        general.pack_start(self._home, False, False, 0)

        general.pack_start(Gtk.Label("Search URL (use {} for query):", xalign=0), False, False, 0)
        self._search = Gtk.Entry()
        self._search.set_text(settings.get("search_engine"))
        general.pack_start(self._search, False, False, 0)

        general.pack_start(Gtk.Label("Download folder:", xalign=0), False, False, 0)
        dl_box = Gtk.Box(spacing=6)
        self._dl_dir = Gtk.Entry()
        self._dl_dir.set_text(settings.get("download_dir"))
        dl_box.pack_start(self._dl_dir, True, True, 0)
        browse = Gtk.Button("...")
        browse.connect("clicked", self._browse)
        dl_box.pack_start(browse, False, False, 0)
        general.pack_start(dl_box, False, False, 0)

        zoom_box = Gtk.Box(spacing=6)
        zoom_box.pack_start(Gtk.Label("Default zoom:", xalign=0), False, False, 0)
        self._zoom_adj = Gtk.Adjustment(value=settings.get("default_zoom"), lower=0.3,
                                         upper=3.0, step_increment=0.1)
        self._zoom_scale = Gtk.HScale(adjustment=self._zoom_adj)
        self._zoom_scale.set_digits(1)
        self._zoom_scale.set_size_request(120, -1)
        zoom_box.pack_start(self._zoom_scale, False, False, 0)
        general.pack_start(zoom_box, False, False, 0)

        sep = Gtk.HSeparator()
        general.pack_start(sep, False, False, 6)

        # Default browser button
        def _set_default(*a):
            try:
                subprocess.check_call(["xdg-settings", "set", "default-web-browser",
                                       "netron-browser.desktop"])
                self._db_label.set_text("Netron Browser is the default browser.")
            except Exception as e:
                self._db_label.set_text(f"Error: {e}")

        db_box = Gtk.Box(spacing=6)
        db_btn = Gtk.Button("Set as Default Browser")
        db_btn.connect("clicked", _set_default)
        db_box.pack_start(db_btn, False, False, 0)
        self._db_label = Gtk.Label("")
        db_box.pack_start(self._db_label, False, False, 0)
        general.pack_start(db_box, False, False, 0)

        nb.append_page(general, Gtk.Label("General"))

        # ---------- Performance ----------
        perf = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        perf.set_border_width(12)

        perf.pack_start(Gtk.Label(
            "<b>Disable features to reduce CPU/memory usage</b>",
            use_markup=True, xalign=0), False, False, 4)

        self._perf_cbs = {}
        perf_toggles = [
            ("javascript_enabled", "Enable JavaScript"),
            ("webaudio_enabled", "Enable WebAudio"),
            ("media_stream_enabled", "Enable Media Stream (camera/mic)"),
            ("webgl_enabled", "Enable WebGL"),
            ("webrtc_enabled", "Enable WebRTC"),
            ("encrypted_media_enabled", "Enable Encrypted Media (DRM)"),
            ("smooth_scrolling_enabled", "Smooth Scrolling"),
            ("plugins_enabled", "Enable Plugins"),
            ("page_cache_enabled", "Page Cache"),
            ("dns_prefetching_enabled", "DNS Prefetching"),
            ("hardware_acceleration", "Hardware Acceleration"),
        ]
        for key, label in perf_toggles:
            cb = _cb(label, settings.get(key))
            self._perf_cbs[key] = cb
            perf.pack_start(cb, False, False, 0)

        nb.append_page(perf, Gtk.Label("Performance"))

        # ---------- Privacy ----------
        priv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        priv.set_border_width(12)

        self._adblock_cb = _cb("Block ads and trackers", settings.get("adblock_enabled"))
        priv.pack_start(self._adblock_cb, False, False, 0)
        self._yt_cb = _cb("Redirect YouTube to yt-dlp + mpv", settings.get("youtube_handler_enabled"))
        priv.pack_start(self._yt_cb, False, False, 0)
        self._confirm_cb = _cb("Confirm before downloading", settings.get("confirm_downloads"))
        priv.pack_start(self._confirm_cb, False, False, 0)
        self._dnt_cb = _cb("Send Do Not Track header", settings.get("do_not_track"))
        priv.pack_start(self._dnt_cb, False, False, 0)
        self._clear_exit_cb = _cb("Clear cookies and data on exit", settings.get("clear_on_exit"))
        priv.pack_start(self._clear_exit_cb, False, False, 0)

        cookie_box = Gtk.Box(spacing=6)
        cookie_box.pack_start(Gtk.Label("Cookie policy:", xalign=0), False, False, 0)
        self._cookie_policy = Gtk.ComboBoxText()
        self._cookie_policy.append("always", "Always")
        self._cookie_policy.append("never", "Never")
        self._cookie_policy.append("same-site", "Same-site only")
        self._cookie_policy.set_active_id(settings.get("cookie_policy"))
        cookie_box.pack_start(self._cookie_policy, False, False, 0)
        priv.pack_start(cookie_box, False, False, 0)

        nb.append_page(priv, Gtk.Label("Privacy"))

        # ---------- Security ----------
        sec = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sec.set_border_width(12)

        self._sec_cbs = {}
        sec_toggles = [
            ("javascript_can_open_windows", "JavaScript can open windows (no popup block)"),
            ("enable_hyperlink_auditing", "Enable hyperlink auditing (ping attr)"),
            ("enable_websecurity", "Enable web security (same-origin)"),
            ("enable_fullscreen", "Enable Fullscreen API"),
            ("enable_mediasource", "Enable Media Source Extensions"),
        ]
        for key, label in sec_toggles:
            cb = _cb(label, settings.get(key))
            self._sec_cbs[key] = cb
            sec.pack_start(cb, False, False, 0)

        nb.append_page(sec, Gtk.Label("Security"))

        # ---------- New Tab ----------
        nt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        nt.set_border_width(12)

        self._newtab_enabled = _cb("Show custom new tab page", settings.get("newtab_enabled"))
        nt.pack_start(self._newtab_enabled, False, False, 0)

        def _entry_row(label, key, box, width=10):
            h = Gtk.Box(spacing=6)
            h.pack_start(Gtk.Label(label, xalign=0), False, False, 0)
            e = Gtk.Entry()
            e.set_text(settings.get(key))
            e.set_width_chars(width)
            setattr(self, "_nt_" + key, e)
            h.pack_start(e, False, False, 0)
            box.pack_start(h, False, False, 0)

        _entry_row("Heading:", "newtab_heading", nt, 20)
        _entry_row("Search placeholder:", "newtab_search_placeholder", nt, 20)
        self._newtab_show_search = _cb("Show search bar", settings.get("newtab_show_search"))
        nt.pack_start(self._newtab_show_search, False, False, 0)
        self._newtab_show_links = _cb("Show bookmark quick links", settings.get("newtab_show_quick_links"))
        nt.pack_start(self._newtab_show_links, False, False, 0)

        _entry_row("Background color:", "newtab_background", nt)
        # Background image with file chooser
        ih = Gtk.Box(spacing=6)
        ih.pack_start(Gtk.Label("Background image:", xalign=0), False, False, 0)
        ie = Gtk.Entry()
        ie.set_text(settings.get("newtab_bg_image"))
        ie.set_width_chars(30)
        setattr(self, "_nt_newtab_bg_image", ie)
        ih.pack_start(ie, False, False, 0)
        ib = Gtk.Button("Browse")
        ib.connect("clicked", self._on_browse_bg)
        ih.pack_start(ib, False, False, 0)
        nt.pack_start(ih, False, False, 0)
        _entry_row("Text color:", "newtab_text_color", nt)
        _entry_row("Accent color:", "newtab_accent_color", nt)

        nb.append_page(nt, Gtk.Label("New Tab"))

        # ---------- Theme ----------
        theme = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        theme.set_border_width(12)

        tbox = Gtk.Box(spacing=6)
        tbox.pack_start(Gtk.Label("Theme:", xalign=0), False, False, 0)
        self._theme_combo = Gtk.ComboBoxText()
        self._theme_combo.append("default", "Default")
        self._theme_combo.append("dark", "Dark")
        self._theme_combo.append("light", "Light")
        self._theme_combo.set_active_id(settings.get("theme"))
        tbox.pack_start(self._theme_combo, False, False, 0)
        theme.pack_start(tbox, False, False, 0)

        def _tcolor_row(label, key):
            h = Gtk.Box(spacing=6)
            h.pack_start(Gtk.Label(label, xalign=0), False, False, 0)
            e = Gtk.Entry()
            e.set_text(settings.get(key))
            e.set_width_chars(10)
            setattr(self, "_th_" + key, e)
            h.pack_start(e, False, False, 0)
            theme.pack_start(h, False, False, 0)

        _tcolor_row("Accent color:", "theme_accent")
        _tcolor_row("Dark bg color:", "theme_dark_bg")
        _tcolor_row("Dark fg color:", "theme_dark_fg")

        nb.append_page(theme, Gtk.Label("Theme"))

        # ---------- User Agent ----------
        ua = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        ua.set_border_width(12)

        ua.pack_start(Gtk.Label("User agent preset:", xalign=0), False, False, 0)
        self._ua_combo = Gtk.ComboBoxText()
        self._ua_combo.append("default", "Default (WebKit)")
        self._ua_combo.append("chrome", "Chrome 124")
        self._ua_combo.append("firefox", "Firefox 125")
        self._ua_combo.append("safari", "Safari 17")
        self._ua_combo.append("custom", "Custom")
        self._ua_combo.set_active_id(settings.get("user_agent_preset"))
        ua.pack_start(self._ua_combo, False, False, 0)

        ua.pack_start(Gtk.Label("Custom UA string:", xalign=0), False, False, 0)
        self._ua_custom = Gtk.Entry()
        self._ua_custom.set_text(settings.get("user_agent_custom"))
        self._ua_custom.set_placeholder_text("Mozilla/5.0 ...")
        ua.pack_start(self._ua_custom, False, False, 0)

        nb.append_page(ua, Gtk.Label("User Agent"))

        # ---------- Default Apps ----------
        apps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        apps.set_border_width(12)

        apps.pack_start(Gtk.Label("Protocol handlers (leave empty for system default):", xalign=0),
                        False, False, 0)

        def _app_row(label, key):
            h = Gtk.Box(spacing=6)
            h.pack_start(Gtk.Label(label, xalign=0), False, False, 0)
            e = Gtk.Entry()
            e.set_text(settings.get(key))
            e.set_hexpand(True)
            setattr(self, "_app_" + key, e)
            h.pack_start(e, True, True, 0)
            apps.pack_start(h, False, False, 0)

        _app_row("mailto:", "mailto_handler")
        _app_row("ftp:", "ftp_handler")

        nb.append_page(apps, Gtk.Label("Default Apps"))

        self.show_all()

    def _browse(self, btn):
        d = Gtk.FileChooserDialog("Download Directory", self,
                                  Gtk.FileChooserAction.SELECT_FOLDER,
                                  ("Cancel", Gtk.ResponseType.CANCEL,
                                   "Select", Gtk.ResponseType.OK))
        if d.run() == Gtk.ResponseType.OK:
            self._dl_dir.set_text(d.get_filename())
        d.destroy()

    def _on_browse_bg(self, btn):
        dlg = Gtk.FileChooserDialog(
            title="Choose background image", parent=self,
            action=Gtk.FileChooserAction.OPEN)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("Open", Gtk.ResponseType.OK)
        filt = Gtk.FileFilter()
        filt.set_name("Images")
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.svg", "*.webp"):
            filt.add_pattern(ext)
        dlg.add_filter(filt)
        if dlg.run() == Gtk.ResponseType.OK:
            self._nt_newtab_bg_image.set_text(dlg.get_filename())
        dlg.destroy()

    def apply(self):
        s = self._settings
        # General
        s.set("home_page", self._home.get_text())
        s.set("search_engine", self._search.get_text())
        s.set("download_dir", self._dl_dir.get_text())
        s.set("default_zoom", round(self._zoom_adj.get_value(), 1))
        # Performance
        for key, cb in self._perf_cbs.items():
            s.set(key, cb.get_active())
        # Privacy
        s.set("adblock_enabled", self._adblock_cb.get_active())
        s.set("youtube_handler_enabled", self._yt_cb.get_active())
        s.set("confirm_downloads", self._confirm_cb.get_active())
        s.set("do_not_track", self._dnt_cb.get_active())
        s.set("clear_on_exit", self._clear_exit_cb.get_active())
        s.set("cookie_policy", self._cookie_policy.get_active_id())
        # Security
        for key, cb in self._sec_cbs.items():
            s.set(key, cb.get_active())
        # New Tab
        s.set("newtab_enabled", self._newtab_enabled.get_active())
        s.set("newtab_show_search", self._newtab_show_search.get_active())
        s.set("newtab_show_quick_links", self._newtab_show_links.get_active())
        for k in ("newtab_heading", "newtab_search_placeholder", "newtab_background", "newtab_bg_image", "newtab_text_color", "newtab_accent_color"):
            e = getattr(self, "_nt_" + k)
            s.set(k, e.get_text())
        # Theme
        s.set("theme", self._theme_combo.get_active_id())
        for k in ("theme_accent", "theme_dark_bg", "theme_dark_fg"):
            e = getattr(self, "_th_" + k)
            s.set(k, e.get_text())
        # User Agent
        s.set("user_agent_preset", self._ua_combo.get_active_id())
        s.set("user_agent_custom", self._ua_custom.get_text())
        # Default Apps
        for k in ("mailto_handler", "ftp_handler"):
            e = getattr(self, "_app_" + k)
            s.set(k, e.get_text())


class AddBookmarkDialog(Gtk.Dialog):
    def __init__(self, title="", url="", parent=None):
        super().__init__(title="Add Bookmark", parent=parent, flags=0)
        self.set_default_size(400, 130)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Save", Gtk.ResponseType.OK)
        box = self.get_content_area()
        box.set_spacing(6)
        box.set_border_width(12)
        box.pack_start(Gtk.Label("Name:", xalign=0), False, False, 0)
        self._title = Gtk.Entry()
        self._title.set_text(title)
        box.pack_start(self._title, False, False, 0)
        box.pack_start(Gtk.Label("URL:", xalign=0), False, False, 0)
        self._url = Gtk.Entry()
        self._url.set_text(url)
        box.pack_start(self._url, False, False, 0)
        self.show_all()

    def result(self):
        return self._title.get_text(), self._url.get_text()


class BookmarkManagerDialog(Gtk.Dialog):
    def __init__(self, store, navigate_cb, parent=None):
        super().__init__(title="Bookmark Manager", parent=parent, flags=0)
        self._store = store
        self._navigate = navigate_cb
        self.set_default_size(500, 350)
        self.add_button("Close", Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_spacing(4)

        self._list = Gtk.ListStore(str, str)
        self._tree = Gtk.TreeView(model=self._list)
        self._tree.set_headers_visible(True)
        col = Gtk.TreeViewColumn("Title", Gtk.CellRendererText(), text=0)
        self._tree.append_column(col)
        col2 = Gtk.TreeViewColumn("URL", Gtk.CellRendererText(), text=1)
        self._tree.append_column(col2)
        self._tree.connect("row-activated", self._open)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self._tree)
        box.pack_start(scroll, True, True, 0)

        btn_box = Gtk.Box(spacing=6)
        add_btn = Gtk.Button("Add")
        add_btn.connect("clicked", self._add)
        btn_box.pack_start(add_btn, False, False, 0)
        rem_btn = Gtk.Button("Remove")
        rem_btn.connect("clicked", self._remove)
        btn_box.pack_start(rem_btn, False, False, 0)
        box.pack_start(btn_box, False, False, 0)

        self._refresh()
        self.show_all()

    def _refresh(self):
        self._list.clear()
        for bm in self._store.items:
            self._list.append([bm.title, bm.url])

    def _add(self, btn):
        dlg = AddBookmarkDialog(parent=self)
        if dlg.run() == Gtk.ResponseType.OK:
            t, u = dlg.result()
            if t and u:
                self._store.add(t, u)
                self._refresh()
        dlg.destroy()

    def _remove(self, btn):
        sel = self._tree.get_selection()
        model, it = sel.get_selected()
        if it:
            url = model.get_value(it, 1)
            for i, bm in enumerate(self._store.items):
                if bm.url == url:
                    self._store.remove(i)
                    break
            self._refresh()

    def _open(self, tree, path, col):
        it = self._list.get_iter(path)
        url = self._list.get_value(it, 1)
        if url:
            self._navigate(url)
            self.destroy()


class HistoryDialog(Gtk.Dialog):
    def __init__(self, store, navigate_cb, parent=None):
        super().__init__(title="History", parent=parent, flags=0)
        self._store = store
        self._navigate = navigate_cb
        self.set_default_size(550, 350)
        self.add_button("Close", Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_spacing(4)

        search_box = Gtk.Box(spacing=6)
        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Search history...")
        self._search.connect("search-changed", self._do_search)
        search_box.pack_start(self._search, True, True, 0)
        clear_btn = Gtk.Button("Clear All")
        clear_btn.connect("clicked", self._clear)
        search_box.pack_start(clear_btn, False, False, 0)
        box.pack_start(search_box, False, False, 0)

        self._list = Gtk.ListStore(str, str)
        self._tree = Gtk.TreeView(model=self._list)
        self._tree.set_headers_visible(True)
        col = Gtk.TreeViewColumn("Title", Gtk.CellRendererText(), text=0)
        self._tree.append_column(col)
        col2 = Gtk.TreeViewColumn("URL", Gtk.CellRendererText(), text=1)
        self._tree.append_column(col2)
        self._tree.connect("row-activated", self._open)

        scroll = Gtk.ScrolledWindow()
        scroll.add(self._tree)
        box.pack_start(scroll, True, True, 0)

        self._do_search()
        self.show_all()

    def _do_search(self, *a):
        q = self._search.get_text()
        self._list.clear()
        for h in self._store.search(q):
            self._list.append([h.title, h.url])

    def _open(self, tree, path, col):
        it = self._list.get_iter(path)
        url = self._list.get_value(it, 1)
        if url:
            self._navigate(url)
            self.destroy()

    def _clear(self, btn):
        d = Gtk.MessageDialog(self, 0, Gtk.MessageType.QUESTION,
                              Gtk.ButtonsType.YES_NO, "Clear all history?")
        if d.run() == Gtk.ResponseType.YES:
            self._store.clear()
            self._do_search()
        d.destroy()


class DownloadBarItem(Gtk.Box):
    def __init__(self, download, name=""):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(2)
        self.set_margin_bottom(2)
        self._download = download
        self._total = 0
        resp = download.get_response()
        if resp:
            self._total = resp.get_content_length() or 0

        self._icon = Gtk.Image.new_from_icon_name("go-down-symbolic", Gtk.IconSize.MENU)
        self.pack_start(self._icon, False, False, 0)

        self._name = Gtk.Label(label=name or "download", xalign=0)
        self._name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._name.set_max_width_chars(25)
        self.pack_start(self._name, True, True, 0)

        self._progress = Gtk.ProgressBar()
        self._progress.set_size_request(100, 14)
        self._progress.set_show_text(False)
        self.pack_start(self._progress, False, False, 0)

        self._pct = Gtk.Label(label="0%", xalign=0)
        self._pct.set_width_chars(4)
        self.pack_start(self._pct, False, False, 0)

        self._btn = Gtk.Button(label="✕")
        self._btn.set_size_request(28, 24)
        self._btn.set_relief(Gtk.ReliefStyle.NONE)
        self._cancel_sig = self._btn.connect("clicked", self._on_cancel)
        self.pack_start(self._btn, False, False, 0)

        self.show_all()
        self._update_progress()
        download.connect("notify::estimated-progress", self._on_progress)
        download.connect("finished", self._on_finished)
        download.connect("failed", self._on_failed)

    def _update_progress(self):
        p = self._download.get_estimated_progress()
        received = self._download.get_received_data_length()
        if p > 0:
            self._progress.set_fraction(p)
            self._pct.set_text(f"{int(p * 100)}%")
        elif received > 0:
            self._pct.set_text(human_size(received))
        else:
            self._pct.set_text("")

    def _on_progress(self, *a):
        self._update_progress()

    def _on_finished(self, download):
        self._progress.set_fraction(1.0)
        self._pct.set_text("Complete")
        self._icon.set_from_icon_name("emblem-ok-symbolic", Gtk.IconSize.MENU)
        if self._cancel_sig is not None:
            self._btn.disconnect(self._cancel_sig)
            self._cancel_sig = None
        self._btn.connect("clicked", self._on_close)

    def _on_failed(self, download, error):
        self._pct.set_text("Failed")
        if self._cancel_sig is not None:
            self._btn.disconnect(self._cancel_sig)
            self._cancel_sig = None
        self._btn.connect("clicked", self._on_close)

    def _on_cancel(self, btn):
        if hasattr(self, "_parent_bar") and self._parent_bar:
            self._parent_bar.remove_download(self)

    def _on_close(self, btn):
        if hasattr(self, "_parent_bar") and self._parent_bar:
            self._parent_bar.remove_download(self)


class DownloadsBar(Gtk.Box):
    def __init__(self, show_all_cb=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._show_all_cb = show_all_cb
        self.set_no_show_all(True)

        # Top separator
        sep = Gtk.HSeparator()
        self.pack_start(sep, False, False, 0)

        # Header row
        hdr = Gtk.Box(spacing=6)
        hdr.set_margin_start(8)
        hdr.set_margin_end(8)
        hdr.set_margin_top(4)
        hdr.set_margin_bottom(2)
        lbl = Gtk.Label(label="Downloads", xalign=0)
        lbl.set_markup("<b>Downloads</b>")
        hdr.pack_start(lbl, True, True, 0)
        self._show_all_link = Gtk.LinkButton(uri="", label="Show all")
        self._show_all_link.connect("activate-link", self._on_show_all)
        hdr.pack_end(self._show_all_link, False, False, 0)
        self.pack_start(hdr, False, False, 0)

        # Container for download items
        self._items_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.pack_start(self._items_box, False, False, 0)

        # Show children explicitly (self stays hidden due to no_show_all)
        sep.show()
        hdr.show_all()
        self._items_box.show()

    def add_download(self, download, name=""):
        item = DownloadBarItem(download, name)
        item._parent_bar = self
        self._items_box.pack_start(item, False, False, 0)
        self.show()
        return item

    def remove_download(self, item):
        self._items_box.remove(item)
        if not self._items_box.get_children():
            self.hide()

    def _on_show_all(self, *a):
        if self._show_all_cb:
            self._show_all_cb()
        return True



