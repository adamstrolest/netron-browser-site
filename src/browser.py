import base64
import json
import mimetypes
import os
import subprocess
import time
from urllib.parse import urlparse, quote, unquote

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_version("GLib", "2.0")
from gi.repository import Gtk, WebKit2, GLib, Pango, Gdk, Gio

from persistence import (
    BookmarkStore, HistoryStore, SettingsStore,
    SessionStore, ZoomStore,
)
from dialogs import (
    SettingsDialog, AddBookmarkDialog, BookmarkManagerDialog,
    HistoryDialog, DownloadsBar,
)
from interceptors import (
    is_youtube_url, launch_ytdlp,
    init_content_filter_store, get_or_create_filter,
)


class TabPage(Gtk.Box):
    def __init__(self, webview):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.webview = webview
        self.pack_start(webview, True, True, 0)
        self.show_all()


class BrowserWindow(Gtk.Window):
    def __init__(self, settings=None, bookmarks=None, history=None,
                 session=None, zoom=None, private=False):
        super().__init__()
        self._private = private
        self._settings = settings or SettingsStore()
        self._bookmarks = bookmarks or BookmarkStore()
        self._history = history or HistoryStore()
        self._session = session or SessionStore()
        self._zoom = zoom or ZoomStore()
        self._adblock_enabled = self._settings.get("adblock_enabled")
        self._yt_enabled = self._settings.get("youtube_handler_enabled")
        self._adblock_filter = None
        self._status_text = "Ready"

        self.set_title("Netron Browser" + (" (Private)" if private else ""))
        self.set_icon_name("netron-browser")
        self.set_wmclass("netron-browser", "Netron Browser")
        self.set_default_size(1024, 700)
        self.connect("destroy", self._on_destroy)
        self.connect("key-press-event", self._on_window_key)

        # Accel group for shortcuts
        self._accel_group = Gtk.AccelGroup()
        self.add_accel_group(self._accel_group)

        # Action group for context menu custom actions (GTK3 compat)
        self._action_group = Gio.SimpleActionGroup()
        self._bookmark_page_action = Gio.SimpleAction.new(
            "bookmark-page", GLib.VariantType.new("s"))
        self._bookmark_page_action.connect("activate",
            self._on_bookmark_action)
        self._action_group.add_action(self._bookmark_page_action)
        self.insert_action_group("browser", self._action_group)

        # Add common Chromium/Firefox shortcuts
        def _accel(seq, cb):
            key, mod = Gtk.accelerator_parse(seq)
            if key and Gtk.accelerator_valid(key, mod):
                self._accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                                          lambda *a: cb() or True)

        _accel("<Ctrl>l", lambda: self._url_entry.grab_focus())
        _accel("<Ctrl>equal", self._zoom_in)
        _accel("<Ctrl>minus", self._zoom_out)
        _accel("<Ctrl>0", self._zoom_reset)
        _accel("F11", self._toggle_fullscreen)
        for i in range(1, 9):
            _accel(f"<Ctrl>{i}", lambda idx=i-1: self._notebook.set_current_page(idx))
        _accel("<Ctrl>9", lambda: self._notebook.set_current_page(
            self._notebook.get_n_pages() - 1))

        # Web context — persistent cookies/storage + performance tuning
        if self._private:
            self._web_context = WebKit2.WebContext.new_ephemeral()
        else:
            data_dir = os.path.expanduser("~/.local/share/netron-browser")
            os.makedirs(data_dir, exist_ok=True)
            data_mgr = WebKit2.WebsiteDataManager(
                base_data_directory=data_dir,
                base_cache_directory=os.path.join(data_dir, "cache"))
            self._web_context = WebKit2.WebContext.new_with_website_data_manager(data_mgr)
            self._web_context.get_cookie_manager().set_persistent_storage(
                os.path.join(data_dir, "cookies.sqlite"),
                WebKit2.CookiePersistentStorage.SQLITE)
            self._apply_cookie_policy()
        self._web_context.set_cache_model(WebKit2.CacheModel.WEB_BROWSER)
        self._web_context.set_preferred_languages(["en-US"])
        self._web_context.set_spell_checking_enabled(False)
        self._web_context.set_favicon_database_directory(
            os.path.expanduser("~/.cache/netron-browser/favicons"))
        self._web_context.connect("download-started", self._on_download_started)

        # UI structure
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(vbox)

        self._build_menu(vbox)
        self._build_toolbar(vbox)
        self._bookmark_bar = self._build_bookmark_bar(vbox)

        self._notebook = Gtk.Notebook()
        self._notebook.set_scrollable(True)
        self._notebook.connect("switch-page", self._on_tab_switch)
        self._notebook.connect("button-press-event", self._on_tab_bar_click)
        new_tab_btn = Gtk.Button(label="+")
        new_tab_btn.set_size_request(28, -1)
        new_tab_btn.set_tooltip_text("New Tab (Ctrl+T)")
        new_tab_btn.connect("clicked", lambda b: self._new_tab())
        new_tab_btn.show()
        self._notebook.set_action_widget(new_tab_btn, Gtk.PackType.END)
        vbox.pack_start(self._notebook, True, True, 0)

        self._find_bar = self._build_find_bar(vbox)

        self._dl_count = 0
        self._downloads_bar = DownloadsBar(
            show_all_cb=lambda: self._safe_open(self._settings.get("download_dir")))

        # Bottom: DownloadsBar + status area
        vbox.pack_end(self._downloads_bar, False, False, 0)
        status_frame = Gtk.Frame()
        status_frame.set_shadow_type(Gtk.ShadowType.IN)
        status_hbox = Gtk.Box(spacing=4)
        self._status_label = Gtk.Label(label=self._status_text, xalign=0)
        status_hbox.pack_start(self._status_label, True, True, 0)
        self._dl_icon = Gtk.Button()
        self._dl_icon.set_relief(Gtk.ReliefStyle.NONE)
        img = Gtk.Image.new_from_icon_name("folder-download-symbolic", Gtk.IconSize.MENU)
        self._dl_icon.add(img)
        self._dl_icon.set_tooltip_text("Open downloads folder")
        self._dl_icon.connect("clicked", self._on_dl_icon_clicked)
        self._dl_icon.set_no_show_all(True)
        status_hbox.pack_end(self._dl_icon, False, False, 0)
        status_frame.add(status_hbox)
        vbox.pack_end(status_frame, False, False, 0)

        self._restoring_session = True

        # Load adblock filter
        self._init_adblock()

        # Session restore or default tab
        if self._private:
            self._new_tab()
        else:
            self._session.load()
            if self._session.tabs:
                for url in self._session.tabs:
                    self._new_tab(url)
                self._notebook.set_current_page(0)
            else:
                self._new_tab()
        self._restoring_session = False

        self._apply_theme()
        self.show_all()

    # --- AdBlock via UserContentFilterStore ---

    def _init_adblock(self):
        if not self._adblock_enabled:
            return

        def on_filter(filt):
            self._adblock_filter = filt

        store = init_content_filter_store()
        get_or_create_filter(store, on_filter)

    def _apply_wv_settings(self, wv):
        s = wv.get_settings()
        st = self._settings
        s.set_enable_javascript(st.get("javascript_enabled"))
        s.set_enable_webaudio(st.get("webaudio_enabled"))
        s.set_enable_media_stream(st.get("media_stream_enabled"))
        s.set_enable_webgl(st.get("webgl_enabled"))
        s.set_enable_page_cache(st.get("page_cache_enabled"))
        s.set_enable_webrtc(st.get("webrtc_enabled"))
        s.set_enable_encrypted_media(st.get("encrypted_media_enabled"))
        s.set_enable_dns_prefetching(st.get("dns_prefetching_enabled"))
        s.set_enable_smooth_scrolling(st.get("smooth_scrolling_enabled"))
        s.set_enable_plugins(st.get("plugins_enabled"))
        s.set_enable_accelerated_2d_canvas(False)
        ha = WebKit2.HardwareAccelerationPolicy.NEVER
        if st.get("hardware_acceleration"):
            ha = WebKit2.HardwareAccelerationPolicy.ON_DEMAND
        s.set_hardware_acceleration_policy(ha)
        s.set_allow_modal_dialogs(st.get("javascript_can_open_windows"))
        s.set_enable_hyperlink_auditing(st.get("enable_hyperlink_auditing"))
        s.set_disable_web_security(not st.get("enable_websecurity"))
        s.set_enable_fullscreen(st.get("enable_fullscreen"))
        s.set_enable_mediasource(st.get("enable_mediasource"))
        ua = st.get_user_agent()
        if ua:
            s.set_user_agent(ua)

    # --- Session save ---

    def _on_destroy(self, *a):
        if not self._private:
            urls = []
            for i in range(self._notebook.get_n_pages()):
                page = self._notebook.get_nth_page(i)
                uri = page.webview.get_uri()
                if uri and uri != "about:blank":
                    urls.append(uri)
            self._session.save(urls)
        if self._private or self._settings.get("clear_on_exit"):
            self._web_context.get_website_data_manager().clear(
                [WebKit2.WebsiteDataTypes.COOKIES,
                 WebKit2.WebsiteDataTypes.MEMORY_CACHE,
                 WebKit2.WebsiteDataTypes.DISK_CACHE,
                 WebKit2.WebsiteDataTypes.LOCAL_STORAGE,
                 WebKit2.WebsiteDataTypes.INDEXEDDB_DATABASES],
                0, None, None, None)
        Gtk.main_quit()

    # --- Menu ---

    def _build_menu(self, vbox):
        mb = Gtk.MenuBar()

        file_m = Gtk.MenuItem("_File", use_underline=True)
        file_s = Gtk.Menu()
        file_m.set_submenu(file_s)
        items = [
            ("_New Tab", "<Ctrl>T", self._new_tab_clicked),
            ("New _Window", "<Ctrl>N", self._new_window),
            ("New _Private Window", "<Ctrl><Shift>N", self._new_private_window),
            None,
            ("_Open File...", "<Ctrl>O", self._open_file),
            ("_Print to PDF...", "<Ctrl>P", self._print_pdf),
            None,
            ("_Close Tab", "<Ctrl>W", self._close_current),
            ("_Quit", "<Ctrl>Q", Gtk.main_quit),
        ]
        self._populate_menu(file_s, items)
        mb.append(file_m)

        edit_m = Gtk.MenuItem("_Edit", use_underline=True)
        edit_s = Gtk.Menu()
        edit_m.set_submenu(edit_s)
        items = [
            ("_Find", "<Ctrl>F", self._toggle_find),
            ("Find _Next", "F3", lambda: self._find_next(True)),
            ("Find Pre_vious", "<Shift>F3", lambda: self._find_next(False)),
        ]
        self._populate_menu(edit_s, items)
        mb.append(edit_m)

        view_m = Gtk.MenuItem("_View", use_underline=True)
        view_s = Gtk.Menu()
        view_m.set_submenu(view_s)
        items = [
            ("_Stop", "Escape", self._stop),
            ("_Reload", "F5", lambda: self._reload(False)),
            ("Reload (_Hard)", "<Ctrl><Shift>R", lambda: self._reload(True)),
            None,
            ("_Fullscreen", "F11", self._toggle_fullscreen),
            None,
            ("_Take Screenshot", None, self._take_screenshot),
            None,
            ("Zoom _In", "<Ctrl>equal", self._zoom_in),
            ("Zoom _Out", "<Ctrl>minus", self._zoom_out),
            ("_Reset Zoom", "<Ctrl>0", self._zoom_reset),
        ]
        self._populate_menu(view_s, items)
        mb.append(view_m)

        book_m = Gtk.MenuItem("_Bookmarks", use_underline=True)
        book_s = Gtk.Menu()
        book_m.set_submenu(book_s)
        items = [
            ("_Add Bookmark", "<Ctrl>D", self._add_bookmark),
            ("Bookmark _Manager", "<Ctrl><Shift>O", self._show_bookmark_mgr),
            None,
            None,
            ("_Import from JSON...", None, self._import_bookmarks),
            ("Import from _Chrome...", None, self._import_chrome_bookmarks),
            ("Import from _Firefox...", None, self._import_firefox_bookmarks),
            ("_Export Bookmarks...", None, self._export_bookmarks),
        ]
        self._populate_menu(book_s, items)
        mb.append(book_m)

        hist_m = Gtk.MenuItem("_History", use_underline=True)
        hist_s = Gtk.Menu()
        hist_m.set_submenu(hist_s)
        items = [
            ("Show _History", "<Ctrl>H", self._show_history),
        ]
        self._populate_menu(hist_s, items)
        mb.append(hist_m)

        tools_m = Gtk.MenuItem("_Tools", use_underline=True)
        tools_s = Gtk.Menu()
        tools_m.set_submenu(tools_s)
        items = [
            ("_Downloads", None, lambda: self._safe_open(self._settings.get("download_dir"))),
            None,
            ("Clear _Browsing Data", None, self._clear_browsing_data),
            ("_Settings", "<Ctrl>comma", self._show_settings),
        ]
        self._populate_menu(tools_s, items)
        mb.append(tools_m)

        help_m = Gtk.MenuItem("_Help", use_underline=True)
        help_s = Gtk.Menu()
        help_m.set_submenu(help_s)
        items = [
            ("_About Netron Browser", None, self._show_about),
        ]
        self._populate_menu(help_s, items)
        mb.append(help_m)

        vbox.pack_start(mb, False, False, 0)

    def _populate_menu(self, menu, items):
        for item in items:
            if item is None:
                menu.append(Gtk.SeparatorMenuItem())
            else:
                label, accel, cb = item
                mi = Gtk.MenuItem(label=label, use_underline=True)
                if accel:
                    key, mod = Gtk.accelerator_parse(accel)
                    if key and Gtk.accelerator_valid(key, mod):
                        mi.add_accelerator("activate", self._accel_group,
                                           key, mod, Gtk.AccelFlags.VISIBLE)
                mi.connect("activate", lambda _, c=cb: c() if c else None)
                menu.append(mi)

    # --- Toolbar ---

    def _build_toolbar(self, vbox):
        tb = Gtk.Toolbar()
        tb.set_style(Gtk.ToolbarStyle.BOTH_HORIZ)
        tb.set_icon_size(Gtk.IconSize.MENU)

        self._back_btn = Gtk.ToolButton(Gtk.STOCK_GO_BACK)
        self._back_btn.set_label("")
        self._back_btn.set_tooltip_text("Back (Alt+Left)")
        self._back_btn.connect("clicked", lambda _: self._go_back())
        tb.insert(self._back_btn, -1)

        self._fwd_btn = Gtk.ToolButton(Gtk.STOCK_GO_FORWARD)
        self._fwd_btn.set_label("")
        self._fwd_btn.set_tooltip_text("Forward (Alt+Right)")
        self._fwd_btn.connect("clicked", lambda _: self._go_forward())
        tb.insert(self._fwd_btn, -1)

        self._reload_btn = Gtk.ToolButton(Gtk.STOCK_REFRESH)
        self._reload_btn.set_label("")
        self._reload_btn.set_tooltip_text("Reload (F5)")
        self._reload_btn.connect("clicked", lambda _: self._reload(False))
        tb.insert(self._reload_btn, -1)

        self._home_btn = Gtk.ToolButton(Gtk.STOCK_HOME)
        self._home_btn.set_label("")
        self._home_btn.set_tooltip_text("Home")
        self._home_btn.connect("clicked", lambda _: self._navigate(self._settings.get("home_page")))
        tb.insert(self._home_btn, -1)

        sep = Gtk.SeparatorToolItem()
        tb.insert(sep, -1)

        # URL entry with completion
        self._url_entry = Gtk.Entry()
        self._url_entry.set_hexpand(True)
        self._url_entry.set_placeholder_text("Enter URL or search...")
        self._url_entry.connect("activate", self._url_navigate)
        self._url_entry.connect("key-press-event", self._on_url_key)
        self._url_entry.set_size_request(200, -1)
        self._url_completion = Gtk.EntryCompletion()
        self._url_liststore = Gtk.ListStore(str)
        self._url_completion.set_model(self._url_liststore)
        self._url_completion.set_text_column(0)
        self._url_completion.set_inline_completion(True)
        self._url_completion.set_popup_single_match(False)
        self._url_completion.connect("match-selected", self._on_completion_match)
        self._url_entry.set_completion(self._url_completion)

        url_item = Gtk.ToolItem()
        url_item.set_expand(True)
        url_item.add(self._url_entry)
        tb.insert(url_item, -1)

        vbox.pack_start(tb, False, False, 0)

    def _on_completion_match(self, completion, model, it):
        url = model.get_value(it, 0)
        self._navigate(url)

    def _update_url_completion(self):
        urls = list(set(h.url for h in self._history.entries[-100:]))
        self._url_liststore.clear()
        for u in urls:
            self._url_liststore.append([u])

    # --- Bookmark bar ---

    def _build_bookmark_bar(self, vbox):
        bar = Gtk.Toolbar()
        bar.set_style(Gtk.ToolbarStyle.TEXT)
        bar.set_icon_size(Gtk.IconSize.MENU)
        self._refresh_bookmark_bar(bar)
        vbox.pack_start(bar, False, False, 0)
        return bar

    def _refresh_bookmark_bar(self, bar=None):
        bar = bar or self._bookmark_bar
        for c in bar.get_children():
            bar.remove(c)
        for bm in self._bookmarks.items:
            btn = Gtk.ToolButton(label=bm.title)
            btn.set_tooltip_text(bm.url)
            btn.connect("clicked", lambda _, u=bm.url: self._navigate(u))
            bar.insert(btn, -1)
        bar.show_all()

    # --- Find bar ---

    def _build_find_bar(self, vbox):
        box = Gtk.Box(spacing=6)
        box.set_no_show_all(True)
        box.pack_start(Gtk.Label("Find:"), False, False, 0)
        self._find_entry = Gtk.SearchEntry()
        self._find_entry.set_size_request(200, -1)
        self._find_entry.connect("activate", lambda e: self._find_next(True))
        self._find_entry.connect("search-changed", lambda e: self._find_next(True))
        box.pack_start(self._find_entry, False, False, 0)
        prev_btn = Gtk.Button(label="Prev")
        prev_btn.connect("clicked", lambda b: self._find_next(False))
        box.pack_start(prev_btn, False, False, 0)
        next_btn = Gtk.Button(label="Next")
        next_btn.connect("clicked", lambda b: self._find_next(True))
        box.pack_start(next_btn, False, False, 0)
        res_label = Gtk.Label("")
        box.pack_start(res_label, False, False, 0)
        self._find_result_label = res_label
        close_btn = Gtk.Button(label="x")
        close_btn.set_size_request(24, -1)
        close_btn.connect("clicked", lambda b: self._find_bar.hide())
        box.pack_start(close_btn, False, False, 0)
        vbox.pack_end(box, False, False, 0)
        return box

    # --- Current tab helpers ---

    def _current_webview(self):
        page = self._notebook.get_nth_page(self._notebook.get_current_page())
        if page and isinstance(page, TabPage):
            return page.webview
        return None

    def _switch_tab(self, direction):
        n = self._notebook.get_n_pages()
        if n <= 1:
            return
        cur = self._notebook.get_current_page()
        nxt = (cur + direction) % n
        self._notebook.set_current_page(nxt)

    def _on_window_key(self, widget, event):
        if event.keyval == Gdk.KEY_Tab and (event.state & Gdk.ModifierType.CONTROL_MASK):
            shift = event.state & Gdk.ModifierType.SHIFT_MASK
            self._switch_tab(-1 if shift else 1)
            return True
        return False

    def _on_url_key(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            wv = self._current_webview()
            if wv:
                wv.grab_focus()
            return True
        return False

    # --- Tab close button ---

    def _make_tab_label(self, title, page):
        box = Gtk.Box(spacing=4)
        label = Gtk.Label(label=title)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_width_chars(6)
        box.pack_start(label, True, True, 0)
        close_btn = Gtk.Button(label="×")
        close_btn.set_relief(Gtk.ReliefStyle.NONE)
        close_btn.set_focus_on_click(False)
        close_btn.set_size_request(20, 20)
        close_btn.connect("clicked", lambda b: self._close_tab(page))
        box.pack_start(close_btn, False, False, 0)
        box.show_all()
        return box

    # --- Tab management ---

    def _new_tab(self, url=None):
        wv = WebKit2.WebView.new_with_context(self._web_context)

        # Apply settings to webview
        self._apply_wv_settings(wv)

        # Apply adblock filter and theme
        mgr = wv.get_user_content_manager()
        if self._adblock_filter:
            mgr.add_filter(self._adblock_filter)
        css = getattr(self, "_theme_css", None)
        if css:
            mgr.add_style_sheet(WebKit2.UserStyleSheet(
                css, WebKit2.UserContentInjectedFrames.ALL_FRAMES,
                WebKit2.UserStyleLevel.USER, None, None))

        wv.connect("load-changed", self._on_load_changed)
        wv.connect("notify::title", self._on_title_changed)
        wv.connect("notify::estimated-load-progress", self._on_progress)
        wv.connect("decide-policy", self._on_decide_policy)
        wv.connect("notify::uri", self._on_uri_changed)
        wv.connect("notify::is-playing-audio", self._on_audio_changed)
        wv.connect("mouse-target-changed", self._on_mouse_target)
        wv.connect("create", self._on_create_window)
        wv.connect("context-menu", self._on_context_menu)

        # Per-site zoom
        if url:
            domain = urlparse(url).hostname or ""
            z = self._zoom.get(domain)
            if z != 1.0:
                wv.set_zoom_level(z)

        page = TabPage(wv)
        tab_label = self._make_tab_label("New Tab", page)
        idx = self._notebook.append_page(page, tab_label)
        self._notebook.set_current_page(idx)
        self._notebook.set_tab_reorderable(page, True)

        target = url or ""
        if target:
            wv.load_uri(target)
        elif self._settings.get("newtab_enabled"):
            wv.load_html(self._new_tab_html(), "")
        else:
            wv.load_uri("about:blank")

        return wv

    def _close_current(self):
        page = self._notebook.get_nth_page(self._notebook.get_current_page())
        self._close_tab(page)

    def _close_tab(self, page):
        if self._notebook.get_n_pages() <= 1:
            return
        idx = self._notebook.page_num(page)
        if idx >= 0:
            self._notebook.remove_page(idx)
            page.destroy()

    def _close_tab_at(self, idx):
        page = self._notebook.get_nth_page(idx)
        self._close_tab(page)

    def _on_tab_switch(self, notebook, page, idx):
        if not isinstance(page, TabPage):
            return
        wv = page.webview
        uri = wv.get_uri() or ""
        self._url_entry.set_text(uri)
        self._back_btn.set_sensitive(wv.can_go_back())
        self._fwd_btn.set_sensitive(wv.can_go_forward())

    # --- Tab context menu (right-click on tab bar) ---

    def _on_tab_bar_click(self, widget, event):
        if event.button != 3:
            return False
        idx = self._notebook.get_current_page()
        menu = Gtk.Menu()
        items = [
            ("New Tab", lambda: self._new_tab()),
            ("Close Tab", lambda: self._close_tab_at(idx)),
            ("Close Other Tabs", lambda: self._close_other_tabs(idx)),
            None,
            ("Reload", lambda: self._notebook.get_nth_page(idx).webview.reload()),
            ("Duplicate", lambda: self._duplicate_tab(idx)),
        ]
        for item in items:
            if item is None:
                menu.append(Gtk.SeparatorMenuItem())
            else:
                label, cb = item
                mi = Gtk.MenuItem(label=label)
                mi.connect("activate", lambda _, c=cb: c())
                menu.append(mi)
        menu.show_all()
        menu.popup(None, None, None, None, event.button, event.time)
        return True

    def _close_other_tabs(self, keep_idx):
        for i in range(self._notebook.get_n_pages() - 1, -1, -1):
            if i != keep_idx:
                self._close_tab_at(i)

    def _duplicate_tab(self, idx):
        page = self._notebook.get_nth_page(idx)
        if isinstance(page, TabPage):
            uri = page.webview.get_uri()
            self._new_tab(uri)

    # --- Page context menu ---

    def _on_context_menu(self, wv, context_menu, event, hit_test):
        context_menu.remove_all()
        link_uri = hit_test.get_link_uri()
        uri = wv.get_uri() or ""

        if link_uri:
            context_menu.append(
                WebKit2.ContextMenuItem.new_from_stock_action_with_label(
                    WebKit2.ContextMenuAction.OPEN_LINK_IN_NEW_WINDOW,
                    "Open Link in New Tab"))
            context_menu.append(WebKit2.ContextMenuItem.new_separator())

        context_menu.append(
            WebKit2.ContextMenuItem.new_from_stock_action_with_label(
                WebKit2.ContextMenuAction.RELOAD, "Reload"))
        context_menu.append(WebKit2.ContextMenuItem.new_separator())
        context_menu.append(
            WebKit2.ContextMenuItem.new_from_stock_action_with_label(
                WebKit2.ContextMenuAction.COPY, "Copy"))
        context_menu.append(
            WebKit2.ContextMenuItem.new_from_stock_action_with_label(
                WebKit2.ContextMenuAction.PASTE, "Paste"))
        context_menu.append(WebKit2.ContextMenuItem.new_separator())

        if uri:
            context_menu.append(
                WebKit2.ContextMenuItem.new_from_gaction(
                    self._bookmark_page_action, "Bookmark This Page",
                    GLib.Variant("s", uri)))
            context_menu.append(WebKit2.ContextMenuItem.new_separator())

        context_menu.append(
            WebKit2.ContextMenuItem.new_from_stock_action_with_label(
                WebKit2.ContextMenuAction.INSPECT_ELEMENT, "Inspect Element"))
        return False

    def _on_bookmark_action(self, action, param):
        url = param.get_string()
        wv = self._current_webview()
        title = wv.get_title() if wv else url
        self._add_bookmark_for(url, title or url)

    def _copy_to_clipboard(self, text):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)

    # --- WebView signals ---

    def _on_load_changed(self, wv, event):
        if event == WebKit2.LoadEvent.COMMITTED:
            uri = wv.get_uri() or ""
            self._url_entry.set_text(uri)
            self._back_btn.set_sensitive(wv.can_go_back())
            self._fwd_btn.set_sensitive(wv.can_go_forward())
        elif event == WebKit2.LoadEvent.FINISHED:
            uri = wv.get_uri() or ""
            title = wv.get_title() or uri
            if uri and not self._private:
                self._history.add(title, uri)
                self._update_url_completion()
            self._update_tab_label(wv)
            self._status_label.set_text("Ready")

    def _on_title_changed(self, wv, pspec):
        self._update_tab_label(wv)

    def _on_progress(self, wv, pspec):
        pct = wv.get_estimated_load_progress()
        if pct > 0 and pct < 1:
            self._status_label.set_text(f"Loading... {int(pct*100)}%")
        else:
            self._status_label.set_text("Ready")

    def _on_mouse_target(self, wv, hit_test_result, modifiers):
        uri = hit_test_result.get_link_uri()
        if uri:
            self._status_label.set_text(uri)
        else:
            self._status_label.set_text(self._status_text)

    def _on_create_window(self, wv, navigation_action):
        new_wv = self._new_tab()
        return new_wv

    def _update_tab_label(self, wv):
        for i in range(self._notebook.get_n_pages()):
            page = self._notebook.get_nth_page(i)
            if isinstance(page, TabPage) and page.webview == wv:
                title = wv.get_title() or "New Tab"
                short = title[:40] + "..." if len(title) > 43 else title
                tab_label = self._notebook.get_tab_label(page)
                if tab_label and hasattr(tab_label, "get_children"):
                    children = tab_label.get_children()
                    if children:
                        label = children[0]
                        if isinstance(label, Gtk.Label):
                            label.set_text(short if short else "New Tab")
                break

    # --- Custom new tab page ---

    def _new_tab_html(self):
        s = self._settings
        bg = s.get("newtab_background")
        tc = s.get("newtab_text_color")
        ac = s.get("newtab_accent_color")
        bg_img = s.get("newtab_bg_image")
        heading = s.get("newtab_heading")
        ph = s.get("newtab_search_placeholder")
        engine = s.get("search_engine")
        show_search = s.get("newtab_show_search")
        show_links = s.get("newtab_show_quick_links")
        max_links = s.get("newtab_max_links")

        bm = ""
        if show_links:
            for i, b in enumerate(self._bookmarks.items[:max_links]):
                bm += f'<a href="{b.url}" class="ql">{b.title}</a>'
        search_html = ""
        if show_search:
            search_html = f'''<form onsubmit="go();return false">
<input id="q" type="text" placeholder="{ph}" autofocus>
</form>'''

        bg_style = f"background:{bg}"
        if bg_img:
            if bg_img.startswith("/"):
                try:
                    with open(bg_img, "rb") as f:
                        data = base64.b64encode(f.read()).decode()
                    mime = mimetypes.guess_type(bg_img)[0] or "image/png"
                    bg_img = f"data:{mime};base64,{data}"
                except Exception:
                    bg_img = ""
            if bg_img:
                bg_style += f";background-image:url('{bg_img}');background-size:cover;background-position:center"
        return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;{bg_style};color:{tc};display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;padding:20px}}
.container{{width:100%;max-width:560px}}
h1{{font-size:28px;font-weight:300;text-align:center;margin-bottom:30px;color:{tc}}}
form{{width:100%}}
#q{{width:100%;padding:14px 18px;font-size:17px;border:2px solid #ddd;border-radius:30px;outline:none;transition:border-color .2s}}
#q:focus{{border-color:{ac}}}
.qls{{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:36px}}
.ql{{display:inline-block;padding:8px 16px;background:{bg};border:1px solid #e0e0e0;border-radius:6px;text-decoration:none;color:{tc};font-size:14px;transition:background .15s}}
.ql:hover{{background:{ac}22;border-color:{ac}}}
</style>
<script>
function go(){{var q=document.getElementById('q');if(q.value){{location.href='{engine}'.replace('{{}}',encodeURIComponent(q.value))}}}}
</script>
</head><body>
<div class="container">
<h1>{heading}</h1>
{search_html}
<div class="qls">{bm}</div>
</div>
</body></html>"""

    def _apply_cookie_policy(self):
        policy = self._settings.get("cookie_policy")
        cm = self._web_context.get_cookie_manager()
        if policy == "never":
            cm.set_accept_policy(WebKit2.CookieAcceptPolicy.NEVER)
        elif policy == "same-site":
            cm.set_accept_policy(WebKit2.CookieAcceptPolicy.NO_THIRD_PARTY)
        else:
            cm.set_accept_policy(WebKit2.CookieAcceptPolicy.ALWAYS)

    def _apply_theme(self):
        theme = self._settings.get("theme")
        bg = "#fff"
        accent = self._settings.get("theme_accent")
        if theme == "dark":
            bg = self._settings.get("theme_dark_bg")
        elif theme == "light":
            bg = "#fff"
        # Non-invasive: set canvas background without forcing text colors
        # html background sets the root canvas (no layout impact)
        # No !important on color to avoid breaking page text styles
        if theme == "dark":
            fg = self._settings.get("theme_dark_fg")
            css = f"html{{background:{bg}!important;color:{fg}}}"
        else:
            css = f"html{{background:{bg}!important}}"
        self._theme_css = css
        for i in range(self._notebook.get_n_pages()):
            page = self._notebook.get_nth_page(i)
            if isinstance(page, TabPage):
                mgr = page.webview.get_user_content_manager()
                mgr.remove_all_style_sheets()
                mgr.add_style_sheet(WebKit2.UserStyleSheet(
                    css, WebKit2.UserContentInjectedFrames.ALL_FRAMES,
                    WebKit2.UserStyleLevel.USER, None, None))

    # --- Policy decision (YouTube only) ---

    def _on_decide_policy(self, wv, decision, decision_type):
        if decision_type == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            action = decision.get_navigation_action()
            uri = action.get_request().get_uri()
            if uri.startswith("ftp://") or uri.startswith("mailto:"):
                handler = self._settings.get("ftp_handler") if uri.startswith("ftp://") else self._settings.get("mailto_handler")
                if handler:
                    self._safe_spawn([handler, uri])
                else:
                    self._safe_open(uri)
                decision.ignore()
                return True
            if self._yt_enabled and is_youtube_url(uri):
                self._status_label.set_text("Launching YouTube via yt-dlp...")
                launch_ytdlp(uri)
                decision.ignore()
                return True
            return False
        if decision_type == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
            action = decision.get_navigation_action()
            uri = action.get_request().get_uri()
            self._new_tab(uri)
            decision.ignore()
            return True
        return False

    def _on_uri_changed(self, wv, pspec):
        uri = wv.get_uri() or ""
        if self._yt_enabled and is_youtube_url(uri):
            self._status_label.set_text("Launching YouTube via yt-dlp...")
            launch_ytdlp(uri)
            wv.stop_loading()
            wv.load_html(
                "<html><body style='font-family:sans-serif;text-align:center;"
                "padding:40px;color:#555'><h2>YouTube</h2>"
                "<p>Playing via yt-dlp + mpv...</p></body></html>", "")

    # --- Navigation ---

    def _navigate(self, url_or_text):
        wv = self._current_webview()
        if not wv:
            return
        url = url_or_text.strip()
        if not url:
            return
        parsed = urlparse(url)
        if not parsed.scheme:
            if "." in url and " " not in url:
                url = "https://" + url
            else:
                search = self._settings.get("search_engine").replace(
                    "{}", quote(url))
                url = search
        wv.load_uri(url)

    def _url_navigate(self, entry):
        self._navigate(entry.get_text())

    def _go_back(self):
        wv = self._current_webview()
        if wv and wv.can_go_back():
            wv.go_back()

    def _go_forward(self):
        wv = self._current_webview()
        if wv and wv.can_go_forward():
            wv.go_forward()

    def _reload(self, hard=False):
        wv = self._current_webview()
        if wv:
            (wv.reload_bypass_cache if hard else wv.reload)()

    def _stop(self):
        wv = self._current_webview()
        if wv:
            wv.stop_loading()

    def _new_tab_clicked(self):
        self._new_tab()

    def _new_window(self):
        self._safe_spawn(
            ["python3", os.path.join(os.path.dirname(__file__), "netron.py")])

    def _open_file(self):
        d = Gtk.FileChooserDialog("Open File", self,
                                  Gtk.FileChooserAction.OPEN,
                                  ("Cancel", Gtk.ResponseType.CANCEL,
                                   "Open", Gtk.ResponseType.OK))
        if d.run() == Gtk.ResponseType.OK:
            self._navigate("file://" + d.get_filename())
        d.destroy()

    # --- Fullscreen ---

    def _toggle_fullscreen(self):
        if self.get_window().get_state() & Gdk.WindowState.FULLSCREEN:
            self.unfullscreen()
        else:
            self.fullscreen()

    # --- Screenshot ---

    def _take_screenshot(self):
        wv = self._current_webview()
        if not wv:
            return
        now = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.expanduser(f"~/Pictures/netron_{now}.png")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        wv.get_snapshot(WebKit2.SnapshotRegion.FULL_DOCUMENT,
                        WebKit2.SnapshotOptions.NONE,
                        None, self._on_snapshot_done, path)

    def _on_snapshot_done(self, wv, result, path):
        try:
            pixbuf = wv.get_snapshot_finish(result)
            if pixbuf:
                pixbuf.savev(path, "png", [], [])
                self._status_label.set_text(f"Screenshot saved: {path}")
        except GLib.Error:
            self._status_label.set_text("Screenshot failed")

    # --- Print to PDF ---

    def _print_pdf(self):
        wv = self._current_webview()
        if not wv:
            return
        d = Gtk.FileChooserDialog("Save PDF", self,
                                  Gtk.FileChooserAction.SAVE,
                                  ("Cancel", Gtk.ResponseType.CANCEL,
                                   "Save", Gtk.ResponseType.OK))
        d.set_current_name("page.pdf")
        if d.run() == Gtk.ResponseType.OK:
            path = d.get_filename()
            op = WebKit2.PrintOperation.new(wv)
            op.set_print_settings(WebKit2.PrintSettings.new())
            op.connect("finished", lambda o, p: self._status_label.set_text(f"PDF saved: {path}"))
            op.print_file(path)
        d.destroy()

    # --- Private Window ---

    def _new_private_window(self):
        self._safe_spawn(
            ["python3", os.path.join(os.path.dirname(__file__), "netron.py"),
             "--private"])

    # --- Audio indicator ---

    def _on_audio_changed(self, wv, pspec):
        playing = wv.get_is_playing_audio()
        for i in range(self._notebook.get_n_pages()):
            page = self._notebook.get_nth_page(i)
            if isinstance(page, TabPage) and page.webview == wv:
                tab_label = self._notebook.get_tab_label(page)
                if tab_label and hasattr(tab_label, "get_children"):
                    children = tab_label.get_children()
                    if children:
                        label = children[0]
                        if isinstance(label, Gtk.Label):
                            text = label.get_text()
                            icon = "🔊" if playing else ""
                            base = text.replace("🔊", "").replace("🔇", "").strip()
                            label.set_text(f"{icon} {base}".strip())
                break

    # --- Import Chrome Bookmarks ---

    def _import_chrome_bookmarks(self):
        d = Gtk.FileChooserDialog("Open Chrome Bookmarks", self,
                                  Gtk.FileChooserAction.OPEN,
                                  ("Cancel", Gtk.ResponseType.CANCEL,
                                   "Open", Gtk.ResponseType.OK))
        if d.run() == Gtk.ResponseType.OK:
            path = d.get_filename()
            self._parse_chrome_bookmarks(path)
        d.destroy()

    def _parse_chrome_bookmarks(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            count = 0

            def walk(node):
                nonlocal count
                if node.get("type") == "url":
                    url = node.get("url", "")
                    name = node.get("name", url)
                    if url and not self._bookmarks.contains(url):
                        self._bookmarks.add(name, url)
                        count += 1
                for c in node.get("children", []):
                    walk(c)

            roots = data.get("roots", {})
            for root in roots.values():
                walk(root)
            self._refresh_bookmark_bar()
            self._status_label.set_text(f"Imported {count} bookmarks")
        except Exception as e:
            d = Gtk.MessageDialog(self, 0, Gtk.MessageType.ERROR,
                                  Gtk.ButtonsType.OK, str(e))
            d.run()
            d.destroy()

    # --- Import Firefox Bookmarks ---

    def _import_firefox_bookmarks(self):
        d = Gtk.FileChooserDialog("Open Firefox Bookmarks HTML", self,
                                  Gtk.FileChooserAction.OPEN,
                                  ("Cancel", Gtk.ResponseType.CANCEL,
                                   "Open", Gtk.ResponseType.OK))
        if d.run() == Gtk.ResponseType.OK:
            path = d.get_filename()
            self._parse_firefox_bookmarks(path)
        d.destroy()

    def _parse_firefox_bookmarks(self, path):
        import html.parser

        class FFBookmarkParser(html.parser.HTMLParser):
            def __init__(self):
                super().__init__()
                self.urls = []
                self._in_a = False
                self._href = ""

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    self._in_a = True
                    for k, v in attrs:
                        if k == "href":
                            self._href = v

            def handle_endtag(self, tag):
                if tag == "a":
                    self._in_a = False
                    self._href = ""

            def handle_data(self, data):
                if self._in_a and self._href:
                    self.urls.append((data.strip(), self._href))

        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                html_content = f.read()
            parser = FFBookmarkParser()
            parser.feed(html_content)
            count = 0
            for title, url in parser.urls:
                if url and not self._bookmarks.contains(url):
                    self._bookmarks.add(title or url, url)
                    count += 1
            self._refresh_bookmark_bar()
            self._status_label.set_text(f"Imported {count} bookmarks")
        except Exception as e:
            d = Gtk.MessageDialog(self, 0, Gtk.MessageType.ERROR,
                                  Gtk.ButtonsType.OK, str(e))
            d.run()
            d.destroy()

    # --- Zoom (with per-site persistence) ---

    def _zoom_in(self):
        wv = self._current_webview()
        if wv:
            level = min(5.0, wv.get_zoom_level() + 0.1)
            wv.set_zoom_level(level)
            self._save_zoom(wv, level)

    def _zoom_out(self):
        wv = self._current_webview()
        if wv:
            level = max(0.3, wv.get_zoom_level() - 0.1)
            wv.set_zoom_level(level)
            self._save_zoom(wv, level)

    def _zoom_reset(self):
        wv = self._current_webview()
        if wv:
            wv.set_zoom_level(1.0)
            self._save_zoom(wv, 1.0)

    def _save_zoom(self, wv, level):
        uri = wv.get_uri()
        if uri:
            domain = urlparse(uri).hostname or ""
            if domain:
                self._zoom.set(domain, round(level, 1))

    # --- Find in page ---

    def _toggle_find(self):
        if self._find_bar.get_visible():
            self._find_bar.hide()
            wv = self._current_webview()
            if wv:
                wv.get_find_controller().search_finish()
        else:
            self._find_entry.set_text("")
            self._find_bar.show_all()
            self._find_entry.grab_focus()

    def _find_next(self, forward):
        if not self._find_bar.get_visible():
            return
        text = self._find_entry.get_text()
        if not text:
            return
        wv = self._current_webview()
        if wv:
            fc = wv.get_find_controller()
            if not hasattr(self, '_find_last_text') or self._find_last_text != text:
                self._find_last_text = text
                fc.search(text, 0, 100)
            elif forward:
                fc.search_next()
            else:
                fc.search_previous()

    # --- Bookmarks ---

    def _add_bookmark(self):
        wv = self._current_webview()
        if not wv:
            return
        url = wv.get_uri() or ""
        title = wv.get_title() or url
        self._add_bookmark_for(url, title)

    def _add_bookmark_for(self, url, title):
        if not url:
            return
        if self._bookmarks.contains(url):
            d = Gtk.MessageDialog(self, 0, Gtk.MessageType.INFO,
                                  Gtk.ButtonsType.OK, "Already bookmarked.")
            d.run()
            d.destroy()
            return
        dlg = AddBookmarkDialog(title, url, self)
        if dlg.run() == Gtk.ResponseType.OK:
            t, u = dlg.result()
            self._bookmarks.add(t, u)
            self._refresh_bookmark_bar()
        dlg.destroy()

    def _show_bookmark_mgr(self):
        dlg = BookmarkManagerDialog(self._bookmarks, self._navigate, self)
        dlg.run()
        dlg.destroy()
        self._refresh_bookmark_bar()

    def _import_bookmarks(self):
        d = Gtk.FileChooserDialog("Import Bookmarks", self,
                                  Gtk.FileChooserAction.OPEN,
                                  ("Cancel", Gtk.ResponseType.CANCEL,
                                   "Import", Gtk.ResponseType.OK))
        if d.run() == Gtk.ResponseType.OK:
            path = d.get_filename()
            try:
                with open(path) as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for b in data:
                            if isinstance(b, dict) and "title" in b and "url" in b:
                                self._bookmarks.add(b["title"], b["url"])
                        self._refresh_bookmark_bar()
            except Exception as e:
                d2 = Gtk.MessageDialog(self, 0, Gtk.MessageType.ERROR,
                                       Gtk.ButtonsType.OK, str(e))
                d2.run()
                d2.destroy()
        d.destroy()

    def _export_bookmarks(self):
        d = Gtk.FileChooserDialog("Export Bookmarks", self,
                                  Gtk.FileChooserAction.SAVE,
                                  ("Cancel", Gtk.ResponseType.CANCEL,
                                   "Export", Gtk.ResponseType.OK))
        if d.run() == Gtk.ResponseType.OK:
            path = d.get_filename()
            try:
                data = [{"title": b.title, "url": b.url}
                        for b in self._bookmarks.items]
                with open(path, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                d2 = Gtk.MessageDialog(self, 0, Gtk.MessageType.ERROR,
                                       Gtk.ButtonsType.OK, str(e))
                d2.run()
                d2.destroy()
        d.destroy()

    # --- History ---

    def _show_history(self):
        dlg = HistoryDialog(self._history, self._navigate, self)
        dlg.run()
        dlg.destroy()

    def _clear_browsing_data(self):
        d = Gtk.MessageDialog(self, 0, Gtk.MessageType.QUESTION,
                              Gtk.ButtonsType.YES_NO,
                              "Clear all cookies, cache, and site data?")
        if d.run() == Gtk.ResponseType.YES:
            self._web_context.get_website_data_manager().clear(
                [WebKit2.WebsiteDataTypes.COOKIES,
                 WebKit2.WebsiteDataTypes.MEMORY_CACHE,
                 WebKit2.WebsiteDataTypes.DISK_CACHE,
                 WebKit2.WebsiteDataTypes.LOCAL_STORAGE,
                 WebKit2.WebsiteDataTypes.INDEXEDDB_DATABASES],
                0, None, None, None)
            self._history.clear()
            self._status_label.set_text("Browsing data cleared")
        d.destroy()

    # --- Settings ---

    def _show_settings(self):
        dlg = SettingsDialog(self._settings, self)
        if dlg.run() == Gtk.ResponseType.OK:
            dlg.apply()
            self._yt_enabled = self._settings.get("youtube_handler_enabled")
            self._apply_cookie_policy()
            for i in range(self._notebook.get_n_pages()):
                page = self._notebook.get_nth_page(i)
                if isinstance(page, TabPage):
                    self._apply_wv_settings(page.webview)
            # Apply theme via CSS
            self._apply_theme()
            # Rebuild current tab if new tab changed
            wv = self._current_webview()
            if wv and (wv.get_uri() or "") == "":
                pass  # will refresh on next new tab
        dlg.destroy()

    # --- Downloads ---

    def _safe_open(self, path):
        try:
            subprocess.Popen(["xdg-open", path],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
        except Exception as e:
            self._status_label.set_text(f"Error opening {path}: {e}")

    def _safe_spawn(self, args):
        try:
            subprocess.Popen(args,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
        except Exception as e:
            self._status_label.set_text(f"Error: {e}")

    def _on_dl_icon_clicked(self, button):
        self._dl_icon.hide()
        self._safe_open(self._settings.get("download_dir"))

    def _pick_filename(self, uri, download):
        """Get best available filename from response headers or URL."""
        resp = download.get_response()
        if resp:
            suggested = resp.get_suggested_filename()
            if suggested:
                return suggested
        path = urlparse(uri).path
        name = os.path.basename(unquote(path))
        if name and name != "/":
            return name
        return "download"

    def _save_as_dialog(self, download, uri):
        dldir = self._settings.get("download_dir")
        if not os.path.exists(dldir):
            os.makedirs(dldir, exist_ok=True)

        name = self._pick_filename(uri, download)
        chooser = Gtk.FileChooserDialog(
            title="Save As", parent=self, action=Gtk.FileChooserAction.SAVE)
        chooser.add_button("Cancel", Gtk.ResponseType.CANCEL)
        chooser.add_button("Save", Gtk.ResponseType.ACCEPT)
        chooser.set_current_name(name)
        chooser.set_current_folder(dldir)
        chooser.set_do_overwrite_confirmation(True)
        result = chooser.run()
        dest = chooser.get_filename()
        chooser.destroy()

        if result != Gtk.ResponseType.ACCEPT:
            download.cancel()
            return

        self._dl_count += 1
        self._downloads_bar.add_download(download, name)

        def on_finish(d):
            self._dl_icon.show()
            self._status_label.set_text(f"✓ {name}")

        download.connect("finished", on_finish)
        download.set_destination(dest)

    def _on_download_started(self, ctx, download):
        uri = download.get_request().get_uri()
        if uri.startswith("http://localhost/"):
            download.cancel()
            return

        if download.get_response():
            self._save_as_dialog(download, uri)
        else:
            # Response not yet available — wait for it to get the filename
            def _on_response(dl, pspec):
                dl.disconnect(resp_id)
                self._save_as_dialog(dl, uri)
            resp_id = download.connect("notify::response", _on_response)

    # --- About ---

    def _show_about(self):
        d = Gtk.AboutDialog()
        d.set_program_name("Netron Browser")
        d.set_version("1.3.0")
        d.set_comments(
            "Lightweight browser for low-power single-core machines.\n"
            "YouTube → yt-dlp + mpv • Ad blocking • Download confirmation")
        d.set_license_type(Gtk.License.MIT_X11)
        d.run()
        d.destroy()
