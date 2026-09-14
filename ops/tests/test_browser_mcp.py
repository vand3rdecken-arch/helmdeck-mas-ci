# -*- coding: utf-8 -*-
"""spine/media/browsercap.py's five bounded browser verbs + ops/tools/
browser_mcp.py's MCP wrapper (ops/docs/backlog/token-burn-hardening/
README.md, Karte C).

The deliverable is OUTPUT SHAPING: a single windows-mcp `Snapshot` returned
600-700 KB of UIA tree per call (the 190M-token Wear-OS turn); read()/find()
must stay under browsercap.MAX_ACTION_CHARS and read() must never leak
off-screen content, however big the page. Also proves the adversarial path a
bounded verb exists for: a selector that matches nothing fails FAST (seconds,
not Playwright's 30s default) with a short, capped error - not a hang and not
an unbounded traceback dumped into the model's context.

Unit-level (no browser): _cap_text, and browser_mcp._shaped's exception
shaping. Live-browser (fallback context, no CDP attach - self-sandboxing,
never touches the owner's real Chrome profile): viewport scoping, the
find()-locator round-trip into click(), and the selector-miss path.

Run: py -3.12 ops/tests/test_browser_mcp.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))

from spine.media import browsercap

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# -- unit: the cap primitive --------------------------------------------
def test_cap_text_leaves_short_strings_alone():
    check(browsercap._cap_text("short") == "short", "well under the cap comes back unchanged")


def test_cap_text_caps_long_strings_with_marker():
    big = "x" * 100
    out = browsercap._cap_text(big, limit=10)
    check(out.startswith("x" * 10), "kept text is the HEAD of the original")
    check(out.endswith(browsercap._TRUNC), "truncated text ends with the marker tail")
    check(len(out) == 10 + len(browsercap._TRUNC), "cap + marker, nothing extra")


def test_cap_text_default_limit_is_the_module_constant():
    out = browsercap._cap_text("y" * (browsercap.MAX_ACTION_CHARS + 500))
    check(len(out) == browsercap.MAX_ACTION_CHARS + len(browsercap._TRUNC),
          "no explicit limit falls back to MAX_ACTION_CHARS (5000)")


# -- unit: browser_mcp's error shaping (no browser needed) --------------
def test_shaped_turns_an_exception_into_a_short_capped_string():
    import browser_mcp as bmcp

    def boom():
        raise RuntimeError("x" * (browsercap.MAX_ACTION_CHARS + 500))
    out = bmcp._shaped(boom)
    check(out.startswith("error: "), "an exception becomes a plain 'error: ...' string, never raised")
    check(len(out) <= browsercap.MAX_ACTION_CHARS + len(browsercap._TRUNC) + 10,
          "even a huge exception message stays capped")


# -- live-browser: fallback context, never the real attached Chrome -----
def _fresh_browser():
    run_dir = tempfile.mkdtemp()
    return browsercap.AgentBrowser(run_dir, attach=False, headless=True)


def _file_url(html):
    d = tempfile.mkdtemp()
    path = os.path.join(d, "page.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return "file:" + "//" + path.replace(os.sep, "/")


def test_read_is_viewport_scoped_not_whole_page():
    paras = "".join("<p>paragraph %d filler text to bulk the page up</p>" % i for i in range(2000))
    url = _file_url("<html><body>%s</body></html>" % paras)
    b = _fresh_browser()
    try:
        b.goto(url)
        out = b.read()
        check(len(out) <= browsercap.MAX_ACTION_CHARS, "read() output never exceeds the cap")
        check("paragraph 1999" not in out,
              "the last of 2000 off-screen paragraphs is excluded - viewport-scoped, not whole-page")
        check("paragraph 0" in out, "the first, on-screen paragraph IS present")
    finally:
        b.close()


def test_find_caps_at_20_and_locators_are_click_addressable():
    links = "".join('<a href="#%d" style="display:block">link %d</a>' % (i, i) for i in range(50))
    url = _file_url("<html><body>%s<div id=marker>untouched</div></body></html>" % links)
    b = _fresh_browser()
    try:
        b.goto(url)
        out = b.find("a")
        matches = [l for l in out.splitlines() if l.strip()]
        check(len(matches) == 20, "find() caps to 20 matches even with 50 in the DOM (got %d)" % len(matches))
        check("-> a >> nth=0" in out, "each match carries a ready-to-use nth locator")
        # round-trip: a locator find() returned must actually work for click()
        b.click("a >> nth=5")
        check(b.page.url.endswith("#5"), "the locator find() reported for index 5 clicks the SAME element")
    finally:
        b.close()


def test_find_reaches_off_screen_elements_that_read_cannot_see():
    # a button far below the fold - read() must not see it, find() must,
    # and click() must be able to act on it anyway (Playwright auto-scrolls).
    html = ("<html><body><div style='height:4000px'>spacer</div>"
            "<button id=deep>deep button</button></body></html>")
    url = _file_url(html)
    b = _fresh_browser()
    try:
        b.goto(url)
        check("deep button" not in b.read(), "read() does not see a button 4000px below the fold")
        out = b.find("button")
        check("deep button" in out, "find() DOES see the same off-screen button (not viewport-limited)")
        b.click("button >> nth=0")
        check(True, "click() on an off-screen locator does not raise (Playwright scrolls it into view)")
    finally:
        b.close()


def test_selector_miss_fails_fast_with_a_bounded_error():
    url = _file_url("<html><body><p>hello</p></body></html>")
    b = _fresh_browser()
    try:
        b.goto(url)
        t0 = time.time()
        try:
            b.click("#totally-absent")
            check(False, "a selector matching nothing must raise, not silently no-op")
        except Exception as e:
            elapsed = time.time() - t0
            check(elapsed < 15, "a selector miss fails in well under Playwright's 30s default (%.1fs)" % elapsed)
            check(len(str(e)) < 2000, "the raised error itself is a bounded Playwright message, not a page dump")
    finally:
        b.close()


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _cdp_json(port, path, method="GET"):
    import json
    import urllib.request
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode() or "null") if "close" not in path else None


def _hang_target(ws_url):
    """Spin a tab's renderer main thread forever - the 2026-09-14 incident
    shape (three App Store Connect tabs that answered no CDP call)."""
    import json
    from websockets.sync.client import connect
    ws = connect(ws_url, open_timeout=5, max_size=None)
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": "for(;;){}"}}))
    ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": "1"}}))
    try:
        while True:
            if json.loads(ws.recv(timeout=2)).get("id") == 2:
                return False
    except TimeoutError:
        return True
    finally:
        ws.close()


def test_attach_survives_a_hung_foreign_tab():
    """THE REAL ATTACH PATH (attach=True, CDP on a debug port) against a
    browser that holds a hung tab belonging to someone else. Playwright's
    connect_over_cdp auto-attaches EVERY tab and awaits all of them, so the
    old attach blocked for 180s on any one hung tab - every card on the
    machine at once. A throwaway headless Chrome on its own port + profile,
    never the owner's; wincap and the action log are stubbed only because
    desktop recording and the live-db audit row are not the connection path."""
    import shutil
    import subprocess
    import threading
    port = _free_port()
    profile = tempfile.mkdtemp()
    chrome = subprocess.Popen([
        browsercap._chrome_exe(), "--headless=new", "--remote-debugging-port=%d" % port,
        "--user-data-dir=%s" % profile, "--no-first-run", "--no-default-browser-check", "about:blank"])
    real_start = browsercap.wincap.start
    browsercap.wincap.start = lambda run_dir: None
    box = {}
    try:
        for _ in range(60):
            if browsercap._cdp_up(port):
                break
            time.sleep(0.25)
        foreign = _cdp_json(port, "/json/new?about:blank", method="PUT")
        check(_hang_target(foreign["webSocketDebuggerUrl"]), "precondition: the foreign tab really answers no CDP call")

        def attach():
            try:
                box["b"] = browsercap.AgentBrowser(tempfile.mkdtemp(), attach=True, port=port,
                                                   log=type("NullLog", (), {"log": lambda *a, **k: None})())
            except BaseException as e:
                box["err"] = e
        t0 = time.time()
        th = threading.Thread(target=attach, daemon=True)
        th.start()
        th.join(20)
        check("b" in box, "attach completes despite the hung foreign tab (%.1fs, err=%r)"
              % (time.time() - t0, box.get("err")))
        if "b" not in box:
            return
        b = box["b"]
        b.goto(_file_url("<html><body><p>own tab alive</p><button id=b onclick=\"document.title='hit'\">Go</button></body></html>"))
        check("own tab alive" in b.read(), "read() works on the card's own tab")
        check("button >> nth=0" in b.find("button"), "find() works on the card's own tab")
        b.click("button >> nth=0")
        check(b.page.title() == "hit", "click() via a find() locator reaches the element")
        b.click("text=own tab")
        check(True, "text= selector resolves")

        b.page.evaluate("() => setTimeout(() => { for(;;){} }, 0)")
        time.sleep(0.5)
        t0 = time.time()
        try:
            b.read()
            check(False, "read() on a hung OWN tab must raise, not return")
        except Exception as e:
            check(time.time() - t0 < 15, "own-tab hang fails in bounded time (%.1fs), not 180s" % (time.time() - t0))
            check("did not answer" in str(e), "the error says plainly the tab did not answer: %r" % str(e)[:160])
        own_id = b.page.target_id
        b.close()
        for waited in range(40):       # /json/close answers "Target is closing" - it is async
            ids = [t["id"] for t in _cdp_json(port, "/json/list")]
            if own_id not in ids:
                break
            time.sleep(0.25)
        print("  info own tab gone after %.2fs" % (waited * 0.25))
        check(foreign["id"] in ids, "close() leaves the foreign (hung) tab alone - never kills another card's tab")
        check(own_id not in ids, "close() removes the card's own tab")
    finally:
        browsercap.wincap.start = real_start
        chrome.kill()
        chrome.wait(timeout=10)
        shutil.rmtree(profile, ignore_errors=True)


def test_mcp_server_end_to_end_over_stdio():
    """THE test that was missing when the verbs shipped (4474e29): the old
    MCP-level check called browser_mcp.navigate() as a plain Python function,
    so FastMCP's real dispatch - a sync tool run ON the asyncio loop thread,
    where Playwright's sync API refuses to work - was never exercised, and a
    server that failed every verb passed green. This one speaks MCP JSON-RPC
    over stdio to the real server process, exactly as the CLI does, and drives
    navigate/read/click through it. HELMDECK_BROWSER_ATTACH=0 = browsercap's
    sandbox context, never the owner's Chrome."""
    import json
    import subprocess
    env = dict(os.environ, HELMDECK_BROWSER_ATTACH="0", PYTHONIOENCODING="utf-8")
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "ops", "tools", "browser_mcp.py")],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", env=env)
    _id = [0]

    def rpc(method, params=None):
        _id[0] += 1
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": _id[0], "method": method,
                                  "params": params or {}}) + "\n")
        p.stdin.flush()
        while True:
            line = p.stdout.readline()
            if not line:
                raise RuntimeError("server closed stdout; stderr: " + p.stderr.read()[-2000:])
            msg = json.loads(line)
            if msg.get("id") == _id[0]:
                return msg

    def call(name, **args):
        r = rpc("tools/call", {"name": name, "arguments": args})
        res = r.get("result") or {}
        text = "".join(c.get("text", "") for c in res.get("content", []))
        return text, bool(res.get("isError")), r.get("error")

    try:
        rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "0"}})
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        p.stdin.flush()
        tools = [t["name"] for t in rpc("tools/list")["result"]["tools"]]
        check(tools == ["navigate", "read", "find", "click", "type"], "tools/list = the five verbs, in order")

        url = _file_url("<html><body><p>hello e2e</p><button id=b>Go</button></body></html>")
        out, err, rpcerr = call("navigate", url=url)
        check(not rpcerr and not err and out.startswith("ok:"),
              "navigate() through REAL FastMCP dispatch succeeds: %r" % out[:120])
        check("asyncio" not in out, "no 'Sync API inside the asyncio loop' - the browser runs on its owner thread")
        out, err, _ = call("read")
        check("hello e2e" in out, "read() through the server returns the page text")
        out, err, _ = call("click", selector="#b")
        check(out.startswith("ok: clicked"), "click() through the server hits the element")
        t0 = time.time()
        out, err, _ = call("click", selector="#totally-absent")
        check(out.startswith("error: ") and time.time() - t0 < 20,
              "a miss surfaces as a shaped 'error: ...' string in bounded time, not a hang")
        check(len(out) <= browsercap.MAX_ACTION_CHARS + len(browsercap._TRUNC) + 10,
              "the MCP-level error stays capped too")
    finally:
        try:
            p.stdin.close()
            p.wait(timeout=30)
        except Exception:
            p.kill()
    check(p.returncode == 0, "server exits 0 on stdin EOF (browser closed on its owner thread)")


if __name__ == "__main__":
    test_cap_text_leaves_short_strings_alone()
    test_cap_text_caps_long_strings_with_marker()
    test_cap_text_default_limit_is_the_module_constant()
    test_shaped_turns_an_exception_into_a_short_capped_string()
    test_read_is_viewport_scoped_not_whole_page()
    test_find_caps_at_20_and_locators_are_click_addressable()
    test_find_reaches_off_screen_elements_that_read_cannot_see()
    test_selector_miss_fails_fast_with_a_bounded_error()
    test_attach_survives_a_hung_foreign_tab()
    test_mcp_server_end_to_end_over_stdio()
    print("OK" if not _fails else "FAILED: %d" % len(_fails))
    sys.exit(1 if _fails else 0)
