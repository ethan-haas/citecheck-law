#!/usr/bin/env python3
"""Component A — corpus acquisition (citecheck-law).

Source: Caselaw Access Project static bulk (https://static.case.law), public-domain
U.S. court opinions. No API key, no bot wall — plain HTTP JSON.

Two-tier corpus:
  * complete-volume metadata  -> authoritative membership of every case in a reporter
    volume (id, name, citations, page range, court, date). Lets the verifier tell
    "not found" (a covered, complete volume has no such case) from "cannot verify"
    (the reporter/volume is not in the corpus at all).
  * full opinion text         -> for the cases we ingest, so a cited proposition can
    be checked as a literal span in the real opinion.

Manifest entry shapes (corpus/acquire_manifest.json -> "volumes": [...]):
  {"reporter_slug": "us", "volume": 347, "text_pages": [483]}
      one explicit volume; pull text for the listed first-pages (curated landmarks).
  {"reporter_slug": "a2d", "auto_volumes": 2, "text_first_n": 6}
      auto-pick N volumes evenly across the reporter's range; pull text for the first
      M cases (by page order) of each. No page-guessing — used for breadth.
  {"reporter_slug": "f2d", "volumes": [148, 159], "text_first_n": 4}
      explicit volumes, first M cases each.

The reporter citation string ("A.2d", "F. Supp. 2d") is derived from the cases'
own official citations, so no reporter is hand-mapped.

Output (all under corpus/):
  store/<opinion_id>.json   one normalized opinion (metadata + full text)
  index.json                coverage: reporter -> volume -> {complete, pages_present}
  manifest.json             per-document provenance (source URL + retrieval date)

Deterministic: same manifest -> same corpus. Re-runs are idempotent (cached files reused).
"""
from __future__ import annotations
import json, re, sys, time, urllib.request, urllib.error, hashlib, datetime
from pathlib import Path

BASE = "https://static.case.law"
UA = "citecheck-law/0.2 (public-domain corpus builder)"
HERE = Path(__file__).resolve().parent
STORE = HERE / "store"
CACHE = HERE / ".httpcache"

# optional canonical-reporter overrides (most reporters are derived from cites)
SLUG_OVERRIDE = {"us": "U.S."}

_CITE_RE = re.compile(r"^\s*(\d+)\s+(.*?)\s+(\d+[A-Za-z]*)\s*$")


def _http_get(url: str, retries: int = 4) -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".bin")
    if key.exists():
        return key.read_bytes()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read()
            key.write_bytes(data)
            time.sleep(0.12)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries}: {url}: {last}")


def get_json(url: str):
    return json.loads(_http_get(url).decode("utf-8", "replace"))


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def volume_metadata(slug: str, volume: int) -> list[dict]:
    return get_json(f"{BASE}/{slug}/{volume}/CasesMetadata.json")


def volume_numbers(slug: str) -> list[int]:
    vm = get_json(f"{BASE}/{slug}/VolumesMetadata.json")
    out = []
    for v in vm:
        n = _as_int(v.get("volume_number"))
        if isinstance(n, int):
            out.append(n)
    return sorted(set(out))


def pick_evenly(items: list, n: int) -> list:
    if n >= len(items):
        return list(items)
    if n <= 1:
        return [items[len(items) // 2]]
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


def derive_reporter(slug: str, cases: list[dict]) -> str:
    if slug in SLUG_OVERRIDE:
        return SLUG_OVERRIDE[slug]
    for c in cases:
        for cit in c.get("citations") or []:
            if cit.get("type") == "official":
                m = _CITE_RE.match(cit.get("cite", ""))
                if m:
                    return m.group(2)
    # fallback: slug uppercased
    return slug.upper()


def opinion_text(casebody: dict) -> str:
    data = casebody.get("data") if isinstance(casebody.get("data"), dict) else casebody
    parts = [op.get("text") for op in (data.get("opinions") or []) if op.get("text")]
    return "\n\n".join(parts)


def normalize_case(reporter: str, slug: str, volume: int, case: dict,
                   src_url: str, retrieved: str) -> dict:
    official, cites = None, []
    for c in case.get("citations") or []:
        cites.append({"type": c.get("type"), "cite": c.get("cite")})
        if c.get("type") == "official" and official is None:
            official = c.get("cite")
    cb = case.get("casebody") or {}
    text = opinion_text(cb)
    court = case.get("court") or {}
    return {
        "opinion_id": f"cap-{case['id']}",
        "cap_id": case["id"],
        "name": case.get("name"),
        "name_abbreviation": case.get("name_abbreviation"),
        "reporter": reporter,
        "reporter_slug": slug,
        "volume": volume,
        "first_page": _as_int(case.get("first_page")),
        "last_page": _as_int(case.get("last_page")),
        "official_citation": official,
        "citations": cites,
        "court": court.get("name") if isinstance(court, dict) else court,
        "court_slug": court.get("slug") if isinstance(court, dict) else None,
        "jurisdiction": (case.get("jurisdiction") or {}).get("name")
        if isinstance(case.get("jurisdiction"), dict) else case.get("jurisdiction"),
        "decision_date": case.get("decision_date"),
        "docket_number": case.get("docket_number"),
        "text": text,
        "text_len": len(text),
        "source_url": src_url,
        "retrieved": retrieved,
    }


def expand_entries(spec: dict) -> list[tuple]:
    """Yield (slug, volume, mode, arg) work items from the manifest."""
    work = []
    for e in spec["volumes"]:
        slug = e["reporter_slug"]
        if "auto_volumes" in e:
            vols = pick_evenly(volume_numbers(slug), int(e["auto_volumes"]))
        elif "volumes" in e:
            vols = [int(v) for v in e["volumes"]]
        else:
            vols = [int(e["volume"])]
        for v in vols:
            if "text_pages" in e:
                work.append((slug, v, "pages", set(int(p) for p in e["text_pages"])))
            elif "text_first_n" in e:
                work.append((slug, v, "first_n", int(e["text_first_n"])))
            else:
                work.append((slug, v, "first_n", 0))
    return work


def main() -> int:
    spec = json.loads((HERE / "acquire_manifest.json").read_text(encoding="utf-8"))
    retrieved = datetime.date.today().isoformat()
    STORE.mkdir(parents=True, exist_ok=True)

    index: dict = {"reporters": {}}
    provenance: list[dict] = []
    seen_vol: set = set()

    for slug, volume, mode, arg in expand_entries(spec):
        try:
            cases = volume_metadata(slug, volume)
        except Exception as e:  # noqa: BLE001
            print(f"[skip] {slug} {volume}: {e}", flush=True)
            continue
        reporter = derive_reporter(slug, cases)
        vmeta_url = f"{BASE}/{slug}/{volume}/CasesMetadata.json"
        print(f"[vol] {reporter} {volume} ({len(cases)} cases)", flush=True)

        pages_present = sorted({_as_int(c.get("first_page")) for c in cases
                                if isinstance(_as_int(c.get("first_page")), int)})
        rep = index["reporters"].setdefault(reporter, {"slug": slug, "volumes": {}})
        rep["volumes"][str(volume)] = {
            "complete": True, "case_count": len(cases),
            "pages_present": pages_present, "source_url": vmeta_url, "retrieved": retrieved,
        }

        # choose cases to pull text for
        if mode == "pages":
            targets = [c for c in cases if _as_int(c.get("first_page")) in arg]
        else:  # first_n, ordered by first_page
            ordered = sorted(cases, key=lambda c: (_as_int(c.get("first_page"))
                             if isinstance(_as_int(c.get("first_page")), int) else 10**9))
            targets = ordered[:arg] if arg else []

        pulled = 0
        for c in targets:
            fn = c.get("file_name")
            case_url = f"{BASE}/{slug}/{volume}/cases/{fn}.json"
            try:
                full = get_json(case_url)
            except Exception as e:  # noqa: BLE001
                print(f"    [skip] {case_url}: {e}", flush=True)
                continue
            doc = normalize_case(reporter, slug, volume, full, case_url, retrieved)
            if not doc["text"]:
                continue  # skip textless stubs
            if not isinstance(doc["first_page"], int):
                continue  # skip prefatory/table matter (non-numeric page, e.g. "(1)") — not citable
            (STORE / f"{doc['opinion_id']}.json").write_text(
                json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            provenance.append({
                "opinion_id": doc["opinion_id"],
                "name_abbreviation": doc["name_abbreviation"],
                "official_citation": doc["official_citation"],
                "source_url": case_url, "retrieved": retrieved, "text_len": doc["text_len"],
            })
            pulled += 1
        rep["volumes"][str(volume)]["text_pulled"] = pulled
        print(f"    [text] pulled {pulled}", flush=True)

    index["retrieved"] = retrieved
    index["source"] = "Caselaw Access Project (static.case.law), public domain"
    (HERE / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    (HERE / "manifest.json").write_text(
        json.dumps(sorted(provenance, key=lambda d: d["opinion_id"]),
                   ensure_ascii=False, indent=2), encoding="utf-8")

    n_docs = len(provenance)
    n_vols = sum(len(r["volumes"]) for r in index["reporters"].values())
    print(f"\nDONE: {n_docs} opinions with text, {n_vols} complete volumes, "
          f"{len(index['reporters'])} reporters.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
