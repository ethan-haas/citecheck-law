"""Extracts citations, parsed fields, and an associated proposition from a
plain-text legal document.

Deliberately independent of resolve.py/corpus.py: this module only looks at
the document text. Whether a citation resolves to anything real is a
downstream question. (acceptance gate 3: parsing must be testable independently of
verification.)

Citation shape recognized: `VOLUME REPORTER PAGE[, PINPOINT]`, e.g.
`347 U.S. 483` or `347 U.S. 483, 495`. REPORTER is matched generically as
1-4 capitalized/period/digit tokens (e.g. "U.S.", "F.3d", "S. Ct.",
"Cal. Rptr. 3d") so citations to reporters this corpus does not carry are
still extracted (and then correctly refused downstream) rather than
silently dropped.

An optional case name `X v. Y` immediately preceding the citation (within a
short window, no sentence break in between) is captured when present.

Proposition association (heuristic, documented as a scope limitation):
  1. The nearest quoted string (straight or curly quotes) in the same
     paragraph that ends before the citation and is not separated from it
     by another citation is used verbatim as the proposition.
  2. Otherwise, the clause of text from the end of the previous citation (or
     start of paragraph) up to the start of the case-name/citation is used
     as the (paraphrase) proposition.
This is a heuristic over where a proposition is written, not over whether it
is TRUE -- the verdict layer only ever accepts a literal-substring match, so
an imperfect proposition span can under-count `verified`/cause a false
`exists, unsupported`, but it can never fabricate support that isn't there.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


REPORTER_TOKEN = (
    r"(?:[A-Z][A-Za-z.]*(?:\d(?:st|nd|rd|th|d))?|\d(?:st|nd|rd|th|d))"
)
REPORTER_RE = rf"(?:{REPORTER_TOKEN})(?:\s(?:{REPORTER_TOKEN})){{0,2}}"

CITATION_RE = re.compile(
    rf"""
    (?P<volume>\d{{1,4}})\s+
    (?P<reporter>{REPORTER_RE})\s+
    (?P<page>\d{{1,5}})
    (?:\s*,\s*(?P<pinpoint>\d{{1,5}})
        # (?!\d) forces the MAXIMAL digit run -- without it, regex
        # backtracking can satisfy the parallel-citation lookahead below by
        # trying a truncated pinpoint ("7" out of "74") that happens to be
        # followed by a bare digit ("4 S. Ct. 686") rather than a full
        # reporter token, silently reintroducing the same bug one digit
        # short.
        (?!\d)
        # a `, <digits>` run is a pinpoint ONLY if it is NOT itself
        # the volume of a PARALLEL citation ("347 U.S. 483, 74 S. Ct. 686"
        # -- 74 is the volume of the parallel S. Ct. cite, not a pinpoint
        # page inside U.S. 483). If what follows the digits is another
        # reporter token + page number, this is a parallel citation, and it
        # is left unconsumed here so the next finditer() scan picks it up
        # as its own, independent citation instead of a fabricated
        # `wrong_pinpoint` flag on this one.
        (?!\s+{REPORTER_RE}\s+\d)
    )?
    """,
    re.VERBOSE,
)

# Case names commonly contain lowercase connector words ("Board of
# Education", "United States of America"), so only the FIRST word of each
# party name is required to be capitalized; a later word may ALSO be
# capitalized (e.g. "St. Louis", "Fed. Election Comm'n"), or it may be one of
# a small whitelist of lowercase connector words. It may NOT be an arbitrary
# lowercase word -- that would let ordinary prose ("...secures Fourth
# Amendment protection.") bleed into the case name across a sentence
# boundary (see _find_case_name / E2 regression tests).
CASE_NAME_CONNECTOR_WORDS = frozenset(
    "of the and for in on de la du des del van von et al by at ex re "
    "a an to or from into as over y".split()
)

# A bare ampersand ("Texas & Pac. Ry. Co. v. Burch") and the lowercase
# relator-phrase continuation words "rel."/"dem." -- the second word of a
# bare-sovereign relator phrasing ("State ex rel. Moorehead v. Reed",
# "People ex rel. X v. Y", "Doe ex dem. Truluck v. Peeples"; "ex" itself is
# already a connector word above, and "United States ex rel." already
# resolves fine since "United States" is capitalized) -- are not ordinary
# English prose words, so accepting them can never bleed unrelated prose
# across a sentence boundary the way accepting an arbitrary lowercase word
# would, but they ARE legitimate in-name continuation tokens for a party
# name and must not stop the backward plaintiff scan (false-refusal escapes
# 1/2, corpus-scale-up round).
CASE_NAME_EXTRA_TOKENS = frozenset({"&", "rel.", "dem."})

# Historically the backward plaintiff scan capped how many tokens it would
# collect; a genuine multi-word plaintiff with lowercase connectors inside it
# ("Sweet Home Chapter of Communities for a Great Oregon v. Babbitt") can
# legitimately run past a small cap, silently truncating a real party name
# (false-refusal escape 3, corpus-scale-up round). The real backstops against
# runaway/prose-bleeding growth are the sentence-boundary check
# (`_party_token_ok` itself, via `_is_abbrev_stem`), the closing-quote hard
# boundary, the party-suffix boundary, and `CASE_NAME_WINDOW` bounding how
# much text is even in scope -- not an arbitrary word count -- so this cap is
# kept only as a generous safety net far above any real Bluebook party name.
MAX_PLAINTIFF_TOKENS = 40

# Bluebook abbreviation stems (periods/apostrophes stripped, lowercased)
# that legitimately end a party-name TOKEN in a period -- i.e. the period is
# part of the word's spelling, not a sentence-ending period. Any token whose
# stem is NOT in this set and is longer than 3 characters is treated as an
# ordinary English word, so a trailing period on it is a real sentence
# boundary (see _is_abbrev_stem / defect-class root cause below).
KNOWN_ABBREV_STEMS = frozenset(
    """
    st ste ft mt co corp inc ltd bd dept assn commn natl nat intl govt
    ry rr mfg mut sav ins dist cong admin auth bur cas ct dir div fed
    gen hosp indus inst mgmt min mun ord org pub sch sec serv sys twp
    univ util dr jr sr esq educ elec mfrs ry's assn's dept's natl's
    cnty commrs commrs's lp
    """.split()
)


def _is_abbrev_stem(stem: str) -> bool:
    """True if `stem` (a token with its trailing period already removed) is
    a standard Bluebook case-name abbreviation, so the period after it does
    NOT mark a sentence boundary.

    Two rules, in order: (1) a short stem (<=3 letters once internal
    periods/apostrophes are removed) covers the vast majority of Bluebook
    party-name abbreviations ("St.", "Bd.", "Co.", "Ft.", "Mt.", "Inc.",
    "Ltd.", ...) without needing to enumerate every one; ordinary capitalized
    English words are essentially never that short, so this rarely
    misclassifies a real sentence-ending word. (2) an explicit whitelist for
    the common 4+ letter abbreviations ("Educ.", "Corp.", "Assn.", ...).
    """
    bare = re.sub(r"[.']", "", stem).lower()
    if len(bare) <= 3:
        return True
    return bare in KNOWN_ABBREV_STEMS or stem.lower() in KNOWN_ABBREV_STEMS


# Bluebook party-suffix abbreviations: these CLOSE a party name --
# they are, by convention, the LAST word of a party immediately before its
# "v." (or the end of the case name). Stems here (periods/apostrophes
# stripped, lowercased) are a strict subset of KNOWN_ABBREV_STEMS used only
# to detect the closing-suffix condition below, never to redefine which
# tokens `_party_token_ok` accepts.
PARTY_SUFFIX_STEMS = frozenset("corp inc co ltd llc llp lp assn na".split())


def _is_party_suffix_token(token: str) -> bool:
    bare = re.sub(r"[.']", "", token).lower()
    return bare in PARTY_SUFFIX_STEMS


# Numbered-district designations ("School District No. 97", "Sewer
# Improvement Dist. No. 1") are a common, genuine part of a Bluebook party
# name -- but a bare digit token ("97", "1") does not itself pass
# `_party_token_ok` (it is neither capitalized nor a connector word), so the
# backward/forward party-name scans previously stopped dead the instant they
# reached the number, discarding the whole party name (false-refusal: `case
# name=None` for a byte-identical, correctly-cited real case). A digit token
# is accepted ONLY when the token immediately preceding it (in document
# order) is a "No."/"Nos." designation word -- this can never bleed ordinary
# prose across a sentence boundary, since a bare number preceded by anything
# else still stops the scan exactly as before.
_NUMBER_DESIGNATION_WORDS = frozenset({"no", "nos"})


def _is_number_designation_word(token: str) -> bool:
    bare = re.sub(r"[.,;:]", "", token).lower()
    return bare in _NUMBER_DESIGNATION_WORDS


def _is_bare_number_token(token: str) -> bool:
    stripped = token.rstrip(".,;:")
    return bool(stripped) and stripped.isdigit()


def _party_tokens_ok_seq(tokens: list, indices: list) -> bool:
    """True if every token at `indices` (a list of indices into `tokens`,
    in ascending/document order) can legitimately extend a party name --
    like `_party_token_ok`, but additionally accepts a purely-numeric token
    when the immediately preceding token IN THIS SEQUENCE is a "No."/"Nos."
    designation word (see module comment above)."""
    prev_token = None
    for j in indices:
        t = tokens[j][0]
        if (
            _is_bare_number_token(t)
            and prev_token is not None
            and _is_number_designation_word(prev_token)
        ):
            prev_token = t
            continue
        if not _party_token_ok(t):
            return False
        prev_token = t
    return True


# A closing quotation mark -- straight or curly double quote, or a straight
# or curly single quote/apostrophe closing a quoted span -- ending a token is
# a HARD BOUNDARY for the backward plaintiff scan (found in independent
# review). A quoted proposition stated immediately before the citation
# (`"<quoted proposition>." Katz v. United States, ...`) is common; when the
# quote's own final word happens to be capitalized (a real, ordinary
# occurrence -- e.g. "...successive Presidents."), that word looks exactly
# like a legitimate capitalized case-name continuation token to the plain
# `token[0].isupper()` check below, and the backward scan glued it onto the
# real plaintiff ("Presidents." Katz v. United States"). The verdict then
# flips to a false `not found` purely because of that final word's
# capitalization -- proven by a controlled pair (identical case+cite+quote,
# differing only in whether the quote's last word is upper- or lowercase).
# A token ending in a closing quote character can never legitimately be part
# of a party name (a case name is never itself typeset inside a quotation),
# so it is rejected unconditionally here, before the uppercase/abbreviation
# checks -- exactly like a genuine sentence-ending period already is.
_CLOSING_QUOTE_CHARS = '"”\'’'


def _ends_with_closing_quote(token: str) -> bool:
    return bool(token) and token[-1] in _CLOSING_QUOTE_CHARS


def _party_token_ok(token: str) -> bool:
    """True if `token` can legitimately extend a case-name party (plaintiff
    or defendant) currently being assembled.

    A token qualifies if it starts with an uppercase letter AND (it does not
    end in a period, OR it does end in a period but is a recognized
    abbreviation per `_is_abbrev_stem` -- otherwise a trailing period marks
    the END of the previous sentence, so the token belongs to the prior
    prose, not to this case name). A lowercase connector word (of, the, and,
    ...), a bare "&", or the relator continuation words "rel."/"dem." also
    qualify. Any other token (an arbitrary lowercase word, a
    bare separator, digits, ...) does not, and callers use that as the
    signal to STOP extending the party name in that direction -- this is
    what keeps the case-name scan from crossing a sentence boundary (E2) or
    absorbing a preceding, unrelated capitalized word from the prior
    sentence (a defect found in review, "...and Delaware. Brown v. Board
    of Education"), or a closing quotation mark (found in independent review).
    """
    if not token:
        return False
    if _ends_with_closing_quote(token):
        return False
    if token in CASE_NAME_EXTRA_TOKENS:
        return True
    if token[0].isupper():
        if token.endswith("."):
            return _is_abbrev_stem(token[:-1])
        return True
    return token.lower() in CASE_NAME_CONNECTOR_WORDS


# Standard Bluebook introductory signals that may precede a case name or a
# proposition clause. Ordered longest-alternative-first so e.g. "see also"
# is preferred over a bare "see" match. A signal token must never end up as
# part of a reported case name (defect 1/E1) NOR as part of a reported
# proposition (defects 3/4) -- it belongs to the citation's framing, not to
# either the party name or the claim being cited for.
#
# Every base signal may ALSO be followed by a compound ", e.g.," suffix
# (a defect found in review: "Cf., e.g.," left a residual "e.g.," glued to the
# proposition because only "See, e.g.," had a dedicated alternative). The
# suffix is expressed once, generically, and applies to every base signal
# uniformly -- "See, e.g.,", "Cf., e.g.,", "But see, e.g.,", "Compare,
# e.g.,", "Accord, e.g.,", "Contra, e.g.," all now parse the same way,
# rather than needing one hand-enumerated alternative per signal.
_SIGNAL_BASE_CORE = (
    r"(?:see\s+also|see\s+generally|but\s+see|but\s+cf\."
    r"|e\.g\.|see|cf\.|compare|accord|contra)"
)
_SIGNAL_CORE = rf"{_SIGNAL_BASE_CORE}(?:\s*,\s*e\.g\.)?"
# Case-name variant: only strips when case-name text follows (requires
# trailing whitespace + more content).
SIGNAL_RE = re.compile(rf"^{_SIGNAL_CORE}\s*,?\s+", re.IGNORECASE)
# Proposition-clause variant: strips even when nothing (or only whitespace)
# follows, so a clause that is JUST a bare signal ("But see") is recognized
# as signal-only rather than left dangling as a 1-2 word "proposition".
SIGNAL_ANY_RE = re.compile(rf"^{_SIGNAL_CORE}\s*,?\s*(.*)$", re.IGNORECASE | re.DOTALL)

# A clause that is nothing but an inter-citation CONNECTOR ("and", "with")
# plus separator punctuation (",", ";") is not a proposition of its own --
# it is what links two citations that share ONE sentence's proposition
# (a defect found in review: "The rule is old. Terry v. Ohio, 392 U.S. 1, and
# Katz v. United States, 389 U.S. 347." was giving Katz the literal text
# ", and" as its "proposition", which then coincidentally substring-matched
# inside Katz's opinion and fabricated a `verified` verdict). Matched as a
# FULL-STRING match only, so real prose that merely starts with "and" is
# never caught by this.
CONNECTOR_ONLY_RE = re.compile(r"^[,;]*\s*(?:and|with)?\s*[,;]*$", re.IGNORECASE)

QUOTE_RE = re.compile(r'["“]([^"“”]{3,600})["”]')

# a bare line break (\n, \r, or \r\n) is intra-sentence
# whitespace, not a proposition terminator -- PDF-extracted briefs routinely
# wrap a single sentence across lines, and treating every soft-wrap as a
# sentence break truncated the proposition to whatever fragment happened to
# follow the LAST line break before the citation (or produced an empty ""
# proposition entirely, a false "exists, unsupported"). Paragraph splitting
# (on a BLANK line, "\n\s*\n") already isolates true paragraph boundaries
# before this regex ever runs, so the only real sentence-break signal within
# a paragraph is terminal punctuation followed by whitespace (which already
# matches across a line break via \s) and the next capital letter/quote.
SENTENCE_BREAK_RE = re.compile(r"[.!?]\s+(?=[A-Z\"“])")

# Reporters that are single capitalized words like "U.S." legitimately end a
# regex token run right before a digit; we bound the case-name search window
# so we don't accidentally walk across an unrelated previous sentence.
CASE_NAME_WINDOW = 160
QUOTE_WINDOW = 400


@dataclass
class Citation:
    raw: str
    doc_start: int
    doc_end: int
    volume: int
    reporter: str
    page: int
    pinpoint: Optional[int]
    case_name: Optional[str]
    proposition: str
    proposition_is_quoted: bool
    proposition_doc_span: Optional[tuple] = None
    # True if an "X v. Y"-shaped case-name CONSTRUCT (a "v." token with an
    # immediately-adjacent, capitalized-looking party token on each side) is
    # present in the citation's immediate context, REGARDLESS of whether the
    # full backward/forward party-name scan below actually managed to
    # validate and return a `case_name` string. A name can be OFFERED
    # (that's what this flag records) without being PARSEABLE (e.g. an
    # abbreviation `_party_token_ok` does not recognize) -- and an offered-
    # but-unparsed name must never be treated the same as no name at all
    # (see verdict.py's fail-closed guard; cardinal-fix root cause).
    name_construct_present: bool = False


def _construct_adjacent_ok(token: str) -> bool:
    """True if `token` (the raw token immediately before or after a "v."
    anchor) LOOKS like it could start/end a party name -- capitalized, and
    not itself a closing-quote-terminated token (see `_ends_with_closing_quote`;
    a quote's own trailing word ending right at "v." is not a real party
    name, matching the same boundary the full scan already applies). This is
    deliberately a much LOOSER test than `_party_token_ok`/the full
    collection loop -- it only asks "was something name-shaped offered
    here?", not "does it fully validate as a Bluebook party name?"."""
    if not token:
        return False
    if _ends_with_closing_quote(token):
        return False
    return token[0].isupper()


# Non-"v." case-name constructs (false-refusal fix): a case is not always
# styled "X v. Y" -- disciplinary, probate, and quasi-in-rem matters are
# conventionally styled with one of these leading phrases followed by a
# single party name and nothing else ("In re Gantt", "In the Matter of
# Lakeisha Gantt", "Ex parte Rhodes", "Succession of Casanova", "Estate of
# Randall", "Application of Smith", "Petition of Doe"). Previously
# `_find_case_name` only ever anchored on a "v." token, so these forms were
# never recognized as a case name at all -- the phrase+party text was left
# in the surrounding prose, where it could bleed into (and corrupt, or
# entirely displace) the citation's proposition (see `_find_proposition`'s
# clause scan, which stops at `case_name_start`). Phrases are tried
# longest-first at each candidate position so "In the Matter of" is
# preferred over the shorter "Matter of" it contains.
NAME_PREFIX_PHRASES = (
    ("in", "the", "matter", "of"),
    ("in", "re"),
    ("matter", "of"),
    ("ex", "parte"),
    ("succession", "of"),
    ("estate", "of"),
    ("application", "of"),
    ("petition", "of"),
)


def _clean_construct_token(token: str) -> str:
    """`token` with any leading/trailing punctuation that isn't part of the
    word itself (commas, semicolons, colons, periods) stripped, lowercased --
    used only to compare a raw document token against a fixed phrase word
    ("in", "re", "matter", ...), never to build the reported case-name text
    (which always uses the ORIGINAL token spelling)."""
    return token.strip(".,;:").lower()


def _phrase_matches_at(tokens: list, idx: int, phrase: tuple) -> bool:
    """True if `phrase` (a tuple of lowercase words) occurs at `tokens[idx:]`
    AND the phrase's own first word is capitalized in the document -- real
    Bluebook case-name phrasing always capitalizes "In", "Ex", "Matter",
    "Estate", etc.; requiring it here is what keeps ordinary lowercase prose
    ("she works in real estate of the family business") from being
    misread as a case-name construct."""
    if idx + len(phrase) > len(tokens):
        return False
    if not tokens[idx][0][0].isupper():
        return False
    for offset, word in enumerate(phrase):
        if _clean_construct_token(tokens[idx + offset][0]) != word:
            return False
    return True


def _find_non_v_case_name(tokens: list, window_start: int) -> tuple:
    """Backward, non-"v." counterpart to the "v."-anchored scan in
    `_find_case_name`. Returns (case_name, doc-relative offset,
    construct_present_loose) exactly like `_find_case_name` does -- case_name
    is None when nothing fully validates, but `construct_present_loose` is
    True whenever one of the recognized phrases was seen immediately
    followed by at least one name-shaped token, even if the full party-name
    scan afterward fails (mirrors `_construct_adjacent_ok`'s looser test in
    the "v." path, so verdict.py's fail-closed guard still fires on an
    offered-but-unparseable non-"v." name).

    Two shapes are recognized:
      1. A leading phrase (`NAME_PREFIX_PHRASES`) immediately followed by one
         or more party-name tokens (each must pass `_party_token_ok`)
         running all the way to the end of the window (i.e., immediately
         adjacent to the citation, exactly like the "v." case name always
         is).
      2. The bare party "Anonymous" standing alone as the entire case name
         (no phrase, no further tokens) -- must be the token immediately
         before the citation.
    """
    n = len(tokens)
    if n == 0:
        return None, None, False

    construct_present = False

    last_tok = tokens[-1][0]
    if (
        _clean_construct_token(last_tok) == "anonymous"
        and last_tok[0].isupper()
        and not _ends_with_closing_quote(last_tok)
    ):
        construct_present = True
        case_name = last_tok.rstrip(".,;:")
        return case_name, window_start + tokens[-1][1], construct_present

    phrases_by_length = sorted(NAME_PREFIX_PHRASES, key=len, reverse=True)
    for idx in range(n):
        for phrase in phrases_by_length:
            if not _phrase_matches_at(tokens, idx, phrase):
                continue
            party_idx = list(range(idx + len(phrase), n))
            if not party_idx:
                continue
            first_party_tok = tokens[party_idx[0]][0]
            if not construct_present and _construct_adjacent_ok(first_party_tok):
                construct_present = True
            if not _party_tokens_ok_seq(tokens, party_idx):
                continue
            if not first_party_tok[0].isupper():
                continue
            full_idx = list(range(idx, n))
            case_name = " ".join(tokens[j][0] for j in full_idx)
            return case_name, window_start + tokens[idx][1], True

    return None, None, construct_present


def _find_case_name(paragraph: str, citation_start: int) -> tuple:
    """Returns (case_name, doc-relative-to-paragraph start offset of the
    case name text, name_construct_present) -- case_name/offset are None if
    no case name could be fully parsed/validated. `name_construct_present`
    is independently True whenever an "X v. Y"-shaped construct was seen
    immediately around a "v." token, even when case_name itself is None
    (see `_construct_adjacent_ok`).

    Redesign (a defect class found in review, all six repros): anchor on the
    literal token "v." immediately preceding the citation, then grow the
    defendant FORWARD (to the citation) and the plaintiff BACKWARD (away
    from the citation) one whitespace-delimited token at a time, accepting
    only tokens `_party_token_ok` allows. Growing the plaintiff backward
    naturally stops at a sentence boundary (a trailing period on a non-
    abbreviation word, or an ordinary lowercase word) instead of a fixed
    character window, which is what makes "St. Louis v. Praprotnik" and
    "New York Times Co. v. Sullivan" still parse correctly while "...and
    Delaware. Brown v. Board of Education" no longer absorbs "Delaware."
    into the case name.

    A leading Bluebook introductory signal ("See", "Cf.", "Accord", ...) is
    stripped from the front of the plaintiff so it never becomes part of the
    reported case name -- the returned start offset points past the signal
    too, so callers that use it as a proposition-clause boundary correctly
    treat the signal word as belonging to the citation, not the prose.

    False-refusal fix: not every case name is "X v. Y" -- when no "v."-
    anchored name validates (including when there is no "v." token in the
    window at all), `_find_non_v_case_name` is tried next for the
    non-adversarial forms ("In re Foo", "In the Matter of Foo", "Matter of
    Foo", "Ex parte Foo", "Succession of Foo", "Estate of Foo", "Application
    of Foo", "Petition of Foo", bare "Anonymous"). A leading signal word is
    handled identically there: since the phrase scan only ever matches
    starting at the phrase's own first token, a signal word preceding it is
    simply never included in the returned case name or its start offset,
    exactly like the "v." path.
    """
    window_start = max(0, citation_start - CASE_NAME_WINDOW)
    window = paragraph[window_start:citation_start].rstrip()
    # Trim a trailing comma so "..., 347 U.S. 483" lines up.
    if window.endswith(","):
        window = window[:-1]
    if not window:
        return None, None, False

    tokens = [(m.group(0), m.start()) for m in re.finditer(r"\S+", window)]
    if not tokens:
        return None, None, False

    v_indices = [i for i, (t, _) in enumerate(tokens) if t == "v."]

    # Computed independently of whether the full scan below succeeds: True
    # iff ANY "v." token in this window has an immediately-adjacent,
    # name-shaped token on both sides. This is what lets the caller tell
    # "no name was ever offered here" (a genuinely bare citation) apart from
    # "a name was offered but this parser couldn't validate/collect it"
    # (e.g. an unrecognized abbreviation like "Cnty.") -- the latter must
    # fail closed downstream, never resolve by citation alone.
    name_construct_present = any(
        v_idx - 1 >= 0
        and v_idx + 1 < len(tokens)
        and _construct_adjacent_ok(tokens[v_idx - 1][0])
        and _construct_adjacent_ok(tokens[v_idx + 1][0])
        for v_idx in v_indices
    )

    for v_idx in reversed(v_indices):
        if v_idx + 1 >= len(tokens):
            continue

        defendant_idx = list(range(v_idx + 1, len(tokens)))
        if not _party_tokens_ok_seq(tokens, defendant_idx):
            continue
        if not tokens[defendant_idx[0]][0][0].isupper():
            continue

        collected = []
        i = v_idx - 1
        while i >= 0 and len(collected) < MAX_PLAINTIFF_TOKENS:
            t = tokens[i][0]
            if collected and _is_party_suffix_token(t):
                # a party-suffix token ("Corp.", "Inc.", "Co.",
                # "Ltd.", "L.L.C."/"LLC", "L.L.P."/"LLP", "Ass'n", "N.A.")
                # is, by Bluebook convention, the LAST word of a party name.
                # Reaching one here -- AFTER already collecting at least one
                # token closer to "v." -- means this suffix belongs to a
                # DIFFERENT, earlier party name in the PREVIOUS sentence
                # ("...negotiated with Acme Corp. Katz v. United States"),
                # not to this citation's plaintiff. Stop without absorbing
                # it or anything further back. A suffix reached as the
                # very FIRST backward token (collected still empty, i.e. it
                # sits immediately before "v.") is exactly the legitimate
                # case -- "New York Times Co. v. Sullivan", "Erie R. Co. v.
                # Tompkins", "Chevron U.S.A. Inc. v. NRDC" -- and is handled
                # by the normal _party_token_ok path below.
                break
            if (
                _is_bare_number_token(t)
                and i - 1 >= 0
                and _is_number_designation_word(tokens[i - 1][0])
            ):
                # Numbered-district designation ("... District No. 97"):
                # the bare digit is only reached backward here because the
                # token immediately before it (further back, "No."/"Nos.")
                # is a designation word -- accept the digit and let the
                # normal loop pick up "No."/"Nos." itself on the very next
                # iteration (it already passes `_party_token_ok` via the
                # short-abbreviation-stem rule).
                collected.append(i)
                i -= 1
                continue
            if not _party_token_ok(t):
                break
            collected.append(i)
            i -= 1
        if not collected:
            continue
        collected.reverse()
        # A case name cannot open on a lowercase connector ("of", "the",
        # ...); trim any until the true first word is reached.
        while collected and not tokens[collected[0]][0][0].isupper():
            collected.pop(0)
        if not collected:
            continue

        plaintiff_raw = " ".join(tokens[j][0] for j in collected)
        defendant = " ".join(tokens[j][0] for j in defendant_idx)

        sig_m = SIGNAL_RE.match(plaintiff_raw)
        plaintiff = plaintiff_raw[sig_m.end():].strip() if sig_m else plaintiff_raw
        if not plaintiff or not plaintiff[0].isupper():
            continue

        # How many leading tokens did the signal consume? (Multi-word
        # signals like "See also" never reach `collected` in the first
        # place -- the scan above already stops on their lowercase second
        # word -- so this only ever trims a single leading signal token.)
        raw_word_count = plaintiff_raw.count(" ") + 1
        stripped_word_count = plaintiff.count(" ") + 1
        consumed = max(0, raw_word_count - stripped_word_count)
        real_first_idx = collected[consumed] if consumed < len(collected) else collected[0]

        case_name = f"{plaintiff} v. {defendant}"
        case_name_start = window_start + tokens[real_first_idx][1]
        return case_name, case_name_start, name_construct_present

    # No "v."-anchored name validated (or no "v." token was present at all).
    # Try the non-"v." constructs ("In re Foo", "Ex parte Foo", "Succession
    # of Foo", "Estate of Foo", "Application of Foo", "Petition of Foo",
    # bare "Anonymous") before giving up -- see `_find_non_v_case_name`.
    non_v_name, non_v_start, non_v_construct_present = _find_non_v_case_name(
        tokens, window_start
    )
    if non_v_name is not None:
        return non_v_name, non_v_start, True
    return None, None, name_construct_present or non_v_construct_present


def _has_alnum(text: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9]", text))


# A parenthetical decision year, e.g. "(1967)", immediately preceding or
# following a citation is CITATION APPARATUS, not prose -- it belongs to the
# reporter/date parenthetical, never to a proposition. Matched narrowly (four
# digits only) so it never eats a genuine parenthetical that happens to
# contain other numbers.
DECISION_YEAR_RE = re.compile(r"\(\d{4}\)")


def _strip_apparatus(text: str) -> str:
    """Remove citation apparatus (a parenthetical decision year like
    '(1967)') from `text` for the sole purpose of judging whether the clause
    is a genuine, checkable proposition (see `_is_propositional`). The
    proposition TEXT actually returned/reported is never rewritten by this
    function -- only used to decide degeneracy -- so a real proposition that
    happens to also contain a parenthetical year is never silently altered.
    """
    return DECISION_YEAR_RE.sub(" ", text)


# A proposition clause shorter than this many letters/digits (after
# stripping any leading signal and surrounding punctuation) is not a real,
# checkable proposition -- see defects 3/4/5.
MIN_PROPOSITION_CHARS = 2

# A genuine proposition must contain at least this many alphabetic CONTENT
# words once citation apparatus (parenthetical decision years) is stripped.
# A clause like "(1967);" has alnum characters (digits) and would pass the
# old `_has_alnum` guard, but it is a citation connector, not a checkable
# claim -- treating it as one lets it coincidentally substring-match the
# NEXT citation's opinion text and fabricate a `verified` verdict on a
# citation connector (a defect found in review).
MIN_PROPOSITION_ALPHA_WORDS = 3


def _looks_like_bare_name(text: str) -> bool:
    """True iff `text` is indistinguishable from a bare case-name span -- a
    party name (or run of party names) with no accompanying "v." -- rather
    than a genuine proposition. This is the backstop for a SHORT-FORM
    citation whose party name defeats `_find_case_name`'s "v."-anchored
    scan (no "v." token present at all, e.g. a corporate short form like
    "Steve Jackson Games, 816 F. Supp. 432." or "Carroll Towing Co., 159
    F.2d 169.") -- the party name then falls through as ordinary preceding
    prose to the backward clause/quote scan, and since it consists of
    multiple capitalized words it can clear the bare word-count check in
    `_is_propositional` on its own (found in review: the tool matched the
    case's own name against its own caption text).

    A trailing separator (the comma that conventionally precedes the
    citation itself, or a stray semicolon/colon) is stripped first. What
    remains is a bare name iff EVERY whitespace-delimited token in it is a
    token that could legitimately extend a case-name party per
    `_party_token_ok` (uppercase-led, a recognized Bluebook abbreviation, or
    a small connector-word whitelist). An ordinary English sentence -- even
    a short one -- almost always contains at least one lowercase,
    non-connector word (an article, verb, or preposition outside that small
    whitelist), which immediately disqualifies it here and lets it through
    as a genuine proposition; a run of proper-noun tokens with nothing else
    does not.
    """
    stripped = text.strip().rstrip(",;:")
    if not stripped:
        return False
    tokens = stripped.split()
    if not tokens:
        return False
    return all(_party_token_ok(t) for t in tokens)


def _is_propositional(text: str) -> bool:
    """True iff `text` -- after stripping citation apparatus -- contains at
    least `MIN_PROPOSITION_ALPHA_WORDS` alphabetic content words AND is not
    itself indistinguishable from a bare case name (`_looks_like_bare_name`).
    Anything failing the word-count check (a bare '(1967);', a bare ';'/',
    and'/', with', pure punctuation or digits) is apparatus/connector
    tissue, not a proposition; anything that IS a bare case name/party-name
    span is citation apparatus of a different kind (the authority's own
    caption, not a claim about it). Either way, callers must fall back (to
    an earlier sentence, or to inheriting the previous citation's real
    proposition) rather than accept it as-is.

    This is the SINGLE degeneracy gate: every proposition source (quoted,
    paraphrase/sentence, trailing-parenthetical, inherited/string-cite) must
    route its candidate text through this function before it can become a
    `verified` proposition -- see `_find_proposition`'s quoted-string branch
    and `_find_trailing_parenthetical`, both of which call this same
    function rather than duplicating (and potentially drifting from) the
    degeneracy rule.
    """
    cleaned = _strip_apparatus(text)
    if len(re.findall(r"[A-Za-z]+", cleaned)) < MIN_PROPOSITION_ALPHA_WORDS:
        return False
    return not _looks_like_bare_name(cleaned)


# a case found in independent review: a proposition stated in the
# canonical TRAILING explanatory parenthetical -- `Katz v. United States,
# 389 U.S. 347 (holding "<real quoted proposition>")` -- is one of the most
# common real-brief citation forms, but `_find_proposition` above only ever
# looks BACKWARD from the citation for a proposition, so it was never
# associated at all and the citation fell through to a false `exists,
# unsupported`. Only a small, explicit whitelist of standard Bluebook
# parenthetical-introducing verbs counts as "explanatory" -- a parenthetical
# that doesn't start with one of these (`(per curiam)`, `(en banc)`,
# `(5-4)`, a bare court/date parenthetical) is never treated as a
# proposition source, so the degenerate-proposition guard is never loosened.
PAREN_LEAD_RE = re.compile(
    r"^(?:holding|finding|noting|stating|explaining|concluding|reasoning"
    r"|recognizing|observing|emphasizing|declaring|determining)\b"
    r"(?:\s+that)?\s*",
    re.IGNORECASE,
)


def _match_balanced_paren(text: str, open_idx: int) -> Optional[tuple]:
    """`text[open_idx]` must be '('. Returns (start, end) such that
    `text[start:end]` is the full, balanced `(...)` group (end exclusive),
    or None if unbalanced (falls off the end of `text`)."""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return (open_idx, i + 1)
    return None


def _find_trailing_parenthetical(paragraph: str, pos: int) -> Optional[tuple]:
    """`pos` is the index in `paragraph` immediately after a citation's raw
    match (and its pinpoint, if any). Returns (text, is_quoted, (start,
    end)) for a genuine explanatory parenthetical (`(holding "...")`,
    `(finding ...)`, `(noting ...)`, ...) immediately following the
    citation -- skipping over at most one intervening bare citation-apparatus
    parenthetical (a decision year `(1967)`, or a court+date form like
    `(9th Cir. 1967)`, neither of which is itself propositional) -- or None
    if no such parenthetical is present.

    The quoted span inside the parenthetical is preferred verbatim when
    present (matching the higher-confidence backward-quote path); otherwise
    the parenthetical's own text after the introductory gerund is used as a
    paraphrase, subject to the same `_is_propositional` degeneracy guard
    used everywhere else -- a non-propositional parenthetical (`(per
    curiam)`, `(en banc)`, `(5-4)`) never yields a proposition, quoted or
    not, so it can never produce a coincidental `verified`.
    """
    idx = pos
    lead_m = re.match(r"[\s,]*", paragraph[idx:])
    idx += lead_m.end()

    for _ in range(2):  # at most: one apparatus parenthetical, then the explanatory one
        if idx >= len(paragraph) or paragraph[idx] != "(":
            return None
        span = _match_balanced_paren(paragraph, idx)
        if span is None:
            return None
        pstart, pend = span
        inner = paragraph[pstart + 1 : pend - 1].strip()

        gerund_m = PAREN_LEAD_RE.match(inner)
        if gerund_m is not None:
            remainder = inner[gerund_m.end():].strip()
            quote_m = QUOTE_RE.search(remainder)
            if quote_m is not None:
                quoted_text = quote_m.group(1)
                if _is_propositional(quoted_text):
                    return (quoted_text, True, (pstart, pend))
                return None
            if _is_propositional(remainder):
                return (remainder, False, (pstart, pend))
            return None

        if _is_propositional(inner):
            # Some other, non-explanatory-lead parenthetical with real
            # content (e.g. a case's own parenthetical about a DIFFERENT
            # authority in a string cite) -- not this citation's own
            # explanatory clause, so stop rather than guess.
            return None

        # A short, non-propositional parenthetical immediately after the
        # citation (a bare decision year, court+date, "(per curiam)", "(en
        # banc)", "(5-4)", ...) is citation apparatus, not this citation's
        # explanatory clause -- skip over it and look for one more
        # parenthetical immediately following.
        idx = pend
        gap_m = re.match(r"[\s,]*", paragraph[idx:])
        idx += gap_m.end()

    return None


def _find_proposition(
    paragraph: str,
    citation_start: int,
    prev_citation_end: int,
    quotes: list,
    case_name_start: Optional[int],
) -> tuple:
    """Returns (proposition_text, is_quoted, (start, end) span in paragraph,
    inherit_from_prev: bool).

    ASSOCIATION MODEL (redesign): a citation supports the
    SENTENCE IT TERMINATES. The "clause" between the previous citation and
    this one's apparatus (signal + case name, or the bare citation start) is
    split into sentences. The LAST of those sentences is the current
    sentence's leading prose; after stripping a leading Bluebook signal from
    it, that is the proposition. If nothing checkable remains -- because the
    clause was only a signal ("See", "But cf.") introducing this citation,
    or only an inter-citation CONNECTOR/separator (";", ", and", ", with")
    linking this citation to a sibling in the same string cite -- two
    different fallbacks apply:

      * Bare signal, no prose of its own (E1): fall back to the sentence
        BEFORE it. A signal introduces a citation for an already-stated
        claim; it does not blank that claim out. "<claim>. See Case, 1
        U.S. 1." must associate <claim> with Case, not "".
      * Bare connector/separator, no signal (defect 5 / E2): this citation
        is a second-or-later authority in the SAME sentence as the previous
        citation (a string cite, "X, and Y", "Compare X, with Y") and
        shares that sentence's proposition -- `inherit_from_prev=True`
        tells the caller to copy the previous citation's already-resolved
        proposition, rather than fabricating one from ", and" / "; " / a
        bare "with" (which can coincidentally substring-match the next
        opinion's text and produce a fabricated `verified`).

    Both fallbacks are tried sentence-by-sentence, walking backward through
    the clause, so a chain of degenerate sentences (rare) still resolves to
    the nearest real prose, and a document that opens directly on a bare
    signal-cite with nothing before it at all correctly ends up with a
    genuinely empty (never inherited, never fabricated) proposition.
    """
    best_quote = None
    for (qs, qe, inner) in quotes:
        if qe <= citation_start and (citation_start - qe) <= QUOTE_WINDOW and qs >= prev_citation_end:
            if best_quote is None or qs > best_quote[0]:
                best_quote = (qs, qe, inner)
    if best_quote is not None:
        qs, qe, inner = best_quote
        # Uniform-guard fix (found in independent review): a
        # QUOTED string is not exempt from the same degeneracy check every
        # other proposition source is subject to. Without this, an
        # explicitly-quoted signal/connector/single-word fragment ("and",
        # "the", "the barge") -- or a quoted case name -- clears straight
        # through to `verified` on a coincidental substring match, and (via
        # `inherit_prev` below) can propagate that fabricated proposition to
        # a SIBLING citation later in the same string cite as well. A quote
        # that fails the guard is treated exactly like "no quote found here"
        # -- fall through to the backward clause/paraphrase scan below,
        # rather than accepting it verbatim.
        if _is_propositional(inner):
            return (inner, True, (qs, qe), False)

    clause_end = case_name_start if case_name_start is not None else citation_start
    clause_base = prev_citation_end
    clause_full = paragraph[clause_base:clause_end]

    # Sentence spans within clause_full, in ascending order. The FINAL span
    # always ends exactly at clause_end (the true boundary of this
    # citation's own sentence -- signal text, if any, trails inside it and
    # is stripped below); only its start needs locating, via the last
    # internal sentence break, if any.
    break_ends = [m.end() for m in SENTENCE_BREAK_RE.finditer(clause_full)]
    sentence_starts = [0] + break_ends
    spans = []
    for i, s in enumerate(sentence_starts):
        e = sentence_starts[i + 1] if i + 1 < len(sentence_starts) else len(clause_full)
        spans.append((s, e))
    last_idx = len(spans) - 1

    for idx in range(last_idx, -1, -1):
        s, e = spans[idx]
        text = clause_full[s:e]
        stripped = text.strip()
        is_last = idx == last_idx

        if is_last:
            sig_m = SIGNAL_ANY_RE.match(stripped)
            if sig_m is not None:
                remainder = sig_m.group(1).strip()
                if not remainder:
                    # Bare signal, no prose in its own clause -- fall back
                    # to the sentence BEFORE it (E1).
                    continue
                stripped = remainder
            elif not _is_propositional(stripped):
                # No signal, and nothing propositional between the previous
                # citation and this one -- either a bare separator/connector
                # (defect 5 / E2) or citation apparatus like a trailing
                # "(1967);" (E1, review): share the previous
                # citation's proposition rather than fabricate one from it.
                return ("", False, None, True)

        if not _is_propositional(stripped):
            # Degenerate earlier "sentence" (or a signal-remainder that
            # itself turned out degenerate) -- keep walking backward.
            continue

        # Locate `stripped` inside `text` to recover accurate offsets -- it
        # is always a substring of `text` (derived only by trimming and/or
        # signal-stripping a prefix off the front).
        idx_in_text = text.find(stripped)
        if idx_in_text == -1:
            idx_in_text = len(text) - len(text.lstrip())
        start = clause_base + s + idx_in_text
        end = start + len(stripped)
        return (stripped, False, (start, end), False)

    # Nothing propositional anywhere in the clause (e.g. the document opens
    # directly on a bare signal-cite with no preceding sentence at all) --
    # genuinely empty: not inherited, not fabricated.
    return ("", False, None, False)


def _find_quotes(paragraph: str) -> list:
    out = []
    for m in QUOTE_RE.finditer(paragraph):
        out.append((m.start(), m.end(), m.group(1)))
    return out


# A bare single-letter-and-period token ("U.", "F."), and a bare
# digit-plus-ordinal-suffix token ("2d", "3d", "4th") with no period. Used
# only to decide which ADJACENT reporter tokens are the SAME abbreviation
# split by a stray internal space, never a real multi-word reporter.
_SINGLE_LETTER_TOKEN_RE = re.compile(r"^[A-Za-z]\.$")
_DIGIT_SUFFIX_TOKEN_RE = re.compile(r"^\d(?:st|nd|rd|th|d)$", re.IGNORECASE)


def _canonicalize_reporter(reporter: str) -> str:
    """Canonicalize a reporter token so a spaced Bluebook/print rendering
    ('U. S.', 'F. 2d' -- the way U.S. Reports and some print sources
    themselves space the abbreviation) resolves identically to its standard
    unspaced form ('U.S.', 'F.2d'). Only collapses the space directly after
    a BARE single-letter-and-period token when the next token is itself
    another single-letter-and-period token or a digit-ordinal suffix -- a
    genuine multi-letter reporter word ('Ct.', 'Rptr.', 'App.') is never
    merged, so a real two-word reporter like 'S. Ct.' or 'Cal. Rptr. 3d'
    is left exactly as spaced (see `test_uncovered_reporter_is_still_extracted`
    and similar, which depend on 'S. Ct.' staying spaced).
    """
    tokens = reporter.split()
    if len(tokens) <= 1:
        return reporter
    out = [tokens[0]]
    for tok in tokens[1:]:
        prev = out[-1]
        if _SINGLE_LETTER_TOKEN_RE.match(prev) and (
            _SINGLE_LETTER_TOKEN_RE.match(tok) or _DIGIT_SUFFIX_TOKEN_RE.match(tok)
        ):
            out[-1] = prev + tok
        else:
            out.append(tok)
    return " ".join(out)


def extract_citations(document: str) -> list:
    """Parses `document` and returns a list of Citation, in document order."""
    citations: list[Citation] = []
    paragraphs = re.split(r"\n\s*\n", document)
    offset = 0
    for paragraph in paragraphs:
        para_start_in_doc = document.index(paragraph, offset)
        offset = para_start_in_doc + len(paragraph)

        quotes = _find_quotes(paragraph)
        prev_end = 0
        prev_citation: Optional[Citation] = None
        for m in CITATION_RE.finditer(paragraph):
            volume = int(m.group("volume"))
            reporter = _canonicalize_reporter(m.group("reporter"))
            page = int(m.group("page"))
            pinpoint = m.group("pinpoint")
            pinpoint = int(pinpoint) if pinpoint else None

            case_name, case_name_start, name_construct_present = _find_case_name(
                paragraph, m.start()
            )

            prop_text, prop_quoted, prop_span, inherit_prev = _find_proposition(
                paragraph, m.start(), prev_end, quotes, case_name_start
            )

            # this case (independent review): a trailing explanatory parenthetical
            # immediately following the citation is a MORE SPECIFIC claim for
            # THIS citation than a backward-derived paraphrase sentence (or a
            # bare string-cite connector), so it takes precedence over both.
            # It is checked only when the backward search did NOT already
            # find an actual quote preceding the citation -- that is the
            # highest-confidence form (the author quoted the exact words
            # right before citing them) and is left untouched.
            if not prop_quoted:
                trailing = _find_trailing_parenthetical(paragraph, m.end())
                if trailing is not None:
                    prop_text, prop_quoted, prop_span = trailing
                    inherit_prev = False

            if inherit_prev and prev_citation is not None:
                # String-cite continuation (defect 5): re-use the nearest
                # actual proposition rather than a bare separator token.
                prop_text = prev_citation.proposition
                prop_quoted = prev_citation.proposition_is_quoted
                doc_span = prev_citation.proposition_doc_span
            else:
                doc_span = None
                if prop_span is not None:
                    doc_span = (
                        para_start_in_doc + prop_span[0],
                        para_start_in_doc + prop_span[1],
                    )

            citation = Citation(
                    raw=" ".join(m.group(0).split()),
                    doc_start=para_start_in_doc + m.start(),
                    doc_end=para_start_in_doc + m.end(),
                    volume=volume,
                    reporter=reporter,
                    page=page,
                    pinpoint=pinpoint,
                    case_name=case_name,
                    proposition=prop_text,
                    proposition_is_quoted=prop_quoted,
                    proposition_doc_span=doc_span,
                    name_construct_present=name_construct_present,
            )
            citations.append(citation)
            prev_end = m.end()
            prev_citation = citation

    return citations
