"""E3 regression: a malformed .labels.json sidecar must never crash the
CLI. independent review finding: a top-level JSON array raised an uncaught
AttributeError (data.get(...) on a list) and an entry missing "index" or
"expected_verdict" raised an uncaught KeyError, both propagating out of
main() as a traceback with rc=1 instead of producing a report.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from citecheck.report import load_labels, LabelsError

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_DIR = os.path.join(REPO_ROOT, "corpus")
EXAMPLE_DOC = os.path.join(REPO_ROOT, "examples", "sample_brief.md")


def _write_tmp_json(text: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def test_top_level_array_raises_labels_error_not_attributeerror():
    path = _write_tmp_json('[{"index": 0, "expected_verdict": "verified"}]')
    try:
        try:
            load_labels(path)
            assert False, "expected LabelsError"
        except LabelsError as exc:
            assert "citations" in str(exc)
        except AttributeError:
            assert False, "load_labels must not raise a bare AttributeError"
    finally:
        os.remove(path)


def test_entry_missing_index_raises_labels_error_not_keyerror():
    path = _write_tmp_json('{"citations": [{"expected_verdict": "verified"}]}')
    try:
        try:
            load_labels(path)
            assert False, "expected LabelsError"
        except LabelsError as exc:
            assert "index" in str(exc)
        except KeyError:
            assert False, "load_labels must not raise a bare KeyError"
    finally:
        os.remove(path)


def test_entry_missing_expected_verdict_raises_labels_error_not_keyerror():
    path = _write_tmp_json('{"citations": [{"index": 0}]}')
    try:
        try:
            load_labels(path)
            assert False, "expected LabelsError"
        except LabelsError as exc:
            assert "expected_verdict" in str(exc)
        except KeyError:
            assert False, "load_labels must not raise a bare KeyError"
    finally:
        os.remove(path)


def test_invalid_json_raises_labels_error_not_json_decode_error_leak():
    path = _write_tmp_json("{not json")
    try:
        try:
            load_labels(path)
            assert False, "expected LabelsError"
        except LabelsError:
            pass
    finally:
        os.remove(path)


def test_well_formed_labels_still_load_correctly():
    path = _write_tmp_json(
        '{"citations": [{"index": 0, "expected_verdict": "verified"}, '
        '{"index": 3, "expected_verdict": "cannot verify"}]}'
    )
    try:
        labels = load_labels(path)
        assert labels == {0: "verified", 3: "cannot verify"}
    finally:
        os.remove(path)


def test_cli_does_not_crash_on_malformed_labels_sidecar_top_level_array():
    """End-to-end: the CLI must exit 0 and still write a full report.json
    even when handed a malformed labels sidecar, per the E3 fix -- a
    malformed sidecar must degrade gracefully (skip labels), never crash
    verdict production."""
    labels_path = _write_tmp_json('[{"index": 0, "expected_verdict": "verified"}]')
    out_fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(out_fd)
    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "citecheck", "verify", EXAMPLE_DOC,
                "--out", out_path, "--labels", labels_path, "--corpus", CORPUS_DIR,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert "Traceback" not in proc.stderr
        with open(out_path, "r", encoding="utf-8") as fh:
            report = json.load(fh)
        assert report["citation_count"] > 0
        assert "refusal_pair" not in report
    finally:
        os.remove(labels_path)
        os.remove(out_path)


def test_non_utf8_labels_sidecar_raises_labels_error_not_unicodedecodeerror():
    """this case regression: a labels sidecar containing invalid UTF-8 bytes
    (e.g. a lone 0xFF byte, or Latin-1 text) must never crash load_labels
    with an uncaught UnicodeDecodeError. The document reader already
    tolerates non-UTF8 bytes (utf-8, errors="replace"); the labels reader
    must be consistent with it. Invalid bytes decode to U+FFFD, which then
    (almost always) fails JSON parsing and must surface as LabelsError, the
    same graceful path a malformed-JSON sidecar already takes."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "wb") as fh:
        fh.write(b'{"citations": [{"index": 0, "expected_verdict": "verifi\xffed"}]}')
    try:
        try:
            load_labels(path)
        except LabelsError:
            pass
        except UnicodeDecodeError:
            assert False, "load_labels must not raise a bare UnicodeDecodeError"
    finally:
        os.remove(path)


def test_cli_does_not_crash_on_non_utf8_labels_sidecar():
    """End-to-end: the CLI must exit 0 and still write a full report.json
    when handed a labels sidecar with invalid UTF-8 bytes, never rc=1 with
    an uncaught UnicodeDecodeError traceback."""
    fd, labels_path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "wb") as fh:
        fh.write(b"\xff\xfe\x00garbage not json at all")
    out_fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(out_fd)
    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "citecheck", "verify", EXAMPLE_DOC,
                "--out", out_path, "--labels", labels_path, "--corpus", CORPUS_DIR,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert "Traceback" not in proc.stderr
        assert "UnicodeDecodeError" not in proc.stderr
        with open(out_path, "r", encoding="utf-8") as fh:
            report = json.load(fh)
        assert report["citation_count"] > 0
    finally:
        os.remove(labels_path)
        os.remove(out_path)


def test_cli_does_not_crash_on_malformed_labels_sidecar_missing_keys():
    labels_path = _write_tmp_json('{"citations": [{"index": 0}]}')
    out_fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(out_fd)
    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "citecheck", "verify", EXAMPLE_DOC,
                "--out", out_path, "--labels", labels_path, "--corpus", CORPUS_DIR,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert "Traceback" not in proc.stderr
        with open(out_path, "r", encoding="utf-8") as fh:
            report = json.load(fh)
        assert report["citation_count"] > 0
    finally:
        os.remove(labels_path)
        os.remove(out_path)


def test_cli_does_not_crash_on_missing_explicit_labels_path():
    """this case regression: a independent review found that passing an
    explicit --labels PATH that does not exist on disk raised an uncaught
    FileNotFoundError (rc=1, traceback, no report.json) -- the one
    unusable-labels input the other malformed-sidecar handling above did
    not cover. It must degrade the same way: warn on stderr and continue
    with labels=None, rc=0, full report.json still written."""
    missing_labels_path = os.path.join(
        tempfile.gettempdir(), "citecheck_r6_1_no_such_labels_file.json"
    )
    assert not os.path.exists(missing_labels_path)
    out_fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(out_fd)
    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "citecheck", "verify", EXAMPLE_DOC,
                "--out", out_path, "--labels", missing_labels_path,
                "--corpus", CORPUS_DIR,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert "Traceback" not in proc.stderr
        assert "FileNotFoundError" not in proc.stderr
        assert "not found" in proc.stderr
        with open(out_path, "r", encoding="utf-8") as fh:
            report = json.load(fh)
        assert report["citation_count"] > 0
        assert "refusal_pair" not in report
    finally:
        os.remove(out_path)


def test_absent_auto_detected_sidecar_stays_silent():
    """Guard the distinction this case requires: an EXPLICIT --labels path that
    is missing must warn (tested above), but the normal no-sidecar-present
    run (no --labels given, and no "<doc>.labels.json" auto-detect
    candidate on disk) must stay completely silent on stderr -- that is
    the ordinary, expected case, not an error. Use a fresh copy of the
    example document in an isolated temp dir so no stray
    "<doc>.labels.json" (e.g. examples/sample_brief.md.labels.json, which
    the fixture corpus intentionally ships) is picked up by auto-detect."""
    with open(EXAMPLE_DOC, "r", encoding="utf-8") as fh:
        doc_text = fh.read()
    tmp_dir = tempfile.mkdtemp()
    tmp_doc = os.path.join(tmp_dir, "no_sidecar_doc.md")
    with open(tmp_doc, "w", encoding="utf-8") as fh:
        fh.write(doc_text)
    auto_candidate = tmp_doc + ".labels.json"
    assert not os.path.exists(auto_candidate)
    out_fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(out_fd)
    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "citecheck", "verify", tmp_doc,
                "--out", out_path, "--corpus", CORPUS_DIR,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stderr == ""
        with open(out_path, "r", encoding="utf-8") as fh:
            report = json.load(fh)
        assert report["citation_count"] > 0
    finally:
        os.remove(out_path)
        os.remove(tmp_doc)
        os.rmdir(tmp_dir)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
