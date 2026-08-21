# -*- coding: utf-8 -*-
"""Server-rendered speech, so the agent can ANSWER OUT LOUD on the glasses.

This exists because of one measured fact, not a preference: **the Meta Ray-Ban
Display webview has no `speechSynthesis`** - confirmed on-device 2026-07-16
(`glass-crud-harness/app/index.html:804`) - **but it DOES play audio** ("podcasts
work"). So the lens cannot synthesise a sentence, and it can play a file you
hand it. Speech is therefore rendered HERE and played there as an ordinary audio
clip. That is the same conclusion docs/glasses-reference.md §4 reached for the
WhatsApp channel; this is the in-app half of it.

Two deliberate differences from the reference recipe
(`glass-crud-harness/tools/voice_note.py`), both because the destination differs:
- **mp3, not ogg/opus.** That recipe targets a WhatsApp voice note, which must
  be ogg/opus mono. The lens just plays a URL, and the reference's own
  announcement path already proves mp3 plays there ("announcements play as an
  AUDIO CLIP (Google TTS mp3)"). Dropping the opus step also drops the whole
  ffmpeg dependency - `transcode.available()` is False on this box, so an
  ffmpeg-shaped design would have been dead on arrival here.
- **Cached by content hash.** A glance surface re-reads the same few sentences
  ("nothing needs you") far more often than a chat does, and each render is a
  network round trip to Microsoft's voice service.

FAILS SOFT, ALWAYS. edge-tts needs the network; the box may be offline, the
package may be missing, the service may rate-limit. Every failure returns None
and the caller shows text instead. Speech is an enhancement to a surface that
already works silently - it must never be able to take the answer away.
"""
import hashlib
import os
import re
import threading
import time

from daemon.paths import DAEMON_ROOT as ROOT
CACHE = os.path.join(ROOT, "voice_cache")

# The multilingual voice is deliberate: HelmDeck card titles are mixed
# German/English ("Dashboard zu überfüllt"), and voice_note.py:11 picked this one
# for exactly that reason - "handles mixed German/English naturally".
DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"
RATE = "+8%"                 # voice_note.py:31

MAX_TEXT = 1200              # ~90s of speech; a lens reply is 2 sentences
MAX_FILES = 200              # cache bound, oldest pruned

_LOCK = threading.RLock()


def available():
    """True when a render could plausibly work. Cheap - does not touch the
    network, so it is safe on a request path."""
    try:
        import edge_tts                                     # noqa: F401
        return True
    except Exception:
        return False


def _key(text, voice):
    return hashlib.sha256(("%s|%s|%s" % (voice, RATE, text)).encode("utf-8")).hexdigest()[:20]


def path_for(vid):
    """Resolve a cache id to a file, or None. Guards traversal: the id is used
    in a URL, so it is checked to be exactly what we mint, never joined raw."""
    if not vid or not vid.isalnum() or len(vid) > 32:
        return None
    p = os.path.join(CACHE, vid + ".mp3")
    return p if os.path.exists(p) else None


def _prune():
    try:
        files = [os.path.join(CACHE, f) for f in os.listdir(CACHE) if f.endswith(".mp3")]
    except OSError:
        return
    if len(files) <= MAX_FILES:
        return
    files.sort(key=lambda f: os.path.getmtime(f))
    for f in files[:len(files) - MAX_FILES]:
        try:
            os.remove(f)
        except OSError:
            pass


_MD_STRIP = [
    (re.compile(r"```.*?(```|$)", re.S), " "),          # code fences: unlistenable
    (re.compile(r"`([^`]*)`"), r"\1"),                  # inline code ticks
    (re.compile(r"\*{1,3}([^*]*)\*{1,3}"), r"\1"),      # *em* **bold** ***both***
    (re.compile(r"_{1,2}([^_]*)_{1,2}"), r"\1"),        # _em_ __bold__
    (re.compile(r"^#{1,6}\s*", re.M), ""),              # # headings
    (re.compile(r"^\s*[-*•]\s+", re.M), ""),            # bullet markers
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),      # [text](url) -> text
    (re.compile(r"[|>~]+"), " "),                       # tables/quotes glyphs
]


def speakable(text):
    """Markdown -> prose a HUMAN would say. The model writes for the screen
    (**bold**, bullets, `code`) and edge-tts reads the glyphs LITERALLY -
    measured 2026-08-21: Henry saying 'Stern Stern Stern' mid-sentence. One
    owner for the cleanup, applied INSIDE render, so every speech path (chat
    voice, streaming sentences, /notify/speak, glance) is covered."""
    for rx, rep in _MD_STRIP:
        text = rx.sub(rep, text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _voice_choice(explicit):
    """settings `tts_voice` overrides the default (owner ask 2026-08-21: the
    multilingual Andrew auto-switches to German but keeps a non-native tint;
    a native de-DE voice is one settings line away, e.g.
    de-DE-SeraphinaMultilingualNeural). Explicit caller choice still wins."""
    if explicit:
        return explicit
    try:
        from daemon.spine.storage import events
        return (events.settings().get("tts_voice") or "").strip() or DEFAULT_VOICE
    except Exception:
        return DEFAULT_VOICE


def render(text, voice=""):
    """Text -> cache id of a playable mp3, or None if speech is unavailable.

    Never raises: a missing package, no network, or a service error all mean
    "no audio this time", which the caller degrades to text.
    """
    voice = _voice_choice(voice)
    text = speakable((text or "")).strip()
    if not text:
        return None
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT]
    vid = _key(text, voice)
    with _LOCK:
        if path_for(vid):
            return vid                       # already spoken once - free
        try:
            import asyncio
            import edge_tts
        except Exception:
            return None
        os.makedirs(CACHE, exist_ok=True)
        tmp = os.path.join(CACHE, ".%s.%d.part" % (vid, os.getpid()))
        out = os.path.join(CACHE, vid + ".mp3")
        try:
            async def _gen():
                await edge_tts.Communicate(text, voice, rate=RATE).save(tmp)
            asyncio.run(_gen())
            if not os.path.exists(tmp) or os.path.getsize(tmp) < 512:
                raise RuntimeError("empty render")
            os.replace(tmp, out)             # atomic: a reader never sees a part file
        except Exception:
            for p in (tmp,):
                try:
                    os.remove(p)
                except OSError:
                    pass
            return None
        _prune()
        return vid


def render_b64(text, voice=""):
    """Speech as an INLINE base64 data payload, or None.

    The glasses take a URL (`/glance/voice/<id>.mp3`) because they talk to the
    daemon directly. The PHONE usually does not: it goes through the E2EE relay,
    which seals and forwards ONE JSON request/response - there is no second
    channel for a browser to fetch a binary from, and a URL pointing at
    localhost means nothing on a phone across the internet. So the phone's audio
    has to ride inside the JSON it already gets.

    Cost of that choice, stated plainly: base64 is ~33% larger than the file, so
    a 30 KB clip becomes ~40 KB inside the sealed frame. That is acceptable for
    two sentences and is the reason MAX_TEXT is small; it would NOT be
    acceptable for reading a long document aloud, which is why the caller speaks
    only Henry's prose and never a transcript.
    """
    vid = render(text, voice)
    if not vid:
        return None
    p = path_for(vid)
    if not p:
        return None
    try:
        import base64
        with open(p, "rb") as f:
            return {"id": vid, "mime": "audio/mpeg",
                    "b64": base64.b64encode(f.read()).decode("ascii")}
    except OSError:
        return None


def stats():
    try:
        files = [f for f in os.listdir(CACHE) if f.endswith(".mp3")]
    except OSError:
        files = []
    return {"available": available(), "cached": len(files)}
