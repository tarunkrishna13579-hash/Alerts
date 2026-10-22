"""Offline tests (no internet). Run: python test_watcher.py"""
import sys, json, pathlib, tempfile, os, types, io, contextlib, datetime as dt, time as _time
sys.argv = [sys.argv[0]]
import watcher as w
CONFIG_COMPANIES = list(w.CFG["companies"])
CONFIG_PRIORITY = list(w.CFG.get("priority_companies", []))

PAD = ("We are looking for a motivated engineer to join our team and build reliable services for our customers. "
       "You will work with product owners and other engineers in an agile environment. ")
def jd(body): return PAD + "\n" + body

# ============ A. experience extraction: overall vs skill-specific ============
def check(name, body, status, lo=None, hi=None, orig=None, fit=None, skills=None, why=None):
    ex = w.extract_experience(jd(body))
    assert ex["verification_status"] == status, (name, ex)
    if status == "VERIFIED":
        assert (ex["overall_experience_min"], ex["overall_experience_max"]) == (lo, hi), (name, ex)
        if orig: assert ex["overall_experience_original_text"].lower() == orig.lower(), (name, ex["overall_experience_original_text"])
    if skills is not None:
        got = {(s["skill"], s["min"], s["mandatory"]) for s in ex["skill_specific_experience"]}
        assert got == skills, (name, got)
    if fit: assert w.evaluate_fit(ex)[0] == fit, (name, w.evaluate_fit(ex))
    if why: assert why in (ex["why"] + w.evaluate_fit(ex)[1]), (name, ex["why"], w.evaluate_fit(ex))
    return ex

check("overall 6, AWS 2, Java 3", "Requirements:\n- 6+ years of overall professional experience.\n- 3+ years of experience in Java.\n- 2+ years of experience in AWS.",
      "VERIFIED", 6.0, None, "6+ years", "ineligible", {("Java", 3.0, True), ("AWS", 2.0, True)})
check("overall 2, AWS 6 (mandatory)", "Requirements:\n- 2+ years of professional experience.\n- 6+ years of experience in AWS.",
      "VERIFIED", 2.0, None, "2+ years", "ineligible", {("AWS", 6.0, True)}, why="AWS")        # overall stays 2+; AWS kept separate and judged separately
check("overall 7.5, Java 2", "Minimum 7.5 year(s) of experience is required\nJava: 2 years of experience\nEducational Qualification : 15 years full time education",
      "VERIFIED", 7.5, None, "7.5 year(s)", "ineligible", {("Java", 2.0, True)})
check("multiple skills, different numbers", "Qualifications:\n- 2-4 years of experience in software development.\n- 3+ years of experience with Java.\n- 2+ years of Spring Boot experience.\n- 1+ years of experience in Kafka.",
      "VERIFIED", 2.0, 4.0, "2-4 years", "eligible", {("Java", 3.0, True), ("Spring Boot", 2.0, True), ("Kafka", 1.0, True)})
check("range word form", "You bring two to four years of professional experience building services.", "VERIFIED", 2.0, 4.0, "two to four years", "eligible")
check("range 0-2 still fits 2.2", "0-2 years of experience in a similar role.", "VERIFIED", 0.0, 2.0, "0-2 years", "eligible")
check("range 3-5 too high", "3-5 years of experience in software engineering.", "VERIFIED", 3.0, 5.0, "3-5 years", "ineligible")
check("range 1 to 3", "1 to 3 years of relevant experience.", "VERIFIED", 1.0, 3.0, "1 to 3 years", "eligible")
check("preferred does not count", "Requirements:\n- 2+ years of experience.\nPreferred qualifications:\n- 5+ years of experience.\n- 6+ years of experience in AWS.",
      "VERIFIED", 2.0, None, "2+ years", "eligible", {("AWS", 6.0, False)})                  # preferred AWS never blocks
check("only preferred overall -> review", "Preferred qualifications:\n- 5+ years of experience in the industry.", "NEEDS_REVIEW", fit="needs_review", why="only preferred")
check("skill only, no overall -> review", "Requirements:\n- 3+ years of experience in Java.", "NEEDS_REVIEW", fit="needs_review", skills={("Java", 3.0, True)}, why="no overall")
check("missing experience entirely", "Build services in Java and Spring Boot. Great culture and benefits.", "NEEDS_REVIEW", fit="needs_review")
check("conflicting overall", "Summary: 2-4 years of experience.\nRequirements:\n- Minimum 5 years of experience.", "NEEDS_REVIEW", fit="needs_review", why="conflicting")
check("consistent overall statements", "Summary: 2-4 years of experience.\nRequirements:\n- 2+ years of professional experience.", "VERIFIED", 2.0, 4.0, "2-4 years", "eligible")
check("overall and skill in one sentence", "Basic qualifications: 6+ years of overall experience, including 3 years in Java.", "VERIFIED", 6.0, None, "6+ years", "ineligible", {("Java", 3.0, True)})
check("inline label line (Accenture style)", "Project Role : Data Architect\nGood to have skills : AWS, Databricks\nMinimum 7.5 year(s) of experience is required\nEducational Qualification : 15 years full time education",
      "VERIFIED", 7.5, None, "7.5 year(s)", "ineligible")
check("experience in a late section", "About us:\nWe have 30 years of experience in consulting.\nResponsibilities:\n- Build APIs.\nMinimum qualifications:\n- 2 years of experience in backend development.",
      "VERIFIED", 2.0, None, "2 years", "eligible")
check("education years ignored", "A bachelor's degree (15 years full time education) and 2+ years of experience are required.", "VERIFIED", 2.0, None, "2+ years", "eligible")
short = w.extract_experience("2+ years of experience"); assert short["verification_status"] == "NEEDS_REVIEW" and "incomplete" in short["why"]
assert w.extract_experience(jd("Freshers welcome, entry level role."))["overall_experience_min"] == 0.0
print("A. experience extraction (overall vs skill-specific, ranges, preferred, missing, conflicting, incomplete, sections): OK")

# analyze: Java must be asked for; incomplete job-board snippets are never trusted
j = dict(id="1", title="Software Engineer", loc="Hyderabad", req="R1", url="u", posted="Today", age=0)
assert w.analyze(j, jd("Java Spring Boot. 2-4 years of experience."), None)[0] == "eligible"
assert w.analyze(j, jd("Python Django. 2-4 years of experience."), None) == ("ineligible", {"why": "no Java in description"})
assert w.analyze(j, jd("JavaScript React. 2-4 years of experience."), None)[0] == "ineligible"
assert w.analyze(j, jd("Java. 2-4 years of experience."), "Pune, India")[0] == "ineligible"
assert w.analyze(dict(j, incomplete=True, trust_java=True), "Java 2-4 years of experience", None)[0] == "needs_review"
v, info = w.analyze(j, jd("Java. Requirements: 2-4 years of experience. 3+ years of experience in Java."), None)
msg = w.fmt("Acme", j, info)
assert "Overall experience (verified): 2-4 years" in msg and "Skill-specific (not overall): Java 3+ years (mandatory)" in msg, msg
print("alert example:\n" + msg)

# ============ B. persistent database: dedupe, retries, restarts ============
def fresh(companies, resolved):
    d = pathlib.Path(tempfile.mkdtemp())
    w.DB_F, w.SEEN_F, w.RES_F = d / "db.json", d / "seen.json", d / "res.json"
    w.CFG["companies"] = companies; w.RES_F.write_text(json.dumps(resolved)); w.F["use_title_filter"] = False
def co(name): return dict(name=name, url="u", match=name.lower(), tier="1")
def job(req, title="Java Developer", loc="Bengaluru", path=None, posted="Posted Today", age=0):
    return dict(id=path or f"/job/{title.replace(' ', '-')}_{req}-1", req=req, title=title, loc=loc, url=f"https://x/{req}", posted=posted, age=age)
class Net:
    def __init__(s): s.jobs = {}; s.detail_calls = 0; s.sent = []; s.tg_ok = True; s.text = jd("Java Spring Boot developer. 2-4 years of professional experience.")
    def install(s):
        w.LIST["workday"] = lambda r: list(s.jobs.get(r["api"], []))
        def det(r, j_): s.detail_calls += 1; return (s.text, "Bengaluru")
        w.DETAIL["workday"] = det
        def snd(t):
            if not s.tg_ok: return False
            s.sent.append(t); return True
        w.send = snd; w.time = types.SimpleNamespace(time=_time.time, sleep=lambda x: None)
    def counters(s): return json.load(open(w.DB_F))["meta"].get("counters", {})
WD = lambda: {"type": "workday", "api": "ACC", "web": "W"}
def quiet_run(n=1):
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(n): w.main()
def alerts(n): return [m for m in n.sent if m.startswith("🆕")]

fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install()
n.jobs["ACC"] = [job("ATCI-1", path="/job/B/Dev_ATCI-1-1"), job("ATCI-1", path="/job/B/Dev_ATCI-1-1")]
quiet_run(1); assert len(alerts(n)) == 1
n.jobs["ACC"] = [job("ATCI-1", path="/job/B/Dev_ATCI-1-2", posted="Posted 2 Days Ago", age=2)]
quiet_run(2); assert len(alerts(n)) == 1, "duplicate alert!"
rec = json.load(open(w.DB_F))["jobs"]["Accenture|ATCI-1"]
assert rec["publication"] == "published" and len(rec["relisted"]) == 1 and rec["experience"]["overall_experience_min"] == 2.0
assert n.detail_calls == 1
print("B1 same Accenture requisition x3 runs (page path -1/-2, label change, pagination repeat) = 1 alert, 1 description download: OK")
n.jobs["ACC"] = [job("ATCI-1"), job("ATCI-2")]; quiet_run(1); assert len(alerts(n)) == 2 and "ATCI-2" in alerts(n)[1]
n.jobs["ACC"] += [job("ATCI-3", title="Backend Engineer")]; quiet_run(3); assert len(alerts(n)) == 3
print("B2 similar title with a different requisition is not suppressed; a new job in a later run is sent once: OK")

fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install(); n.tg_ok = False; n.jobs["ACC"] = [job("ATCI-9")]
quiet_run(2); assert n.sent == [] and json.load(open(w.DB_F))["jobs"]["Accenture|ATCI-9"]["publication"] == "pending" and n.detail_calls == 1
n.tg_ok = True; quiet_run(3); assert len(alerts(n)) == 1
print("B3 failed Telegram delivery stays pending, retried once, no duplicate, no re-download: OK")

for first in ("board", "official"):
    fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install(); w.ADZ_ON = True
    board = dict(job("A-1", title="Java Developer", loc="Bengaluru, Karnataka"), id="777", req="777", url="https://adz/777",
                 desc=jd("2-4 years of professional experience. Java Spring"), company="Accenture")
    official = [job("ATCI-77", title="Java Developer", loc="Bengaluru")]
    for src in (["board", "official"] if first == "board" else ["official", "board"]):
        if src == "board": w.RES_F.write_text(json.dumps({"Accenture": {"type": "nofeed"}})); w.adzuna_jobs = lambda: [board]
        else: w.RES_F.write_text(json.dumps({"Accenture": WD()})); n.jobs["ACC"] = official
        if w.DB_F.exists():
            d = json.load(open(w.DB_F)); d["meta"]["last_run"].pop("__adzuna", None); json.dump(d, open(w.DB_F, "w"))
        quiet_run(1)
    assert len(alerts(n)) == 1 and n.counters().get("duplicate_across_sources") == 1, (first, n.sent)
w.ADZ_ON = False
print("B4 same vacancy on a job board and the official site = one alert, either order: OK")

fresh([co("Zeta")], {"Zeta": {"type": "nofeed"}}); n = Net(); n.install(); w.ADZ_ON = True
mk = lambda i: dict(job("x"), id=str(i), req=str(i), url=f"https://adz/{i}", desc=jd("2-4 years of experience. Java"), company="Zeta")
w.adzuna_jobs = lambda: [mk(1), mk(2)]; quiet_run(1)
assert len(alerts(n)) == 2 and n.counters().get("ambiguous_flagged") == 1; w.ADZ_ON = False
print("B5 jobs without official ids and identical titles are both kept, one flagged: OK")

fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install()
json.dump({"seen": {"Accenture|/job/B/Dev_ATCI-5-1": _time.time()}}, open(w.SEEN_F, "w"))
n.jobs["ACC"] = [job("ATCI-5", path="/job/B/Dev_ATCI-5-2")]; quiet_run(2); assert n.sent == []
print("B6 requisitions already sent by the older version are not re-sent: OK")

# ============ C. NEEDS_REVIEW: stored, never shown as a match, listed in the report ============
fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install(); os.environ["TELEGRAM_BOT_TOKEN"] = "t"
n.text = jd("Build services in Java and Spring Boot. Great culture and benefits.")                    # no experience statement at all
n.jobs["ACC"] = [job("ATCI-1"), job("ATCI-2", title="Java Engineer")]
n.jobs["ACC"][1] = dict(n.jobs["ACC"][1])
ten_am = dt.datetime(2026, 10, 19, 5, 0, tzinfo=dt.timezone.utc).timestamp()
w.time = types.SimpleNamespace(time=lambda: ten_am, sleep=lambda x: None)
quiet_run(1)
d = json.load(open(w.DB_F))["jobs"]
assert all(r["eligibility"] == "needs_review" and r["publication"] == "none" for r in d.values()) and alerts(n) == []
rep = [m for m in n.sent if m.startswith("📊")]; assert len(rep) == 1 and "Needs your review" in rep[0] and "NOT matches" in rep[0], n.sent
quiet_run(2); assert len([m for m in n.sent if m.startswith("📊")]) == 1
del os.environ["TELEGRAM_BOT_TOKEN"]
print("C unknown/conflicting experience is kept as NEEDS_REVIEW, never alerted as a match, listed once in the report: OK")

# ============ D. job-board snippets: full page is fetched; snippets alone are never trusted ============
for outcome in ("full page", "no page"):
    fresh([co("Zeta")], {"Zeta": {"type": "nofeed"}}); n = Net(); n.install(); w.ADZ_ON = True
    snippet = dict(job("x"), id="55", req="55", url="https://adz/55", desc="Java developer 2-4 years of experience ...", snippet=True, company="Zeta")
    w.adzuna_jobs = lambda: [dict(snippet)]
    if outcome == "full page": w.page_text = lambda url: jd("Java Spring Boot. Requirements: 2-4 years of professional experience. " * 10)
    else:
        def boom(url): raise RuntimeError("js shell")
        w.page_text = boom
    quiet_run(1)
    if outcome == "full page": assert len(alerts(n)) == 1 and "Overall experience (verified): 2-4 years" in alerts(n)[0]
    else: assert alerts(n) == [] and n.counters().get("needs_review") == 1
    w.ADZ_ON = False
print("D job-board snippet: verified from the full page when readable, otherwise NEEDS_REVIEW (never a match): OK")

# ============ E. acceptance: every alert shows the verified overall requirement ============
fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install()
n.text = jd("Requirements:\n- 2-4 years of professional experience.\n- 3+ years of experience in Java.\n- 2+ years of experience in AWS.\nJava Spring Boot.")
n.jobs["ACC"] = [job("A1"), job("A2", title="Backend Engineer")]; quiet_run(1)
assert alerts(n) and all("Overall experience (verified): 2-4 years" in m and "Skill-specific (not overall)" in m for m in alerts(n))
assert not any(m.split("Overall experience (verified): ")[1].startswith(("3+", "2+ years of")) for m in alerts(n))
print("E every alert shows the verified overall requirement; skill numbers appear only on their own line: OK")

# ============ F. source fallback safety (offline) ============
assert w.conf_for({"name": "NoFeedCo", "url": "https://careers.example/jobs", "match": "nofeedco"}, {})["type"] == "nofeed"

# A Workday rate-limit during discovery must stop probing candidate tenants/sites.
old_candidates, old_ping = w.candidates, w.wd_ping
calls = []
w.candidates = lambda c: iter([{"type": "workday", "api": "https://one/jobs", "web": "https://one"},
                                {"type": "workday", "api": "https://two/jobs", "web": "https://two"}])
def limited(api):
    calls.append(api)
    import requests
    response = types.SimpleNamespace(status_code=429)
    raise requests.HTTPError("HTTP 429", response=response)
w.wd_ping = limited
result = w.discover({"name": "Rate Limited Co", "url": "https://careers.example/jobs"})
assert result["type"] == "nofeed" and "HTTP 429" in result["why"] and len(calls) == 1, (result, calls)
w.candidates, w.wd_ping = old_candidates, old_ping

# Retry-After is honored but capped to avoid unbounded sleeping on malformed/hostile headers.
resp = types.SimpleNamespace(headers={"Retry-After": "7"})
assert 7 <= w.retry_delay(resp, 1) < 7.36
resp = types.SimpleNamespace(headers={"Retry-After": "9999"})
assert w.retry_delay(resp, 1) < 31
class FakeResponse:
    def __init__(self, data=None, url="https://careers.example/jobs", text="", error=None):
        self.data, self.url, self.text, self.error = data, url, text, error
        self.status_code, self.headers = 200, {}
    def raise_for_status(self): pass
    def json(self):
        if self.error: raise self.error
        return self.data

# ============ G. feeds: malformed JSON, valid empty response, schema and parser failures ============
assert len(CONFIG_COMPANIES) == 107 and len({c["name"] for c in CONFIG_COMPANIES}) == 107
assert len(CONFIG_PRIORITY) == 45 and all(n in {c["name"] for c in CONFIG_COMPANIES} for n in CONFIG_PRIORITY)
ordered = w.ordered_companies([co("backup"), co(CONFIG_PRIORITY[0])])
assert ordered[0]["name"] == CONFIG_PRIORITY[0]
assert w.response_json(FakeResponse(data=[]), "test", list) == []
try: w.response_json(FakeResponse(error=json.JSONDecodeError("bad", "{", 1)), "mock ATS", dict)
except w.InvalidJSONResponse as exc: assert "invalid JSON" in w.reason(exc) and "mock ATS" in str(exc)
else: raise AssertionError("malformed JSON was not reported as a feed failure")
try: w.response_json(FakeResponse(data={"oops": []}), "mock ATS", list)
except w.InvalidFeedShape as exc: assert "invalid response schema" in w.reason(exc)
else: raise AssertionError("unexpected response shape was accepted")
print("G1 malformed JSON and invalid schema are explicit failures; empty JSON array is valid: OK")

old_get = w.get
calls = []
pages = {
    "https://careers.example/search": '<a href="/job/1001">Java Engineer</a><a rel="next" href="/search?page=2">Next</a>',
    "https://careers.example/search?page=2": '<a href="/job/1002">Backend Developer</a>',
}
def page_get(url, **kw):
    calls.append(url)
    return FakeResponse(text=pages.get(url, ""), url=url)
w.get = page_get
try:
    jobs = w.careerhtml_list({"url": "https://careers.example/search"})
    assert {j["req"] for j in jobs} == {"1001", "1002"} and len(calls) == 2
    try: w.careerhtml_list({"url": "https://careers.example/empty"})
    except w.NoListingsParsed as exc: assert "zero jobs is not confirmed" in str(exc)
    else: raise AssertionError("a page without listings was incorrectly called a successful zero-job feed")
finally: w.get = old_get
print("G2 official career-page rel=next pagination retrieves all pages within the cap: OK")

old_get = w.get; sr_calls = []
def sr_get(url, **kw):
    sr_calls.append(kw["params"]["offset"])
    offset = kw["params"]["offset"]
    content = ([{"id": str(i), "name": "Java Engineer", "location": {"city": "Hyderabad", "country": "India"}}
                for i in range(offset, min(offset + 100, 101))])
    return FakeResponse(data={"content": content, "totalFound": 101})
w.get = sr_get
try:
    jobs = w.sr_list({"company_id": "mockco"})
    assert len(jobs) == 101 and sr_calls == [0, 100], (len(jobs), sr_calls)
    sr_calls.clear()
    w.get = lambda url, **kw: FakeResponse(data={"content": [], "totalFound": 0})
    assert w.sr_list({"company_id": "emptyco"}) == []
finally: w.get = old_get
print("G3 SmartRecruiters uses documented offset/limit paging and recognizes a valid zero-job result: OK")

old_get, old_search = w.get, w.F["search_terms"]
lever_calls = []
def lever_get(url, **kw):
    skip = kw["params"]["skip"]; lever_calls.append(skip)
    size = 100 if skip == 0 else 1 if skip == 100 else 0
    data = [{"id": f"L{i}", "text": "Java Engineer", "hostedUrl": f"https://jobs.example/{i}", "categories": {}}
            for i in range(skip, skip + size)]
    return FakeResponse(data=data)
w.get, w.F["search_terms"] = lever_get, ["java"]
try:
    jobs = w.lv_list({"slug": "mockco"})
    assert len(jobs) == 101 and lever_calls == [0, 100], (len(jobs), lever_calls)
finally: w.get, w.F["search_terms"] = old_get, old_search
print("G4 Lever's documented skip/limit pagination retrieves the next page: OK")

old_post = w.post; wd_calls = []
def wd_post(url, **kw):
    offset = kw["json"]["offset"]; wd_calls.append(offset)
    lo, hi = (0, 20) if offset == 0 else (20, 25)
    postings = [{"externalPath": f"/job/Java-{i}", "title": "Java Engineer", "locationsText": "Hyderabad", "postedOn": "Today"}
                for i in range(lo, hi)]
    return FakeResponse(data={"jobPostings": postings, "total": 25})
w.post = wd_post
try:
    jobs = w.wd_list({"api": "https://tenant.example/api", "web": "https://jobs.example"})
    assert len(jobs) == 25 and wd_calls == [0, 20], (len(jobs), wd_calls)
finally: w.post = old_post
print("G5 Workday offset paging follows the feed total beyond its former 15-page cap: OK")

old_get, old_terms = w.get, w.F["search_terms"]
oracle_calls = []
def oracle_get(url, **kw):
    finder = kw["params"]["finder"]
    offset = int(finder.split("offset=")[1].split(",")[0]); oracle_calls.append(offset)
    n = 50 if offset == 0 else 1
    reqs = [{"Id": str(i), "Title": "Java Engineer", "PrimaryLocation": "Hyderabad", "PostedDate": "2026-10-23"}
            for i in range(offset, offset + n)]
    return FakeResponse(data={"items": [{"requisitionList": reqs}], "hasMore": offset == 0})
w.get, w.F["search_terms"] = oracle_get, ["java"]
try:
    jobs = w.oh_list({"host": "tenant.fa.oraclecloud.com", "site": "CX_1"})
    assert len(jobs) == 51 and oracle_calls == [0, 50], (len(jobs), oracle_calls)
finally: w.get, w.F["search_terms"] = old_get, old_terms
print("G6 Oracle HCM uses documented offset paging and follows hasMore: OK")

# Runtime coverage export preserves a successful empty result and keeps failures explicit.
old_root, old_dry = w.ROOT, w.DRY
try:
    with tempfile.TemporaryDirectory() as temp:
        w.ROOT, w.DRY = pathlib.Path(temp), False
        coverage_companies = [co("EmptyCo"), co("FailCo")]
        coverage_health = {
            "EmptyCo": {"status": "ok", "last_attempt_at": 1792713600, "last_success_at": 1792713600, "last_success_count": 0},
            "FailCo": {"status": "failed", "last_attempt_at": 1792713600, "failure_reason": "invalid JSON"},
        }
        coverage_resolved = {"EmptyCo": {"type": "smartrecruiters"}, "FailCo": {"type": "nofeed", "why": "invalid JSON"}}
        w.write_coverage_csv(coverage_companies, coverage_health, coverage_resolved)
        with open(pathlib.Path(temp) / "state" / "source_coverage.csv", newline="", encoding="utf-8") as f:
            coverage_rows = list(w.csv.DictReader(f))
        assert len(coverage_rows) == 2 and coverage_rows[0]["status"] == "ok" and coverage_rows[0]["successful_result_count"] == "0"
        assert coverage_rows[1]["status"] == "failed" and coverage_rows[1]["failure_reason"] == "invalid JSON"
finally:
    w.ROOT, w.DRY = old_root, old_dry
print("G7 coverage CSV records valid zero-job success separately from failure: OK")

print("F no-feed state is explicit; Workday 429 stops discovery; Retry-After is bounded: OK")
print("ALL TESTS PASSED (including targeted source coverage and pagination checks)")
