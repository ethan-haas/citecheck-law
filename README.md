# citecheck

A deterministic, offline, no-API-key CLI that checks whether the case
citations in a legal document actually resolve to real authorities in a
committed public-domain corpus, and whether the proposition each citation is
offered for is actually supported by that authority's text.

**This is not legal advice.** citecheck produces a report about *text*: does
a citation string resolve to an opinion in this corpus, and does a quoted or
paraphrased proposition appear as a literal substring of that opinion. It
says nothing about whether a legal argument is sound, whether a case is good
law, or whether a citation is being used honestly in context beyond that one
mechanical check.

## The refusal contract

Every citation gets exactly one of four verdicts:

| verdict | meaning |
|---|---|
| `verified` | The citation resolves to an opinion **this corpus has full text for**, and the cited proposition is a literal substring of that text (whitespace/quote/case-folding normalized only -- no fuzzy matching). Carries `opinion_id`, `span`, and `quoted_sentence`. |
| `exists, unsupported` | The citation resolves to an opinion we have full text for, but the proposition was **not** found in it. |
| `not found` | The (reporter, volume) is a **complete, authoritative** index in this corpus, and **no case begins at the cited page** -- or a case name is attached to a real citation number for a *different* case. Worded as "no such case at this citation in a covered volume," never as "the case does not exist." |
| `cannot verify` | **The refusal state.** Either the reporter/volume is not represented in this corpus at all, or a case is known (via a complete volume index) to exist at that page but its text was never ingested. The `reason` field always says which. Never conflated with `not found`. |

citecheck will **never** state that a case "does not exist," anywhere in
its output. The strongest claim it ever makes is that an authority is not
represented in this corpus. A real, resolvable case cited under the wrong
name is reported as "no case named X exists at this citation; the case
actually reported there is Y" -- Y's existence is affirmed, not denied.

A `wrong_pinpoint` flag is set (not a separate verdict) when a pinpoint page
falls outside the resolved opinion's `[first_page, last_page]` range. A
`name_mismatch` flag accompanies the `not found` verdict produced when a
citation number is real but the attached case name does not corroborate it.

## Honest corpus coverage

**Source:** Caselaw Access Project (`static.case.law`), public domain. See
[`NOTICE`](NOTICE) for corpus provenance and the excluded copyrighted reporters.
Retrieved 2026-09-01. Every opinion and volume-index entry in `corpus/`
carries its own `source_url` and `retrieved` date.

**Courts:** the U.S. Supreme Court (`U.S.`); the full federal hierarchy --
courts of appeals (`F.`, `F.2d`, `F.3d`) and district courts (`F. Supp.`,
`F. Supp. 2d`, `F. Supp. 3d`); the regional reporters of the National Reporter
System (`A.2d`, `A.3d`, `N.E.2d`, `N.W.2d`, `P.2d`, `P.3d`, `S.E.2d`, `So. 2d`,
`S.W.2d`, `S.W.3d`); and many state high and intermediate courts (`N.Y.`,
`N.Y.2d`, `Cal. 2d`, `Cal. App. 2d`, `Mass.`, `Ill. 2d`, `Tex.`, `Ohio St.`,
`Pa.`, `Pa. Super.`, `Fla.`, `Ga.`, `Mich.`, `N.J.`, `Va.`, `Wash. 2d`, `Wis.`,
`Md.`, `Conn.`) -- **36 reporters**. This is a curated demonstration corpus,
**not** comprehensive coverage of any court: only the specific volumes actually
ingested are present. A citation to any reporter or volume not in the corpus is
`cannot verify` by construction -- the corpus has no membership index for it.
West's `S. Ct.` and Lawyers' Edition (`L. Ed.`) are deliberately absent (still
under copyright); only public-domain official and National-Reporter-System text
is used.

**Reporter/volume coverage** -- **90 volumes across 36 reporters** (~22,400
cases known to exist via complete, authoritative page indexes), with **352
opinions fully ingested with text**: 22 curated landmark cases plus, per
breadth volume, the first several cases by page order (real cases, no cherry-
picking). Every *other* case in an ingested volume is known to exist (its first
page is in the index) but its proposition cannot be checked -- citing it
correctly returns `cannot verify` with reason "text not ingested," not a false
negative. A volume whose page index could not be recorded (non-numeric CAP
pagination) is also `cannot verify`, never `not found` -- the tool never asserts
a case does not exist.

| Reporter | Volumes | Cases indexed | Opinions with text |
|---|---|---|---|
| U.S. | 17 | 11129 | 25 |
| F.2d | 4 | 1264 | 12 |
| F.3d | 3 | 494 | 11 |
| F. Supp. | 3 | 677 | 11 |
| F. Supp. 2d | 3 | 369 | 11 |
| F. | 1 | 252 | 1 |
| F. Supp. 3d | 2 | 175 | 10 |
| A.2d, A.3d | 4 | 314 | 18 |
| N.E.2d, N.W.2d | 4 | 440 | 20 |
| P.2d, P.3d | 4 | 459 | 20 |
| S.E.2d | 2 | 271 | 9 |
| So. 2d | 2 | 549 | 10 |
| S.W.2d, S.W.3d | 4 | 650 | 20 |
| N.Y., N.Y.2d | 3 | 726 | 11 |
| Cal. 2d, Cal. App. 2d | 4 | 486 | 20 |
| Mass., Ill. 2d, Md., Conn. | 8 | 744 | 40 |
| Tex., Ohio St., Pa., Pa. Super. | 8 | 924 | 33 |
| Fla., Ga., Mich., N.J., Va., Wash. 2d, Wis. | 14 | 2438 | 70 |

(Per-reporter totals; the machine-readable `corpus/index.json` lists every
volume with its exact `case_count` and page index.)

**Year range:** 1754-2019. Nothing outside that span, and no reporter/volume
not ingested, can be decided by this corpus -- those citations are correctly
`cannot verify`, not `not found`.

**What this tool can decide:** whether a citation in one of the 90 ingested
volumes resolves to a real case, and, for the 352 fully-ingested opinions
specifically, whether a quoted or paraphrased proposition is literally present
in that opinion's text.

**What this tool cannot decide:** anything about any reporter, court, volume,
or year outside the ingested set; anything about the ~22,000 non-ingested cases
known to exist in the ingested volumes (it will correctly refuse rather than
guess); internal page location of a proposition within a multi-page opinion
(the ingested text has no page-break markers, so pinpoint validity is checked
only against `[first_page, last_page]`, never against where in the opinion a
quote physically sits on the printed page); and it will not fuzzy-match a
misquote into passing.

## Known data quality notes

A small number of curly quotation marks in the ingested opinion text were
corrupted to the Unicode replacement character (`U+FFFD`) during upstream
acquisition (visible, e.g., in `Gideon v. Wainwright`'s use of "public's").
citecheck's normalization folds curly quotes to straight quotes but cannot
recover a replacement character back into the quote mark it once was. A
proposition that quotes verbatim text spanning one of these characters with
a real quotation mark will not match. This is a corpus acquisition gap, not
a matching bug, and is called out here rather than papered over with
fuzzier matching (which the specification explicitly forbids: "do NOT fuzzy-match to the
point that a misquote passes").

## Install / run

No install step beyond a Python 3.9+ interpreter and the standard library --
citecheck has **zero third-party runtime dependencies**.

```bash
python -m citecheck verify examples/sample_brief.md --out report.json
```

Writes `report.json` and prints a human-readable per-citation summary to
stdout. Exit code 0 on success (a low-quality document with many refusals
is not a tool failure -- it is the tool doing its job).

Optional gold-label sidecar for the refusal-pair report (acceptance gate 5): put
`<document>.labels.json` next to the input (auto-detected), or pass
`--labels PATH` explicitly. Format:

```json
{"citations": [{"index": 0, "expected_verdict": "verified"}, ...]}
```

`index` is 0-based citation order as extracted from the document.
`report.json` will then include a `refusal_pair` block reporting
`correct_refusal_rate` and `false_refusal_rate` **separately** -- a single
blended accuracy number is not produced, because acceptance gate 5 explicitly
does not accept one.

See `examples/sample_brief.md` and its `.labels.json` sidecar for a worked
demonstration exercising all four verdicts plus both flags.

## Determinism

Same input document (+ same corpus on disk) -> byte-identical `report.json`.
No network calls, no timestamps in the report body, no randomness. See
`tests/test_report.py::test_report_is_deterministic`.

## Package layout

```
citecheck/
  extract.py   - citation + proposition extraction from raw document text
                 (independently testable, no corpus dependency)
  corpus.py    - read-only loader for corpus/index.json + corpus/store/*.json;
                 answers INGESTED / COVERED_NOT_INGESTED / NOT_FOUND / NOT_COVERED
  support.py   - length-preserving text normalization + literal substring search
  resolve.py   - heuristic case-name corroboration
  verdict.py   - combines the above into the four-way verdict + flags
  report.py    - report.json assembly, refusal-pair stats, CLI summary text
  __main__.py  - CLI entry point
```

## Tests

```bash
python -m pytest tests/ -v
```

These are the builder's own smoke tests, not the independent adversarial
review described above. They cover: extraction independent of
resolution (gate 3), the not-found/cannot-verify distinction never being
conflated and never wording a real case as nonexistent (gate 2), every
`verified` verdict's span actually resolving in the opinion text (gate 4),
report determinism and the separately-reported refusal pair (gate 5), and a
literal red/green check that corrupting an opinion's text flips its
citation from `verified` to `exists, unsupported` (gate 6).
