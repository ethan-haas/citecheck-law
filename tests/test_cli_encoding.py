"""independent review, defect 6 (MED): a document containing
non-UTF8/invalid bytes crashed the CLI with an uncaught UnicodeDecodeError
(rc=1, traceback, no report.json written at all). Root cause:
__main__.py's `open(..., encoding="utf-8")` had no error-handling fallback.
Fixed by reading with `errors="replace"`, so invalid bytes become U+FFFD
replacement characters instead of raising -- the CLI always exits 0 and
always produces a report."""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_DIR = os.path.join(REPO_ROOT, "corpus")


def _write_tmp_bytes(data: bytes, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path


def test_cli_does_not_crash_on_invalid_utf8_bytes():
    doc_bytes = (
        b"See Brown v. Board of Education, 347 U.S. 483 (1954). "
        b"\xff\xfe some invalid bytes here \xc0\xaf more."
    )
    doc_path = _write_tmp_bytes(doc_bytes, ".txt")
    out_fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(out_fd)
    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "citecheck", "verify", doc_path,
                "--out", out_path, "--corpus", CORPUS_DIR,
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
        assert report["citation_count"] >= 1
    finally:
        os.remove(doc_path)
        os.remove(out_path)


def test_valid_utf8_document_is_unaffected_by_the_errors_replace_fallback():
    """A well-formed UTF-8 document (including non-ASCII characters) must
    read byte-identically whether or not the errors='replace' fallback is
    active -- it only ever engages on genuinely invalid byte sequences."""
    doc_bytes = 'See Brown v. Board of "Éducation", 347 U.S. 483 (1954).'.encode("utf-8")
    doc_path = _write_tmp_bytes(doc_bytes, ".txt")
    out_fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(out_fd)
    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "citecheck", "verify", doc_path,
                "--out", out_path, "--corpus", CORPUS_DIR,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        with open(out_path, "r", encoding="utf-8") as fh:
            report = json.load(fh)
        assert "�" not in json.dumps(report)
    finally:
        os.remove(doc_path)
        os.remove(out_path)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
