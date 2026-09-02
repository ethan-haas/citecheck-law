"""Combines extraction + corpus resolution + support-checking + name
corroboration into the final four-way verdict per citation.

Verdict semantics (see the specification and the task brief for the authoritative
text):
  verified          - resolves to an ingested opinion (name corroborated
                       when given) AND the proposition is a literal
                       substring of its text under support.normalize().
  exists, unsupported - resolves to an ingested opinion but the proposition
                       is not found in it.
  not found         - the (reporter, volume) is a complete, covered volume
                       but no case begins at the cited page -- OR a case
                       name is given that does not match the real case that
                       DOES begin at that page (never phrased as "does not
                       exist").
  cannot verify     - refusal state. Either the reporter/volume is not
                       covered by this corpus at all, or the case exists in
                       a complete volume but its text was never ingested.
                       The `reason` field always distinguishes which.

A `wrong_pinpoint` flag (not a separate verdict) is set when a pinpoint page
is given and falls outside [first_page, last_page] of the resolved opinion.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from . import support
from .corpus import Corpus, INGESTED, COVERED_NOT_INGESTED, NOT_FOUND, NOT_COVERED
from .resolve import name_matches

VERIFIED = "verified"
EXISTS_UNSUPPORTED = "exists, unsupported"
NOT_FOUND_VERDICT = "not found"
CANNOT_VERIFY = "cannot verify"


@dataclass
class Verdict:
    raw_citation: str
    volume: int
    reporter: str
    page: int
    pinpoint: Optional[int]
    case_name: Optional[str]
    proposition: str
    proposition_is_quoted: bool
    verdict: str
    reason: str
    wrong_pinpoint: bool = False
    name_mismatch: bool = False
    opinion_id: Optional[str] = None
    opinion_name: Optional[str] = None
    span: Optional[list] = None
    quoted_sentence: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _pinpoint_ok(pinpoint: Optional[int], first_page: int, last_page: int) -> bool:
    if pinpoint is None:
        return True
    return first_page <= pinpoint <= last_page


def judge_citation(corpus: Corpus, citation) -> Verdict:
    res = corpus.resolve(
        citation.reporter, citation.volume, citation.page, citation.case_name
    )

    if res.status == NOT_COVERED:
        return Verdict(
            raw_citation=citation.raw,
            volume=citation.volume,
            reporter=citation.reporter,
            page=citation.page,
            pinpoint=citation.pinpoint,
            case_name=citation.case_name,
            proposition=citation.proposition,
            proposition_is_quoted=citation.proposition_is_quoted,
            verdict=CANNOT_VERIFY,
            reason=res.reason,
        )

    if res.status == NOT_FOUND:
        return Verdict(
            raw_citation=citation.raw,
            volume=citation.volume,
            reporter=citation.reporter,
            page=citation.page,
            pinpoint=citation.pinpoint,
            case_name=citation.case_name,
            proposition=citation.proposition,
            proposition_is_quoted=citation.proposition_is_quoted,
            verdict=NOT_FOUND_VERDICT,
            reason=res.reason,
            name_mismatch=res.name_mismatch,
        )

    if res.status == COVERED_NOT_INGESTED:
        return Verdict(
            raw_citation=citation.raw,
            volume=citation.volume,
            reporter=citation.reporter,
            page=citation.page,
            pinpoint=citation.pinpoint,
            case_name=citation.case_name,
            proposition=citation.proposition,
            proposition_is_quoted=citation.proposition_is_quoted,
            verdict=CANNOT_VERIFY,
            reason=res.reason,
        )

    # INGESTED
    op = res.opinion
    name_mismatch = False
    if citation.case_name:
        if not name_matches(citation.case_name, op["name"], op["name_abbreviation"]):
            name_mismatch = True
            return Verdict(
                raw_citation=citation.raw,
                volume=citation.volume,
                reporter=citation.reporter,
                page=citation.page,
                pinpoint=citation.pinpoint,
                case_name=citation.case_name,
                proposition=citation.proposition,
                proposition_is_quoted=citation.proposition_is_quoted,
                verdict=NOT_FOUND_VERDICT,
                reason=(
                    f"no case named '{citation.case_name}' exists at "
                    f"{citation.reporter} {citation.volume} {citation.page}; "
                    f"the case actually reported there in this corpus is "
                    f"'{op['name_abbreviation']}'"
                ),
                name_mismatch=True,
            )
    elif getattr(citation, "name_construct_present", False):
        # CARDINAL FIX (fail-closed guard): a case name is PRESENT in the
        # citation's immediate context (an "X v. Y"-shaped construct was
        # seen) but this tool's name parser could not turn it into a
        # corroborated `case_name` -- e.g. an unrecognized Bluebook
        # abbreviation ("Cnty.", or any other token `_party_token_ok`
        # doesn't know). Previously this silently fell through to resolving
        # by CITATION ALONE, which is exactly how a fabricated party name
        # attached to a real citation number got blessed `verified` (the
        # false-verified cardinal defect this fix addresses). The guard
        # keys on "was a name OFFERED?", never on "did we manage to PARSE
        # it?" -- an unparsed name is an UNVERIFIED name and must fail
        # closed to the same NOT_FOUND/name_mismatch outcome a parsed-but-
        # wrong name already gets, naming the real case at that cite
        # (never claiming it "does not exist").
        return Verdict(
            raw_citation=citation.raw,
            volume=citation.volume,
            reporter=citation.reporter,
            page=citation.page,
            pinpoint=citation.pinpoint,
            case_name=citation.case_name,
            proposition=citation.proposition,
            proposition_is_quoted=citation.proposition_is_quoted,
            verdict=NOT_FOUND_VERDICT,
            reason=(
                "a case name appears to be given immediately before this "
                "citation but this tool could not parse/corroborate it "
                f"(unrecognized abbreviation or form); no case name could "
                f"be verified against {citation.reporter} {citation.volume} "
                f"{citation.page}, so it is treated as unverified rather "
                f"than resolved by citation number alone; the case actually "
                f"reported there in this corpus is '{op['name_abbreviation']}'"
            ),
            name_mismatch=True,
        )

    wrong_pinpoint = not _pinpoint_ok(citation.pinpoint, op["first_page"], op["last_page"])

    if not citation.proposition.strip():
        # No checkable proposition was ever associated with this citation --
        # e.g. it is introduced by a bare Bluebook signal ("But see", "See",
        # "Cf.") with nothing else in its own clause. This is deliberately
        # EXISTS_UNSUPPORTED (never VERIFIED, since there is nothing to
        # verify) with a reason distinct from "not found as a literal
        # substring", so callers can tell "we checked and it wasn't there"
        # apart from "nothing was offered to check" (review defects: a
        # signal token or its coincidental appearance in the
        # opinion text must never itself count as support).
        reason = (
            "the citation resolves to an ingested opinion, but no checkable "
            "proposition was associated with it (only a citation signal or "
            "separator was found in its clause)"
        )
        return Verdict(
            raw_citation=citation.raw,
            volume=citation.volume,
            reporter=citation.reporter,
            page=citation.page,
            pinpoint=citation.pinpoint,
            case_name=citation.case_name,
            proposition=citation.proposition,
            proposition_is_quoted=citation.proposition_is_quoted,
            verdict=EXISTS_UNSUPPORTED,
            reason=reason,
            wrong_pinpoint=wrong_pinpoint,
            opinion_id=op["opinion_id"],
            opinion_name=op["name_abbreviation"],
        )

    span = support.find_support(citation.proposition, op["text"])
    if span is None:
        reason = (
            "the citation resolves to an ingested opinion but the cited "
            "proposition was not found as a literal substring of its text"
        )
        return Verdict(
            raw_citation=citation.raw,
            volume=citation.volume,
            reporter=citation.reporter,
            page=citation.page,
            pinpoint=citation.pinpoint,
            case_name=citation.case_name,
            proposition=citation.proposition,
            proposition_is_quoted=citation.proposition_is_quoted,
            verdict=EXISTS_UNSUPPORTED,
            reason=reason,
            wrong_pinpoint=wrong_pinpoint,
            opinion_id=op["opinion_id"],
            opinion_name=op["name_abbreviation"],
        )

    start, end = span
    quoted_sentence = op["text"][start:end]
    reason = "resolved to an ingested opinion and the proposition is a literal substring of its text"
    if wrong_pinpoint:
        reason += (
            f"; NOTE: pinpoint page {citation.pinpoint} is outside this "
            f"opinion's page range [{op['first_page']}, {op['last_page']}] "
            "(wrong_pinpoint)"
        )
    return Verdict(
        raw_citation=citation.raw,
        volume=citation.volume,
        reporter=citation.reporter,
        page=citation.page,
        pinpoint=citation.pinpoint,
        case_name=citation.case_name,
        proposition=citation.proposition,
        proposition_is_quoted=citation.proposition_is_quoted,
        verdict=VERIFIED,
        reason=reason,
        wrong_pinpoint=wrong_pinpoint,
        opinion_id=op["opinion_id"],
        opinion_name=op["name_abbreviation"],
        span=[start, end],
        quoted_sentence=quoted_sentence,
    )
