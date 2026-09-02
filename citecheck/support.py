"""Text normalization + literal-substring support checking.

The normalization is deliberately CHARACTER-LENGTH-PRESERVING: every input
character maps to exactly one output character. That means a substring match
found in normalize(text) lands at the SAME offset in the original text, so a
`span` reported against the raw opinion text is never approximate and never
needs a second alignment pass. This is what makes "a span that does not
resolve is a hard defect" checkable by construction: span = the exact
[start, end) that FIND already proved is inside the text.

Normalization folds:
  - all whitespace characters -> a single space character (count preserved,
    NOT collapsed -- "a  b" stays two chars of whitespace, just each mapped
    to ' ').
  - curly/smart quotes -> straight quotes (' and ").
  - case -> lower, character-by-character, and ONLY when Python's per-char
    .lower() returns exactly one character (guards the rare multi-char
    lower() expansions so length-preservation is never violated).

This is intentionally strict: it does NOT collapse repeated whitespace, does
NOT strip punctuation, and does NOT fuzzy-match. A misquote (wrong word,
transposed clause, altered number) will not match. See README "Known data
quality notes" for one corpus-side gap this strictness deliberately does not
paper over: some opinion text in this corpus has smart quotes that were
corrupted to U+FFFD during acquisition, and a document that quotes those
exact words with a real quotation mark will not match across that
character. That is a corpus data-quality boundary, not a matching bug, and
is documented rather than fuzzy-matched around.
"""
from __future__ import annotations

_QUOTE_SINGLE = {"‘", "’", "ʼ", "′"}
_QUOTE_DOUBLE = {"“", "”", "″"}


def _normalize_char(c: str) -> str:
    if c.isspace():
        return " "
    if c in _QUOTE_SINGLE:
        return "'"
    if c in _QUOTE_DOUBLE:
        return '"'
    lowered = c.lower()
    if len(lowered) == 1:
        return lowered
    return c


def normalize(text: str) -> str:
    """Length-preserving normalization. len(normalize(s)) == len(s) always."""
    return "".join(_normalize_char(c) for c in text)


def _canonicalize_for_matching(text: str) -> "tuple[str, list, list]":
    """Case/quote-normalize AND collapse every run of whitespace to a single
    ' ' (unlike `normalize()`, which is deliberately length-preserving and
    keeps a doubled space doubled). This is used only for MATCHING -- so a
    doubled/irregular internal space in a proposition (or, symmetrically, in
    the opinion text) does not defeat an otherwise-exact literal-substring
    match (the specification gate: internal whitespace runs are equivalent for matching
    purposes).

    Returns (canonical, starts, ends), where for every index i into
    `canonical`:
      starts[i] -- the offset in the ORIGINAL `text` where canonical[i]
                   begins.
      ends[i]   -- the offset in the ORIGINAL `text` immediately after the
                   run of original characters canonical[i] represents. For
                   an ordinary (non-whitespace) character this is
                   `starts[i] + 1`; for a collapsed whitespace run it is the
                   offset right after the WHOLE original run, so a match
                   spanning that character maps back to the exact original
                   span, not a truncated one.

    This lets a caller recover an exact, literal ORIGINAL-text span for any
    match found in `canonical` -- the reported span/quoted_sentence always
    slices the untouched stored text, never a normalized copy of it.
    """
    canonical_chars: list = []
    starts: list = []
    ends: list = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            canonical_chars.append(" ")
            starts.append(i)
            ends.append(j)
            i = j
        else:
            canonical_chars.append(_normalize_char(ch))
            starts.append(i)
            ends.append(i + 1)
            i += 1
    return "".join(canonical_chars), starts, ends


def find_support(proposition: str, opinion_text: str) -> "tuple[int, int] | None":
    """Return (start, end) span in opinion_text where proposition appears as
    a literal substring under case/quote normalization AND whitespace-run
    collapsing, or None if it does not.

    Matching is done against a CANONICAL form of both strings (whitespace
    runs collapsed to one space), so e.g. a doubled internal space in the
    proposition matches a single space in the opinion text and vice versa.
    The returned span, however, is mapped back to exact offsets in the
    ORIGINAL (uncollapsed) `opinion_text` via the canonical->original offset
    map from `_canonicalize_for_matching`, so `opinion_text[start:end]` is
    always a literal, unaltered slice of the stored text -- normalization is
    never allowed to fabricate or approximate a span.
    """
    proposition = proposition.strip()
    if not proposition:
        return None
    canon_prop, _, _ = _canonicalize_for_matching(proposition)
    if not canon_prop:
        return None
    canon_text, starts, ends = _canonicalize_for_matching(opinion_text)
    idx = canon_text.find(canon_prop)
    if idx == -1:
        return None
    match_end = idx + len(canon_prop) - 1
    start = starts[idx]
    end = ends[match_end]
    return (start, end)
