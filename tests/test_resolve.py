"""Case-name matching is tested independently of extraction/resolution
(mirrors the specification gate-3 independence discipline for extract.py): these
tests exercise citecheck.resolve.name_matches directly against hand-built
given/official name pairs, never against the real corpus.

independent review, defect 2 (HIGH): standard Bluebook party-name
abbreviations ('Bd.' for 'Board', 'Educ.' for 'Education', etc.) were
rejected as a name_mismatch even though they refer to the exact same real
case at the exact same citation. Root cause: normalize_name() only stripped
punctuation; it never expanded an abbreviation to the word it stands for, so
'bd' never equalled 'board' and the first-word prefix check in _side_match
had nothing to make them agree on (whereas 'U.S.' vs 'United States' had
happened to work already, by the accident of 'u'.startswith-being-a-prefix-
of 'united' -- see test_us_abbreviation_still_matches_united_states below,
now backed by a principled bigram expansion instead of that accident).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from citecheck.resolve import name_matches, normalize_name


def test_bd_expands_to_board():
    assert normalize_name("Bd.") == "board"


def test_educ_expands_to_education():
    assert normalize_name("Educ.") == "education"


def test_bluebook_abbreviated_defendant_matches_full_official_name():
    assert name_matches(
        "Brown v. Bd. of Educ.",
        "Brown v. Board of Education",
        "Brown v. Board of Education",
    )


def test_bluebook_abbreviated_defendant_matches_abbreviated_official_name():
    """Also holds when the OFFICIAL name itself carries the abbreviation
    (both sides normalize to the same expanded form)."""
    assert name_matches(
        "Brown v. Board of Education",
        "Brown v. Bd. of Educ.",
        "Brown v. Bd. of Educ.",
    )


def test_us_abbreviation_still_matches_united_states():
    assert name_matches(
        "Katz v. U.S.", "Katz v. United States", "Katz v. United States"
    )


def test_corp_co_assn_commn_dept_natl_abbreviations_expand():
    assert normalize_name("Corp.") == "corporation"
    assert normalize_name("Co.") == "company"
    assert normalize_name("Ass'n") == "association"
    assert normalize_name("Comm'n") == "commission"
    assert normalize_name("Dep't") == "department"
    assert normalize_name("Nat'l") == "national"


def test_wrong_case_at_a_page_still_does_not_match():
    """Guard against over-loosening: abbreviation expansion must not make an
    actually-wrong case name at a page silently verify."""
    assert not name_matches(
        "Smith v. Jones",
        "Brown v. Board of Education",
        "Brown v. Board of Education",
    )


# --- independent review, defect E3 (MED): a defendant initialism
# ("NRDC" for "Natural Resources Defense Council, Inc.") was rejected as a
# name_mismatch even though it names the exact real party at the exact real
# citation. Fixed by an acronym-tolerant side-match gated on the RAW
# (pre-normalize) given token actually being an all-uppercase initialism, so
# an ordinary wrong short surname is never loosened into a false match. ---

def test_defendant_initialism_matches_full_official_multiword_name():
    assert name_matches(
        "Chevron U.S.A. Inc. v. NRDC",
        "CHEVRON U. S. A. INC. v. NATURAL RESOURCES DEFENSE COUNCIL, INC., et al.",
        "Chevron U. S. A. Inc. v. Natural Resources Defense Council, Inc.",
    )


def test_defendant_initialism_matches_abbreviated_official_name():
    assert name_matches(
        "Chevron U.S.A. Inc. v. NRDC",
        "Chevron U.S.A. Inc. v. Natural Resources Defense Council, Inc.",
        "Chevron U.S.A. Inc. v. NRDC",
    )


def test_plaintiff_initialism_also_tolerated():
    assert name_matches(
        "NAACP v. Alabama",
        "National Association for the Advancement of Colored People v. Alabama",
        "NAACP v. Alabama",
    )


def test_acronym_gate_requires_raw_uppercase_not_just_a_short_word():
    """Guard against over-loosening: the acronym heuristic is gated on the
    given token being written in raw ALL CAPS (a real Bluebook-style
    initialism), not merely on being short. The identical short token
    written in ordinary mixed case must NOT be acronym-matched (it also
    fails the plain prefix `_side_match`, so it correctly does not verify
    either way -- this test demonstrates the gate matters by holding the
    official name fixed and varying only the given token's case)."""
    official_full = "Doe v. Board of Education"
    assert name_matches("Doe v. BE", official_full, official_full)
    assert not name_matches("Doe v. Be", official_full, official_full)


def test_wrong_initialism_at_a_real_citation_still_does_not_match():
    """A short all-caps token that is NOT a real acronym of the official
    name must still fail -- the acronym match requires the initials to
    actually line up, not just be short and uppercase."""
    assert not name_matches(
        "Chevron U.S.A. Inc. v. ABC",
        "Chevron U.S.A. Inc. v. Natural Resources Defense Council, Inc.",
        "Chevron U.S.A. Inc. v. Natural Resources Defense Council, Inc.",
    )


# --- Defect 1 fix (extract.py now parses a trailing "No. <digits>" party
# designation): a numbered designation is the IDENTITY of the party, not
# free variation like an abbreviation. `_side_match` only ever compares the
# FIRST word of each side, so once extract.py could capture "No. <N>" as
# part of the name, a FABRICATED number would otherwise still pass
# `_side_match` purely because the district's first word agrees -- this
# would silently promote a fabricated case name at a real citation to a
# match. Guards that a "no <digits>" designation, when present on either
# side, must agree exactly on both. ---

def test_matching_no_designation_matches():
    assert name_matches(
        "Bush v. Quinault School District No. 97",
        "Vera Bush, a Minor, by Clarence Bush, her Guardian ad Litem, Respondent, v. Quinault School District No. 97, of Grays Harbor County, Appellant",
        "Bush v. Quinault School District No. 97",
    )


def test_fabricated_no_designation_number_does_not_match():
    """A fabricated district number must NOT be loosened into a match by
    the first-word-only `_side_match` heuristic -- the case is a real,
    different district otherwise identically named."""
    assert not name_matches(
        "Bush v. Quinault School District No. 999",
        "Vera Bush, a Minor, by Clarence Bush, her Guardian ad Litem, Respondent, v. Quinault School District No. 97, of Grays Harbor County, Appellant",
        "Bush v. Quinault School District No. 97",
    )


def test_no_designation_omitted_on_given_side_still_matches():
    """A "No. <N>" designation present only on the OFFICIAL side (the
    given name is a common, legitimate short form that simply omits the
    number, e.g. "Bush v. Quinault School District") must NOT be treated
    as a mismatch -- the strict-number-agreement rule only applies when
    BOTH sides actually carry a designation to compare; this preserves the
    pre-existing loose first-word behavior for a given name that never
    mentions a number at all."""
    assert name_matches(
        "Quinault School District v. Smith",
        "Quinault School District No. 97 v. Smith",
        "Quinault School District No. 97 v. Smith",
    )


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
