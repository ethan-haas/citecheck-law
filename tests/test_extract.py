"""Extraction is tested independently of resolution/verification (acceptance gate 3):
these tests never touch corpus.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from citecheck.extract import extract_citations


def test_basic_citation_with_pinpoint_and_case_name():
    doc = '"It is emphatically the province and duty of the judicial department to say what the law is." Marbury v. Madison, 5 U.S. 137, 177 (1803).'
    cites = extract_citations(doc)
    assert len(cites) == 1
    c = cites[0]
    assert c.volume == 5
    assert c.reporter == "U.S."
    assert c.page == 137
    assert c.pinpoint == 177
    assert c.case_name == "Marbury v. Madison"
    assert c.proposition_is_quoted is True
    assert c.proposition == (
        "It is emphatically the province and duty of the judicial "
        "department to say what the law is."
    )


def test_citation_without_pinpoint():
    doc = "See Brown v. Board of Education, 347 U.S. 483 (1954)."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].pinpoint is None
    assert cites[0].page == 483


def test_two_citations_in_one_paragraph_do_not_bleed_propositions():
    doc = (
        '"First quote here." Marbury v. Madison, 5 U.S. 137, 177 (1803). '
        '"Second quote here." Gideon v. Wainwright, 372 U.S. 335, 344 (1963).'
    )
    cites = extract_citations(doc)
    assert len(cites) == 2
    assert cites[0].proposition == "First quote here."
    assert cites[1].proposition == "Second quote here."
    assert cites[0].case_name == "Marbury v. Madison"
    assert cites[1].case_name == "Gideon v. Wainwright"


def test_uncovered_reporter_is_still_extracted():
    doc = "Anderson v. Creighton, 483 S. Ct. 635 (1987)."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].reporter == "S. Ct."
    assert cites[0].volume == 483
    assert cites[0].page == 635


def test_bare_citation_no_case_name_no_quote():
    doc = "See 347 U.S. 484 (1954)."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name is None


def test_multiword_case_name_with_lowercase_connector():
    doc = "Brown v. Board of Education, 347 U.S. 483, 495 (1954)."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Brown v. Board of Education"


def test_wrapped_whitespace_normalized_in_raw_and_case_name():
    doc = "Brown v. Board of\nEducation, 347 U.S.\n483, 495 (1954)."
    cites = extract_citations(doc)
    assert "\n" not in cites[0].raw
    assert cites[0].case_name == "Brown v. Board of Education"


# --- E1 regression: Bluebook introductory signals must not be absorbed
# into case_name (independent review finding, root cause: CASE_NAME_RE's
# plaintiff group happily consumed a leading capitalized signal word as if
# it were the first word of the party name). ---

def test_signal_see_is_stripped_from_case_name():
    doc = "See Katz v. United States, 389 U.S. 347."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Katz v. United States"


def test_signal_see_also_is_stripped_from_case_name():
    doc = "See also Katz v. United States, 389 U.S. 347."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Katz v. United States"


def test_signal_see_generally_is_stripped_from_case_name():
    doc = "See generally Katz v. United States, 389 U.S. 347."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Katz v. United States"


def test_signal_see_eg_is_stripped_from_case_name():
    doc = "See, e.g., Katz v. United States, 389 U.S. 347."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Katz v. United States"


def test_signal_eg_is_stripped_from_case_name():
    doc = "E.g., Katz v. United States, 389 U.S. 347."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Katz v. United States"


def test_signal_cf_is_stripped_from_case_name():
    doc = "Cf. Katz v. United States, 389 U.S. 347."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Katz v. United States"


def test_signal_compare_accord_contra_are_stripped_from_case_name():
    for signal in ("Compare", "Accord", "Contra"):
        doc = f"{signal} Katz v. United States, 389 U.S. 347."
        cites = extract_citations(doc)
        assert cites[0].case_name == "Katz v. United States", signal


def test_signal_but_see_but_cf_are_stripped_from_case_name():
    for signal in ("But see", "But cf."):
        doc = f"{signal} Katz v. United States, 389 U.S. 347."
        cites = extract_citations(doc)
        assert cites[0].case_name == "Katz v. United States", signal


def test_signal_stripping_is_case_insensitive():
    doc = "see Katz v. United States, 389 U.S. 347."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Katz v. United States"


# --- E2 regression: an unquoted proposition ending in capitalized tokens
# must not bleed into case_name across the sentence boundary (root cause:
# CASE_NAME_RE's continuation-word class accepted ANY lowercase word, not
# just short connector words, so ordinary prose was swallowed as if it were
# part of the party name). ---

def test_proposition_tail_does_not_bleed_into_case_name():
    doc = (
        "The government must obtain a warrant. This secures Fourth "
        "Amendment protection. Katz v. United States, 389 U.S. 347."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Katz v. United States"
    assert cites[0].proposition == "This secures Fourth Amendment protection."


def test_case_name_with_legitimate_abbreviated_party_is_preserved():
    """Guards against a naive sentence-boundary-truncation fix for E2 that
    would also cut real abbreviations like 'St.' out of a party name."""
    doc = "St. Louis v. Praprotnik, 485 U.S. 112 (1988)."
    cites = extract_citations(doc)
    assert cites[0].case_name == "St. Louis v. Praprotnik"


# --- independent review (defect class: case-name/proposition
# segmentation and matching) -- redesign regression tests. Root cause: the
# case-name regex's continuation class accepted ANY capitalized token
# regardless of whether the prior token ended a sentence, and the
# proposition clause never stripped a leading Bluebook signal or detected a
# degenerate/separator-only span. Fixed by anchoring on the literal "v."
# token and growing plaintiff/defendant word-by-word with a principled
# sentence-safety check (_party_token_ok / _is_abbrev_stem), and by
# signal-stripping + degeneracy-checking the proposition clause. ---

def test_case_name_does_not_bleed_across_a_full_sentence_from_the_prior_prose():
    """Defect 1 (HIGH): a capitalized word ending the PRIOR sentence
    ("Delaware.") must not be absorbed into the case name just because it
    is capitalized and the case-name window happens to include it."""
    doc = (
        "This argument is premised on the law of Kansas and Delaware. "
        "Brown v. Board of Education, 347 U.S. 483."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Brown v. Board of Education"


def test_case_name_bleed_guard_does_not_break_multiword_geographic_defendant():
    """A defendant that is itself a full, unabbreviated capitalized phrase
    (no sentence break involved) must still parse whole."""
    doc = "New York Times Co. v. Sullivan, 376 U.S. 254 (1964)."
    cites = extract_citations(doc)
    assert cites[0].case_name == "New York Times Co. v. Sullivan"


def test_bluebook_abbreviated_party_names_are_parsed_verbatim():
    """Defect 2 (HIGH), extraction half: 'Bd.'/'Educ.' must parse as part of
    the case name (not treated as sentence-ending prose) -- the abbreviation
    EXPANSION for matching purposes is a resolve.py concern, tested
    separately in test_resolve.py."""
    doc = "Brown v. Bd. of Educ., 347 U.S. 483, 495 (1954)."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Brown v. Bd. of Educ."


def test_signal_only_clause_falls_back_to_preceding_sentence_not_the_signal_text():
    """Defects 3/4 (HIGH), superseded by a defect found in review: a proposition
    clause that is ONLY a Bluebook signal ("But see", "See", "Cf.", "Accord",
    "Compare") must never resolve to the signal text itself as if it were
    the cited proposition (still true) -- but it must ALSO never resolve to
    a blank proposition when a real preceding sentence exists: the signal
    introduces a citation for the claim already made in that sentence, so
    the citation associates with THAT sentence, not with nothing (E1: this
    was previously producing a false `exists, unsupported`/false refusal for
    admissible support)."""
    doc = (
        "The government must obtain a warrant. But see Katz v. United "
        "States, 389 U.S. 347."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Katz v. United States"
    assert cites[0].proposition == "The government must obtain a warrant."
    assert cites[0].proposition != "But see"


def test_bare_single_word_signals_fall_back_to_preceding_sentence():
    for signal in ("See", "See also", "Cf.", "Accord", "Compare"):
        doc = f"A prior unrelated sentence ends here. {signal} Katz v. United States, 389 U.S. 347."
        cites = extract_citations(doc)
        assert cites[0].proposition == "A prior unrelated sentence ends here.", signal
        assert signal.lower() not in cites[0].proposition.lower(), signal


def test_signal_only_clause_with_no_preceding_sentence_yields_empty_proposition():
    """When there truly is NO preceding sentence to fall back to (the
    document opens directly on a bare signal-cite), the proposition is
    genuinely empty -- not fabricated from the signal, not inherited."""
    doc = "But see Katz v. United States, 389 U.S. 347."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Katz v. United States"
    assert cites[0].proposition == ""


def test_string_cite_second_authority_inherits_shared_proposition_not_separator():
    """Defect 5 (HIGH): a semicolon-separated second authority in a string
    cite must inherit the shared/nearest proposition, never the bare ';'
    separator itself."""
    doc = (
        '"the Fourth Amendment protects people, not places." Katz v. United '
        "States, 389 U.S. 347; Terry v. Ohio, 392 U.S. 1."
    )
    cites = extract_citations(doc)
    assert len(cites) == 2
    assert cites[0].case_name == "Katz v. United States"
    assert cites[1].case_name == "Terry v. Ohio"
    assert cites[0].proposition == "the Fourth Amendment protects people, not places."
    assert cites[1].proposition == cites[0].proposition
    assert cites[1].proposition != ";"


def test_string_cite_each_authority_gets_its_own_case_name():
    doc = "Katz v. United States, 389 U.S. 347; Terry v. Ohio, 392 U.S. 1."
    cites = extract_citations(doc)
    assert len(cites) == 2
    assert cites[0].case_name == "Katz v. United States"
    assert cites[1].case_name == "Terry v. Ohio"


# --- independent review (defect class: association model between a
# proposition and the citation apparatus). Root cause: the proposition
# heuristic modeled "the clause immediately before this citation's
# apparatus" but had no concept of (a) falling back to the PRECEDING
# sentence when that clause was signal-only, or (b) an inter-citation
# CONNECTOR word ("and", "with") being just as much a non-propositional
# separator as ";"/",". Redesigned in `_find_proposition` as a
# sentence-by-sentence backward walk with two distinct fallbacks. ---

def test_e1_bare_signal_falls_back_to_preceding_sentence():
    """E1 (HIGH): a real proposition stated in the sentence BEFORE a
    signal-introduced citation must be associated with that citation, not
    dropped -- the signal introduces a citation for an already-stated
    claim, it does not blank the claim out."""
    doc = (
        "Separate educational facilities are inherently unequal. See Brown "
        "v. Board of Education, 347 U.S. 483."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Brown v. Board of Education"
    assert cites[0].proposition == "Separate educational facilities are inherently unequal."


def test_e1_fallback_applies_to_every_signal():
    for signal in ("See", "See also", "See generally", "Cf.", "But see", "But cf.", "Compare", "Accord", "Contra", "E.g."):
        doc = f"A real claim is stated here. {signal} Katz v. United States, 389 U.S. 347."
        cites = extract_citations(doc)
        assert cites[0].proposition == "A real claim is stated here.", signal


def test_e1_fallback_does_not_fire_when_signal_is_at_sentence_front_with_no_prior_sentence():
    """Documented scope: with nothing before the signal at all, the
    proposition is genuinely empty (there is nothing to fall back to)."""
    doc = "See Katz v. United States, 389 U.S. 347."
    cites = extract_citations(doc)
    assert cites[0].proposition == ""


def test_e2_connector_and_between_string_cites_inherits_not_the_connector():
    """E2 (HIGH): a non-first citation in a multi-cite sentence joined by
    ", and" must inherit the shared sentence proposition, never the literal
    connector text (which can coincidentally substring-match the next
    opinion and fabricate a `verified`)."""
    doc = (
        "The rule is old. Terry v. Ohio, 392 U.S. 1, and Katz v. United "
        "States, 389 U.S. 347."
    )
    cites = extract_citations(doc)
    assert len(cites) == 2
    assert cites[0].proposition == "The rule is old."
    assert cites[1].proposition == "The rule is old."
    assert cites[1].proposition != ", and"


def test_e2_connector_with_in_compare_form_inherits_not_the_connector():
    doc = (
        "The rule is old. Compare Terry v. Ohio, 392 U.S. 1, with Katz v. "
        "United States, 389 U.S. 347."
    )
    cites = extract_citations(doc)
    assert len(cites) == 2
    assert cites[0].proposition == "The rule is old."
    assert cites[1].proposition == "The rule is old."
    assert cites[1].proposition != ", with"


def test_e2_bare_and_semicolon_connectors_still_inherit():
    """Regression guard: the E2 fix (word connectors) must not disturb the
    pre-existing punctuation-only separator handling (bare ';', ',')."""
    doc = (
        "The rule is old. Katz v. United States, 389 U.S. 347; Terry v. "
        "Ohio, 392 U.S. 1."
    )
    cites = extract_citations(doc)
    assert cites[0].proposition == "The rule is old."
    assert cites[1].proposition == "The rule is old."


def test_e4_compound_signal_cf_eg_leaves_no_residue():
    """E4 (MED): 'Cf., e.g.,' (and other compound '<signal>, e.g.,' forms)
    must strip cleanly, same as the already-working 'See, e.g.,' -- no
    residual 'e.g.,' glued to the proposition."""
    doc = (
        "This segregation of children generates a feeling of inferiority. "
        "Cf., e.g., Brown v. Board of Education, 347 U.S. 483."
    )
    cites = extract_citations(doc)
    assert cites[0].proposition == "This segregation of children generates a feeling of inferiority."
    assert "e.g." not in cites[0].proposition.lower()


def test_e4_compound_signal_generalizes_to_every_base_signal():
    for signal in ("But see", "Compare", "Accord", "Contra", "See also", "See generally"):
        doc = f"A real claim is stated here. {signal}, e.g., Katz v. United States, 389 U.S. 347."
        cites = extract_citations(doc)
        assert cites[0].proposition == "A real claim is stated here.", signal
        assert "e.g." not in cites[0].proposition.lower(), signal
        assert cites[0].case_name == "Katz v. United States", signal


# --- independent review ---
# E1 (HIGH): a "(YYYY);" citation connector between two string-cited
# authorities was being mis-extracted as the SECOND citation's own
# proposition, because "(1967);" has an alnum character (a digit) and so
# passed the old degeneracy guard. Root cause: (a) a parenthetical decision
# year is citation apparatus, never prose, and (b) the old guard checked
# only "has ANY alnum char", not "has real alphabetic content" -- fixed by
# `_strip_apparatus` + `_is_propositional` (>=3 alphabetic words).

def test_e1_parenthetical_year_connector_is_not_a_proposition():
    """A bare '(YYYY);' between two string-cited authorities must never
    itself be treated as a proposition -- it is citation apparatus, and
    with nothing real to fall back to (the whole document opens on a bare
    signal), the correct result is an empty (never-fabricated,
    never-inherited-from-nothing) proposition on both citations."""
    doc = (
        "See Katz v. United States, 389 U.S. 347 (1967); Terry v. Ohio, "
        "392 U.S. 1 (1968)."
    )
    cites = extract_citations(doc)
    assert len(cites) == 2
    assert cites[0].proposition == ""
    assert cites[1].proposition == ""
    assert "(1967)" not in cites[1].proposition
    assert ";" not in cites[1].proposition


def test_e1_parenthetical_year_connector_inherits_real_preceding_proposition():
    """With a real proposition available (a preceding quote), the second
    citation in a '(YYYY);'-joined string cite must inherit THAT real
    proposition -- never the coincidental '(1967);' apparatus fragment."""
    doc = (
        '"the Fourth Amendment protects people, not places." Katz v. United '
        "States, 389 U.S. 347 (1967); Terry v. Ohio, 392 U.S. 1 (1968)."
    )
    cites = extract_citations(doc)
    assert len(cites) == 2
    assert cites[0].proposition == "the Fourth Amendment protects people, not places."
    assert cites[1].proposition == cites[0].proposition
    assert cites[1].proposition != "(1967);"
    assert "(1967)" not in cites[1].proposition


def test_e1_propositional_guard_rejects_pure_punctuation_and_digits():
    """Direct unit coverage of the new guard: a clause with digits/
    punctuation but no real alphabetic content is never propositional, even
    outside the specific '(YYYY);' shape."""
    from citecheck.extract import _is_propositional

    assert _is_propositional("(1967);") is False
    assert _is_propositional(";") is False
    assert _is_propositional(", and") is False
    assert _is_propositional("123, 456") is False
    assert _is_propositional("This is a real claim.") is True
    # Exactly at the 3-alpha-word boundary.
    assert _is_propositional("one two three") is True
    assert _is_propositional("one two") is False


def test_e1_signal_only_clause_with_parenthetical_year_before_it_still_falls_back():
    """A real preceding sentence must still be found even when a
    parenthetical year sits between it and a signal-introduced citation."""
    doc = (
        "A real claim is stated here (1954). See Katz v. United States, "
        "389 U.S. 347."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    # The preceding sentence itself contains a parenthetical year, and is
    # still picked up whole (apparatus-stripping only affects the
    # DEGENERACY judgment, never rewrites a genuine proposition's text).
    assert cites[0].proposition == "A real claim is stated here (1954)."


# --- E3 (MED): a spaced reporter rendering ('U. S.', as U.S. Reports
# itself prints it) must canonicalize to the same reporter as the unspaced
# form, so it resolves against the corpus identically. ---

def test_e3_spaced_reporter_canonicalizes_to_unspaced_form():
    doc = "Katz v. United States, 389 U. S. 347."
    cites = extract_citations(doc)
    assert cites[0].reporter == "U.S."


def test_e3_unspaced_reporter_still_parses_unchanged():
    doc = "Katz v. United States, 389 U.S. 347."
    cites = extract_citations(doc)
    assert cites[0].reporter == "U.S."


def test_e3_multiword_reporter_is_not_over_collapsed():
    """Regression guard: the E3 fix must not merge a genuine two-word
    reporter like 'S. Ct.' into 'S.Ct.'."""
    doc = "Anderson v. Creighton, 483 S. Ct. 635 (1987)."
    cites = extract_citations(doc)
    assert cites[0].reporter == "S. Ct."


def test_e3_raw_citation_text_preserves_original_spacing():
    """Canonicalization is a lookup-key concern -- the human-readable `raw`
    citation text is not rewritten."""
    doc = "Katz v. United States, 389 U. S. 347."
    cites = extract_citations(doc)
    assert "U. S." in cites[0].raw


# --- Line-wrapped propositions, party suffixes, parallel-cite pinpoints ---

def test_linewrap_proposition_extraction_spans_a_line_wrap():
    """A proposition wrapped across a bare newline (a soft line-wrap, as is
    the norm in a PDF-extracted brief) must be extracted whole, not
    truncated to the fragment after the last newline."""
    doc = (
        "The exclusionary rule bars evidence obtained\n"
        "in violation of the Fourth Amendment. Mapp v. Ohio, 367 U.S. 643."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == (
        "The exclusionary rule bars evidence obtained\n"
        "in violation of the Fourth Amendment."
    )


def test_linewrap_proposition_extraction_spans_a_crlf_wrap():
    doc = (
        "The exclusionary rule bars evidence obtained\r\n"
        "in violation of the Fourth Amendment. Mapp v. Ohio, 367 U.S. 643."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == (
        "The exclusionary rule bars evidence obtained\r\n"
        "in violation of the Fourth Amendment."
    )


def test_linewrap_proposition_extraction_spans_a_lone_cr_wrap():
    doc = (
        "The exclusionary rule bars evidence obtained\r"
        "in violation of the Fourth Amendment. Mapp v. Ohio, 367 U.S. 643."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == (
        "The exclusionary rule bars evidence obtained\r"
        "in violation of the Fourth Amendment."
    )


def test_linewrap_proposition_is_never_falsely_empty_across_a_line_wrap():
    """Before the fix, a citation whose entire preceding sentence was
    line-wrapped (with no earlier sentence to fall back to) extracted the
    empty string, producing a false 'exists, unsupported' downstream."""
    doc = "Words break across\na line. Mapp v. Ohio, 367 U.S. 643."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == "Words break across\na line."


def test_linewrap_blank_line_paragraph_break_is_still_a_real_boundary():
    """Regression guard: the newline fix must not make a genuine blank-line
    PARAGRAPH break bleed a proposition from one paragraph into the next --
    paragraph splitting (on "\\n\\s*\\n") still isolates them."""
    doc = (
        "First paragraph entirely unrelated to the citation below.\n"
        "\n"
        "Second paragraph states the actual rule. Mapp v. Ohio, 367 U.S. 643."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert "First paragraph" not in cites[0].proposition
    assert cites[0].proposition == "Second paragraph states the actual rule."


def test_partysuffix_party_suffix_does_not_absorb_prior_sentence_prose():
    """A sentence ending in a party-suffix abbreviation ('Acme Corp.')
    immediately before an unrelated citation must not have that suffix (and
    the prose before it) swept into the citation's case name."""
    doc = "The parties negotiated with Acme Corp. Katz v. United States, 389 U.S. 347."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Katz v. United States"


def test_partysuffix_party_suffix_variants_do_not_absorb_prior_sentence_prose():
    for suffix, prior in (
        ("Inc.", "We contracted with Global Retail Inc."),
        ("Co.", "We contracted with Pacific Shipping Co."),
        ("Ltd.", "We contracted with Danforth Holdings Ltd."),
        ("Ass'n", "We joined the Riverside Homeowners Ass'n."),
        ("N.A.", "We banked with First National N.A."),
    ):
        doc = f"{prior} Katz v. United States, 389 U.S. 347."
        cites = extract_citations(doc)
        assert len(cites) == 1, (suffix, doc)
        assert cites[0].case_name == "Katz v. United States", (suffix, cites[0].case_name)


def test_partysuffix_party_suffix_on_the_actual_plaintiff_still_parses():
    """Regression guard: a suffix that legitimately belongs to THIS
    citation's plaintiff (immediately adjacent to 'v.') must keep working."""
    cases = {
        "New York Times Co. v. Sullivan, 376 U.S. 254.": "New York Times Co. v. Sullivan",
        "Erie R. Co. v. Tompkins, 304 U.S. 64.": "Erie R. Co. v. Tompkins",
        "Chevron U.S.A. Inc. v. NRDC, 467 U.S. 837.": "Chevron U.S.A. Inc. v. NRDC",
        "Int'l Shoe Co. v. Washington, 326 U.S. 310.": "Int'l Shoe Co. v. Washington",
    }
    for doc, expected in cases.items():
        cites = extract_citations(doc)
        assert len(cites) == 1, doc
        assert cites[0].case_name == expected, (doc, cites[0].case_name)


def test_parallelcite_parallel_citation_volume_is_not_a_pinpoint():
    """'347 U.S. 483, 74 S. Ct. 686' -- 74 is the VOLUME of the parallel
    S. Ct. citation, not a pinpoint page inside U.S. 483. Must parse as two
    independent citations, neither with a fabricated pinpoint."""
    doc = "Brown v. Board, 347 U.S. 483, 74 S. Ct. 686."
    cites = extract_citations(doc)
    assert len(cites) == 2
    first, second = cites
    assert (first.volume, first.reporter, first.page) == (347, "U.S.", 483)
    assert first.pinpoint is None
    assert first.raw == "347 U.S. 483"
    assert (second.volume, second.reporter, second.page) == (74, "S. Ct.", 686)
    assert second.pinpoint is None


def test_parallelcite_three_way_parallel_citation_all_independent():
    doc = "Miranda v. Arizona, 384 U.S. 436, 86 S. Ct. 1602, 16 L. Ed. 2d 694 (1966)."
    cites = extract_citations(doc)
    assert len(cites) == 3
    assert [(c.volume, c.reporter, c.page, c.pinpoint) for c in cites] == [
        (384, "U.S.", 436, None),
        (86, "S. Ct.", 1602, None),
        (16, "L. Ed. 2d", 694, None),
    ]


def test_parallelcite_genuine_pinpoint_still_parses_when_no_parallel_cite_follows():
    """Regression guard: an ordinary pinpoint (nothing reporter-shaped after
    it) must still parse as a pinpoint, not get swallowed by the new
    lookahead."""
    doc = "Brown v. Board, 347 U.S. 483, 495 (1954)."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].page == 483
    assert cites[0].pinpoint == 495


# ---------------------------------------------------------------------------
# A closing quote is a hard boundary
# for the backward case-name scan.
# ---------------------------------------------------------------------------

def test_closingquote_closing_quote_is_a_hard_boundary_for_case_name_scan():
    """Repro: a quoted proposition whose FINAL WORD is capitalized, stated
    immediately before the citation in the natural order, must not glue that
    word onto the case name -- 'case_name' must be exactly 'Katz v. United
    States', never 'Presidents." Katz v. United States'."""
    doc = (
        '"Wiretapping to protect the security of the Nation has been '
        'authorized by successive Presidents." Katz v. United States, '
        "389 U.S. 347."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Katz v. United States"


def test_closingquote_capitalization_flip_controlled_pair():
    """Controlled pair: identical case,
    citation, and quoted proposition text, differing ONLY in whether the
    quote's final word is upper- or lowercase. Before the fix, the verdict
    flipped solely on that capitalization -- both must now parse the same
    case name."""
    lower = (
        '"wiretapping to protect the security of the nation has been '
        'authorized by successive presidents." Katz v. United States, '
        "389 U.S. 347."
    )
    upper = (
        '"Wiretapping to protect the security of the Nation has been '
        'authorized by successive Presidents." Katz v. United States, '
        "389 U.S. 347."
    )
    lower_cite = extract_citations(lower)[0]
    upper_cite = extract_citations(upper)[0]
    assert lower_cite.case_name == "Katz v. United States"
    assert upper_cite.case_name == "Katz v. United States"
    assert lower_cite.case_name == upper_cite.case_name


def test_closingquote_curly_closing_quote_is_also_a_hard_boundary():
    """The same boundary must hold for a curly closing double quote
    (U+201D), not just a straight ASCII quote."""
    doc = (
        "“Separate but Equal.” Brown v. Board of Education, "
        "347 U.S. 483."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Brown v. Board of Education"


def test_closingquote_closing_single_quote_is_also_a_hard_boundary():
    """A closing single quote (a quote-within-a-quote, or a bare apostrophe
    closing a quoted span) must also stop the backward scan."""
    doc = "‘Equal Protection.’ Katz v. United States, 389 U.S. 347."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Katz v. United States"


def test_closingquote_lowercase_quote_tail_still_correctly_excluded_unchanged():
    """Regression guard: the pre-existing, already-correct lowercase-ending
    case (the control half of the pair) must keep working exactly
    as before -- this is not a new fix, but confirms the new closing-quote
    check does not change behavior on the already-passing path."""
    doc = (
        '"the Fourth Amendment protects people, not places." Katz v. '
        "United States, 389 U.S. 347."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Katz v. United States"


def test_closingquote_genuine_abbreviated_party_with_internal_apostrophe_unaffected():
    """Regression guard: a genuine party-name abbreviation with an internal
    apostrophe ("Int'l") does not end in a closing-quote character and must
    keep parsing exactly as before -- the new check only fires on a token
    whose LAST character is a closing quote mark."""
    doc = "Int'l Shoe Co. v. Washington, 326 U.S. 310."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Int'l Shoe Co. v. Washington"


# ---------------------------------------------------------------------------
# A trailing explanatory parenthetical
# is associated as this citation's proposition.
# ---------------------------------------------------------------------------

def test_trailingparen_trailing_holding_parenthetical_with_quote_is_associated():
    """Repro: the canonical trailing-parenthetical form -- a quoted
    proposition inside '(holding "...")' immediately after the citation --
    must be associated as this citation's proposition, quoted verbatim."""
    doc = 'Katz v. United States, 389 U.S. 347 (holding "the quoted holding").'
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == "the quoted holding"
    assert cites[0].proposition_is_quoted is True


def test_trailingparen_trailing_finding_and_noting_parentheticals_also_associated():
    for verb in ("finding", "noting", "stating", "explaining", "concluding"):
        doc = f'Katz v. United States, 389 U.S. 347 ({verb} "a real claim here").'
        cites = extract_citations(doc)
        assert len(cites) == 1, verb
        assert cites[0].proposition == "a real claim here", verb
        assert cites[0].proposition_is_quoted is True, verb


def test_trailingparen_trailing_parenthetical_paraphrase_without_quotes():
    """Without an inner quote, the parenthetical's own text after the
    introductory gerund (and optional 'that') is used as a paraphrase
    proposition."""
    doc = (
        "Katz v. United States, 389 U.S. 347 (holding that warrantless "
        "wiretapping violates the Fourth Amendment)."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == "warrantless wiretapping violates the Fourth Amendment"
    assert cites[0].proposition_is_quoted is False


def test_trailingparen_decision_year_parenthetical_before_trailing_explanatory_is_skipped():
    """'(1967) (holding "...")' -- the bare decision-year parenthetical is
    citation apparatus, not the explanatory clause; it must be skipped over,
    not mistaken for (or block) the real explanatory parenthetical that
    follows it."""
    doc = (
        'Katz v. United States, 389 U.S. 347 (1967) (holding "a real '
        'claim here").'
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == "a real claim here"
    assert cites[0].proposition_is_quoted is True


def test_trailingparen_court_and_date_parenthetical_before_trailing_explanatory_is_skipped():
    """'(9th Cir. 1967) (holding "...")' -- same as above, for a court+date
    apparatus parenthetical rather than a bare year."""
    doc = (
        'Katz v. United States, 389 U.S. 347 (9th Cir. 1967) (holding "a '
        'real claim here").'
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == "a real claim here"
    assert cites[0].proposition_is_quoted is True


def test_trailingparen_per_curiam_parenthetical_is_never_a_proposition():
    """Degenerate-proposition guard: '(per curiam)' must never yield a
    proposition -- neither used directly, nor mistaken for an apparatus
    parenthetical that unlocks a (nonexistent) explanatory one after it."""
    doc = "Katz v. United States, 389 U.S. 347 (per curiam)."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == ""
    assert cites[0].proposition_is_quoted is False


def test_trailingparen_en_banc_and_vote_split_parentheticals_are_never_propositions():
    for paren in ("(en banc)", "(5-4)", "(9th Cir.)"):
        doc = f"Katz v. United States, 389 U.S. 347 {paren}."
        cites = extract_citations(doc)
        assert len(cites) == 1, paren
        assert cites[0].proposition == "", paren


def test_trailingparen_non_explanatory_parenthetical_with_real_prose_is_not_guessed_at():
    """A parenthetical that does NOT start with a recognized explanatory
    verb, but does have real prose content, is not this citation's
    explanatory clause (e.g. a remark about a different, unrelated
    authority) -- it must not be guessed at as a proposition."""
    doc = (
        "Katz v. United States, 389 U.S. 347 (discussed at length by "
        "commentators over the following decade)."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == ""


def test_trailingparen_trailing_parenthetical_overrides_a_weaker_sentence_paraphrase():
    """'If both a sentence proposition and a trailing parenthetical exist,
    the parenthetical is the more specific claim for THIS citation' -- a
    preceding unquoted sentence must not win over a genuine trailing
    explanatory parenthetical."""
    doc = (
        "The Court addressed wiretapping. Katz v. United States, 389 U.S. "
        '347 (holding "the real, specific holding").'
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == "the real, specific holding"
    assert cites[0].proposition_is_quoted is True


def test_trailingparen_preceding_quote_still_takes_priority_over_trailing_parenthetical():
    """Regression/precedence guard: when a verbatim quote already precedes
    the citation (the pre-existing, highest-confidence association path),
    it is NOT overridden by a trailing parenthetical."""
    doc = (
        '"the preceding quoted proposition." Katz v. United States, 389 '
        'U.S. 347 (holding "a different trailing claim").'
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == "the preceding quoted proposition."
    assert cites[0].proposition_is_quoted is True


# ---------------------------------------------------------------------------
# independent review (post-corpus-scale, 7 reporters) -- 3 reproduced
# FALSE-`verified` escapes, one root cause: the degenerate-proposition guard
# (`_is_propositional`) was applied on some proposition sources but not on
# the quoted-proposition path, and had no concept of a bare case-name span
# at all. Fixed by making `_is_propositional` the single, uniformly-applied
# gate for every proposition source (quoted, paraphrase/sentence, trailing
# parenthetical, inherited/string-cite).
# ---------------------------------------------------------------------------

def test_bare_corporate_name_short_form_yields_no_proposition():
    """A short-form citation that is only `<party name>,
    <cite>` with no accompanying "v." (so `_find_case_name` cannot anchor a
    case name at all) must NOT fall back to using the party name itself as
    the proposition -- the case name (or a substring of it) must never
    become a proposition."""
    doc = "Steve Jackson Games, 816 F. Supp. 432."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name is None
    assert cites[0].proposition == ""


def test_bare_corporate_name_with_suffix_still_yields_no_proposition():
    doc = "Steve Jackson Games, Inc., 816 F. Supp. 432."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == ""


def test_signal_prefixed_bare_name_still_yields_no_proposition():
    doc = "See also Carroll Towing Co., 159 F.2d 169."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == ""


def test_clean_v_short_form_is_unaffected_case_name_still_parses():
    """Regression guard: a CLEAN `X v. Y` short form (where `_find_case_name`
    DOES find a "v.") is not affected by the bare-name guard -- the case
    name still parses normally, and any real preceding prose is still used
    as the proposition."""
    doc = "A clean short form: Frye v. United States, 293 F. 1013."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Frye v. United States"
    assert cites[0].proposition == "A clean short form:"


def test_genuine_prose_with_capitalized_words_is_not_treated_as_a_name():
    """Over-loosening guard: ordinary prose that happens to contain several
    capitalized words (proper nouns) but ALSO contains ordinary lowercase
    content words is not a bare name and must still be used as a genuine
    proposition."""
    doc = "The Steve Jackson Games raid violated the Fourth Amendment. 816 F. Supp. 432."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == "The Steve Jackson Games raid violated the Fourth Amendment."


def test_quoted_connector_word_yields_no_proposition():
    """An explicitly-QUOTED single-word connector/degenerate
    string is not exempt from the same degeneracy guard every other
    proposition source is subject to."""
    for word in ("and", "the"):
        doc = f'The court reasoned "{word}" Frye v. United States, 293 F. 1013.'
        cites = extract_citations(doc)
        assert len(cites) == 1, word
        assert cites[0].proposition != word, word
        assert cites[0].proposition_is_quoted is False, word


def test_quoted_two_word_fragment_yields_no_proposition():
    for phrase in ("the barge", "is difficult"):
        doc = f'The court reasoned "{phrase}" Frye v. United States, 293 F. 1013.'
        cites = extract_citations(doc)
        assert len(cites) == 1, phrase
        assert cites[0].proposition != phrase, phrase
        assert cites[0].proposition_is_quoted is False, phrase


def test_genuine_quoted_proposition_is_unaffected():
    """Regression guard: a real, multi-word quoted proposition (>=3 alpha
    content words) still takes the quoted-verbatim path exactly as before."""
    doc = '"It is emphatically the province and duty" Frye v. United States, 293 F. 1013.'
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].proposition == "It is emphatically the province and duty"
    assert cites[0].proposition_is_quoted is True


def test_degenerate_quote_does_not_propagate_via_string_cite_inheritance():
    """A degenerate quote associated with the FIRST citation in a
    string cite must not be inherited by a SECOND, sibling citation either --
    once the quote is rejected by the guard, there is nothing real to
    inherit, so the second citation falls back to its own (possibly empty)
    clause rather than the rejected quote text."""
    doc = 'The opinion said "the barge". 148 F.2d 416; 159 F.2d 169.'
    cites = extract_citations(doc)
    assert len(cites) == 2
    for c in cites:
        assert c.proposition != "the barge"
        assert c.proposition_is_quoted is False


def test_no_proposition_source_can_yield_a_case_name_signal_or_fragment():
    """Sweep across every proposition source (quoted, paraphrase, trailing
    parenthetical, string-cite inheritance): none may ever produce a
    proposition that is a case name, a bare Bluebook signal, a connector, or
    a sub-threshold fragment."""
    docs = [
        "Steve Jackson Games, 816 F. Supp. 432.",
        "See also Carroll Towing Co., 159 F.2d 169.",
        'The court reasoned "and" Frye v. United States, 293 F. 1013.',
        'The court reasoned "the" Frye v. United States, 293 F. 1013.',
        "Frye v. United States, 293 F. 1013 (per curiam).",
        'The opinion said "the barge". 148 F.2d 416; 159 F.2d 169.',
    ]
    forbidden = {"Steve Jackson Games", "Carroll Towing Co.", "and", "the", "the barge"}
    for doc in docs:
        for c in extract_citations(doc):
            assert c.proposition.strip() not in forbidden, (doc, c.proposition)


# ---------------------------------------------------------------------------
# Corpus-scale-up round (36 reporters / 352 opinions) -- false-refusal
# escapes 1/2/3: the backward plaintiff scan reframed to accept the whole
# in-sentence span up to "v." (an "&", the "ex rel."/"ex dem." relator
# continuation words, and an uncapped run of lowercase connector words) --
# instead of stopping at the first token outside a narrow per-type
# whitelist or an arbitrary word-count cap.
# ---------------------------------------------------------------------------

def test_ampersand_plaintiff_is_captured_in_full():
    """Escape 1 (HIGH): a bare '&' inside the plaintiff name ('Texas & Pac.
    Ry. Co.') must not truncate the backward scan -- real corpus case
    cap-10033449."""
    doc = "Texas & Pac. Ry. Co. v. Burch, 1 So. 2d 64. This holds a rule."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Texas & Pac. Ry. Co. v. Burch"


def test_ampersand_does_not_let_unrelated_prior_sentence_bleed_in():
    """Regression guard: accepting '&' as an in-name token must not, on its
    own, let an unrelated prior sentence that happens to contain '&' bleed
    into the case name -- the real sentence-ending period still stops the
    scan first."""
    doc = "Smith & Wesson reported record earnings. Katz v. United States, 389 U.S. 347."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Katz v. United States"


def test_bare_sovereign_ex_rel_relator_is_captured_in_full():
    """Escape 2 (HIGH): 'State ex rel. X v. Y' -- a bare-sovereign relator
    phrasing (not the already-special-cased 'United States ex rel.') --
    must capture the full 'State ex rel. Moorehead' plaintiff, not just
    'Moorehead'. Real corpus case cap-1771311."""
    doc = "State ex rel. Moorehead v. Reed, 177 Ohio St. 4. This holds a rule."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "State ex rel. Moorehead v. Reed"


def test_people_and_commonwealth_ex_rel_also_captured():
    for sovereign in ("People", "Commonwealth"):
        doc = f"{sovereign} ex rel. Moorehead v. Reed, 177 Ohio St. 4. This holds a rule."
        cites = extract_citations(doc)
        assert len(cites) == 1, doc
        assert cites[0].case_name == f"{sovereign} ex rel. Moorehead v. Reed", doc


def test_ex_dem_relator_is_captured_in_full():
    """'ex dem.' (the historical 'on the demise of') relator phrasing --
    real corpus case cap-1373752."""
    doc = "Doe ex dem. Truluck v. Peeples, 1 Ga. 1. This holds a rule."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Doe ex dem. Truluck v. Peeples"


def test_united_states_ex_rel_still_parses_unaffected():
    """Regression guard: the pre-existing 'United States ex rel.' path
    (already worked before this fix, since 'United States' is capitalized)
    must be unaffected."""
    doc = "United States ex rel. Long v. SCS Bus. & Technical Inst., 1 F.3d 1. This holds a rule."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "United States ex rel. Long v. SCS Bus. & Technical Inst."


def test_long_multiword_plaintiff_with_connectors_not_truncated():
    """Escape 3 (HIGH): a plaintiff with lowercase connector words inside it
    ('Sweet Home Chapter of Communities for a Great Oregon') must not be
    truncated by an arbitrary word-count cap -- real corpus case
    cap-10507259."""
    doc = "Sweet Home Chapter of Communities for a Great Oregon v. Babbitt, 1 F.3d 1. This holds a rule."
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Sweet Home Chapter of Communities for a Great Oregon v. Babbitt"


def test_long_plaintiff_still_stops_at_real_prior_sentence_boundary():
    """Regression guard: uncapping the plaintiff word count must not let an
    unrelated PRIOR sentence (even one containing capitalized proper nouns
    and connector words of its own) bleed into a long plaintiff name."""
    doc = (
        "The National Wildlife Federation opposed the rule change in Oregon. "
        "Sweet Home Chapter of Communities for a Great Oregon v. Babbitt, "
        "1 F.3d 1."
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Sweet Home Chapter of Communities for a Great Oregon v. Babbitt"


def test_prior_fixes_still_hold_after_plaintiff_boundary_reframing():
    """Sweep of the pre-existing plaintiff-boundary regression tests
    (closing quote, party suffix, prior-sentence prose, St./Corp./Inc.
    abbreviations) -- must all still hold unchanged after widening what the
    backward scan accepts as an in-name token and uncapping its length."""
    cases = [
        (
            "This argument is premised on the law of Kansas and Delaware. "
            "Brown v. Board of Education, 347 U.S. 483.",
            "Brown v. Board of Education",
        ),
        ("New York Times Co. v. Sullivan, 376 U.S. 254 (1964).", "New York Times Co. v. Sullivan"),
        ("St. Louis v. Praprotnik, 485 U.S. 112 (1988).", "St. Louis v. Praprotnik"),
        (
            "The parties negotiated with Acme Corp. Katz v. United States, 389 U.S. 347.",
            "Katz v. United States",
        ),
        (
            '"Wiretapping to protect the security of the Nation has been '
            'authorized by successive Presidents." Katz v. United States, '
            "389 U.S. 347.",
            "Katz v. United States",
        ),
        ("Int'l Shoe Co. v. Washington, 326 U.S. 310.", "Int'l Shoe Co. v. Washington"),
    ]
    for doc, expected in cases:
        cites = extract_citations(doc)
        assert cites[0].case_name == expected, (doc, cites[0].case_name)


# ---------------------------------------------------------------------------
# CARDINAL FIX (secondary): standard Bluebook jurisdiction/entity
# abbreviations must parse as valid party-name tokens, matching the existing
# "Bd."/"Educ." pattern above -- extraction-only, no corpus involved.
# ---------------------------------------------------------------------------

def test_cnty_abbreviation_parses_as_case_name():
    doc = "Rafaeli, LLC v. Oakland Cnty., 932 N.W.2d 1."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Rafaeli, LLC v. Oakland Cnty."
    assert cites[0].name_construct_present is True


def test_twp_abbreviation_parses_as_case_name():
    doc = "Doe v. Marlboro Twp., 1 F.3d 1."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Doe v. Marlboro Twp."


def test_commrs_abbreviation_parses_as_case_name():
    doc = "Reed v. Bd. of Comm'rs, 1 F.3d 1."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Reed v. Bd. of Comm'rs"


def test_lp_and_llc_suffixes_parse_as_case_name():
    for doc, expected in (
        ("Acme, L.P. v. Widget Co., 1 F.3d 1.", "Acme, L.P. v. Widget Co."),
        ("Rafaeli, LLC v. Doe, 1 F.3d 1.", "Rafaeli, LLC v. Doe"),
        ("Rafaeli, L.L.C. v. Doe, 1 F.3d 1.", "Rafaeli, L.L.C. v. Doe"),
        ("Widget, LLP v. Doe, 1 F.3d 1.", "Widget, LLP v. Doe"),
    ):
        cites = extract_citations(doc)
        assert cites[0].case_name == expected, (doc, cites[0].case_name)


# ---------------------------------------------------------------------------
# CARDINAL FIX (primary): `name_construct_present` must be True whenever an
# "X v. Y"-shaped construct appears in context, INDEPENDENTLY of whether the
# full scan manages to parse a `case_name` out of it -- this is the signal
# verdict.py's fail-closed guard depends on.
# ---------------------------------------------------------------------------

def test_name_construct_present_true_even_when_case_name_fails_to_parse():
    """An unrecognized abbreviation ('Xyzzyplonk.', not a known Bluebook
    stem) defeats the full parse (case_name is None) but the "X v. Y"
    adjacency is still plainly present -- name_construct_present must stay
    True so the caller can distinguish this from a genuinely bare cite."""
    doc = "Roe v. Xyzzyplonk., 347 U.S. 483."
    cites = extract_citations(doc)
    assert cites[0].case_name is None
    assert cites[0].name_construct_present is True


def test_name_construct_present_false_for_genuinely_bare_citation():
    doc = "See 347 U.S. 483 (1954)."
    cites = extract_citations(doc)
    assert cites[0].case_name is None
    assert cites[0].name_construct_present is False


def test_name_construct_present_false_when_no_v_token_at_all():
    """A bare corporate short form with no 'v.' token anywhere in context
    must not be misclassified as a name construct (this case short-form
    guard, extraction-only)."""
    doc = "Steve Jackson Games, 816 F. Supp. 432."
    cites = extract_citations(doc)
    assert cites[0].case_name is None
    assert cites[0].name_construct_present is False


def test_name_construct_present_true_when_case_name_parses_normally():
    """Sanity check: when the full scan DOES successfully parse a
    case_name, name_construct_present is also True (a parsed name is
    trivially an offered name)."""
    doc = "Brown v. Board of Education, 347 U.S. 483."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Brown v. Board of Education"
    assert cites[0].name_construct_present is True


# ---------------------------------------------------------------------------
# FALSE-REFUSAL FIX: non-"v." case-name constructs ("In re Foo", "In the
# Matter of Foo", "Matter of Foo", "Ex parte Foo", "Succession of Foo",
# "Estate of Foo", "Application of Foo", "Petition of Foo", bare
# "Anonymous") must be recognized as case names too, exactly like "X v. Y",
# so they are excluded from the proposition clause instead of bleeding into
# (and corrupting/displacing) it.
# ---------------------------------------------------------------------------

def test_in_re_recognized_as_case_name():
    doc = "In re Gantt, 302 Ga. 3."
    cites = extract_citations(doc)
    assert cites[0].case_name == "In re Gantt"
    assert cites[0].name_construct_present is True


def test_in_the_matter_of_recognized_as_case_name():
    doc = "In the Matter of Gantt, 302 Ga. 3."
    cites = extract_citations(doc)
    assert cites[0].case_name == "In the Matter of Gantt"


def test_bare_matter_of_recognized_as_case_name():
    doc = "Matter of Gantt, 302 Ga. 3."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Matter of Gantt"


def test_ex_parte_recognized_as_case_name():
    doc = "Ex parte Rhodes, 163 Tex. 31."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Ex parte Rhodes"


def test_succession_of_recognized_as_case_name():
    doc = "Succession of Casanova, 999 So. 2d 1."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Succession of Casanova"


def test_estate_of_recognized_as_case_name():
    doc = "Estate of Randall, 999 A.2d 51."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Estate of Randall"


def test_nested_in_re_estate_of_recognized_as_case_name():
    """A phrase construct may itself contain another ("In re Estate of
    Randall") -- the party-name scan tolerates the second phrase's
    lowercase connector ("of") exactly like it already tolerates "Board
    of Education", so the FULL name is captured rather than just the
    innermost phrase."""
    doc = "In re Estate of Randall, 999 A.2d 51."
    cites = extract_citations(doc)
    assert cites[0].case_name == "In re Estate of Randall"


def test_application_of_recognized_as_case_name():
    doc = "Application of Smith, 1 A.2d 1."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Application of Smith"


def test_petition_of_recognized_as_case_name():
    doc = "Petition of Doe, 1 A.2d 1."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Petition of Doe"


def test_bare_anonymous_recognized_as_case_name():
    doc = "Anonymous, 1 U.S. 1."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Anonymous"
    assert cites[0].name_construct_present is True


def test_non_v_name_with_abbreviation_recognized():
    """A non-"v." party name containing a dotted-initial short form
    ("K.C.W.") must still parse -- each initial-plus-period token is <=3
    letters once punctuation is stripped, so `_is_abbrev_stem` already
    accepts it (same rule that lets "St." and "Bd." continue a "v." party
    name)."""
    doc = "In re K.C.W., 456 Pa. Super. 1."
    cites = extract_citations(doc)
    assert cites[0].case_name == "In re K.C.W."


def test_signal_stripped_from_non_v_case_name():
    """A leading Bluebook signal before a non-"v." construct must never
    become part of the reported case name, mirroring the "v." path."""
    doc = "See In re Gantt, 302 Ga. 3."
    cites = extract_citations(doc)
    assert cites[0].case_name == "In re Gantt"


def test_non_v_case_name_excluded_from_proposition_clause():
    """CORE false-refusal fix: previously, because a non-"v." construct was
    never recognized as a case name at all, its text was left inside the
    proposition-clause scan and (depending on shape) either corrupted the
    reported proposition or -- as here -- caused the whole clause to be
    judged a bare name and discarded, producing an empty proposition and a
    spurious `exists, unsupported` even though a real, checkable sentence
    immediately precedes the citation. The case name must now be excluded
    from the clause exactly like an "X v. Y" name already is."""
    doc = (
        "The court held that the officer lacked reasonable suspicion. "
        "In re Gantt, 302 Ga. 3."
    )
    cites = extract_citations(doc)
    c = cites[0]
    assert c.case_name == "In re Gantt"
    assert c.proposition == "The court held that the officer lacked reasonable suspicion."


def test_name_construct_present_true_for_unparseable_non_v_construct():
    """A non-"v." phrase followed by an unrecognized abbreviation ("
    Xyzzyplonk.", not a known Bluebook stem) defeats the full parse
    (case_name is None) but the construct is still plainly present --
    name_construct_present must stay True so verdict.py's fail-closed guard
    fires (mirrors the "v." cardinal-fix guard)."""
    doc = "In re Xyzzyplonk., 302 Ga. 3."
    cites = extract_citations(doc)
    assert cites[0].case_name is None
    assert cites[0].name_construct_present is True


def test_name_construct_present_false_for_lowercase_prose_after_phrase():
    """A capitalized phrase word followed immediately by an ordinary
    lowercase prose word ("the") is not name-shaped -- construct_present
    must stay False (no name was actually offered here)."""
    doc = "In re the unknown matter, 302 Ga. 3."
    cites = extract_citations(doc)
    assert cites[0].case_name is None
    assert cites[0].name_construct_present is False


def test_lowercase_estate_of_in_prose_not_misread_as_case_name():
    """Ordinary prose containing the words "estate of" in lowercase (a
    common noun, not a case-name phrase) must never be misread as a
    non-"v." construct -- the phrase match requires the phrase's own first
    word to be capitalized."""
    doc = "The decedent's estate of the deceased was valued highly. 1 A.2d 1."
    cites = extract_citations(doc)
    assert cites[0].case_name is None
    assert cites[0].name_construct_present is False


def test_no_v_token_and_no_non_v_phrase_stays_bare():
    """Sanity check: a genuinely bare corporate short form (no "v.", no
    recognized non-"v." phrase) is unaffected by this fix."""
    doc = "Steve Jackson Games, 816 F. Supp. 432."
    cites = extract_citations(doc)
    assert cites[0].case_name is None
    assert cites[0].name_construct_present is False


# --- Defect 1 (over-refusal): a trailing "No. <digits>"/"Nos. <digits>"
# district/party designation is a common, genuine part of a Bluebook party
# name ("School District No. 97", "Sewer Improvement Dist. No. 1"), but a
# bare digit token does not itself pass `_party_token_ok` (it is neither
# capitalized nor a connector word), so the scans previously stopped dead
# the instant they reached the number, discarding the entire party name.
# Real corpus repros: `In re Washington County Sewer Improvement Dist. No.
# 1, 252 P.2d 139` (cap-10493889, non-"v." path) and `Bush v. Quinault
# School District No. 97, 1 Wash. 2d 28` (cap-1963361, "v." forward/
# defendant-side path). ---

def test_no_designation_parses_on_non_v_path():
    doc = "In re Washington County Sewer Improvement Dist. No. 1, 252 P.2d 139."
    cites = extract_citations(doc)
    assert cites[0].case_name == "In re Washington County Sewer Improvement Dist. No. 1"


def test_no_designation_parses_on_v_defendant_side():
    doc = "Bush v. Quinault School District No. 97, 1 Wash. 2d 28."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Bush v. Quinault School District No. 97"


def test_nos_plural_designation_also_recognized():
    """"Nos." (plural) is the same designation word and must parse the
    same way as the singular "No."."""
    doc = "In re Consolidated Drainage Dist. Nos. 4, 302 Ga. 3."
    cites = extract_citations(doc)
    assert cites[0].case_name == "In re Consolidated Drainage Dist. Nos. 4"


def test_no_designation_parses_on_v_plaintiff_backward_scan():
    """The numbered designation must also be picked up by the BACKWARD
    plaintiff scan (the plaintiff side of an "X v. Y" name), not just the
    forward defendant scan -- exercises the digit-peek added to the
    backward while-loop in `_find_case_name`."""
    doc = "Water Improvement District No. 5 v. Smith, 302 Ga. 3."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Water Improvement District No. 5 v. Smith"


def test_bare_digit_not_preceded_by_no_still_stops_the_scan():
    """Guard against over-loosening: an ordinary bare number NOT preceded
    by a "No."/"Nos." designation word must still stop the party-name
    scan exactly as before (e.g. a stray page/section number bleeding in
    from unrelated prose must never be absorbed into a case name)."""
    doc = "The court cited section 5. Brown v. Board of Education, 347 U.S. 483."
    cites = extract_citations(doc)
    assert cites[0].case_name == "Brown v. Board of Education"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
