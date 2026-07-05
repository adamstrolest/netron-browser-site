#!/usr/bin/env python3
"""Netron Browser — lightweight browser for low-power machines."""

import os
import sys

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_version("GLib", "2.0")
from gi.repository import Gtk

from persistence import BookmarkStore, HistoryStore, SettingsStore, SessionStore, ZoomStore
from browser import BrowserWindow


def main():
    private = "--private" in sys.argv
    settings = SettingsStore()
    bookmarks = BookmarkStore()
    history = HistoryStore()
    session = SessionStore()
    zoom = ZoomStore()
    session.load()
    zoom.load()

    win = BrowserWindow(settings, bookmarks, history, session, zoom, private=private)
    Gtk.main()


if __name__ == "__main__":
    main()
