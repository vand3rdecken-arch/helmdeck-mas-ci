# -*- coding: utf-8 -*-
"""Serve an `expo export --platform web` output for screenshotting.

The Expo DEV server is interactive and needs a TTY, which Git-Bash/MinTTY does
not give node (see ops/docs traps) - it binds the port and then never bundles.
A static export plus this server is the non-interactive path to the same UI.

Falls back to index.html for unknown paths so expo-router's client routes
(/chat, /card/<id>) resolve the way they do in the dev server.

Usage:  py -3.12 ops/tools/serve_export.py <dir> <port>
"""
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "dist-shot")
port = int(sys.argv[2] if len(sys.argv) > 2 else "3560")


class SPA(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=root, **kw)

    def send_head(self):
        path = self.translate_path(self.path)
        if not os.path.exists(path):
            # try <route>.html first (expo-router emits static route files),
            # then the SPA shell
            for cand in (path + ".html", os.path.join(root, "index.html")):
                if os.path.exists(cand):
                    self.path = "/" + os.path.relpath(cand, root).replace(os.sep, "/")
                    break
        return super().send_head()

    def log_message(self, *a):
        pass            # quiet - the screenshot tool is the only consumer


print("serving %s on http://localhost:%d" % (root, port), flush=True)
ThreadingHTTPServer(("127.0.0.1", port), SPA).serve_forever()
