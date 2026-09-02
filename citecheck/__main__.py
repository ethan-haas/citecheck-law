"""CLI: python -m citecheck verify <input_document> --out report.json [--labels PATH] [--corpus DIR]"""
from __future__ import annotations

import argparse
import os
import sys

from .corpus import Corpus
from .report import build_report, write_report, format_summary, load_labels, LabelsError


def _default_corpus_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "corpus")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="citecheck")
    sub = parser.add_subparsers(dest="command", required=True)

    verify_p = sub.add_parser("verify", help="verify citations in a document")
    verify_p.add_argument("input_document", help="path to a plain-text/markdown document")
    verify_p.add_argument("--out", default="report.json", help="path to write report.json")
    verify_p.add_argument("--labels", default=None, help="path to a labels sidecar JSON file")
    verify_p.add_argument(
        "--corpus", default=None,
        help="path to the corpus directory (default: <repo>/corpus)",
    )

    args = parser.parse_args(argv)

    if args.command == "verify":
        corpus_dir = args.corpus or _default_corpus_dir()
        if not os.path.isdir(corpus_dir):
            print(f"error: corpus directory not found: {corpus_dir}", file=sys.stderr)
            return 2

        # Safe input reading (defect 6): odd/invalid byte sequences must
        # never crash the CLI with an uncaught UnicodeDecodeError. Read as
        # UTF-8 with a documented replace-on-error fallback -- well-formed
        # UTF-8 documents are read byte-identically either way, and a
        # document with invalid bytes still produces a full report (with
        # U+FFFD replacement characters in place of the invalid bytes)
        # instead of rc=1 and a traceback.
        with open(
            args.input_document, "r", encoding="utf-8", errors="replace"
        ) as fh:
            document_text = fh.read()

        labels_path = args.labels
        if labels_path is None:
            candidate = args.input_document + ".labels.json"
            if os.path.isfile(candidate):
                labels_path = candidate
        labels = None
        if labels_path:
            try:
                labels = load_labels(labels_path)
            except FileNotFoundError:
                # a --labels path (or an explicitly-resolved
                # candidate) that does not exist must degrade the same
                # way a malformed sidecar does -- warn and continue with
                # labels=None -- never an uncaught traceback/rc=1. Note
                # this branch is only reachable for an EXPLICIT --labels
                # path: the auto-detected "<doc>.labels.json" candidate
                # above is only assigned to labels_path after an
                # os.path.isfile() check, so the normal no-sidecar-present
                # run never reaches here and stays silent.
                print(
                    f"warning: labels file not found, skipping labels "
                    f"(verdict report is unaffected): {labels_path}",
                    file=sys.stderr,
                )
                labels = None
            except LabelsError as exc:
                print(
                    f"warning: labels sidecar unusable, skipping labels "
                    f"(verdict report is unaffected): {exc}",
                    file=sys.stderr,
                )
                labels = None

        corpus = Corpus(corpus_dir)
        report = build_report(document_text, corpus, labels)
        write_report(report, args.out)
        print(format_summary(report))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
