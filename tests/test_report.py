import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from citecheck.corpus import Corpus
from citecheck.report import build_report, load_labels

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_DIR = os.path.join(REPO_ROOT, "corpus")
EXAMPLE_DOC = os.path.join(REPO_ROOT, "examples", "sample_brief.md")
EXAMPLE_LABELS = EXAMPLE_DOC + ".labels.json"


def test_report_is_deterministic():
    corpus = Corpus(CORPUS_DIR)
    with open(EXAMPLE_DOC, "r", encoding="utf-8") as fh:
        text = fh.read()
    r1 = build_report(text, corpus)
    r2 = build_report(text, corpus)
    assert r1 == r2


def test_report_verdict_counts_on_example():
    corpus = Corpus(CORPUS_DIR)
    with open(EXAMPLE_DOC, "r", encoding="utf-8") as fh:
        text = fh.read()
    report = build_report(text, corpus)
    assert report["citation_count"] == 10
    counts = report["verdict_counts"]
    assert counts.get("verified", 0) >= 3
    assert counts.get("exists, unsupported", 0) >= 1
    assert counts.get("not found", 0) >= 1
    assert counts.get("cannot verify", 0) >= 1


def test_refusal_pair_matches_gold_labels():
    corpus = Corpus(CORPUS_DIR)
    with open(EXAMPLE_DOC, "r", encoding="utf-8") as fh:
        text = fh.read()
    labels = load_labels(EXAMPLE_LABELS)
    report = build_report(text, corpus, labels)
    rp = report["refusal_pair"]
    assert rp["correct_refusal_rate"] == 1.0
    assert rp["false_refusal_rate"] == 0.0


def test_no_verified_verdict_ever_lacks_a_resolvable_span():
    """acceptance gate 4, generalized: every verified verdict in the report must
    carry an opinion_id/span/quoted_sentence that actually resolves."""
    corpus = Corpus(CORPUS_DIR)
    with open(EXAMPLE_DOC, "r", encoding="utf-8") as fh:
        text = fh.read()
    report = build_report(text, corpus)
    checked = 0
    for c in report["citations"]:
        if c["verdict"] == "verified":
            checked += 1
            assert c["opinion_id"] is not None
            op = corpus.get_opinion(c["opinion_id"])
            assert op is not None
            start, end = c["span"]
            assert 0 <= start < end <= len(op.text)
            assert op.text[start:end] == c["quoted_sentence"]
    assert checked >= 3


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
