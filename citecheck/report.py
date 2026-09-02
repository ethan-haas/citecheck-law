"""Builds the report.json structure and the human-readable CLI summary.

Determinism: build_report() only ever consumes the document text, the
corpus (loaded read-only from disk), and an optional labels sidecar -- no
wall-clock timestamps, no random iteration order (dict insertion order is
fixed by document order), so the same input always produces a
byte-identical report.json (json.dump with fixed key order, ensure_ascii,
and a trailing newline).
"""
from __future__ import annotations

import json
from typing import Optional

from .corpus import Corpus
from .extract import extract_citations
from .verdict import judge_citation, CANNOT_VERIFY, VERIFIED, NOT_FOUND_VERDICT, EXISTS_UNSUPPORTED


class LabelsError(ValueError):
    """Raised when a labels sidecar file does not match the documented
    shape. Callers (the CLI) are expected to catch this, report it as a
    diagnostic, and continue without labels -- a malformed sidecar must
    never crash verdict production, and it must never be silently accepted
    as if it were valid data."""


def load_labels(path: str) -> dict:
    """Labels sidecar format:
    {"citations": [{"index": 0, "expected_verdict": "verified"}, ...]}
    Indexes correspond to extraction order (0-based) in the document.

    Raises LabelsError (not AttributeError/KeyError, and never a raw
    UnicodeDecodeError) on any shape that does not match the above -- e.g. a
    top-level JSON array instead of an object, an entry missing
    "index"/"expected_verdict", or a sidecar file that is not valid UTF-8
    text at all. Read with the same tolerant utf-8/errors="replace" decoding
    the input document uses: a non-UTF8 sidecar must degrade
    to "graceful diagnostic, no labels" like a malformed-JSON sidecar does,
    never crash the CLI with an uncaught UnicodeDecodeError.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise LabelsError(f"{path}: not valid JSON ({exc})") from exc

    if not isinstance(data, dict):
        raise LabelsError(
            f"{path}: expected a JSON object with a top-level \"citations\" "
            f"key, got {type(data).__name__}"
        )

    citations = data.get("citations", [])
    if not isinstance(citations, list):
        raise LabelsError(f"{path}: \"citations\" must be a JSON array")

    out = {}
    for i, entry in enumerate(citations):
        if not isinstance(entry, dict) or "index" not in entry or "expected_verdict" not in entry:
            raise LabelsError(
                f"{path}: citations[{i}] is missing required key(s) "
                f'"index"/"expected_verdict": {entry!r}'
            )
        try:
            idx = int(entry["index"])
        except (TypeError, ValueError) as exc:
            raise LabelsError(
                f'{path}: citations[{i}]["index"] is not an integer: '
                f'{entry["index"]!r}'
            ) from exc
        out[idx] = entry["expected_verdict"]
    return out


def compute_refusal_pair(verdicts: list, labels: dict) -> Optional[dict]:
    if not labels:
        return None
    undecidable = []  # gold says cannot verify
    decidable = []     # gold says something else (a decision was possible)
    for idx, expected in labels.items():
        if idx >= len(verdicts):
            continue
        predicted = verdicts[idx].verdict
        if expected == CANNOT_VERIFY:
            undecidable.append((expected, predicted))
        else:
            decidable.append((expected, predicted))

    correct_refusals = sum(1 for e, p in undecidable if p == CANNOT_VERIFY)
    false_refusals = sum(1 for e, p in decidable if p == CANNOT_VERIFY)

    return {
        "labelled_citations": len(labels),
        "undecidable_gold_count": len(undecidable),
        "decidable_gold_count": len(decidable),
        "correct_refusal_count": correct_refusals,
        "correct_refusal_rate": (
            correct_refusals / len(undecidable) if undecidable else None
        ),
        "false_refusal_count": false_refusals,
        "false_refusal_rate": (
            false_refusals / len(decidable) if decidable else None
        ),
        "note": (
            "correct_refusal_rate = fraction of gold-undecidable citations "
            "correctly returned as 'cannot verify'. false_refusal_rate = "
            "fraction of gold-decidable citations wrongly returned as "
            "'cannot verify'. Reported separately per acceptance gate 5; a single "
            "blended accuracy number does not satisfy that gate."
        ),
    }


def build_report(document_text: str, corpus: Corpus, labels: Optional[dict] = None) -> dict:
    citations = extract_citations(document_text)
    verdicts = [judge_citation(corpus, c) for c in citations]

    verdict_counts = {}
    for v in verdicts:
        verdict_counts[v.verdict] = verdict_counts.get(v.verdict, 0) + 1

    report = {
        "tool": "citecheck",
        "corpus_coverage": corpus.coverage_summary(),
        "citation_count": len(verdicts),
        "verdict_counts": verdict_counts,
        "citations": [v.to_dict() for v in verdicts],
    }

    if labels:
        refusal_pair = compute_refusal_pair(verdicts, labels)
        if refusal_pair is not None:
            report["refusal_pair"] = refusal_pair

    return report


def write_report(report: dict, out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=True, sort_keys=False)
        fh.write("\n")


def format_summary(report: dict) -> str:
    lines = []
    lines.append(f"citecheck: {report['citation_count']} citation(s) found")
    counts = report["verdict_counts"]
    for verdict in (VERIFIED, EXISTS_UNSUPPORTED, NOT_FOUND_VERDICT, CANNOT_VERIFY):
        if verdict in counts:
            lines.append(f"  {verdict}: {counts[verdict]}")
    lines.append("")
    for i, c in enumerate(report["citations"]):
        name = c["case_name"] or "(no case name parsed)"
        lines.append(f"[{i}] {c['raw_citation']}  -- {name}")
        lines.append(f"    verdict: {c['verdict']}")
        lines.append(f"    reason: {c['reason']}")
        if c.get("wrong_pinpoint"):
            lines.append("    FLAG: wrong_pinpoint")
        if c.get("name_mismatch"):
            lines.append("    FLAG: name_mismatch")
        if c["verdict"] == VERIFIED:
            lines.append(f"    opinion_id: {c['opinion_id']}  span: {c['span']}")
            lines.append(f"    quoted_sentence: {c['quoted_sentence']!r}")
        lines.append("")
    if "refusal_pair" in report:
        rp = report["refusal_pair"]
        lines.append("refusal pair (against labels sidecar):")
        lines.append(f"  correct_refusal_rate: {rp['correct_refusal_rate']}")
        lines.append(f"  false_refusal_rate: {rp['false_refusal_rate']}")
    return "\n".join(lines)
