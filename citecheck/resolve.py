"""Case-name corroboration heuristic.

Used only when a citation carries a parsed case name AND the citation number
resolves to an ingested opinion. It decides whether the given name is
consistent with the resolved opinion's own name, so a fabricated name
attached to a real citation number is not silently accepted as that real
case.

This is intentionally a heuristic (courts, briefs, and casebooks abbreviate
party names in many different ways: "Bd." vs "Board", "Nat'l" vs
"National"), not a byte-exact match. It is documented in the README as a
heuristic, and it never lets the ENGINE claim a real, resolvable case
"does not exist" -- it only refuses to say a mismatched name is the exact
opinion at that citation, which downstream this is treated as a NOT_FOUND
("no case named X exists at this citation") rather than declaring the
correctly-named case at that spot fabricated.
"""
from __future__ import annotations

import re
from typing import Optional

# Standard Bluebook party-name abbreviations, expanded to their full word so
# that both a given name written in abbreviated form ("Brown v. Bd. of
# Educ.") and the corpus's fully-spelled-out official name ("Brown v. Board
# of Education") normalize to the SAME token stream before comparison
# (a defect found in review: "Bd." vs "Board" / "Educ." vs "Education" was
# previously rejected as a name_mismatch even though the citation was
# correctly located). Keys are the abbreviation with punctuation already
# stripped by normalize_name's `[^a-z0-9 ]` pass (so "Bd." -> "bd", "Ass'n"
# -> "assn", "Dep't" -> "dept").
_ABBREV_EXPANSIONS = {
    "bd": "board",
    "educ": "education",
    "co": "company",
    "corp": "corporation",
    "inc": "incorporated",
    "ltd": "limited",
    "assn": "association",
    "commn": "commission",
    "dept": "department",
    "natl": "national",
    "nat": "national",
    "intl": "international",
    "govt": "government",
    "ry": "railway",
    "rr": "railroad",
    "mfg": "manufacturing",
    "mut": "mutual",
    "sav": "savings",
    "ins": "insurance",
    "dist": "district",
    "admin": "administration",
    "auth": "authority",
    "hosp": "hospital",
    "indus": "industries",
    "inst": "institute",
    "mgmt": "management",
    "sch": "school",
    "univ": "university",
    # cardinal-fix secondary addition: county/township jurisdiction
    # abbreviations, so a given name written "Oakland Cnty." normalizes to
    # the same token stream as the corpus's fully-spelled-out official name
    # "Oakland County" (mirrors the "Bd."/"Board" pattern above).
    "cnty": "county",
    "twp": "township",
}
# Multi-word abbreviations survive punctuation-stripping as a SEQUENCE of
# single-letter/short tokens -- either because periods split them ("U.S."
# -> "u s") or because normalize_name's punctuation strip turns an internal
# apostrophe into a space too ("Ass'n" -> "ass n", "Dep't" -> "dep t").
# Matched as a bigram before the single-word table above is consulted.
_BIGRAM_ABBREV_EXPANSIONS = {
    ("u", "s"): "united states",
    ("ass", "n"): "association",
    ("comm", "n"): "commission",
    ("dep", "t"): "department",
    ("nat", "l"): "national",
    ("gov", "t"): "government",
    # "Comm'rs" -> apostrophe-strip yields the token pair ("comm", "rs").
    ("comm", "rs"): "commissioners",
}


def _expand_abbreviations(words: list) -> list:
    out = []
    i = 0
    while i < len(words):
        if i + 1 < len(words):
            pair = (words[i], words[i + 1])
            bigram_expansion = _BIGRAM_ABBREV_EXPANSIONS.get(pair)
            if bigram_expansion is not None:
                out.extend(bigram_expansion.split(" "))
                i += 2
                continue
        w = words[i]
        out.append(_ABBREV_EXPANSIONS.get(w, w))
        i += 1
    return out


def normalize_name(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\bet al\.?\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return s
    return " ".join(_expand_abbreviations(s.split(" ")))


def split_parties(name: str):
    parts = name.split(" v ")
    if len(parts) != 2:
        return None
    return parts[0].strip(), parts[1].strip()


# A numbered-district/party designation ("School District No. 97", "Sewer
# Improvement Dist. No. 1") is the IDENTITY of the party, not free variation
# like an abbreviation/spelling difference -- two districts that differ only
# in this number are different real parties. `_side_match` below only ever
# compares the FIRST word of each side (a deliberately loose heuristic so
# "Bush" matches "Bush, a Minor, ..."), so once extract.py's case-name parser
# learned to capture a trailing "No. <N>" as part of the party name (see
# extract.py's `_party_tokens_ok_seq`), a FABRICATED number ("No. 999" for
# the real "No. 97") would otherwise still pass `_side_match` purely because
# the district's first word ("Quinault") agrees -- silently promoting a
# fabricated case name at a real citation to `verified`. When a "no
# <digits>" designation is present on BOTH sides, the digits must agree
# exactly; when it is present on only one side (a given name that simply
# omits the number -- a common, legitimate short form, "Bush v. Quinault
# School District") the existing loose first-word heuristic is left
# untouched, exactly as it behaved before this designation was ever parsed
# out of the name at all.
_NO_DESIGNATION_RE = re.compile(r"\bnos? (\d+)\b")


def _side_match(a: str, b: str) -> bool:
    at = a.split()
    bt = b.split()
    if not at or not bt:
        return False
    a0, b0 = at[0], bt[0]
    if not (a0 == b0 or a0.startswith(b0) or b0.startswith(a0)):
        return False
    a_no = _NO_DESIGNATION_RE.search(a)
    b_no = _NO_DESIGNATION_RE.search(b)
    if a_no is not None and b_no is not None:
        return a_no.group(1) == b_no.group(1)
    return True


# Filler words that a Bluebook/press-style initialism ordinarily skips when
# it is built from a multi-word official party name (a review defect:
# "NRDC" for "Natural Resources Defense Council, Inc." only
# initials the four substantive words, not "Inc."). Reused for BOTH sides so
# an initialism given for either the plaintiff or defendant is tolerated the
# same way.
_ACRONYM_SKIP_WORDS = frozenset(
    "incorporated inc corporation corp company co limited ltd llc llp "
    "association assn commission commn department dept the of and".split()
)


def _acronym(words: list) -> str:
    return "".join(w[0] for w in words if w and w not in _ACRONYM_SKIP_WORDS)


def _is_upper_initialism(raw_token: str) -> bool:
    """True if `raw_token`, taken from the ORIGINAL (pre-normalize, case-
    preserved) case name text, is a short all-uppercase initialism like
    "NRDC" or "N.R.D.C." -- i.e. a real Bluebook-style abbreviation of a
    multi-word party name, not just an ordinary short surname. Gating the
    acronym tolerance below on this RAW-case signal (rather than trying to
    detect "initialism-ness" after normalize_name has already lowercased
    everything) is what keeps a genuinely wrong case name (e.g. an ordinary
    capitalized surname like "Jones") from being loosened into a match."""
    bare = raw_token.replace(".", "").strip()
    return 2 <= len(bare) <= 6 and bare.isalpha() and bare.isupper()


def _side_initialism_match(given_raw_token: Optional[str], given_norm: str, official_norm_words: list) -> bool:
    """True if `given_raw_token` is a real initialism (per
    `_is_upper_initialism`) of the official side's full word sequence, once
    corporate-suffix/connector filler words are excluded from the
    acronym."""
    if given_raw_token is None or not _is_upper_initialism(given_raw_token):
        return False
    acro = _acronym(official_norm_words)
    return bool(given_norm) and (acro == given_norm or acro.startswith(given_norm))


def name_matches(given_name: str, official_name: str, name_abbreviation: str) -> bool:
    """True if given_name is a plausible match for either the opinion's full
    caption name or its short (name_abbreviation) form."""
    g = normalize_name(given_name)

    # Recover the RAW (pre-normalize) plaintiff/defendant tokens, if
    # `given_name` has the standard "X v. Y" shape extract.py always
    # produces, so initialism-ness can be judged on the original spelling
    # (see `_is_upper_initialism`).
    raw_plaintiff_token = raw_defendant_token = None
    if " v. " in given_name:
        raw_plaintiff_raw, raw_defendant_raw = given_name.split(" v. ", 1)
        raw_plaintiff_tokens = raw_plaintiff_raw.split()
        raw_defendant_tokens = raw_defendant_raw.split()
        if len(raw_plaintiff_tokens) == 1:
            raw_plaintiff_token = raw_plaintiff_tokens[0]
        if len(raw_defendant_tokens) == 1:
            raw_defendant_token = raw_defendant_tokens[0]

    for official in (official_name, name_abbreviation):
        o = normalize_name(official)
        if not o:
            continue
        if g == o:
            return True
        gp = split_parties(g)
        op = split_parties(o)
        if gp and op:
            g1, g2 = gp
            o1, o2 = op
            plaintiff_ok = _side_match(g1, o1) or _side_initialism_match(
                raw_plaintiff_token, g1, o1.split()
            )
            defendant_ok = _side_match(g2, o2) or _side_initialism_match(
                raw_defendant_token, g2, o2.split()
            )
            if plaintiff_ok and defendant_ok:
                return True
        else:
            if g and (g in o or o in g):
                return True
    return False
