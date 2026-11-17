#!/usr/bin/env python3
"""Conflict-aware JSON state merge for concurrent GitHub Actions state commits.

Usage: python merge_state.py --resolve-conflicts
Only resolves unmerged state/*.json files. Job records are unioned by stable key;
a published record is never downgraded to pending/none.
"""
import json
import subprocess
import sys
from pathlib import Path


def git(*args, check=True):
    return subprocess.run(["git", *args], check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def stage_json(stage, path):
    p = git("show", f":{stage}:{path}", check=False)
    if p.returncode:
        return {}
    try:
        return json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        raise RuntimeError(f"Cannot parse stage {stage} JSON for {path}")


def unique_list(*values):
    out, seen = [], set()
    for value in values:
        if not isinstance(value, list):
            continue
        for item in value:
            key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key); out.append(item)
    return out


def merge_value(base, ours, theirs, path=()):
    if ours == theirs: return ours
    if ours == base: return theirs
    if theirs == base: return ours
    key = path[-1] if path else ""
    if isinstance(ours, dict) and isinstance(theirs, dict):
        base = base if isinstance(base, dict) else {}
        out = {}
        for k in set(base) | set(ours) | set(theirs):
            if k not in ours and k not in theirs: continue
            b, o, t = base.get(k), ours.get(k), theirs.get(k)
            if k not in ours: out[k] = t; continue
            if k not in theirs: out[k] = o; continue
            out[k] = merge_value(b, o, t, path + (k,))
        return out
    if isinstance(ours, list) and isinstance(theirs, list):
        return unique_list(ours, theirs)
    if isinstance(ours, (int, float)) and isinstance(theirs, (int, float)) and not isinstance(ours, bool) and not isinstance(theirs, bool):
        if key in {"counters", "by_company"}:
            b = base if isinstance(base, (int, float)) else 0
            return max(0, b + (ours - b) + (theirs - b))
        if key in {"first_seen"}:
            return min(ours, theirs)
        if key in {"last_checked", "last_retrieval", "first_published", "ok_ts", "err_ts", "tried", "timestamp"}:
            return max(ours, theirs)
        return max(ours, theirs)
    if key == "publication":
        # Delivery is monotonic: once confirmed published, never requeue it.
        if "published" in (ours, theirs): return "published"
        if "pending" in (ours, theirs): return "pending"
    if key == "eligibility":
        # The caller's record merge selects the most recently checked record; this is a safe fallback.
        return theirs
    return theirs


def merge_job_record(base, ours, theirs):
    b = base if isinstance(base, dict) else {}
    o = ours if isinstance(ours, dict) else {}
    t = theirs if isinstance(theirs, dict) else {}
    merged = merge_value(b, o, t, ("jobs",))
    # Merge fields with monotonic / history-preserving semantics.
    merged["first_seen"] = min(x for x in (o.get("first_seen"), t.get("first_seen")) if isinstance(x, (int, float))) if any(isinstance(x, (int, float)) for x in (o.get("first_seen"), t.get("first_seen"))) else merged.get("first_seen")
    for field in ("paths", "relisted"):
        if field in o or field in t: merged[field] = unique_list(o.get(field), t.get(field))
    if "published" in (o.get("publication"), t.get("publication")):
        merged["publication"] = "published"
        merged.pop("relist_alert", None)
    elif "pending" in (o.get("publication"), t.get("publication")):
        merged["publication"] = "pending"
    merged["last_checked"] = max(x for x in (o.get("last_checked"), t.get("last_checked")) if isinstance(x, (int, float))) if any(isinstance(x, (int, float)) for x in (o.get("last_checked"), t.get("last_checked"))) else merged.get("last_checked")
    merged["last_retrieval"] = max(x for x in (o.get("last_retrieval"), t.get("last_retrieval")) if isinstance(x, (int, float))) if any(isinstance(x, (int, float)) for x in (o.get("last_retrieval"), t.get("last_retrieval"))) else merged.get("last_retrieval")
    return merged


def merge_db(base, ours, theirs):
    base = base if isinstance(base, dict) else {}
    ours = ours if isinstance(ours, dict) else {}
    theirs = theirs if isinstance(theirs, dict) else {}
    out = merge_value(base, ours, theirs, ())
    bjobs, ojobs, tjobs = base.get("jobs", {}), ours.get("jobs", {}), theirs.get("jobs", {})
    jobs = {}
    for key in set(bjobs) | set(ojobs) | set(tjobs):
        b, o, t = bjobs.get(key), ojobs.get(key), tjobs.get(key)
        if o is None: jobs[key] = t
        elif t is None: jobs[key] = o
        else: jobs[key] = merge_job_record(b, o, t)
    out["jobs"] = jobs
    # Rebuild fingerprints from both histories, dropping references to absent records.
    fp = {}
    for src in (ours.get("fp", {}), theirs.get("fp", {})):
        for fingerprint, keys in (src or {}).items():
            fp[fingerprint] = unique_list(fp.get(fingerprint, []), keys)
    out["fp"] = {k: [job_key for job_key in keys if job_key in jobs] for k, keys in fp.items() if any(job_key in jobs for job_key in keys)}
    out["legacy_seen"] = merge_value(base.get("legacy_seen", {}), ours.get("legacy_seen", {}), theirs.get("legacy_seen", {}), ("legacy_seen",))
    # Counters are accumulated as independent run deltas, not overwritten by whichever run committed last.
    bm, om, tm = base.get("meta", {}), ours.get("meta", {}), theirs.get("meta", {})
    meta = merge_value(bm, om, tm, ("meta",))
    for field in ("counters", "by_company"):
        bdict, odict, tdict = bm.get(field, {}), om.get(field, {}), tm.get(field, {})
        merged_counts = {}
        for k in set(bdict) | set(odict) | set(tdict):
            b, o, t = bdict.get(k, 0), odict.get(k, 0), tdict.get(k, 0)
            if all(isinstance(v, (int, float)) for v in (b, o, t)):
                merged_counts[k] = max(0, b + (o - b) + (t - b))
            else: merged_counts[k] = o if o != b else t
        meta[field] = merged_counts
    out["meta"] = meta
    return out


def main():
    if sys.argv[1:] != ["--resolve-conflicts"]:
        raise SystemExit("usage: python merge_state.py --resolve-conflicts")
    paths = git("diff", "--name-only", "--diff-filter=U").stdout.splitlines()
    if not paths: return
    for path in paths:
        if not path.startswith("state/") or not path.endswith(".json"):
            raise RuntimeError(f"Refusing to auto-resolve non-state JSON conflict: {path}")
        base, ours, theirs = (stage_json(i, path) for i in (1, 2, 3))
        if path == "state/db.json": merged = merge_db(base, ours, theirs)
        else: merged = merge_value(base, ours, theirs, ())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(merged, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        git("add", path)
        print(f"Merged concurrent state safely: {path}")


if __name__ == "__main__":
    main()
