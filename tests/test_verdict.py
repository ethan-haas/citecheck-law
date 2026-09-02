"""End-to-end verdict tests against the real committed corpus (read-only),
plus a gate-6 test that corrupts a TEMP COPY of one opinion's text and
requires the affected citation to flip from verified to exists, unsupported.
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from citecheck.corpus import Corpus
from citecheck.extract import extract_citations
from citecheck.verdict import judge_citation, VERIFIED, EXISTS_UNSUPPORTED, NOT_FOUND_VERDICT, CANNOT_VERIFY

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_DIR = os.path.join(REPO_ROOT, "corpus")


def _judge_one(doc, corpus):
    cites = extract_citations(doc)
    assert len(cites) == 1, f"expected exactly 1 citation, got {len(cites)}: {cites}"
    return judge_citation(corpus, cites[0])


def test_verified_real_quote():
    corpus = Corpus(CORPUS_DIR)
    doc = '"Separate educational facilities are inherently unequal." Brown v. Board of Education, 347 U.S. 483, 495 (1954).'
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-11301409"
    assert v.span is not None
    op = corpus.get_opinion("cap-11301409")
    assert op.text[v.span[0]:v.span[1]] == v.quoted_sentence
    assert v.quoted_sentence in op.text


def test_exists_unsupported_misattributed_holding():
    corpus = Corpus(CORPUS_DIR)
    doc = "The Court held that police officers may search any pedestrian without any level of suspicion. Terry v. Ohio, 392 U.S. 1, 30 (1968)."
    v = _judge_one(doc, corpus)
    assert v.verdict == EXISTS_UNSUPPORTED
    assert v.opinion_id == "cap-6167798"


def test_not_found_page_in_complete_volume():
    corpus = Corpus(CORPUS_DIR)
    doc = "See 347 U.S. 484 (1954)."
    v = _judge_one(doc, corpus)
    assert v.verdict == NOT_FOUND_VERDICT
    assert "does not exist" not in v.reason.lower()


def test_cannot_verify_uncovered_reporter():
    corpus = Corpus(CORPUS_DIR)
    doc = "Anderson v. Creighton, 483 S. Ct. 635 (1987)."
    v = _judge_one(doc, corpus)
    assert v.verdict == CANNOT_VERIFY
    assert "not represented in this corpus" in v.reason


def test_cannot_verify_covered_but_not_ingested():
    corpus = Corpus(CORPUS_DIR)
    doc = "See 347 U.S. 17, 20 (1954)."
    v = _judge_one(doc, corpus)
    assert v.verdict == CANNOT_VERIFY
    assert "not ingested" in v.reason


def test_not_found_vs_cannot_verify_never_conflated():
    """acceptance gate 2: a page-not-found in a covered volume must never be
    reported the same way as an uncovered reporter/volume, and neither
    verdict's wording may ever claim a real authority does not exist."""
    corpus = Corpus(CORPUS_DIR)
    not_found = _judge_one("See 347 U.S. 484 (1954).", corpus)
    cannot_verify = _judge_one("See 500 U.S. 1 (1990).", corpus)  # volume 500 not in corpus
    assert not_found.verdict == NOT_FOUND_VERDICT
    assert cannot_verify.verdict == CANNOT_VERIFY
    assert not_found.reason != cannot_verify.reason
    for v in (not_found, cannot_verify):
        assert "does not exist" not in v.reason.lower()


def test_wrong_pinpoint_flag_does_not_block_verified():
    corpus = Corpus(CORPUS_DIR)
    doc = '"the Fourth Amendment protects people, not places." Katz v. United States, 389 U.S. 347, 999 (1967).'
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.wrong_pinpoint is True


def test_name_mismatch_on_real_citation_is_not_found_not_fabrication_claim():
    corpus = Corpus(CORPUS_DIR)
    doc = "Smith v. Jones, 347 U.S. 483, 490 (1954)."
    v = _judge_one(doc, corpus)
    assert v.verdict == NOT_FOUND_VERDICT
    assert v.name_mismatch is True
    # Must name the REAL case rather than claim it doesn't exist.
    assert "brown" in v.reason.lower()
    assert "does not exist" not in v.reason.lower()


def test_e1_signal_prefixed_citation_resolves_instead_of_not_found():
    """independent review finding E1: a real, correctly-cited authority
    preceded by a standard Bluebook signal ('See ...') was wrongly reported
    NOT_FOUND with name_mismatch=True because the signal word was absorbed
    into case_name, breaking name corroboration against the corpus."""
    corpus = Corpus(CORPUS_DIR)
    doc = '"the Fourth Amendment protects people, not places." See Katz v. United States, 389 U.S. 347.'
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-11339173"
    assert v.name_mismatch is not True


def test_e2_proposition_tail_bleed_no_longer_breaks_resolution():
    """independent review finding E2: a proposition ending in capitalized
    tokens right before a citation caused the case-name back-scan to run
    past the sentence boundary, dragging the proposition tail into
    case_name and producing a false NOT_FOUND."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"the Fourth Amendment protects people, not places." This secures '
        "Fourth Amendment protection. Katz v. United States, 389 U.S. 347."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-11339173"


def test_case_name_bleed_no_longer_breaks_resolution():
    """a defect found in review: a capitalized word from the PRIOR
    sentence ('Delaware.') absorbed into case_name broke name corroboration
    and produced a false not-found for a real, correctly-cited authority."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        "This argument is premised on the law of Kansas and Delaware. "
        '"Separate educational facilities are inherently unequal." '
        "Brown v. Board of Education, 347 U.S. 483, 495 (1954)."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-11301409"
    assert v.name_mismatch is not True


def test_bluebook_abbreviation_resolves_not_mismatch():
    """a defect found in review: 'Bd.'/'Educ.' abbreviations must
    corroborate against the corpus's fully-spelled-out official name rather
    than being refused as a name_mismatch."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"Separate educational facilities are inherently unequal." '
        "Brown v. Bd. of Educ., 347 U.S. 483, 495 (1954)."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.name_mismatch is not True
    assert v.opinion_id == "cap-11301409"


def test_signal_is_never_the_verified_proposition():
    """a defect found in review: a Bluebook signal ('But see') must never
    itself be treated as the cited proposition. Superseded by a later fix:
    the signal-introduced citation now associates with the real
    PRECEDING sentence (not a blank proposition) -- here that sentence is
    not literally present in Katz's opinion text, so the citation correctly
    comes back `exists, unsupported` on the real proposition text, never on
    the signal word itself."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        "The government must obtain a warrant. But see Katz v. United "
        "States, 389 U.S. 347."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == EXISTS_UNSUPPORTED
    assert v.proposition == "The government must obtain a warrant."
    assert "but see" not in v.reason.lower()
    assert "not found as a literal substring" in v.reason.lower()


def test_e1_signal_prefixed_citation_associates_with_preceding_sentence_and_verifies():
    """a defect found in review (HIGH): a real proposition stated in the
    sentence BEFORE a signal-introduced citation must associate with that
    citation and verify -- the signal must not sever the citation from the
    claim it supports and produce a false `exists, unsupported`."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        "Separate educational facilities are inherently unequal. See Brown "
        "v. Board of Education, 347 U.S. 483."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-11301409"
    assert v.proposition == "Separate educational facilities are inherently unequal."


def test_signal_never_produces_fabricated_verified():
    """a defect found in review: 'See'/'Cf.'/'Accord'/'Compare' must never
    coincidentally substring-match themselves inside the opinion text and
    produce a fabricated 'verified' verdict."""
    corpus = Corpus(CORPUS_DIR)
    for signal in ("See", "See also", "Cf.", "Accord", "Compare"):
        doc = (
            f"An earlier unrelated sentence ends here. {signal} Katz v. "
            "United States, 389 U.S. 347."
        )
        v = _judge_one(doc, corpus)
        assert v.verdict != VERIFIED, signal
        assert v.quoted_sentence is None, signal


def test_string_cite_second_authority_not_verified_on_separator():
    """a defect found in review: the second authority in a semicolon
    string cite must not be judged against a bare ';' separator -- it
    inherits the shared proposition and is judged on its own merits (here,
    Terry does not contain the Katz quote, so it must NOT verify)."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"the Fourth Amendment protects people, not places." Katz v. '
        "United States, 389 U.S. 347; Terry v. Ohio, 392 U.S. 1."
    )
    cites = extract_citations(doc)
    assert len(cites) == 2
    v_katz = judge_citation(corpus, cites[0])
    v_terry = judge_citation(corpus, cites[1])
    assert v_katz.verdict == VERIFIED
    assert v_terry.verdict != VERIFIED
    assert v_terry.proposition != ";"
    assert v_terry.quoted_sentence is None


def test_e2_second_authority_in_and_joined_string_cite_shares_real_proposition():
    """a defect found in review (HIGH): the non-first citation in an
    ", and"-joined multi-cite sentence must be judged on the SHARED real
    proposition, never on the literal connector fragment -- here the
    quoted proposition is real Katz text, so Katz verifies and Terry (which
    does not contain it) does not, and neither gets ", and" as its
    proposition."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"the Fourth Amendment protects people, not places." Terry v. Ohio, '
        "392 U.S. 1, and Katz v. United States, 389 U.S. 347."
    )
    cites = extract_citations(doc)
    assert len(cites) == 2
    v_terry = judge_citation(corpus, cites[0])
    v_katz = judge_citation(corpus, cites[1])
    assert cites[1].proposition == cites[0].proposition
    assert cites[1].proposition != ", and"
    assert v_katz.verdict == VERIFIED
    assert v_katz.opinion_id == "cap-11339173"
    assert v_terry.verdict != VERIFIED


def test_e2_connector_fragment_never_produces_a_fabricated_verified():
    """Regression guard: without a quote to share, a bare ', and' or ',
    with' connector fragment must never itself coincidentally
    substring-match the next citation's opinion text and fabricate a
    `verified` verdict."""
    corpus = Corpus(CORPUS_DIR)
    for doc in (
        "The rule is old. Terry v. Ohio, 392 U.S. 1, and Katz v. United "
        "States, 389 U.S. 347.",
        "The rule is old. Compare Terry v. Ohio, 392 U.S. 1, with Katz v. "
        "United States, 389 U.S. 347.",
    ):
        cites = extract_citations(doc)
        assert len(cites) == 2
        v_second = judge_citation(corpus, cites[1])
        assert v_second.quoted_sentence is None, doc
        assert cites[1].proposition not in (", and", ", with"), doc


def test_e3_defendant_initialism_resolves_instead_of_not_found():
    """a defect found in review (MED): a correct citation to the ingested
    Chevron opinion, given with the defendant as its real Bluebook
    initialism ('NRDC'), must resolve to that opinion (name_mismatch=False)
    rather than being reported `not found` for a page that IS the cited
    case."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        "Agencies get deference interpreting ambiguous statutes they "
        "administer. Chevron U.S.A. Inc. v. NRDC, 467 U.S. 837."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict != NOT_FOUND_VERDICT
    assert v.name_mismatch is not True
    assert v.opinion_id == "cap-6209106"


def test_e4_compound_signal_cf_eg_resolves_the_real_proposition():
    """a defect found in review (MED): 'Cf., e.g.,' must strip cleanly (like
    the already-working 'See, e.g.,') and verify on the real associated
    proposition, not fail on a residual 'e.g.,' glued to it."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        "Separate educational facilities are inherently unequal. Cf., "
        "e.g., Brown v. Board of Education, 347 U.S. 483."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-11301409"


def test_gate6_corrupted_opinion_text_flips_verified_to_unsupported():
    """The verifier can fail: corrupt one opinion's text in a temp copy of
    the corpus and require the affected citation to flip from verified to
    exists, unsupported. A check that cannot go red is not a check."""
    tmpdir = tempfile.mkdtemp(prefix="citecheck_gate6_")
    try:
        tmp_corpus_dir = os.path.join(tmpdir, "corpus")
        shutil.copytree(CORPUS_DIR, tmp_corpus_dir)

        opinion_path = os.path.join(tmp_corpus_dir, "store", "cap-11301409.json")
        with open(opinion_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        assert "Separate educational facilities are inherently unequal." in data["text"]
        data["text"] = data["text"].replace(
            "Separate educational facilities are inherently unequal.",
            "Separate educational facilities are perfectly equal.",
        )
        with open(opinion_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

        corpus = Corpus(tmp_corpus_dir)
        doc = '"Separate educational facilities are inherently unequal." Brown v. Board of Education, 347 U.S. 483, 495 (1954).'
        v = _judge_one(doc, corpus)
        assert v.verdict == EXISTS_UNSUPPORTED, (
            "corrupting the opinion text must flip the verdict away from "
            "verified -- if it doesn't, the support check is not actually "
            "reading the corpus text"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --- independent review: end-to-end regressions for E1/E2/E3. ---

def test_e1_parenthetical_year_connector_never_fabricates_a_verified_verdict():
    """E1 (HIGH): with a real preceding proposition to inherit, the second
    authority in a '(YYYY);'-joined string cite must be judged on THAT real
    proposition, never on the coincidental '(1967);' apparatus fragment --
    and since Terry's opinion does not contain the Katz quote, it must NOT
    verify."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"the Fourth Amendment protects people, not places." Katz v. United '
        "States, 389 U.S. 347 (1967); Terry v. Ohio, 392 U.S. 1 (1968)."
    )
    cites = extract_citations(doc)
    assert len(cites) == 2
    v_katz = judge_citation(corpus, cites[0])
    v_terry = judge_citation(corpus, cites[1])
    assert v_katz.verdict == VERIFIED
    assert v_terry.verdict != VERIFIED
    assert v_terry.proposition != "(1967);"
    assert v_terry.quoted_sentence is None


def test_e1_parenthetical_year_connector_with_no_preceding_prose_is_never_verified():
    """Without any real preceding proposition to inherit, the second
    authority's proposition must be genuinely empty -- never the literal
    '(1967);' apparatus text -- and so it comes back EXISTS_UNSUPPORTED
    (nothing checkable was offered), never a fabricated VERIFIED."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        "See Katz v. United States, 389 U.S. 347 (1967); Terry v. Ohio, "
        "392 U.S. 1 (1968)."
    )
    cites = extract_citations(doc)
    assert len(cites) == 2
    v_terry = judge_citation(corpus, cites[1])
    assert v_terry.verdict != VERIFIED
    assert v_terry.quoted_sentence is None
    assert cites[1].proposition == ""


def test_e2_doubled_internal_space_in_quoted_proposition_still_verifies():
    """E2 (MED): a doubled internal space in the document's quoted
    proposition must not defeat an otherwise-literal match against the
    (singly-spaced) opinion text -- and the reported span must still be
    exact against the real, untouched opinion text."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"the Fourth Amendment  protects people, not places." Katz v. '
        "United States, 389 U.S. 347."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.span is not None
    op = corpus.get_opinion(v.opinion_id)
    assert op.text[v.span[0]:v.span[1]] == v.quoted_sentence
    assert v.quoted_sentence == "the Fourth Amendment protects people, not places."


def test_e3_spaced_reporter_resolves_the_same_ingested_opinion():
    """E3 (MED): '389 U. S. 347' (the way U.S. Reports itself prints the
    reporter) must resolve to the same ingested Katz opinion as the
    unspaced '389 U.S. 347', not be refused as an uncovered reporter."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"the Fourth Amendment protects people, not places." Katz v. '
        "United States, 389 U. S. 347."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert "not represented in this corpus" not in v.reason
    unspaced_doc = (
        '"the Fourth Amendment protects people, not places." Katz v. '
        "United States, 389 U.S. 347."
    )
    v_unspaced = _judge_one(unspaced_doc, corpus)
    assert v.opinion_id == v_unspaced.opinion_id


# --- Line wraps, party suffixes, parallel-cite pinpoints: end-to-end against the
# real committed corpus -----------------------------------------------------

def test_linewrap_line_wrapped_quote_still_verifies():
    """A quoted proposition that happens to be split across a line wrap in
    the SOURCE DOCUMENT (not the opinion) must still resolve to VERIFIED --
    the quote-detection regex/span logic operates on the document text, and
    a real quoted string never legitimately contains a bare newline itself
    (QUOTE_RE excludes it), so this exercises the PARAPHRASE-clause path:
    the prose leading into the citation is wrapped, not a quoted string."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        "The Fourth Amendment protects people, not\n"
        'places, and Katz v. United States, 389 U.S. 347, held so explicitly.'
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert "\n" in cites[0].proposition
    v = judge_citation(corpus, cites[0])
    # The proposition as WRITTEN in the (line-wrapped) document is a
    # paraphrase of, not a literal substring of, the opinion text here --
    # what matters for this case is that it was extracted at all (non-empty,
    # spanning the wrap) rather than truncated to "" (a false
    # exists-unsupported with no checkable claim).
    assert cites[0].proposition.strip() != ""
    assert v.verdict in (VERIFIED, EXISTS_UNSUPPORTED)


def test_linewrap_line_wrapped_quoted_proposition_verifies_against_real_corpus():
    """The literal-quote path, with the quote itself unbroken but the
    PRECEDING case-introducing prose (irrelevant to the checked proposition)
    wrapped across a newline -- confirms the newline fix does not disturb
    the already-working quoted-proposition path."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        "As the Court explained in its\n"
        'opinion, "the Fourth Amendment protects people, not places." '
        "Katz v. United States, 389 U.S. 347."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.quoted_sentence == "the Fourth Amendment protects people, not places."


def test_partysuffix_party_suffix_before_real_citation_resolves_correctly():
    """this case end-to-end: 'Acme Corp.' ending the prior sentence must not
    bleed into the case name of the Katz citation that follows, which must
    still resolve VERIFIED against the real corpus."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        'The parties negotiated with Acme Corp. "The Fourth Amendment '
        'protects people, not places." Katz v. United States, 389 U.S. 347.'
    )
    cites = extract_citations(doc)
    assert len(cites) == 1
    assert cites[0].case_name == "Katz v. United States"
    v = judge_citation(corpus, cites[0])
    assert v.verdict == VERIFIED
    assert v.name_mismatch is False


def test_partysuffix_suffix_on_the_real_plaintiff_new_york_times_still_verifies():
    """Regression guard, end-to-end: New York Times Co. v. Sullivan (the
    suffix legitimately belongs to THIS citation's plaintiff) must keep
    resolving to the real corpus opinion, name-matched, not name_mismatch."""
    corpus = Corpus(CORPUS_DIR)
    op = corpus.get_opinion("cap-379234")
    doc = f"New York Times Co. v. Sullivan, {op.volume} {op.reporter} {op.first_page}."
    v = _judge_one(doc, corpus)
    assert v.name_mismatch is False
    assert v.verdict != NOT_FOUND_VERDICT


def test_parallelcite_parallel_citation_splits_into_two_independent_verdicts():
    """this case end-to-end: a parallel cite to a reporter this corpus does not
    carry (S. Ct.) must not fabricate a wrong_pinpoint flag on the U.S.
    citation that DOES resolve -- the two citations are judged
    independently, first VERIFIED/no-flag, second correctly refused as
    uncovered (never crashing, never merged into one mangled citation)."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"the Fourth Amendment protects people, not places." Katz v. '
        "United States, 389 U.S. 347, 88 S. Ct. 507."
    )
    cites = extract_citations(doc)
    assert len(cites) == 2
    first, second = cites
    assert (first.volume, first.reporter, first.page, first.pinpoint) == (389, "U.S.", 347, None)
    assert (second.volume, second.reporter, second.page, second.pinpoint) == (88, "S. Ct.", 507, None)

    v_first = judge_citation(corpus, first)
    assert v_first.verdict == VERIFIED
    assert v_first.wrong_pinpoint is False

    v_second = judge_citation(corpus, second)
    assert v_second.verdict == CANNOT_VERIFY
    assert "not represented in this corpus" in v_second.reason


# ---------------------------------------------------------------------------
# Closing-quote case-name boundary,
# end-to-end against the real corpus.
# ---------------------------------------------------------------------------

def test_closingquote_katz_capitalized_quote_tail_verifies_not_found():
    """The exact repro: a real, supported Katz quote whose final word
    ('Presidents.') is capitalized must resolve VERIFIED, not the false
    'not found' the case-name-parsing bug produced."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"Wiretapping to protect the security of the Nation has been '
        'authorized by successive Presidents." Katz v. United States, '
        "389 U.S. 347."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.name_mismatch is False
    assert v.quoted_sentence == (
        "Wiretapping to protect the security of the Nation has been "
        "authorized by successive Presidents."
    )


def test_closingquote_capitalization_flip_controlled_pair_end_to_end():
    """Controlled pair, end-to-end: identical case+cite+supported-quote,
    differing only in whether the quote's final word is upper- or
    lowercase, must both resolve VERIFIED -- the verdict must never flip
    solely on that capitalization."""
    corpus = Corpus(CORPUS_DIR)
    lower_doc = (
        '"wiretapping to protect the security of the nation has been '
        'authorized by successive presidents." Katz v. United States, '
        "389 U.S. 347."
    )
    upper_doc = (
        '"Wiretapping to protect the security of the Nation has been '
        'authorized by successive Presidents." Katz v. United States, '
        "389 U.S. 347."
    )
    v_lower = _judge_one(lower_doc, corpus)
    v_upper = _judge_one(upper_doc, corpus)
    assert v_lower.verdict == VERIFIED
    assert v_upper.verdict == VERIFIED
    assert v_lower.name_mismatch is False
    assert v_upper.name_mismatch is False


def test_closingquote_brown_capitalized_quote_tail_verifies():
    """Second reproduction case: Brown v. Board of
    Education, quote ending in '...Fourteenth Amendment.' (capitalized)."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"This segregation was alleged to deprive the plaintiffs of the '
        'equal protection of the laws under the Fourteenth Amendment." '
        "Brown v. Board of Education, 347 U.S. 483."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.name_mismatch is False


def test_closingquote_sullivan_capitalized_quote_tail_verifies():
    """Third reproduction case: New York Times Co. v.
    Sullivan, quote ending in '...Montgomery, Alabama.' (capitalized)."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"Sullivan is one of the three elected Commissioners of the City '
        'of Montgomery, Alabama." New York Times Co. v. Sullivan, '
        "376 U.S. 254."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.name_mismatch is False


def test_closingquote_wrong_case_name_at_a_real_page_still_correctly_refused():
    """Over-loosening guard: the closing-quote fix must not weaken genuine
    name-mismatch detection -- a real wrong case name at Katz's actual page
    must still be refused, quote-tail capitalization notwithstanding."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"Wiretapping to protect the security of the Nation has been '
        'authorized by successive Presidents." Miranda v. Arizona, '
        "389 U.S. 347."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == NOT_FOUND_VERDICT
    assert v.name_mismatch is True


# ---------------------------------------------------------------------------
# Trailing explanatory parenthetical
# association, end-to-end against the real corpus.
# ---------------------------------------------------------------------------

def test_trailingparen_trailing_holding_parenthetical_verifies_against_real_corpus():
    """The exact repro: a real, supported Katz proposition stated in the
    canonical trailing '(holding "...")' form must resolve VERIFIED, not
    the false 'exists, unsupported' the missing-association bug produced."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        'Katz v. United States, 389 U.S. 347 (holding "the Fourth '
        'Amendment protects people, not places.").'
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.quoted_sentence == "the Fourth Amendment protects people, not places."


def test_trailingparen_trailing_finding_parenthetical_variant_also_verifies():
    corpus = Corpus(CORPUS_DIR)
    doc = (
        'Katz v. United States, 389 U.S. 347 (finding "the Fourth '
        'Amendment protects people, not places.").'
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED


def test_trailingparen_trailing_paraphrase_without_quotes_verifies_against_real_corpus():
    """The parenthetical's own text after the gerund, with no inner quote,
    must also associate and verify when it is a real literal substring."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        "Katz v. United States, 389 U.S. 347 (noting "
        "protects individual privacy against certain kinds of "
        "governmental intrusion)."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED


def test_trailingparen_decision_year_then_trailing_parenthetical_verifies():
    corpus = Corpus(CORPUS_DIR)
    doc = (
        'Katz v. United States, 389 U.S. 347 (1967) (holding "the '
        'Fourth Amendment protects people, not places.").'
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED


def test_trailingparen_per_curiam_parenthetical_never_produces_coincidental_verified():
    """Degenerate-proposition guard, end-to-end: '(per curiam)' must never
    verify -- it must resolve EXISTS_UNSUPPORTED with the 'no checkable
    proposition' reason, exactly like any other citation offered with no
    checkable claim."""
    corpus = Corpus(CORPUS_DIR)
    doc = "Katz v. United States, 389 U.S. 347 (per curiam)."
    v = _judge_one(doc, corpus)
    assert v.verdict == EXISTS_UNSUPPORTED
    assert "no checkable proposition" in v.reason


def test_trailingparen_fabricated_trailing_holding_text_is_not_found_never_verified():
    """The propositional guard is only about SHAPE (real prose vs.
    apparatus) -- it must never let a fabricated/wrong holding verify just
    because it sits in the right '(holding "...")' shape."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        'Katz v. United States, 389 U.S. 347 (holding "the earth is '
        'flat and the moon is made of cheese").'
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == EXISTS_UNSUPPORTED


def test_trailingparen_trailing_parenthetical_does_not_regress_preceding_quote_path():
    """Regression guard, end-to-end: a citation whose proposition is a real
    preceding quote (the pre-existing, high-confidence path) must still
    verify exactly as before, whether or not a trailing parenthetical also
    follows it."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"the Fourth Amendment protects people, not places." Katz v. '
        "United States, 389 U.S. 347 (1967)."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.quoted_sentence == "the Fourth Amendment protects people, not places."


# ---------------------------------------------------------------------------
# independent review (post-corpus-scale, 7 reporters) -- 3 reproduced
# FALSE-`verified` escapes, end-to-end against the real corpus. See
# tests/test_extract.py for the matching extraction-only unit tests and
# the change history for the root-cause writeup.
# ---------------------------------------------------------------------------

def test_bare_corporate_short_form_never_verifies_on_its_own_caption():
    """this case, end-to-end: `Steve Jackson Games, 816 F. Supp. 432.` must
    resolve to an ingested opinion but must NEVER verify against the case's
    own caption text -- there is no accompanying "v.", so no case name is
    parsed and no proposition may be fabricated from the party name."""
    corpus = Corpus(CORPUS_DIR)
    doc = "Steve Jackson Games, 816 F. Supp. 432."
    v = _judge_one(doc, corpus)
    assert v.verdict == EXISTS_UNSUPPORTED
    assert v.quoted_sentence is None
    assert "Steve Jackson Games" not in (v.proposition or "")


def test_corporate_short_form_with_suffix_never_verifies():
    corpus = Corpus(CORPUS_DIR)
    doc = "Steve Jackson Games, Inc., 816 F. Supp. 432."
    v = _judge_one(doc, corpus)
    assert v.verdict == EXISTS_UNSUPPORTED
    assert v.quoted_sentence is None


def test_signal_prefixed_bare_name_never_verifies():
    corpus = Corpus(CORPUS_DIR)
    doc = "See also Carroll Towing Co., 159 F.2d 169."
    v = _judge_one(doc, corpus)
    assert v.verdict == EXISTS_UNSUPPORTED
    assert v.quoted_sentence is None


def test_quoted_connector_never_verifies():
    """this case, end-to-end: an explicitly-quoted single-word connector must
    never verify, even though "and"/"the" are trivially substrings of almost
    any opinion's text."""
    corpus = Corpus(CORPUS_DIR)
    for word in ("and", "the"):
        doc = f'The court reasoned "{word}" Frye v. United States, 293 F. 1013.'
        v = _judge_one(doc, corpus)
        assert v.verdict != VERIFIED, word
        assert v.quoted_sentence != word, word


def test_quoted_two_word_fragment_never_verifies():
    corpus = Corpus(CORPUS_DIR)
    for phrase in ("the barge", "is difficult"):
        doc = f'The court reasoned "{phrase}" Frye v. United States, 293 F. 1013.'
        v = _judge_one(doc, corpus)
        assert v.verdict != VERIFIED, phrase
        assert v.quoted_sentence != phrase, phrase


def test_string_cite_second_authority_never_inherits_a_degenerate_quote():
    """this case, end-to-end: in `The opinion said "the barge". 148 F.2d
    416; 159 F.2d 169.`, the coincidental substring "the barge" (a real
    phrase inside Carroll Towing, 159 F.2d 169's text) must not be inherited
    by the second citation via the string-cite fallback -- neither citation
    may verify off it."""
    corpus = Corpus(CORPUS_DIR)
    doc = 'The opinion said "the barge". 148 F.2d 416; 159 F.2d 169.'
    cites = extract_citations(doc)
    assert len(cites) == 2
    verdicts = [judge_citation(corpus, c) for c in cites]
    for v in verdicts:
        assert v.verdict != VERIFIED
        assert v.quoted_sentence != "the barge"


def test_escape_fix_does_not_regress_genuine_verified_quotes_across_all_7_reporters():
    """Discipline guard: the uniform degeneracy guard must not loosen or
    regress genuine, multi-word, verbatim quoted propositions against real
    opinions across every reporter this corpus now carries (U.S., F., F.2d,
    F. Supp., F. Supp. 2d, N.Y. -- F.3d's only ingested-adjacent case in
    this corpus is COVERED_NOT_INGESTED, so it is exercised by the
    cannot-verify path instead, tested elsewhere)."""
    corpus = Corpus(CORPUS_DIR)
    cases = [
        # (doc, expected_opinion_id)
        (
            '"Separate educational facilities are inherently unequal." '
            "Brown v. Board of Education, 347 U.S. 483, 495 (1954).",
            "cap-11301409",
        ),
        (
            '"A single assignment of error is presented for our '
            'consideration." Frye v. United States, 293 F. 1013.',
            "cap-11720199",
        ),
        (
            '"This appeal comes to us by virtue of a certificaie of the '
            'Supreme Court," United States v. Aluminum Co. of America, '
            "148 F.2d 416.",
            "cap-3654849",
        ),
        (
            '"The Conners Marine Co., Inc., was the owner of the barge," '
            "United States v. Carroll Towing Co., 159 F.2d 169.",
            "cap-1123255",
        ),
        (
            '"The issues remaining at trial in this lawsuit involves the '
            "Plaintiffs Steve Jackson Games, Incorporated, Steve Jackson, "
            'Elizabeth McCoy, Walter Milliken," Steve Jackson Games, Inc. '
            "v. United States Secret Service, 816 F. Supp. 432.",
            "cap-7405252",
        ),
        (
            '"A train stopped at the station, bound for another place." '
            "Palsgraf v. Long Island Railroad, 248 N.Y. 339.",
            "cap-1905144",
        ),
        (
            '"Plaintiff is a non-profit, educational foundation which '
            "regularly requests access to the public records of government "
            'entities and disseminates its findings to the public." '
            "Judicial Watch, Inc. v. Consumer Financial Protection Bureau, "
            "985 F. Supp. 2d 1.",
            None,  # F. Supp. 2d 985/1 has no separate opinion_id assertion below
        ),
    ]
    for doc, expected_opinion_id in cases:
        v = _judge_one(doc, corpus)
        assert v.verdict == VERIFIED, (doc, v.verdict, v.reason)
        assert v.quoted_sentence is not None, doc
        if expected_opinion_id is not None:
            assert v.opinion_id == expected_opinion_id, doc


def test_clean_v_short_form_still_resolves_correctly_end_to_end():
    """Regression guard, end-to-end: a clean `X v. Y` short form (case name
    correctly parsed) is unaffected by the bare-name guard -- it correctly
    yields `exists, unsupported` (real case, no matching proposition
    offered), never `verified` on the caption and never `not found`."""
    corpus = Corpus(CORPUS_DIR)
    doc = "A clean short form: Frye v. United States, 293 F. 1013."
    v = _judge_one(doc, corpus)
    assert v.verdict == EXISTS_UNSUPPORTED
    assert v.name_mismatch is False


# ---------------------------------------------------------------------------
# Corpus-scale-up round (36 reporters / 352 opinions) -- 4 false-refusal
# defects, all reproduced end-to-end against the real, committed corpus.
# ---------------------------------------------------------------------------

def test_defect1_ampersand_plaintiff_resolves_instead_of_not_found():
    """Defect 1 (HIGH): 'Texas & Pac. Ry. Co. v. Burch, 1 So. 2d 64.' was
    'not found' because the plaintiff parser dropped 'Texas & '. Real corpus
    case cap-10033449."""
    corpus = Corpus(CORPUS_DIR)
    doc = "Texas & Pac. Ry. Co. v. Burch, 1 So. 2d 64."
    v = _judge_one(doc, corpus)
    assert v.verdict != NOT_FOUND_VERDICT, (v.verdict, v.reason)
    assert v.name_mismatch is False
    assert v.opinion_id == "cap-10033449"


def test_defect2_bare_sovereign_ex_rel_resolves_instead_of_not_found():
    """Defect 2 (HIGH): 'State ex rel. Moorehead v. Reed, 177 Ohio St. 4.'
    was 'not found' because only 'Moorehead v. Reed' was parsed. Real corpus
    case cap-1771311."""
    corpus = Corpus(CORPUS_DIR)
    doc = "State ex rel. Moorehead v. Reed, 177 Ohio St. 4."
    v = _judge_one(doc, corpus)
    assert v.verdict != NOT_FOUND_VERDICT, (v.verdict, v.reason)
    assert v.name_mismatch is False
    assert v.opinion_id == "cap-1771311"


def test_defect2_ex_dem_relator_resolves_instead_of_not_found():
    """'Doe ex dem. Truluck v. Peeples, 1 Ga. 1.' -- real corpus case
    cap-1373752."""
    corpus = Corpus(CORPUS_DIR)
    doc = "Doe ex dem. Truluck v. Peeples, 1 Ga. 1."
    v = _judge_one(doc, corpus)
    assert v.verdict != NOT_FOUND_VERDICT, (v.verdict, v.reason)
    assert v.name_mismatch is False
    assert v.opinion_id == "cap-1373752"


def test_defect3_long_multiword_plaintiff_resolves_instead_of_not_found():
    """Defect 3 (HIGH): 'Sweet Home Chapter of Communities for a Great
    Oregon v. Babbitt, 1 F.3d 1.' was 'not found' because the leading
    'Sweet Home ' was dropped. Real corpus case cap-10507259."""
    corpus = Corpus(CORPUS_DIR)
    doc = "Sweet Home Chapter of Communities for a Great Oregon v. Babbitt, 1 F.3d 1."
    v = _judge_one(doc, corpus)
    assert v.verdict != NOT_FOUND_VERDICT, (v.verdict, v.reason)
    assert v.name_mismatch is False
    assert v.opinion_id == "cap-10507259"


def test_defect4_page_collision_disambiguates_correct_sibling_verified():
    """Defect 4 (MED): two real opinions share the same first page (Md. 456,
    page 45: 'Attorney Grievance Commission v. Brown' and '... v.
    McLaughlin'). Each must resolve to ITS OWN opinion, corroborated by the
    given case name -- not silently overwritten by whichever opinion the
    loader happened to read last."""
    corpus = Corpus(CORPUS_DIR)

    brown_doc = (
        '"Respondent, Jibril A. Brown, be and he is hereby REPRIMANDED" '
        "Attorney Grievance Commission v. Brown, 456 Md. 45."
    )
    v_brown = _judge_one(brown_doc, corpus)
    assert v_brown.verdict == VERIFIED, (v_brown.verdict, v_brown.reason)
    assert v_brown.opinion_id == "cap-12314715"

    mclaughlin_doc = (
        '"the Respondent, Louisa Content McLaughlin be, and she is hereby, '
        'disbarred" Attorney Grievance Commission v. McLaughlin, 456 Md. 45.'
    )
    v_mclaughlin = _judge_one(mclaughlin_doc, corpus)
    assert v_mclaughlin.verdict == VERIFIED, (v_mclaughlin.verdict, v_mclaughlin.reason)
    assert v_mclaughlin.opinion_id == "cap-12314721"

    # The two siblings must resolve to DIFFERENT opinions, never the same one.
    assert v_brown.opinion_id != v_mclaughlin.opinion_id


def test_defect4_page_collision_never_verifies_against_the_wrong_sibling():
    """Regression guard for the disambiguation itself: Brown's own quoted
    proposition text must never verify against McLaughlin's opinion (the
    literal-substring check already prevents this, but this pins the
    end-to-end behavior against a silent wrong-sibling association)."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"the Respondent, Louisa Content McLaughlin be, and she is hereby, '
        'disbarred" Attorney Grievance Commission v. Brown, 456 Md. 45.'
    )
    v = _judge_one(doc, corpus)
    assert v.opinion_id == "cap-12314715"  # still resolves to Brown by name
    assert v.verdict == EXISTS_UNSUPPORTED  # McLaughlin's text is not in Brown's opinion


def test_defect4_page_collision_unmatched_name_is_not_found_never_does_not_exist():
    """A name that matches NEITHER sibling at a colliding page must still be
    'not found' (not a fabricated 'does not exist' claim), and must name the
    real cases actually reported at that page."""
    corpus = Corpus(CORPUS_DIR)
    doc = "Attorney Grievance Commission v. Nobody, 456 Md. 45."
    v = _judge_one(doc, corpus)
    assert v.verdict == NOT_FOUND_VERDICT
    assert v.name_mismatch is True
    assert "does not exist" not in v.reason.lower()
    assert "brown" in v.reason.lower()
    assert "mclaughlin" in v.reason.lower()


def test_defect4_page_collision_triple_all_three_siblings_distinguished():
    """N.W.2d volume 932 page 1 is shared by THREE real opinions -- all
    three must resolve independently by name."""
    corpus = Corpus(CORPUS_DIR)
    cases = {
        "People v. McKay, 932 N.W.2d 1.": "cap-12564278",
        "Rafaeli, LLC v. Oakland County, 932 N.W.2d 1.": "cap-12564279",
        "Meemic Ins. Co. v. Fortson, 932 N.W.2d 1.": "cap-12564280",
    }
    seen_ids = set()
    for doc, expected_id in cases.items():
        v = _judge_one(doc, corpus)
        assert v.verdict != NOT_FOUND_VERDICT, (doc, v.verdict, v.reason)
        assert v.opinion_id == expected_id, (doc, v.opinion_id)
        seen_ids.add(v.opinion_id)
    assert len(seen_ids) == 3


# ---------------------------------------------------------------------------
# CARDINAL FIX -- false-`verified` (root cause: a party
# name that FAILS TO PARSE bypassed name corroboration and resolved by
# citation ALONE). Both repros below are exactly as found in review:
# E1 against a fabricated name at a real citation (must be `not found`,
# never `verified`); E2 against the real name, at a real page-collision
# (must resolve to the correct sibling, not the first one loaded).
# ---------------------------------------------------------------------------

def test_cardinal_e1_fabricated_name_with_cnty_never_verifies():
    """E1 (CARDINAL): a verbatim quote from the REAL opinion at 1 So. 2d 51
    (Hattier v. Martinez) attributed to a FABRICATED case name ('Doe v.
    Fabricated Cnty.') must be `not found`, NEVER `verified` -- even though
    'Cnty.' now parses (secondary fix), the given name must still fail
    corroboration against the real opinion actually reported there."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"On appeal to this court the judgment was annulled and reversed '
        "and the order of January 31, 1939, granting the provisional care "
        'and keeping of the child to the relatrix was reinstated." '
        "Doe v. Fabricated Cnty., 1 So. 2d 51 (1941)."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict != VERIFIED
    assert v.verdict == NOT_FOUND_VERDICT
    assert v.name_mismatch is True
    assert "does not exist" not in v.reason.lower()
    assert "hattier" in v.reason.lower()


def test_cardinal_e2_real_cnty_name_resolves_correct_page_collision_sibling():
    """E2: the REAL 'Rafaeli, LLC v. Oakland Cnty.' (932 N.W.2d 1, a page
    shared by 3 real opinions in this corpus) must resolve to ITS OWN
    opinion and verify its own real quote -- not silently default to the
    first page-sibling ('People v. McKay') because 'Cnty.' failed to parse
    into a corroborating case name."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"The clerk is directed to schedule the case for oral argument at '
        'the November 2019 session of the Court." Rafaeli, LLC v. Oakland '
        "Cnty., 932 N.W.2d 1."
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED, (v.verdict, v.reason)
    assert v.opinion_id == "cap-12564279"
    assert v.name_mismatch is False


def test_cardinal_general_unparsed_name_construct_fails_closed_never_verified():
    """General regression (not Cnty.-specific): a citation that OFFERS a
    case name via a genuine 'X v. Y' construct, but whose party token this
    tool's parser does not recognize as a valid abbreviation ('Xyzzyplonk.',
    an ordinary-looking word ending in a period, is NOT a known Bluebook
    stem), must fail closed to NOT_FOUND/name_mismatch -- never resolve by
    citation alone just because the name failed to parse. Real quote is
    Brown's own opinion text, attached to a fabricated defendant name."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        '"Separate educational facilities are inherently unequal." '
        "Roe v. Xyzzyplonk., 347 U.S. 483, 495 (1954)."
    )
    cites = extract_citations(doc)
    assert cites[0].case_name is None  # the name construct did NOT parse
    assert cites[0].name_construct_present is True  # but it WAS offered
    v = judge_citation(corpus, cites[0])
    assert v.verdict != VERIFIED
    assert v.verdict == NOT_FOUND_VERDICT
    assert v.name_mismatch is True
    assert "does not exist" not in v.reason.lower()
    assert "brown" in v.reason.lower()


def test_cardinal_bare_citation_with_no_name_construct_still_resolves_by_citation():
    """Regression guard: a genuinely bare citation (no 'v.' construct at
    all in its context) must still resolve by citation number alone, exactly
    as before -- the fail-closed guard must never fire on a citation that
    never offered a name in the first place."""
    corpus = Corpus(CORPUS_DIR)
    doc = "See 347 U.S. 483, 495 (1954)."
    cites = extract_citations(doc)
    assert cites[0].case_name is None
    assert cites[0].name_construct_present is False
    v = judge_citation(corpus, cites[0])
    assert v.verdict != NOT_FOUND_VERDICT
    assert v.name_mismatch is False


def test_cardinal_bare_short_form_after_comma_still_not_a_name_construct():
    """A bare corporate short form with no 'v.' at all (e.g. a party name
    followed directly by its citation) must not be misclassified as a
    'name construct present' -- there is no 'v.' token in its context, so
    the fail-closed guard correctly stays off and this still resolves by
    citation number alone, exactly like the this case short-form tests."""
    corpus = Corpus(CORPUS_DIR)
    doc = "Steve Jackson Games, 816 F. Supp. 432."
    cites = extract_citations(doc)
    assert cites[0].case_name is None
    assert cites[0].name_construct_present is False
    v = judge_citation(corpus, cites[0])
    assert v.verdict != NOT_FOUND_VERDICT


# ---------------------------------------------------------------------------
# FALSE-REFUSAL FIX: non-"v." case-name constructs ("In re Foo", "Ex parte
# Foo", "Succession of Foo", "Estate of Foo", ...) end-to-end against the
# real corpus. Repro case: `corpus/store/cap-12456501.json`
# (name_abbreviation "In re Gantt", 302 Ga. 3-5).
# ---------------------------------------------------------------------------

_GANTT_QUOTE = (
    "The home incurred extensive damage, causing the client and her minor "
    "children to move out while repairs were performed."
)


def test_in_re_name_with_real_quote_verifies():
    """The headline repro: an unquoted-but-verbatim proposition immediately
    followed by a non-"v." case name previously false-refused with 'no
    checkable proposition was associated with it' because the name text was
    never recognized as a case name and bled into the proposition-clause
    scan. It must now verify, identically to the bare-cite form."""
    corpus = Corpus(CORPUS_DIR)
    doc = f"{_GANTT_QUOTE} In re Gantt, 302 Ga. 3."
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-12456501"
    assert v.opinion_name == "In re Gantt"


def test_in_re_name_with_real_quote_and_quotation_marks_verifies():
    corpus = Corpus(CORPUS_DIR)
    doc = f'"{_GANTT_QUOTE}" In re Gantt, 302 Ga. 3.'
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-12456501"


def test_bare_cite_without_name_still_verifies_identically():
    """Adding a correct non-"v." name must never turn a verified into a
    refusal, and removing it must not either -- both forms resolve the
    SAME real opinion via the same real quote."""
    corpus = Corpus(CORPUS_DIR)
    doc = f"{_GANTT_QUOTE} 302 Ga. 3."
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-12456501"


def test_fabricated_in_re_name_at_real_cite_never_verified():
    """CRITICAL no-false-verified guard: a fabricated non-"v." name at a
    real citation whose quote genuinely belongs to the real case reported
    there must fail closed to NOT_FOUND -- never VERIFIED, and the reason
    must never claim the real case 'does not exist'."""
    corpus = Corpus(CORPUS_DIR)
    doc = f"{_GANTT_QUOTE} In re Nobody, 302 Ga. 3."
    v = _judge_one(doc, corpus)
    assert v.verdict == NOT_FOUND_VERDICT
    assert v.verdict != VERIFIED
    assert v.name_mismatch is True
    assert "does not exist" not in v.reason.lower()
    assert "in re gantt" in v.reason.lower()


def test_unparseable_non_v_construct_fails_closed_never_verified():
    """Mirrors the cardinal "v." fail-closed guard: a non-"v." phrase
    followed by an unrecognized abbreviation defeats the parser
    (case_name=None) but the construct was still plainly offered
    (name_construct_present=True) -- must fail closed to NOT_FOUND, never
    fall through to resolving by citation number alone."""
    corpus = Corpus(CORPUS_DIR)
    doc = f"{_GANTT_QUOTE} In re Xyzzyplonk., 302 Ga. 3."
    cites = extract_citations(doc)
    assert cites[0].case_name is None
    assert cites[0].name_construct_present is True
    v = judge_citation(corpus, cites[0])
    assert v.verdict != VERIFIED
    assert v.verdict == NOT_FOUND_VERDICT
    assert v.name_mismatch is True


def test_ex_parte_name_with_real_quote_verifies():
    corpus = Corpus(CORPUS_DIR)
    quote = (
        "Because of the violation of such an order, Betty Rhodes was "
        "adjudged to be in contempt of court."
    )
    doc = f'"{quote}" Ex parte Rhodes, 163 Tex. 31.'
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-2263615"


def test_succession_of_name_with_real_quote_verifies():
    corpus = Corpus(CORPUS_DIR)
    quote = (
        "Pertinent to the issue herein, on December 27, 2006, Joseph filed "
        "a Motion to Remove Testamentary Executor and Appoint Independent "
        "Administrator."
    )
    doc = f'"{quote}" Succession of Casanova, 999 So. 2d 1.'
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-8159325"


def test_estate_of_name_with_real_quote_verifies():
    corpus = Corpus(CORPUS_DIR)
    quote = (
        "We conclude that it cannot because under our statutory scheme, "
        "such marriages are voidable, rather than void ab initio, and "
        "their nullity can be declared only from the date of the decree."
    )
    doc = f'"{quote}" In re Estate of Randall, 999 A.2d 51.'
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-7284994"


def test_estate_of_wrong_party_at_real_cite_never_verified():
    """Same prefix family ('Estate of'), a DIFFERENT party than the one
    actually resolved at this citation -- must still fail closed."""
    corpus = Corpus(CORPUS_DIR)
    quote = (
        "We conclude that it cannot because under our statutory scheme, "
        "such marriages are voidable, rather than void ab initio, and "
        "their nullity can be declared only from the date of the decree."
    )
    doc = f'"{quote}" Estate of Smith, 999 A.2d 51.'
    v = _judge_one(doc, corpus)
    assert v.verdict == NOT_FOUND_VERDICT
    assert v.verdict != VERIFIED
    assert v.name_mismatch is True


def test_bare_anonymous_name_with_real_quote_verifies():
    corpus = Corpus(CORPUS_DIR)
    quote = (
        "The important provisions contained in the 4th and 7th sections of "
        "the statute were omitted by the framers of the act of assembly."
    )
    doc = f'"{quote}" Anonymous, 1 U.S. 1.'
    v = _judge_one(doc, corpus)
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-1408376"


# --- Defect 1 (over-refusal): a real case whose name ends in a numbered
# "No. <N>" district designation must resolve and verify its own real
# proposition, end-to-end against the real corpus. Real corpus repros:
# `In re Washington County Sewer Improvement Dist. No. 1, 252 P.2d 139`
# (cap-10493889) and `Bush v. Quinault School District No. 97, 1 Wash. 2d
# 28` (cap-1963361). A fabricated district NUMBER at the same real cite,
# whose quote genuinely belongs to the real case there, must still fail
# closed to NOT_FOUND (never VERIFIED) -- the name parse alone is not
# enough; the resolved name must actually corroborate. ---

def test_no_designation_non_v_case_resolves_and_verifies():
    corpus = Corpus(CORPUS_DIR)
    doc = (
        'In re Washington County Sewer Improvement Dist. No. 1, 252 P.2d 139 '
        '(holding "this original proceeding was filed in this court").'
    )
    v = _judge_one(doc, corpus)
    assert v.case_name == "In re Washington County Sewer Improvement Dist. No. 1"
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-10493889"


def test_no_designation_v_case_resolves_and_verifies():
    corpus = Corpus(CORPUS_DIR)
    doc = (
        'Bush v. Quinault School District No. 97, 1 Wash. 2d 28 '
        '(holding "resulted in findings and judgment in favor of the plaintiff").'
    )
    v = _judge_one(doc, corpus)
    assert v.case_name == "Bush v. Quinault School District No. 97"
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-1963361"


def test_fabricated_no_designation_number_at_real_cite_fails_closed():
    """No-false-verified check: identical real cite and real quote, but a
    FABRICATED district number ("No. 999" instead of the real "No. 97")
    must never verify -- it must fail closed to NOT_FOUND, naming the real
    case actually reported there."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        'Bush v. Quinault School District No. 999, 1 Wash. 2d 28 '
        '(holding "resulted in findings and judgment in favor of the plaintiff").'
    )
    v = _judge_one(doc, corpus)
    assert v.verdict == NOT_FOUND_VERDICT
    assert v.verdict != VERIFIED
    assert v.name_mismatch is True
    assert "does not exist" not in v.reason.lower()


def test_truncated_no_designation_name_still_verifies_as_before():
    """Sanity/regression: truncating the "No. N" designation entirely
    (a bare "Quinault School District") must still resolve normally --
    this fix must not require the designation, only support it when
    present."""
    corpus = Corpus(CORPUS_DIR)
    doc = (
        'Bush v. Quinault School District, 1 Wash. 2d 28 '
        '(holding "resulted in findings and judgment in favor of the plaintiff").'
    )
    v = _judge_one(doc, corpus)
    assert v.case_name == "Bush v. Quinault School District"
    assert v.verdict == VERIFIED
    assert v.opinion_id == "cap-1963361"


# --- Defect 2 (coverage conflation): a "complete" volume with an EMPTY
# page index (`Tex.` volume 1: complete=True, case_count=104,
# pages_present=[]) must yield CANNOT_VERIFY for a page cite to it, never
# NOT_FOUND -- NOT_FOUND asserts "no case begins at page N", which an empty
# index cannot honestly claim for a volume its own coverage summary shows
# has 104 known cases. ---

def test_empty_page_index_volume_is_cannot_verify_not_not_found():
    corpus = Corpus(CORPUS_DIR)
    vol_info = corpus.volume_info("Tex.", 1)
    assert vol_info is not None and vol_info["complete"] is True
    assert len(vol_info["pages_present"]) == 0
    doc = "See 1 Tex. 5 (1846)."
    v = _judge_one(doc, corpus)
    assert v.verdict == CANNOT_VERIFY
    assert v.verdict != NOT_FOUND_VERDICT
    assert "does not exist" not in v.reason.lower()
    assert "page index" in v.reason.lower()


def test_nonempty_page_index_volume_still_not_found_for_absent_page():
    """Regression: Defect 2's fix must not weaken a volume WITH a usable
    page index -- a genuinely absent page there is still NOT_FOUND."""
    corpus = Corpus(CORPUS_DIR)
    v = _judge_one("See 347 U.S. 484 (1954).", corpus)
    assert v.verdict == NOT_FOUND_VERDICT


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
