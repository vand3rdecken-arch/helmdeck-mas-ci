# -*- coding: utf-8 -*-
"""Serve an `expo export --platform web` build so CLIENT-SIDE ROUTES RESOLVE.

Plain `http.server` cannot host this build: the export writes one file per route
(`chat.html`), but expo-router matches on the URL PATH, so fetching `/chat.html`
loads the bundle and then renders "Unmatched Route" because `/chat.html` is not
a route the app declares. This maps `/chat` -> `chat.html` (and falls back to
`index.html`) so the path the router sees is the path it was built for.

Usage:  py -3.12 tools/serve_export.py <dir> <port>
"""
import os
import sys
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler


class RouteHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        p = super().translate_path(path.split("?")[0].split("#")[0])
        if os.path.isdir(p):
            idx = os.path.join(p, "index.html")
            if os.path.exists(idx):
                return idx
        if not os.path.exists(p):
            html = p + ".html"
            if os.path.exists(html):
                return html
            # SPA fallback: unknown deep link still boots the app
            return os.path.join(self.directory, "index.html")
        return p

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    root = sys.argv[1]
    port = int(sys.argv[2])
    os.chdir(root)
    print("serving %s on %d" % (root, port), flush=True)
    HTTPServer(("127.0.0.1", port),
               partial(RouteHandler, directory=root)).serve_forever()
