import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from citecheck.support import normalize, find_support


def test_normalize_is_length_preserving():
    samples = [
        "hello world",
        "curly ‘quotes’ and “double”",
        "Tabs\tand\nnewlines",
        "MiXeD CaSe",
    ]
    for s in samples:
        assert len(normalize(s)) == len(s)


def test_find_support_exact_match():
    text = "The quick brown fox jumps over the lazy dog."
    span = find_support("brown fox jumps", text)
    assert span is not None
    start, end = span
    assert text[start:end] == "brown fox jumps"


def test_find_support_case_and_quote_insensitive():
    text = 'She said, “the law is clear” today.'
    span = find_support('THE LAW IS CLEAR', text)
    assert span is not None


def test_find_support_misquote_does_not_match():
    text = "The Fourth Amendment protects people, not places."
    assert find_support("The Fourth Amendment protects places, not people.", text) is None


def test_find_support_empty_proposition_is_none():
    assert find_support("", "some text") is None
    assert find_support("   ", "some text") is None


# --- independent review, E2 (MED): a doubled/irregular internal
# whitespace run in the PROPOSITION must not defeat an otherwise-literal
# match against opinion text that has a single space in the same spot (or
# vice versa) -- whitespace runs are equivalent for matching purposes. The
# delicate part: the reported span must still be EXACT against the
# untouched ORIGINAL opinion text, never fabricated/approximate. ---

def test_find_support_collapses_doubled_internal_space_in_proposition():
    text = "The Fourth Amendment protects people, not places."
    span = find_support("The Fourth Amendment  protects people, not places.", text)
    assert span is not None
    start, end = span
    # Span is exact against the ORIGINAL (single-spaced) opinion text.
    assert text[start:end] == "The Fourth Amendment protects people, not places."


def test_find_support_collapses_doubled_internal_space_in_opinion_text():
    """Symmetric case: the OPINION text has the doubled space, the
    proposition (as quoted by the document) has a single space."""
    text = "The Fourth Amendment  protects people, not places."
    span = find_support("The Fourth Amendment protects people, not places.", text)
    assert span is not None
    start, end = span
    # The returned span must slice the ORIGINAL text literally -- including
    # the real doubled space that is actually there -- never a normalized
    # copy of it.
    assert text[start:end] == "The Fourth Amendment  protects people, not places."


def test_find_support_span_exact_after_whitespace_collapse_offset_map():
    """The delicate offset-map property: matching happens on a COLLAPSED
    canonical string, but the returned (start, end) must map back to exact
    original-text offsets, not canonical-string offsets, even when a run
    of 3+ whitespace characters sits inside the matched region."""
    text = "Fourth    Amendment protects people."
    span = find_support("Fourth Amendment protects people.", text)
    assert span is not None
    start, end = span
    assert text[start:end] == "Fourth    Amendment protects people."
    assert end - start == len("Fourth    Amendment protects people.")


def test_find_support_single_space_tab_and_newline_all_still_match():
    """Regression guard: the whitespace-collapsing fix must not disturb the
    pre-existing behavior for a SINGLE whitespace character of any kind in
    the same spot (space, tab, or a lone newline) -- these already worked
    under plain normalize() and must keep working."""
    text = "The Fourth Amendment protects people, not places."
    for prop in (
        "The Fourth Amendment protects people, not places.",
        "The Fourth\tAmendment protects people, not places.",
        "The Fourth\nAmendment protects people, not places.",
    ):
        span = find_support(prop, text)
        assert span is not None, prop
        start, end = span
        assert text[start:end] == text


def test_find_support_whitespace_collapse_never_matches_across_a_real_word_difference():
    """Whitespace-run collapsing must not become fuzzy word matching -- a
    genuinely different word still fails to match regardless of spacing."""
    text = "The Fourth Amendment protects people, not places."
    assert find_support("The Fourth  Amendment protects  citizens, not places.", text) is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
