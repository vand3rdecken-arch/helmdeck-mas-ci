# -*- coding: utf-8 -*-
"""Text that reached a record already mangled: UTF-8 bytes decoded once as
cp1252/latin-1 ('VollstÃ¤ndigkeit' for 'Vollständigkeit').

ONE owner, applied at the PERSISTENCE edge (processes._save) - never at each
display site. Measured 2026-10-05: 30 process step titles in the live db carried
it and the Henry thread list showed them raw, while chat had its own private
repair that the list never called. Idempotent and lossless: a string that is
not mojibake (no 'Ã'/'Â', or does not round-trip) comes back unchanged."""


def demojibake(s):
    if not isinstance(s, str) or ("Ã" not in s and "Â" not in s):
        return s
    for enc in ("cp1252", "latin-1"):
        try:
            return s.encode(enc).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return s
