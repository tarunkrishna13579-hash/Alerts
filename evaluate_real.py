"""Measure the engine on real posting wording. Run: python evaluate_real.py [dev|heldout|all] [--captured DIR]
Reports accuracy and EVERY false-eligible / false-ineligible item. With --captured DIR it also lists what the engine says about full descriptions you captured
(CAPTURE_DIR from a bot run) so you can label them and add them to evaluation/real_labels.json."""
import sys, json, glob, os
import experience as E
from experience import Retrieval as R

def engine(excerpt, profile):
    d = E.Description(excerpt, R.FULL_EMPLOYER, "evaluation", "")
    req = E.extract_experience_requirements(d, profile.total_years, profile.tolerance)
    return req, E.evaluate_candidate_fit(req, profile)

def main(split="all"):
    data = json.load(open(os.path.join(os.path.dirname(__file__), "evaluation", "real_labels.json"), encoding="utf-8"))
    profile = E.CandidateProfile(2.2, {}, skill_mode="info")
    rows = [i for i in data["items"] if split in ("all", i["split"])]
    stats = dict(n=len(rows), scope_ok=0, bounds_ok=0, bounds_n=0, verdict_ok=0, false_elig=[], false_inelig=[], review=0)
    for it in rows:
        req, dec = engine(it["excerpt"], profile)
        st = next((s for s in req.statements if s.scope in (E.Scope.OVERALL, E.Scope.SKILL_SPECIFIC, E.Scope.ROLE_DOMAIN, E.Scope.UNKNOWN)), None)
        got_scope = "NONE" if st is None else "OVERALL" if st.scope == E.Scope.OVERALL else "SKILL_SPECIFIC" if st.scope == E.Scope.SKILL_SPECIFIC else "AMBIGUOUS"
        scope_ok = got_scope == it["expected_scope"] or (it["expected_scope"] == "AMBIGUOUS" and got_scope in ("AMBIGUOUS", "SKILL_SPECIFIC"))
        stats["scope_ok"] += scope_ok
        if st is not None and it["expected_min"] is not None:
            stats["bounds_n"] += 1; b_ok = (st.min_years, st.max_years) == (it["expected_min"], it["expected_max"]); stats["bounds_ok"] += b_ok
        else: b_ok = None
        v = dec.verdict.value; stats["verdict_ok"] += v == it["expected_verdict"]; stats["review"] += v == "NEEDS_REVIEW"
        if v == "ELIGIBLE" and it["expected_verdict"] != "ELIGIBLE": stats["false_elig"].append(it["id"])
        if v == "INELIGIBLE" and it["expected_verdict"] != "INELIGIBLE": stats["false_inelig"].append(it["id"])
        flag = "" if (scope_ok and b_ok in (True, None) and v == it["expected_verdict"]) else "   <-- MISMATCH"
        print(f"{it['id']} [{it['split']:7}] {it['excerpt'][:52]!r:56} scope {got_scope:14} bounds {None if st is None else (st.min_years, st.max_years)} -> {v:12} (expected {it['expected_verdict']}){flag}")
    n = stats["n"]
    print(f"\n[{split}] n={n}  scope accuracy {stats['scope_ok']}/{n}  exact bounds {stats['bounds_ok']}/{stats['bounds_n']}  verdict accuracy {stats['verdict_ok']}/{n}")
    print(f"       false-ELIGIBLE: {stats['false_elig'] or 'none'}   false-INELIGIBLE: {stats['false_inelig'] or 'none'}   sent to review: {stats['review']}/{n} ({100*stats['review']//max(n,1)}%)")
    print("       not measurable from single excerpts: conflict detection, mandatory-vs-preferred (all excerpts mandatory), source retrieval / completeness rate")
    return stats

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    s = main(args[0] if args else "all")
    if "--captured" in sys.argv:
        d = sys.argv[sys.argv.index("--captured") + 1]
        for f in sorted(glob.glob(os.path.join(d, "*.txt"))):
            lines = open(f, encoding="utf-8").read().split("\n", 1)
            req = E.extract_experience_requirements(E.Description(lines[1], R.FULL_EMPLOYER, "captured", ""))
            print(os.path.basename(f), "->", req.verification_status, req.overall and req.overall["raw_text"], "|", req.why)
    sys.exit(1 if s["false_elig"] else 0)           # a false-eligible item is a regression
