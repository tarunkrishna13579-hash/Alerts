"""Unit tests for the extraction + eligibility engine (synthetic inputs).  Run: python test_experience.py
These prove the RULES behave as specified. They do NOT prove accuracy on real postings - see evaluate_real.py for that."""
import sys
import experience as E
from experience import Retrieval as R, Verdict as V, Scope as S, ReqType as T

PAD = "We are looking for an engineer to join our team and build reliable services for our customers in an agile environment. "
P = E.CandidateProfile(total_years=2.2, skill_years={"Java": 2.2, "Spring Boot": 2.2, "Kafka": 2.2, "Redis": 2.2}, skill_mode="strict")
PASSED = FAILED = 0
ANY = object()                      # "an overall requirement is expected, but this test does not pin its wording"

def run(body, profile=P, status=R.FULL_EMPLOYER, pad=True):
    d = E.Description((PAD + "\n" + body) if pad else body, status, "test", "https://example.test/job")
    req = E.extract_experience_requirements(d, profile.total_years, profile.tolerance)
    return req, E.evaluate_candidate_fit(req, profile)

def case(name, body, verdict, overall=None, codes=(), skills=None, profile=P, status=R.FULL_EMPLOYER, pad=True, note=None):
    """overall = (raw_text, min, max) or None; skills = {(skill, min, requirement_type)}; codes must all be present"""
    global PASSED, FAILED
    try:
        req, dec = run(body, profile, status, pad)
        assert dec.verdict == verdict, f"verdict {dec.verdict.value} != {verdict.value} :: {dec.explanation} {dec.reason_codes}"
        if overall is ANY: assert req.overall, "expected a verified overall requirement"
        elif overall is None: assert req.overall is None or verdict != V.ELIGIBLE, req.overall
        else:
            assert req.overall and (req.overall["raw_text"].lower(), req.overall["min"], req.overall["max"]) == (overall[0].lower(), overall[1], overall[2]), req.overall
        for c in codes: assert c in dec.reason_codes, (c, dec.reason_codes)
        if skills is not None:
            got = {(s["skill"], s["min_years"], s["requirement_type"]) for s in req.skills}
            assert got == skills, got
        if note: assert note(req, dec), "extra check failed"
        PASSED += 1
    except AssertionError as e:
        FAILED += 1; print(f"FAIL  {name}\n      {e}")

M, PF = T.MANDATORY.value, T.PREFERRED.value

# 1-3: the three headline cases
case("1 overall 6+, AWS 2+, Java 3+", "Requirements:\n- 6+ years of overall professional experience.\n- 3+ years of experience in Java.\n- 2+ years of experience in AWS.",
     V.INELIGIBLE, ("6+ years", 6.0, None), ["OVERALL_ABOVE_PROFILE"], {("Java", 3.0, M), ("AWS", 2.0, M)})
case("2 overall 2+, mandatory AWS 6+ -> impossible for any 2.2-year career", "Requirements:\n- 2+ years of professional experience.\n- 6+ years of experience in AWS.",
     V.INELIGIBLE, ("2+ years", 2.0, None), ["SKILL_EXCEEDS_TOTAL_CAREER"], {("AWS", 6.0, M)})
case("2b same, impossible-rule switched off -> cannot verify -> review", "Requirements:\n- 2+ years of professional experience.\n- 6+ years of experience in AWS.",
     V.NEEDS_REVIEW, ("2+ years", 2.0, None), ["MANDATORY_SKILL_UNVERIFIABLE"], profile=E.CandidateProfile(2.2, P.skill_years, impossible_skill_is_ineligible=False, skill_mode="strict"))
case("3 overall 7.5 years, Java 2+", "Minimum 7.5 year(s) of experience is required\nJava: 2 years of experience",
     V.INELIGIBLE, ("7.5 year(s)", 7.5, None), ["OVERALL_ABOVE_PROFILE"], {("Java", 2.0, M)})

# 4: ranges keep both bounds
case("4 overall 2-4 years", "Requirements: 2-4 years of professional experience.", V.ELIGIBLE, ("2-4 years", 2.0, 4.0),
     note=lambda r, d: r.overall["bound_type"] == "RANGE" and r.overall["normalized"] == "2-4 years")
# 5: contradictory overall statements in different sections
case("5 overall 2-4 vs minimum 5 elsewhere", "Summary:\n2-4 years of professional experience.\nBasic qualifications:\nMinimum 5 years of professional experience.", V.NEEDS_REVIEW, None, ["CONFLICTING_OVERALL"],
     note=lambda r, d: len(r.conflicts) == 1)
# 6: compatible statements -> stricter minimum, both preserved, derivation documented
case("6 overall 2+ and minimum 3+ (same role)", "Summary:\n2+ years of professional experience.\nBasic qualifications:\nMinimum 3 years of professional experience.", V.INELIGIBLE, ANY, ["OVERALL_ABOVE_PROFILE"],
     note=lambda r, d: r.overall["min"] == 3.0 and "2+ years" in r.overall["raw_text"] and "3 years" in r.overall["raw_text"] and "intersection" in r.overall["derivation"])
case("6b 2-4 and 2+ are compatible", "Summary: 2-4 years of professional experience.\nQualifications: 2+ years of professional experience.", V.ELIGIBLE, ANY,
     note=lambda r, d: (r.overall["min"], r.overall["max"]) == (2.0, 4.0))

# 7: several skills with different durations (only your recorded skills can be checked)
case("7a Java 2, Spring Boot 2, Kafka 1, Redis 1 -> all within profile", "Requirements:\n- 2-4 years of experience in software development.\n- 2+ years of Java experience.\n- 2 years of experience with Spring Boot.\n- 1+ years of experience in Kafka.\n- 1 year of Redis experience.",
     V.ELIGIBLE, ("2-4 years", 2.0, 4.0), skills={("Java", 2.0, M), ("Spring Boot", 2.0, M), ("Kafka", 1.0, M), ("Redis", 1.0, M)})
case("7b Java 3 vs profile 2.2 (no free allowance)", "Requirements:\n- 2-4 years of experience in software development.\n- 3+ years of experience in Java.", V.INELIGIBLE, ("2-4 years", 2.0, 4.0), ["SKILL_ABOVE_PROFILE"])
case("7c mandatory AWS 2, no recorded AWS experience -> review (no assumption)", "Requirements:\n- 2-4 years of experience in software development.\n- 2+ years of experience in AWS.", V.NEEDS_REVIEW, ("2-4 years", 2.0, 4.0), ["MANDATORY_SKILL_UNVERIFIABLE"])
case("19 candidate skill duration unknown (Docker)", "Requirements:\n- 2+ years of professional experience.\n- 1+ years of experience in Docker.", V.NEEDS_REVIEW, ("2+ years", 2.0, None), ["MANDATORY_SKILL_UNVERIFIABLE"])

# 8, 21: preferred is not mandatory
case("8 preferred overall must not count", "Requirements:\n- 2+ years of professional experience.\nPreferred qualifications:\n- 5+ years of professional experience.", V.ELIGIBLE, ("2+ years", 2.0, None))
case("8b only preferred overall -> review", "Preferred qualifications:\n- 5+ years of professional experience.", V.NEEDS_REVIEW, None, ["ONLY_PREFERRED"])
case("21 preferred 6-year AWS does not block", "Requirements:\n- 2+ years of professional experience.\nNice to have:\n- 6+ years of experience in AWS.", V.ELIGIBLE, ("2+ years", 2.0, None), skills={("AWS", 6.0, PF)})
case("21b 'is a plus' wording", "Requirements:\n- 2+ years of professional experience.\n- 6 years of experience in AWS is a plus.", V.ELIGIBLE, ("2+ years", 2.0, None), skills={("AWS", 6.0, PF)})

# 9, 10: education / company history excluded; headings are not education
case("9 education and company history excluded", "About us:\nWe have 30 years of experience in consulting.\nRequirements:\nBachelor's degree (15 years full time education) and 2+ years of professional experience.", V.ELIGIBLE, ("2+ years", 2.0, None),
     note=lambda r, d: {s.scope for s in r.statements} >= {S.EDUCATION, S.COMPANY_HISTORY, S.OVERALL})
case("10 'Basic Qualifications' is not education", "Basic qualifications: 6+ years of overall experience, including 3 years in Java.", V.INELIGIBLE, ("6+ years", 6.0, None), ["OVERALL_ABOVE_PROFILE"], {("Java", 3.0, M)})

# 11, 12: skill vs role-domain
case("11 '3 years in Java' is skill-specific", "Requirements:\n- 3 years in Java.", V.INELIGIBLE, None, ["SKILL_ABOVE_PROFILE"], {("Java", 3.0, M)})
case("12 '5 years of backend development' -> ambiguous, not guessed", "Requirements:\n- 5 years of backend development.", V.NEEDS_REVIEW, None, ["AMBIGUOUS_STATEMENT"],
     note=lambda r, d: r.statements[0].scope == S.ROLE_DOMAIN and r.statements[0].classification_status == "AMBIGUOUS")
case("12b ambiguous domain years next to a clear overall 2+ -> review", "Requirements:\n- 2+ years of professional experience.\n- 5 years of backend development.", V.NEEDS_REVIEW, None, ["AMBIGUOUS_STATEMENT"])
case("12c domain years below my profile do not matter", "Requirements:\n- 2+ years of professional experience.\n- 1 year of backend development.", V.ELIGIBLE, ("2+ years", 2.0, None))

# 13, 14: wording variants and bound types
for name, body, rawl, lo, hi, bound in [("13 five-plus", "We want five-plus years of experience.", "five-plus years", 5.0, None, "MINIMUM"),
                                        ("13 spelled-out range", "You bring two to four years of professional experience.", "two to four years", 2.0, 4.0, "RANGE"),
                                        ("13 decimal + year(s)", "Minimum 7.5 year(s) of experience is required.", "7.5 year(s)", 7.5, None, "MINIMUM"),
                                        ("13 typographic apostrophe", "With a minimum of 3 years\u2019 experience working in a software development role.", "3 years", 3.0, None, "MINIMUM"),
                                        ("14 between X and Y", "Candidates need between 2 and 4 years of experience.", "between 2 and 4 years", 2.0, 4.0, "RANGE"),
                                        ("14 at least", "At least 2 years of professional experience.", "2 years", 2.0, None, "MINIMUM"),
                                        ("14 2+", "2+ years of industry experience.", "2+ years", 2.0, None, "MINIMUM"),
                                        ("14 header style", "Exp: 4-6 Years", "4-6 Years", 4.0, 6.0, "RANGE"),
                                        ("14 value on the next line", "Experience Required :\nMinimum 4 Years", "4 Years", 4.0, None, "MINIMUM"),
                                        ("14 parenthetical", "Team Leader (7-10 Years Experience).", "7-10 Years", 7.0, 10.0, "RANGE")]:
    case(name, body, V.INELIGIBLE if lo > 2.2 else V.ELIGIBLE, (rawl, lo, hi), note=lambda r, d, b=bound: r.overall["bound_type"] == b)
req, _ = run("Requirements:\n- Up to 3 years of experience in a similar role.\n- 2+ years of professional experience.")
assert any(s.bound_type == E.Bound.MAXIMUM and s.max_years == 3.0 and s.min_years is None for s in req.statements) and req.overall["min"] == 2.0; PASSED += 1
req, _ = run("Exactly 2 years of professional experience."); assert req.statements[0].bound_type == E.Bound.EXACT; PASSED += 1
case("14 'exp' with a skill word: Total exp 4+ years in Java development", "Total exp of 4+ years in Java Development.", V.INELIGIBLE, ("4+ years", 4.0, None))

# 15, 16, 18: missing / conflicting / repeated statements
case("15 no overall statement (skills only)", "Requirements:\n- Strong Java skills.\n- 2+ years of experience in Java.", V.NEEDS_REVIEW, None, ["NO_OVERALL_STATEMENT"])
case("15b no experience statement at all", "Build services in Java and Spring Boot. Great culture and benefits.", V.NEEDS_REVIEW, None, ["NO_OVERALL_STATEMENT"])
case("16 conflicting", "Requirements: 2-4 years of experience. Also, minimum 6 years of experience.", V.NEEDS_REVIEW, None, ["CONFLICTING_OVERALL"])
case("18 repeated identical statements in several sections", "Summary: 2-4 years of professional experience.\nQualifications:\n2-4 years of professional experience.\nRequirements:\n2-4 years of professional experience.", V.ELIGIBLE, ("2-4 years", 2.0, 4.0))
case("18b repeated section, one contradicts", "Summary: 2-4 years of professional experience.\nQualifications:\n2-4 years of professional experience.\nRequirements:\nMinimum 6 years of professional experience.", V.NEEDS_REVIEW, None, ["CONFLICTING_OVERALL"])

# 17: description completeness is decided by retrieval status, not by length
case("17a snippet only, even with a clear statement", "2-4 years of professional experience. Java.", V.NEEDS_REVIEW, None, ["DESCRIPTION_NOT_FULL"], status=R.PARTIAL_SNIPPET)
case("17b inaccessible", "", V.NEEDS_REVIEW, None, ["DESCRIPTION_NOT_FULL"], status=R.INACCESSIBLE, pad=False)
case("17c empty", "", V.NEEDS_REVIEW, None, ["DESCRIPTION_NOT_FULL"], status=R.EMPTY, pad=False)
req, dec = run("2-4 years of professional experience.", pad=False)                  # short but fully retrieved: length is only a WARNING
assert dec.verdict == V.ELIGIBLE and "SHORT_DESCRIPTION" in req.description["warnings"]; PASSED += 1
req, dec = run(PAD * 3, status=R.FULL_EMPLOYER); assert dec.verdict == V.NEEDS_REVIEW; PASSED += 1   # long text without any statement is not "complete evidence"

# 20: candidate with 2.2 years vs 2+, 3+, 2-4
for body, want in [("2+ years of professional experience.", V.ELIGIBLE), ("3+ years of professional experience.", V.INELIGIBLE), ("2-4 years of professional experience.", V.ELIGIBLE)]:
    case("20 " + body, body, want, ANY)
case("20 0-2 years: your 2.2 is above the top of the range", "0-2 years of professional experience.", V.ELIGIBLE, ("0-2 years", 0.0, 2.0))
case("20 0-1 years fails", "0-1 years of professional experience.", V.INELIGIBLE, None, ["RANGE_BELOW_PROFILE"])
case("20 fresher wording", "Freshers can apply for this role. Java.", V.ELIGIBLE, ("fresher / entry-level", 0.0, None))

# negatives: misleading wording, unrelated numbers, tables, nested bullets, duplicated text, unknown scope
case("N1 'within 3-5 years' is not a requirement", "Join us and grow within 3-5 years with the company. Java.", V.NEEDS_REVIEW, None, ["NO_OVERALL_STATEMENT"])
case("N2 company plans", "In 5 years we plan to double our team. Java developer role.", V.NEEDS_REVIEW, None, ["NO_OVERALL_STATEMENT"])
case("N3 nested bullets", "Requirements:\n  - Core skills:\n    - 2-4 years of professional experience\n    - 1+ years of experience in Kafka", V.ELIGIBLE, ("2-4 years", 2.0, 4.0), skills={("Kafka", 1.0, M)})
case("N4 table rows", "Skill | Years\nOverall | 2-4 years\nJava | 3+ years", V.INELIGIBLE, ("2-4 years", 2.0, 4.0), ["SKILL_ABOVE_PROFILE"], {("Java", 3.0, M)})
case("N5 duplicated JD text", ("Requirements: 2-4 years of professional experience.\n") * 3, V.ELIGIBLE, ("2-4 years", 2.0, 4.0))
case("N6 duration with unknown scope", "Requirements:\n- 4 years.", V.NEEDS_REVIEW, None)
case("N7 years of age / unrelated", "Candidates must be at least 18 years old. Experience: 2-4 years.", V.ELIGIBLE, ("2-4 years", 2.0, 4.0))
case("N8 'responsibilities' sentence mentioning years", "Responsibilities:\n- Mentor engineers who have 5 years of experience.\nRequirements:\n- 2+ years of professional experience.", V.ELIGIBLE, ("2+ years", 2.0, None))

# evidence is traceable: offsets point at the exact raw text
txt = PAD + "\nRequirements:\n- 2-4 years of professional experience."
req = E.extract_experience_requirements(E.Description(txt, R.FULL_EMPLOYER, "t", "u"))
st = [s for s in req.statements if s.scope == S.OVERALL][0]
assert txt[st.evidence_start: st.evidence_end] == st.raw_text == "2-4 years" and st.source_section == "Requirements"; PASSED += 1
assert E.Description("x", R.PARTIAL_SNIPPET).complete is False and E.Description("x", R.FULL_JOBBOARD).complete is True; PASSED += 1

# skill_mode="info": skill years are recorded and shown but never decide (your latest instruction: experience match only)
INFO = E.CandidateProfile(2.2, {"Java": 2.2}, skill_mode="info")
req, dec = run("Requirements:\n- 2-4 years of professional experience.\n- 6+ years of experience in AWS.\n- 3+ years of experience in Java.", INFO)
assert dec.verdict == V.ELIGIBLE and {c["result"] for c in dec.skill_checks} == {"NOTE"} and "information only" in dec.explanation; PASSED += 1
req, dec = run("Requirements:\n- 3+ years of professional experience.\n- 1+ years of experience in Java.", INFO); assert dec.verdict == V.INELIGIBLE; PASSED += 1   # overall still decides

print(f"\n{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
