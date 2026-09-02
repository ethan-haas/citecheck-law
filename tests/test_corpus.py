"""Corpus loader + resolve() are tested independently of extraction/verdict
(mirrors the specification gate-3 independence discipline used elsewhere): these
tests build a small, synthetic corpus directory on disk (never mutating the
real committed corpus/) so the multi-opinion-per-page and defensive-loader
behaviors are pinned in isolation from real corpus data quirks.

Corpus-scale-up round (36 reporters / 352 opinions) -- false-refusal
escape 4: a (reporter, volume, first_page) key can legitimately be shared
by more than one real, distinct opinion (e.g. two per-curiam order entries
filed on the same page of the same volume). The old loader silently kept
only the LAST opinion loaded at each key, so a citation to any DISCARDED
sibling -- even with its own, correctly-parsed case name -- fell through to
a spurious name_mismatch/NOT_FOUND. Fixed by storing a LIST of opinions per
key and disambiguating by case-name corroboration in `Corpus.resolve`.

Also covers the defensive loader guard: a store doc whose `first_page` is
not an int must be skipped, never crash the whole corpus load.
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from citecheck.corpus import Corpus, INGESTED, NOT_FOUND, COVERED_NOT_INGESTED, NOT_COVERED


def _write_index(corpus_dir, reporter, volume, pages_present, complete=True, case_count=None):
    index = {
        "source": "synthetic test fixture",
        "retrieved": "2026-01-01",
        "reporters": {
            reporter: {
                "volumes": {
                    str(volume): {
                        "complete": complete,
                        "case_count": case_count if case_count is not None else len(pages_present),
                        "pages_present": pages_present,
                        "source_url": "https://example.invalid/",
                        "retrieved": "2026-01-01",
                    }
                }
            }
        },
    }
    with open(os.path.join(corpus_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh)


def _write_opinion(corpus_dir, opinion_id, name, name_abbreviation, reporter, volume,
                    first_page, last_page, text, **extra):
    doc = {
        "opinion_id": opinion_id,
        "name": name,
        "name_abbreviation": name_abbreviation,
        "reporter": reporter,
        "volume": volume,
        "first_page": first_page,
        "last_page": last_page,
        "official_citation": "",
        "court": "",
        "decision_date": "",
        "text": text,
        "source_url": "",
        "retrieved": "",
    }
    doc.update(extra)
    with open(os.path.join(corpus_dir, "store", f"{opinion_id}.json"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh)


class _TempCorpus:
    """Builds a fresh, empty synthetic corpus/ directory (index.json +
    store/) for one test, and cleans it up afterward."""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "corpus")
        os.makedirs(os.path.join(self.dir, "store"))
        return self.dir

    def __exit__(self, *exc):
        shutil.rmtree(self.tmp, ignore_errors=True)


def test_single_opinion_per_page_resolves_as_before():
    with _TempCorpus() as d:
        _write_index(d, "T.", 1, [10])
        _write_opinion(d, "op-1", "Alpha v. Beta", "Alpha v. Beta", "T.", 1, 10, 12, "some opinion text")
        corpus = Corpus(d)
        res = corpus.resolve("T.", 1, 10, "Alpha v. Beta")
        assert res.status == INGESTED
        assert res.opinion["opinion_id"] == "op-1"


def test_multiple_opinions_same_page_disambiguated_by_given_name():
    with _TempCorpus() as d:
        _write_index(d, "T.", 1, [10], case_count=2)
        _write_opinion(d, "op-1", "Alpha v. Beta", "Alpha v. Beta", "T.", 1, 10, 10, "alpha text")
        _write_opinion(d, "op-2", "Gamma v. Delta", "Gamma v. Delta", "T.", 1, 10, 10, "gamma text")
        corpus = Corpus(d)

        res_alpha = corpus.resolve("T.", 1, 10, "Alpha v. Beta")
        assert res_alpha.status == INGESTED
        assert res_alpha.opinion["opinion_id"] == "op-1"

        res_gamma = corpus.resolve("T.", 1, 10, "Gamma v. Delta")
        assert res_gamma.status == INGESTED
        assert res_gamma.opinion["opinion_id"] == "op-2"


def test_multiple_opinions_same_page_unmatched_name_is_not_found_never_does_not_exist():
    with _TempCorpus() as d:
        _write_index(d, "T.", 1, [10], case_count=2)
        _write_opinion(d, "op-1", "Alpha v. Beta", "Alpha v. Beta", "T.", 1, 10, 10, "alpha text")
        _write_opinion(d, "op-2", "Gamma v. Delta", "Gamma v. Delta", "T.", 1, 10, 10, "gamma text")
        corpus = Corpus(d)

        res = corpus.resolve("T.", 1, 10, "Nobody v. Nothing")
        assert res.status == NOT_FOUND
        assert res.name_mismatch is True
        assert "does not exist" not in res.reason.lower()
        assert "alpha" in res.reason.lower()
        assert "gamma" in res.reason.lower()


def test_multiple_opinions_same_page_no_given_name_defaults_to_first_deterministically():
    """No case name to disambiguate with -- must not crash, and must
    deterministically pick the same (first, filename-order) candidate every
    time rather than whichever the OS happened to list last."""
    with _TempCorpus() as d:
        _write_index(d, "T.", 1, [10], case_count=2)
        _write_opinion(d, "op-1", "Alpha v. Beta", "Alpha v. Beta", "T.", 1, 10, 10, "alpha text")
        _write_opinion(d, "op-2", "Gamma v. Delta", "Gamma v. Delta", "T.", 1, 10, 10, "gamma text")
        corpus = Corpus(d)

        res1 = corpus.resolve("T.", 1, 10, None)
        res2 = corpus.resolve("T.", 1, 10, None)
        assert res1.status == INGESTED
        assert res1.opinion["opinion_id"] == res2.opinion["opinion_id"] == "op-1"


def test_ingested_opinions_and_coverage_summary_count_every_sibling():
    with _TempCorpus() as d:
        _write_index(d, "T.", 1, [10], case_count=2)
        _write_opinion(d, "op-1", "Alpha v. Beta", "Alpha v. Beta", "T.", 1, 10, 10, "alpha text")
        _write_opinion(d, "op-2", "Gamma v. Delta", "Gamma v. Delta", "T.", 1, 10, 10, "gamma text")
        corpus = Corpus(d)

        assert len(corpus.ingested_opinions()) == 2
        summary = corpus.coverage_summary()
        assert summary["total_opinions_with_full_text"] == 2
        assert summary["reporters"]["T."][0]["opinions_with_full_text"] == 2


def test_loader_skips_store_doc_with_non_int_first_page():
    """A malformed store doc whose first_page is not an int (a string, a
    null, or simply missing) must be skipped -- never crash the whole
    corpus load -- while every other, well-formed opinion still loads."""
    with _TempCorpus() as d:
        _write_index(d, "T.", 1, [10, 20])
        _write_opinion(d, "op-good", "Alpha v. Beta", "Alpha v. Beta", "T.", 1, 10, 10, "alpha text")
        _write_opinion(d, "op-bad-string", "Bad v. Doc", "Bad v. Doc", "T.", 1, "N/A", 20, "bad text")
        corpus = Corpus(d)

        assert corpus.get_opinion("op-good") is not None
        assert corpus.get_opinion("op-bad-string") is None
        assert len(corpus.ingested_opinions()) == 1

        # The well-formed opinion still resolves normally.
        res = corpus.resolve("T.", 1, 10, "Alpha v. Beta")
        assert res.status == INGESTED
        assert res.opinion["opinion_id"] == "op-good"

        # The page the malformed doc WOULD have occupied is a real page in
        # the complete index but has no ingested opinion object -- must
        # degrade to the honest COVERED_NOT_INGESTED refusal, never crash
        # and never silently report NOT_FOUND for a page that IS present.
        res_bad_page = corpus.resolve("T.", 1, 20, None)
        assert res_bad_page.status == COVERED_NOT_INGESTED


def test_loader_skips_store_doc_with_null_first_page():
    with _TempCorpus() as d:
        _write_index(d, "T.", 1, [10])
        _write_opinion(d, "op-good", "Alpha v. Beta", "Alpha v. Beta", "T.", 1, 10, 10, "alpha text")
        _write_opinion(d, "op-bad-null", "Bad v. Doc", "Bad v. Doc", "T.", 1, None, 10, "bad text")
        corpus = Corpus(d)

        assert corpus.get_opinion("op-good") is not None
        assert corpus.get_opinion("op-bad-null") is None
        assert len(corpus.ingested_opinions()) == 1


def test_loader_skips_store_doc_missing_first_page_entirely():
    with _TempCorpus() as d:
        _write_index(d, "T.", 1, [10])
        _write_opinion(d, "op-good", "Alpha v. Beta", "Alpha v. Beta", "T.", 1, 10, 10, "alpha text")
        doc = {
            "opinion_id": "op-missing",
            "name": "Bad v. Doc",
            "name_abbreviation": "Bad v. Doc",
            "reporter": "T.",
            "volume": 1,
            "last_page": 10,
            "text": "bad text",
        }
        with open(os.path.join(d, "store", "op-missing.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        corpus = Corpus(d)

        assert corpus.get_opinion("op-good") is not None
        assert corpus.get_opinion("op-missing") is None
        assert len(corpus.ingested_opinions()) == 1


# --- Defect 2 fix (coverage conflation): a "complete" volume whose
# `pages_present` is EMPTY (its cases have non-numeric first-pages, so no
# usable page membership was recorded -- real repro: this corpus's `Tex.`
# volume 1, complete=True, case_count=104, pages_present=[]) must yield
# `cannot verify` for a page cite to it, never `not found` -- `not found`
# ASSERTS "no case begins at page N", which is not something an EMPTY page
# index can honestly claim for a volume whose own coverage summary shows
# 104 known cases and 0 known first-pages. The three coverage states
# (NOT_COVERED / NOT_FOUND / INGESTED-adjacent) must stay distinct: an
# empty index is NOT_COVERED (page membership unknown), a non-empty index
# still correctly yields NOT_FOUND for a page genuinely absent from it. ---

def test_complete_volume_with_empty_pages_present_is_not_covered():
    with _TempCorpus() as d:
        _write_index(d, "T.", 1, [], case_count=104)
        corpus = Corpus(d)
        res = corpus.resolve("T.", 1, 5)
        assert res.status == NOT_COVERED
        assert "does not exist" not in res.reason.lower()
        assert "not found" not in res.reason.lower()


def test_complete_volume_with_nonempty_pages_present_still_not_found_for_absent_page():
    """Regression: the fix must not weaken the ordinary case -- a complete
    volume WITH a usable (non-empty) page index still correctly refuses a
    genuinely absent page as NOT_FOUND, not NOT_COVERED."""
    with _TempCorpus() as d:
        _write_index(d, "T.", 1, [10, 20])
        _write_opinion(d, "op-1", "Alpha v. Beta", "Alpha v. Beta", "T.", 1, 10, 12, "some opinion text")
        corpus = Corpus(d)
        res = corpus.resolve("T.", 1, 999)
        assert res.status == NOT_FOUND


def test_complete_volume_with_nonempty_pages_present_still_resolves_present_page():
    """Regression: a genuinely present page in a non-empty-index volume
    must still resolve normally (INGESTED), unaffected by the empty-index
    guard."""
    with _TempCorpus() as d:
        _write_index(d, "T.", 1, [10, 20])
        _write_opinion(d, "op-1", "Alpha v. Beta", "Alpha v. Beta", "T.", 1, 10, 12, "some opinion text")
        corpus = Corpus(d)
        res = corpus.resolve("T.", 1, 10, "Alpha v. Beta")
        assert res.status == INGESTED


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
