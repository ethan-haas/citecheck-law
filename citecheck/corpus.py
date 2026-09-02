"""Loads the committed corpus (corpus/index.json + corpus/store/*.json) and
answers the single question everything else depends on: for a given
(reporter, volume, page), what does this corpus actually know?

Four possible resolutions, deliberately distinct:
  INGESTED            - we have the opinion's full text.
  COVERED_NOT_INGESTED- the volume is a complete, authoritative index and a
                         case is known to begin at that page, but we never
                         pulled its text.
  NOT_FOUND           - the volume is a complete, authoritative index and NO
                         case begins at that page.
  NOT_COVERED         - the reporter, or that volume of it, is not
                         represented in this corpus at all. We cannot rule
                         anything in or out.

NOT_FOUND and NOT_COVERED are the two refusal-adjacent states the specification
requires never be conflated: NOT_FOUND is a claim about a page inside a
volume we DO have complete authoritative membership for; NOT_COVERED is an
admission that we have no such membership list to consult.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from .resolve import name_matches


# ---------------------------------------------------------------------------
# Resolution result
# ---------------------------------------------------------------------------

INGESTED = "INGESTED"
COVERED_NOT_INGESTED = "COVERED_NOT_INGESTED"
NOT_FOUND = "NOT_FOUND"
NOT_COVERED = "NOT_COVERED"


@dataclass
class Resolution:
    status: str  # one of the four constants above
    reason: str
    opinion: Optional[dict] = None  # populated only when status == INGESTED
    # True only for the NOT_FOUND case produced when a (reporter, volume,
    # page) is shared by multiple real opinions and the citation's given
    # case name matched none of them (see `Corpus.resolve`) -- lets
    # verdict.py flag it the same way as the pre-existing single-opinion
    # name-mismatch NOT_FOUND, rather than looking indistinguishable from an
    # ordinary "no case begins at this page at all" NOT_FOUND.
    name_mismatch: bool = False


@dataclass
class Opinion:
    opinion_id: str
    name: str
    name_abbreviation: str
    reporter: str
    volume: int
    first_page: int
    last_page: int
    official_citation: str
    court: str
    decision_date: str
    text: str
    source_url: str
    retrieved: str


class Corpus:
    """In-memory view of corpus/index.json + corpus/store/*.json.

    Read-only. Never mutates anything under corpus/.
    """

    def __init__(self, corpus_dir: str):
        self.corpus_dir = corpus_dir
        index_path = os.path.join(corpus_dir, "index.json")
        with open(index_path, "r", encoding="utf-8") as fh:
            self.index = json.load(fh)

        # reporter -> volume(str) -> {complete, case_count, pages_present:set}
        self._volumes: dict[str, dict[str, dict]] = {}
        for reporter, rdata in self.index.get("reporters", {}).items():
            vols = {}
            for vol, vdata in rdata.get("volumes", {}).items():
                vols[str(vol)] = {
                    "complete": bool(vdata.get("complete")),
                    "case_count": vdata.get("case_count"),
                    "pages_present": set(vdata.get("pages_present", [])),
                    "source_url": vdata.get("source_url"),
                    "retrieved": vdata.get("retrieved"),
                }
            self._volumes[reporter] = vols

        # (reporter, volume, first_page) -> list[Opinion], built by scanning
        # corpus/store/*.json directly (not manifest.json) so the package
        # doesn't depend on an intermediate listing file. A LIST, not a
        # single Opinion: two (or more) real, distinct opinions can
        # legitimately share the same (reporter, volume, first_page) --
        # e.g. two per-curiam order entries filed on the same page of the
        # same volume -- and collapsing them onto one dict slot silently
        # discarded every opinion but the last one loaded, so a citation to
        # any DISCARDED sibling by its own (correct) name fell through to a
        # spurious name_mismatch/NOT_FOUND even though it cites a real,
        # correctly-named case at that exact reporter/volume/page
        # (false-refusal escape 4, corpus-scale-up round). See `resolve()`
        # for how a citation's given case name disambiguates among siblings.
        self._by_key: dict[tuple[str, int, int], list[Opinion]] = {}
        self._by_id: dict[str, Opinion] = {}
        store_dir = os.path.join(corpus_dir, "store")
        for fname in sorted(os.listdir(store_dir)):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(store_dir, fname), "r", encoding="utf-8") as fh:
                raw = json.load(fh)

            # Defensive loader guard: the acquisition pipeline already
            # filters out malformed store docs before they are committed,
            # but the loader must never ASSUME that and crash the whole run
            # over one bad file reaching corpus/store/ -- a doc whose
            # first_page is not an int (missing, null, a non-numeric
            # string, ...) is skipped rather than raising, and every other,
            # well-formed opinion in the corpus is still loaded normally.
            raw_first_page = raw.get("first_page")
            if isinstance(raw_first_page, bool) or not isinstance(raw_first_page, int):
                continue

            op = Opinion(
                opinion_id=raw["opinion_id"],
                name=raw.get("name", raw.get("name_abbreviation", "")),
                name_abbreviation=raw.get("name_abbreviation", raw.get("name", "")),
                reporter=raw["reporter"],
                volume=int(raw["volume"]),
                first_page=raw_first_page,
                last_page=int(raw["last_page"]),
                official_citation=raw.get("official_citation", ""),
                court=raw.get("court", ""),
                decision_date=raw.get("decision_date", ""),
                text=raw["text"],
                source_url=raw.get("source_url", ""),
                retrieved=raw.get("retrieved", ""),
            )
            key = (op.reporter, op.volume, op.first_page)
            self._by_key.setdefault(key, []).append(op)
            self._by_id[op.opinion_id] = op

    # -- lookups -----------------------------------------------------------

    def reporters(self) -> list[str]:
        return sorted(self._volumes.keys())

    def volume_info(self, reporter: str, volume: int) -> Optional[dict]:
        vols = self._volumes.get(reporter)
        if vols is None:
            return None
        return vols.get(str(volume))

    def get_opinion(self, opinion_id: str) -> Optional[Opinion]:
        return self._by_id.get(opinion_id)

    def ingested_opinions(self) -> list[Opinion]:
        out: list[Opinion] = []
        for opinions in self._by_key.values():
            out.extend(opinions)
        return out

    @staticmethod
    def _opinion_dict(op: "Opinion") -> dict:
        return {
            "opinion_id": op.opinion_id,
            "name": op.name,
            "name_abbreviation": op.name_abbreviation,
            "reporter": op.reporter,
            "volume": op.volume,
            "first_page": op.first_page,
            "last_page": op.last_page,
            "official_citation": op.official_citation,
            "court": op.court,
            "decision_date": op.decision_date,
            "text": op.text,
        }

    def resolve(
        self, reporter: str, volume: int, page: int, case_name: Optional[str] = None
    ) -> Resolution:
        """`case_name`, when given, is the citation's OWN parsed case name --
        used only to disambiguate when more than one real opinion in this
        corpus begins at the exact same (reporter, volume, page) (see the
        `_by_key` docstring above). When there is only a single opinion at
        that key, `case_name` is not consulted here at all; verdict.py does
        its own, independent name-corroboration check against that single
        opinion afterward, exactly as before this parameter existed."""
        vol_info = self.volume_info(reporter, volume)
        if vol_info is None:
            if reporter not in self._volumes:
                reason = (
                    f"reporter '{reporter}' is not represented in this corpus at all"
                )
            else:
                reason = (
                    f"{reporter} volume {volume} is not represented in this corpus"
                )
            return Resolution(NOT_COVERED, reason)

        if not vol_info["complete"]:
            reason = (
                f"{reporter} volume {volume} is present in this corpus but not "
                "marked as a complete, authoritative index of that volume's "
                "case membership; page presence cannot be decided"
            )
            return Resolution(NOT_COVERED, reason)

        if not vol_info["pages_present"]:
            # `complete=True` only asserts that the volume's CASE LIST is
            # authoritative (we know every case that belongs to it); it does
            # NOT by itself mean page membership was ever recorded. A volume
            # whose cases have non-numeric/unusable first-pages (e.g. this
            # corpus's `Tex.` volume 1) is ingested with `pages_present=[]`
            # -- an EMPTY page index, not an authoritative "no case begins
            # at any page" index. Treating an empty index the same as "page
            # N is absent" would ASSERT non-existence for a page in a volume
            # whose own coverage summary shows 104 known cases and 0 known
            # first-pages -- exactly the "does not exist" claim the specification
            # forbids. This is a refusal (`cannot verify`), distinct from
            # both NOT_FOUND (page index usable, page genuinely absent) and
            # the ordinary NOT_COVERED (reporter/volume missing entirely).
            reason = (
                f"{reporter} volume {volume} is present in this corpus and "
                "marked complete, but its page index was not ingested "
                "(pages_present is empty); page presence cannot be decided"
            )
            return Resolution(NOT_COVERED, reason)

        if page not in vol_info["pages_present"]:
            reason = (
                f"{reporter} volume {volume} is a complete, authoritative index "
                f"in this corpus, and no case begins at page {page} in it"
            )
            return Resolution(NOT_FOUND, reason)

        candidates = self._by_key.get((reporter, volume, page), [])
        if not candidates:
            reason = (
                f"a case is known to begin at {reporter} {volume} {page} "
                "(per the complete volume index) but its opinion text was "
                "not ingested into this corpus, so the cited proposition "
                "cannot be checked"
            )
            return Resolution(COVERED_NOT_INGESTED, reason)

        if len(candidates) == 1:
            return Resolution(
                INGESTED,
                "resolved to an ingested opinion",
                opinion=self._opinion_dict(candidates[0]),
            )

        # More than one real, distinct opinion in this corpus begins at this
        # exact (reporter, volume, page) -- a genuine page collision (two
        # per-curiam order entries filed on the same page of the same
        # volume is the common real-world cause). Corroborate the citation's
        # OWN given case name against each sibling and resolve to the one
        # whose name it actually matches, rather than an arbitrary "last one
        # loaded" -- that silent-overwrite behavior is exactly what produced
        # false-refusal escape 4 (a citation to the DISCARDED sibling, by
        # its own correct name, fell through to a spurious NOT_FOUND).
        if case_name:
            matches = [
                op for op in candidates
                if name_matches(case_name, op.name, op.name_abbreviation)
            ]
            if len(matches) >= 1:
                # A name given for a page shared by multiple opinions
                # corroborates one of them; if it happens to be ambiguous
                # among the matches themselves (practically never -- two
                # real siblings sharing both a page AND a corroborating
                # name), take the first in stable (filename) order rather
                # than guess further.
                return Resolution(
                    INGESTED,
                    (
                        "resolved to an ingested opinion (this reporter/volume/"
                        f"page is shared by {len(candidates)} opinions in this "
                        "corpus; the given case name corroborated this one)"
                    ),
                    opinion=self._opinion_dict(matches[0]),
                )
            # The given name matches NONE of the real opinions at this page
            # -- still name a real case (or cases) actually reported there,
            # never claim the page itself does not exist.
            sibling_names = "; ".join(
                f"'{op.name_abbreviation}'" for op in candidates
            )
            reason = (
                f"{reporter} volume {volume} is a complete, authoritative index "
                f"in this corpus; {len(candidates)} opinions begin at page "
                f"{page} in it ({sibling_names}), and no case named "
                f"'{case_name}' matches any of them"
            )
            return Resolution(NOT_FOUND, reason, name_mismatch=True)

        # No case name was parsed for this citation at all, so there is
        # nothing to disambiguate with -- fall back to the first candidate
        # in stable (filename) order. (Every real repro/regression for this
        # corpus's page collisions carries a parsed "X v. Y" name; this
        # branch only guards a citation form with no name at all, e.g. a
        # bare short-form pincite, at one of these rare shared pages.)
        return Resolution(
            INGESTED,
            (
                "resolved to an ingested opinion (this reporter/volume/page "
                f"is shared by {len(candidates)} opinions in this corpus; no "
                "case name was given to disambiguate, defaulted to the first)"
            ),
            opinion=self._opinion_dict(candidates[0]),
        )

    # -- coverage summary ----------------------------------------------------

    def coverage_summary(self) -> dict:
        all_opinions = self.ingested_opinions()
        reporters = {}
        for reporter, vols in self._volumes.items():
            vol_list = []
            for vol, vdata in sorted(vols.items(), key=lambda kv: int(kv[0])):
                ingested_count = sum(
                    1 for op in all_opinions
                    if op.reporter == reporter and op.volume == int(vol)
                )
                vol_list.append({
                    "volume": int(vol),
                    "complete": vdata["complete"],
                    "case_count": vdata["case_count"],
                    "distinct_first_pages_known": len(vdata["pages_present"]),
                    "opinions_with_full_text": ingested_count,
                })
            reporters[reporter] = vol_list
        return {
            "source": self.index.get("source"),
            "retrieved": self.index.get("retrieved"),
            "reporters": reporters,
            "total_opinions_with_full_text": len(all_opinions),
        }
