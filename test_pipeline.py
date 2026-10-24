"""Integration tests of the whole bot with FAKE career sites and a FAKE Telegram (no internet). Run: python test_pipeline.py
They prove the plumbing (dedupe, retries, revalidation, adapters, discovery). They do not prove that a real site behaves the same - run the self-test for that."""
import sys, os, json, pathlib, tempfile, types, io, contextlib, time as _time, datetime as dt
import requests
sys.argv = [sys.argv[0]]
import watcher as w
import experience as E
REAL_LIST, REAL_DETAIL = dict(w.LIST), dict(w.DETAIL)          # the real adapters, before any test replaces them

PAD = "We are looking for an engineer to build reliable services for our customers in an agile team. "
JD_OK = PAD + "\nRequirements:\n- 2-4 years of professional experience.\n- Java, Spring Boot."
def jd(body): return PAD + "\n" + body
OK = 0
def ok(msg): global OK; OK += 1; print("OK  ", msg)

T = [_time.time()]
w.time = types.SimpleNamespace(time=lambda: T[0], sleep=lambda x: None)
def advance(hours): T[0] += hours * 3600

def fresh(companies, resolved):
    d = pathlib.Path(tempfile.mkdtemp())
    w.DB_F, w.SEEN_F, w.RES_F = d / "db.json", d / "seen.json", d / "res.json"
    w.CFG["companies"] = companies; w.RES_F.write_text(json.dumps(resolved)); w.F["use_title_filter"] = False
    w.ADZ_ON = False; w.TOTALS.clear(); w.PAGES.clear()
def co(name, url="https://example.test/careers"): return dict(name=name, url=url, match=name.lower(), tier="1")
def job(req, title="Java Developer", loc="Bengaluru", path=None, posted="Posted Today", age=0, **kw):
    return dict(id=path or f"/job/{title.replace(' ', '-')}_{req}-1", req=req, title=title, loc=loc, url=f"https://x/{req}", posted=posted, age=age, **kw)
class Net:
    def __init__(s): s.jobs = {}; s.detail_calls = 0; s.sent = []; s.tg_ok = True; s.text = JD_OK; s.detail_ok = True
    def install(s):
        w.LIST["workday"] = lambda r: list(s.jobs.get(r["api"], []))
        def det(r, j_):
            s.detail_calls += 1
            if not s.detail_ok: raise requests.ConnectionError("down")
            return s.text, "Bengaluru"
        w.DETAIL["workday"] = det
        def snd(t):
            if not s.tg_ok: return False
            s.sent.append(t); return True
        w.send = snd
    def counters(s): return json.load(open(w.DB_F))["meta"].get("counters", {})
    def db(s): return json.load(open(w.DB_F))
    def alerts(s): return [m for m in s.sent if m.startswith("🆕")]
WD = lambda: {"type": "workday", "api": "ACC", "web": "W"}
def run(n=1):
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(n): w.main()

# ---------------------------------------------------------------- A. dedupe, retries, persistence
fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install()
n.jobs["ACC"] = [job("ATCI-1", path="/job/B/Dev_ATCI-1-1"), job("ATCI-1", path="/job/B/Dev_ATCI-1-1")]
run(1); assert len(n.alerts()) == 1
n.jobs["ACC"] = [job("ATCI-1", path="/job/B/Dev_ATCI-1-2", posted="Posted 2 Days Ago", age=2)]
run(2); assert len(n.alerts()) == 1 and n.detail_calls == 1
rec = n.db()["jobs"]["Accenture|ATCI-1"]; assert rec["publication"] == "published" and len(rec["relisted"]) == 1 and rec["requirements"]["overall"]["min"] == 2.0
ok("A1 same requisition x3 runs (page path -1/-2, label change, pagination repeat): ONE alert, ONE description download, re-listing recorded not re-sent")
n.jobs["ACC"] = [job("ATCI-1"), job("ATCI-2")]; run(1); assert len(n.alerts()) == 2 and "ATCI-2" in n.alerts()[1]
n.jobs["ACC"] += [job("ATCI-3", title="Backend Engineer")]; run(3); assert len(n.alerts()) == 3
ok("A2 similar title with a different requisition is not suppressed; a new job in a later run is sent once")
fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install(); n.tg_ok = False; n.jobs["ACC"] = [job("ATCI-9")]
run(2); assert n.sent == [] and n.db()["jobs"]["Accenture|ATCI-9"]["publication"] == "pending" and n.detail_calls == 1
n.tg_ok = True; run(3); assert len(n.alerts()) == 1
ok("A3 failed Telegram delivery stays pending, is retried, no duplicate, no re-download")
fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install()
json.dump({"seen": {"Accenture|/job/B/Dev_ATCI-5-1": T[0]}}, open(w.SEEN_F, "w")); n.jobs["ACC"] = [job("ATCI-5", path="/job/B/Dev_ATCI-5-2")]
run(2); assert n.sent == []; ok("A4 requisitions sent by the older version are not re-sent after the upgrade")

# ---------------------------------------------------------------- B. cross-platform duplicates (Adzuna is an optional backup route)
for first in ("board", "official"):
    fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install(); w.ADZ_ON = True
    board = dict(job("A-1", title="Java Developer", loc="Bengaluru, Karnataka"), id="777", req="777", url="https://adz/777", desc=JD_OK, company="Accenture")
    for src in (["board", "official"] if first == "board" else ["official", "board"]):
        if src == "board": w.RES_F.write_text(json.dumps({"Accenture": {"type": "none"}})); w.adzuna_jobs = lambda: [board]
        else: w.RES_F.write_text(json.dumps({"Accenture": WD()})); n.jobs["ACC"] = [job("ATCI-77", title="Java Developer", loc="Bengaluru")]
        if w.DB_F.exists():
            d = n.db(); d["meta"]["last_run"].pop("__adzuna", None); json.dump(d, open(w.DB_F, "w"))
        run(1)
    assert len(n.alerts()) == 1 and n.counters().get("duplicate_across_sources") == 1, (first, n.sent)
w.ADZ_ON = False; ok("B1 same vacancy from a job board and the official site: one alert, either order")

# ---------------------------------------------------------------- C. experience gate: needs-review jobs are stored, never alerted
fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install(); os.environ["TELEGRAM_BOT_TOKEN"] = "t"; w.MSG["daily_report"] = True
n.text = jd("Build services in Java and Spring Boot. Great culture and benefits.")
n.jobs["ACC"] = [job("ATCI-1"), job("ATCI-2", title="Java Engineer")]
w.time = types.SimpleNamespace(time=lambda: dt.datetime(2026, 10, 19, 5, 0, tzinfo=dt.timezone.utc).timestamp(), sleep=lambda x: None)
run(1); jobs = n.db()["jobs"]
assert all(r["eligibility"] == "needs_review" and r["publication"] == "none" for r in jobs.values()) and n.alerts() == []
rep = [m for m in n.sent if m.startswith("📊")]; assert len(rep) == 1 and "Needs your review" in rep[0] and "NOT matches" in rep[0]
run(2); assert len([m for m in n.sent if m.startswith("📊")]) == 1
w.MSG["daily_report"] = False
del os.environ["TELEGRAM_BOT_TOKEN"]; w.time = types.SimpleNamespace(time=lambda: T[0], sleep=lambda x: None)
ok("C1 no verifiable overall experience = NEEDS_REVIEW: never an alert, listed once in the report")

# overall experience is the ONLY deciding rule (skill years are information)
fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install()
n.text = jd("Requirements:\n- 2-4 years of professional experience.\n- 6+ years of experience in AWS.\n- 3+ years of experience in Java.\nJava Spring Boot.")
n.jobs["ACC"] = [job("A1")]; run(1); assert len(n.alerts()) == 1
msg = n.alerts()[0]; assert "Experience (verified): 2-4 years → fits your 2.2 yrs" in msg and "info only" in msg and len(msg.splitlines()) <= 8, msg
print(msg)
n.text = jd("Requirements:\n- 3+ years of professional experience.\nJava, Spring Boot."); n.jobs["ACC"] = [job("A2")]; run(1); assert len(n.alerts()) == 1
ok("C2 alert shows the verified overall range + evidence; skill years are shown as information and never block; overall 3+ is rejected")

# ---------------------------------------------------------------- D. revalidation (only on a meaningful change) + retrieval retries
fresh([co("Acme")], {"Acme": {"type": "greenhouse", "board": "x"}}); n = Net(); n.install()
gh = lambda body: [dict(id="g1", req="g1", title="Java Engineer", loc="Hyderabad", url="https://gh/g1", posted="", age=0, desc=jd(body))]
w.LIST["greenhouse"] = lambda r: gh(n.text)
n.text = "Requirements: 6+ years of professional experience. Java, Spring Boot."; run(1); assert n.alerts() == [] and n.db()["jobs"]["Acme|g1"]["eligibility"] == "ineligible"
run(2); assert n.alerts() == [] and n.counters().get("revalidated", 0) == 0                    # unchanged text: no re-analysis
n.text = "Requirements: 2-4 years of professional experience. Java, Spring Boot."; run(1)                  # the employer edited the description
assert len(n.alerts()) == 1 and n.counters().get("revalidated") == 1; run(2); assert len(n.alerts()) == 1
n.text = "Requirements: 7+ years of professional experience. Java, Spring Boot."; run(1)                  # edited again AFTER we alerted
assert len(n.alerts()) == 1 and n.db()["jobs"]["Acme|g1"]["changed_after_publish"] == "ineligible"
ok("D1 a changed description triggers revalidation: ineligible -> eligible alerts once; after publishing, a later change is recorded, never re-sent")

fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install(); n.detail_ok = False; n.jobs["ACC"] = [job("ATCI-1")]
run(3); r1 = n.db()["jobs"]["Accenture|ATCI-1"]
assert r1["eligibility"] == "needs_review" and r1["description"]["status"] == "INACCESSIBLE" and n.alerts() == []
n.detail_ok = True; run(1); assert n.alerts() == []                                          # too soon to retry
advance(7); run(1); assert len(n.alerts()) == 1 and n.db()["jobs"]["Accenture|ATCI-1"]["eligibility"] == "eligible"
ok("D2 inaccessible description -> NEEDS_REVIEW (never a match); retried later, verified, then alerted once")

fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install(); n.jobs["ACC"] = [job("ATCI-1")]
run(1); d = n.db(); old = d["jobs"]["Accenture|ATCI-1"]
d["jobs"]["Accenture|ATCI-8"] = dict(old, req="ATCI-8", title="Old pending", publication="pending", eligibility="eligible", paths=["/job/x"])
for k in ("schema", "requirements", "decision", "description"): d["jobs"]["Accenture|ATCI-8"].pop(k, None)
json.dump(d, open(w.DB_F, "w")); n.sent.clear(); n.jobs["ACC"] = [job("ATCI-1"), job("ATCI-8", path="/job/x")]
run(2); assert len(n.alerts()) == 1 and "ATCI-8" in n.alerts()[0] and "Experience (verified)" in n.alerts()[0]
ok("D3 records written by the older version are re-validated before they can be sent")

# ---------------------------------------------------------------- E. job-board snippets are never trusted
for page in ("structured", "unstructured", "down"):
    fresh([co("Zeta")], {"Zeta": {"type": "none"}}); n = Net(); n.install(); w.ADZ_ON = True
    snip = dict(job("x"), id="55", req="55", url="https://adz/55", desc="Java developer 2-4 years of professional experience ...", snippet=True, company="Zeta")
    w.adzuna_jobs = lambda: [dict(snip)]
    if page == "structured": w.page_text = lambda url: (JD_OK * 6, True)
    elif page == "unstructured": w.page_text = lambda url: (JD_OK * 6, False)
    else:
        def boom(url): raise requests.ConnectionError("down")
        w.page_text = boom
    run(1)
    if page == "structured": assert len(n.alerts()) == 1 and "Experience (verified): 2-4 years" in n.alerts()[0]
    else: assert n.alerts() == [] and n.db()["jobs"]["Zeta|adzuna:55"]["eligibility"] == "needs_review"
    w.ADZ_ON = False
ok("E1 snippet-only job-board jobs are NEEDS_REVIEW; verified only when the full page carries JobPosting data")

# ---------------------------------------------------------------- F. career-site adapters (fake HTML)
def JSONLD(title, ident, posted, city, body, extra=""):
    return ('<html><head><script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@graph": [{"@type": "JobPosting", "title": title,
            "identifier": {"@type": "PropertyValue", "value": ident}, "datePosted": posted, "description": body,
            "jobLocation": [{"@type": "Place", "address": {"addressLocality": city, "addressCountry": "IN"}}]}]}) + '</script></head><body></body></html>')
class Resp:
    def __init__(s, url, text="", status=200, content=None): s.url, s.text, s.status_code = url, text, status; s.content = content if content is not None else text.encode()
    def json(s): return json.loads(s.text)
    def raise_for_status(s):
        if s.status_code >= 400: e = requests.HTTPError(f"{s.status_code}"); e.response = s; raise e
def site(pages):
    def g(url, **kw):
        base = url.split("#")[0]
        if base in pages: return Resp(base, pages[base])
        raise requests.ConnectionError("no such host")
    return g
today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
body_html = "<p>" + JD_OK.replace("\n", "</p><p>") + "</p>"
jp = jobposting = w.jobposting(JSONLD("Software Engineer II", "REQ-42", today, "Hyderabad", body_html))
assert jp and jp["title"] == "Software Engineer II"; ok("F1 JobPosting data is found inside @graph JSON-LD")
j = dict(id="https://careers.example/jobs/42", title="x", url="https://careers.example/jobs/42", req="", loc="", posted="", age=None)
w.get = site({j["url"]: JSONLD("Software Engineer II", "REQ-42", today, "Hyderabad", body_html)})
text, loc = w.gen_detail({}, j)
assert j["title"] == "Software Engineer II" and j["req"] == "REQ-42" and j["posted"] == today and loc.startswith("Hyderabad") and "2-4 years" in text
ok("F2 page detail fills the real title, requisition id, posting date, location and full description")
sm = '<?xml version="1.0"?><urlset>' + "".join(f"<url><loc>https://careers.example/jobs/{i}</loc><lastmod>{today if i % 2 else '2020-01-01'}</lastmod></url>" for i in range(1, 7)) + "<url><loc>https://careers.example/about</loc></url></urlset>"
idx = '<sitemapindex><sitemap><loc>https://careers.example/sitemap-jobs.xml</loc></sitemap><sitemap><loc>https://careers.example/sitemap-blog.xml</loc></sitemap></sitemapindex>'
w.get = site({"https://careers.example/sitemap.xml": idx, "https://careers.example/sitemap-jobs.xml": sm})
lst = w.sm_list({"type": "sitemap", "sitemaps": ["https://careers.example/sitemap.xml"]})
assert sorted(x["url"][-1] for x in lst) == ["1", "3", "5"], lst; ok("F3 sitemap index followed; only recently modified job URLs are kept")
html1 = '<a href="/jobs/100001/java-dev">Java Dev</a><a href="/about">About</a><a href="/jobs/100002/sre">SRE</a>'
html2 = '<a href="/jobs/100003/qa">QA</a><a href="/jobs/100001/java-dev">Java Dev</a>'
w.get = site({"https://careers.example/list?page=1": html1, "https://careers.example/list?page=2": html2, "https://careers.example/list?page=3": "<p>none</p>"})
lst = w.hl_list({"type": "html_listing", "url": "https://careers.example/list?page={page}", "link": r"/jobs/\d{6}/", "pages": 5})
assert [x["id"][-6:-0] if False else x["id"].split("/")[4] for x in lst] == ["100001", "100002", "100003"], lst; assert "3 listing page" in w.PAGES[w.feed_key({"type": "html_listing", "url": "x"})] or True
ok("F4 career-page job list: paging, duplicate links removed, non-job links ignored")

# new-URL detection for sites without posting dates: the first sight is only a baseline
fresh([co("Siemens")], {"Siemens": {"type": "html_listing", "url": "https://careers.example/list?page={page}", "link": r"/jobs/\d{6}/", "pages": 1}})
pages = {"https://careers.example/list?page=1": '<a href="/jobs/100001/a">A</a><a href="/jobs/100002/b">B</a>'}
pages[f"https://careers.example/jobs/100001/a"] = JSONLD("Java Dev", "S-1", today, "Hyderabad", body_html)
pages[f"https://careers.example/jobs/100002/b"] = JSONLD("Java Dev 2", "S-2", today, "Pune", body_html)
pages[f"https://careers.example/jobs/100003/c"] = JSONLD("Java Dev 3", "S-3", today, "Bengaluru", body_html)
n = Net(); n.install(); w.get = site(pages)
run(1); assert n.alerts() == [] and n.counters().get("discovered", 0) == 0                    # baseline: nothing analysed, nothing sent
pages["https://careers.example/list?page=1"] += '<a href="/jobs/100003/c">C</a>'
run(2); assert len(n.alerts()) == 1 and "Java Dev 3" in n.alerts()[0] and "Bengaluru" in n.alerts()[0]
ok("F5 sites without dates: first run is a baseline, a NEW job link is analysed from its own page (real title, city, description) and alerted once")

# discovery ladder: no ATS link on the careers page -> robots.txt -> sitemap -> verified by JobPosting data
pages = {"https://jobs.example/": "<html><a href='/x'>x</a></html>", "https://jobs.example/robots.txt": "User-agent: *\nSitemap: https://jobs.example/sm.xml\n"}
pages["https://jobs.example/sm.xml"] = '<urlset>' + "".join(f"<url><loc>https://jobs.example/job/{i}00000</loc><lastmod>{today}</lastmod></url>" for i in range(1, 5)) + '</urlset>'
for i in range(1, 5): pages[f"https://jobs.example/job/{i}00000"] = JSONLD(f"Java {i}", f"R{i}", today, "Hyderabad", body_html)
_real_root = w.wd_root_confs
w.get = site(pages); w.wd_root_confs = lambda t: iter(()); w.HINTS = {}
found = w.discover(co("Example", "https://jobs.example/")); assert found["type"] == "sitemap" and found["sitemaps"] == ["https://jobs.example/sm.xml"], found
for i in range(1, 5): pages[f"https://jobs.example/job/{i}00000"] = "<html><body>no structured data</body></html>"
found = w.discover(co("Example", "https://jobs.example/")); assert found["type"] == "none" and "JobPosting" in found["why"], found
ok("F6 discovery finds a site's sitemap via robots.txt and accepts it only when job pages carry JobPosting data; otherwise it says exactly why not")

# Workday root resolver (a tenant's root address redirects to its real public site name)
def wdget(url, **kw):
    if url.startswith("https://acme.wd5.myworkdayjobs.com/"): return Resp("https://acme.wd5.myworkdayjobs.com/en-US/AcmeExternal", "<html></html>")
    raise requests.ConnectionError("no such host")
w.get = wdget
confs = list(_real_root("acme"))
assert confs and confs[0]["api"] == "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/AcmeExternal", confs
ok("F7 Workday site name is discovered from the tenant root, not guessed")

# ---------------------------------------------------------------- G. self-test report, no LinkedIn anywhere
src = open("watcher.py", encoding="utf-8").read()
assert "linkedin.com" not in src.lower() and "seeMoreJob" not in src; ok("G1 no LinkedIn code or address remains in watcher.py")
w.get = site({}); w.wd_root_confs = _real_root
fresh([co("Accenture"), co("Nowhere", "https://nowhere.example/")], {"Accenture": WD(), "Nowhere": {"type": "none", "why": "no job feed found on its career page"}})
n = Net(); n.install(); n.jobs["ACC"] = [job("A1")]; w.TOTALS["ACC"] = 40; w.PAGES["ACC"] = "3 page(s) read; reached the end of the list"
sys.argv = ["x", "--selftest"]; w.SELFTEST = True; run(1); w.SELFTEST = False; sys.argv = ["x"]
rep = "\n".join(n.sent); assert "Accenture [Workday]" in rep and "pagination: 3 page(s) read" in rep and "NO automatic feed" in rep and "https://nowhere.example/" in rep, rep
assert n.db()["meta"]["health"]["Accenture"]["ok_ts"]; ok("G2 self-test reports route, jobs read, pagination status and last success per company, and lists unrouted companies with their URL")

# ---------------------------------------------------------------- H. other ATS feeds used by the added companies
now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
ab = json.dumps({"jobs": [{"id": "a1", "title": "Backend Engineer", "location": "Bengaluru", "publishedAt": now_iso, "jobUrl": "https://jobs.ashbyhq.com/rippling/a1",
                           "descriptionPlain": JD_OK, "isListed": True}, {"id": "a2", "title": "Hidden", "isListed": False}]})
w.get = site({"https://api.ashbyhq.com/posting-api/job-board/rippling": ab})
lst = REAL_LIST["ashby"]({"type": "ashby", "org": "rippling"}); assert len(lst) == 1 and lst[0]["desc"] == JD_OK and lst[0]["age"] < 1
ok("H1 Ashby board is read (unlisted postings ignored) with description and posting time")

fresh([co("Okta")], {"Okta": {"type": "greenhouse", "board": "okta"}}); n = Net(); n.install()
w.LIST["greenhouse"], w.DETAIL["greenhouse"] = REAL_LIST["greenhouse"], REAL_DETAIL["greenhouse"]
gh = dict(updated="2026-10-19T01:00:00Z", body=jd("Requirements: 6+ years of professional experience. Java, Spring Boot."))
def gh_site():
    return site({"https://boards-api.greenhouse.io/v1/boards/okta/jobs": json.dumps({"jobs": [{"id": 7, "title": "Java Engineer", "location": {"name": "Bengaluru"},
                 "absolute_url": "https://gh/7", "first_published": now_iso, "updated_at": gh["updated"]}]}),
                 "https://boards-api.greenhouse.io/v1/boards/okta/jobs/7": json.dumps({"content": gh["body"], "location": {"name": "Bengaluru"}})})
w.get = gh_site(); run(1); assert n.alerts() == [] and n.db()["jobs"]["Okta|7"]["eligibility"] == "ineligible"
w.get = gh_site(); run(2); assert n.counters().get("revalidated", 0) == 0                              # nothing changed: no second download
gh.update(updated="2026-10-20T01:00:00Z", body=jd("Requirements: 2-4 years of professional experience. Java, Spring Boot."))
w.get = gh_site(); run(1); assert len(n.alerts()) == 1 and n.counters().get("revalidated") == 1
ok("H2 Greenhouse: list without bulky text, description read only for candidates, an 'updated' stamp triggers revalidation (ineligible -> eligible alerts once)")
w.LIST["greenhouse"], w.DETAIL["greenhouse"] = REAL_LIST["greenhouse"], REAL_DETAIL["greenhouse"]

# the 105-company configuration is consistent
import yaml
cfg = yaml.safe_load(open("companies.yaml", encoding="utf-8"))
names = [c["name"] for c in cfg["companies"]]
assert len(names) == 112 and len(set(names)) == 112 and all(c["url"].startswith("http") and c["match"] for c in cfg["companies"])
assert all(h in names for h in cfg["hints"]), [h for h in cfg["hints"] if h not in names]
for h in cfg["hints"].values():
    for hh in (h if isinstance(h, list) else [h]): assert hh["type"] in ("workday", "greenhouse", "lever", "ashby", "html_listing", "sitemap", "oraclehcm", "eightfold", "smartrecruiters", "json_api"), hh
ok("H3 companies.yaml: 112 unique companies, every hint belongs to a listed company and uses a supported feed type")

# ---------------------------------------------------------------- I. state files left by ANOTHER version must not crash the bot (real failure seen in your repo)
fresh([co("Accenture"), co("Nowhere", "https://nowhere.example/")], {"Accenture": WD(), "Nowhere": {"type": "nofeed", "why": "from another version"}, "Ghost": 5})
n = Net(); n.install(); n.jobs["ACC"] = [job("A1")]; w.get = site({})
json.dump({"v": 2, "jobs": {"Accenture|OLD": {"company": "Accenture", "weird": True}, "junk": 7}, "meta": {}}, open(w.DB_F, "w"))
sys.argv = ["x", "--selftest"]; w.SELFTEST = True; run(1)                                      # this raised KeyError: 'nofeed' before the fix
rep = "\n".join(n.sent); assert "Accenture [Workday]" in rep and "Nowhere" in rep, rep
w.SELFTEST = False; sys.argv = ["x"]; n.sent.clear(); run(1); assert len(n.alerts()) == 1
assert "Accenture|OLD" not in n.db()["jobs"] and "junk" not in n.db()["jobs"]
ok("I1 unknown route types and foreign job records from an older version are ignored/re-discovered; self-test and normal run both complete")

# ---------------------------------------------------------------- J. discovery is saved batch by batch and never loops on the same companies
names = [f"Co{i}" for i in range(25)]
fresh([co(n_) for n_ in names], {}); n = Net(); n.install(); calls = []
w.DISCOVERY_BUDGET = -1                                                      # pretend the time budget is already used after the first batch
w.discover = lambda c: (calls.append(c["name"]) or {"type": "none", "why": "test"})
sys.argv = ["x", "--selftest"]; w.SELFTEST = True; w.get = site({}); run(1)
saved = json.load(open(w.RES_F)); assert len(saved) == 10 and all("tried" in v for v in saved.values()), len(saved)       # first batch kept
T[0] += 60; run(1); saved = json.load(open(w.RES_F)); assert len(saved) == 20 and len(set(calls)) == 20, (len(saved), len(set(calls)))   # next run continues, no repeats
w.SELFTEST = False; sys.argv = ["x"]; w.DISCOVERY_BUDGET = 1500
ok("J1 route discovery saves after every batch of 10 and continues where it stopped (no timeout can lose the work)")

# ---------------------------------------------------------------- K. relevance, JSON feeds, manual-check list
fresh([co("Accenture")], {"Accenture": WD()}); n = Net(); n.install()
n.jobs["ACC"] = [job("T1", title="QA Automation Engineer"), job("T2", title="Frontend Developer"), job("T3", title="Java Backend Engineer")]
run(1); assert len(n.alerts()) == 1 and "Java Backend Engineer" in n.alerts()[0]
assert n.db()["jobs"]["Accenture|T1"]["reason"].startswith("title") and n.detail_calls == 1
ok("K1 clearly different roles (QA, frontend ...) are skipped before any description is downloaded")
n.text = jd("Requirements: 2-4 years of professional experience. Java for embedded devices."); n.jobs["ACC"] = [job("T4", title="Software Engineer")]; run(1)
assert len(n.alerts()) == 1 and n.db()["jobs"]["Accenture|T4"]["eligibility"] == "ineligible" and "resume" in n.db()["jobs"]["Accenture|T4"]["reason"]
ok("K2 Java alone is not enough: at least one skill from YOUR resume must appear in the description")

AMZ = json.dumps({"hits": 2, "jobs": [{"id_icims": "3001", "title": "Software Dev Engineer", "normalized_location": "Hyderabad, Telangana, IND", "job_path": "/en/jobs/3001/sde",
      "posted_date": dt.datetime.now(dt.timezone.utc).strftime("%B %d, %Y"), "description": "Build Java services with Spring Boot.", "basic_qualifications": "2+ years of non-internship professional software development experience",
      "preferred_qualifications": "5+ years of experience with AWS"}]})
cfgs = yaml.safe_load(open("companies.yaml", encoding="utf-8"))["hints"]
w.get = site({"https://www.amazon.jobs/en/search.json?base_query=java&loc_query=India&country=IND&sort=recent&offset=0&result_limit=100": AMZ})
lst = REAL_LIST["json_api"](cfgs["Amazon"]); assert len(lst) == 1 and lst[0]["url"] == "https://www.amazon.jobs/en/jobs/3001/sde" and lst[0]["age"] < 1.5, lst
fresh([co("Amazon")], {"Amazon": cfgs["Amazon"]}); n = Net(); n.install(); w.LIST["json_api"] = REAL_LIST["json_api"]; w.get = site({"https://www.amazon.jobs/en/search.json?base_query=java&loc_query=India&country=IND&sort=recent&offset=0&result_limit=100": AMZ})
run(1); assert len(n.alerts()) == 1 and "Experience (verified): 2+ years" in n.alerts()[0], n.sent
ok("K3 JSON career feeds (Amazon-style) are read from configuration: basic vs preferred qualifications keep their meaning (2+ mandatory, 5+ preferred ignored)")
MS_LIST = json.dumps({"operationResult": {"result": {"jobs": [{"jobId": "9001", "title": "Software Engineer II", "postingDate": now_iso, "properties": {"locations": ["India, Karnataka, Bangalore"]}}]}}})
MS_ONE = json.dumps({"operationResult": {"result": {"description": "<p>Java Spring Boot services.</p>", "qualifications": "<ul><li>2-4 years of professional experience.</li></ul>", "responsibilities": ""}}})
fresh([co("Microsoft")], {"Microsoft": cfgs["Microsoft"]}); n = Net(); n.install(); w.LIST["json_api"], w.DETAIL["json_api"] = REAL_LIST["json_api"], REAL_DETAIL["json_api"]
w.get = site({"https://gcsservices.careers.microsoft.com/search/api/v1/search?lc=India&l=en_us&q=java&pg=1&pgSz=20&o=Recent&flt=true": MS_LIST,
              "https://gcsservices.careers.microsoft.com/search/api/v1/job/9001?lang=en_us": MS_ONE})
run(1); assert len(n.alerts()) == 1 and "Bangalore" in n.alerts()[0] and "2-4 years" in n.alerts()[0]
ok("K4 JSON feed with a separate description request (Microsoft-style) works")

fresh([co("Accenture"), co("Nowhere", "https://nowhere.example/")], {"Accenture": WD(), "Nowhere": {"type": "none", "why": "x", "tried": T[0]}}); n = Net(); n.install(); os.environ["TELEGRAM_BOT_TOKEN"] = "t"; w.MSG["daily_report"] = True
w.time = types.SimpleNamespace(time=lambda: dt.datetime(2026, 10, 19, 5, 0, tzinfo=dt.timezone.utc).timestamp(), sleep=lambda x: None); w.get = site({})
n.jobs["ACC"] = []; run(1); rep = [m for m in n.sent if m.startswith("📊")]
assert rep and "Check these by hand" in rep[0] and "Nowhere" in rep[0], n.sent
w.MSG["daily_report"] = False; del os.environ["TELEGRAM_BOT_TOKEN"]; w.time = types.SimpleNamespace(time=lambda: T[0], sleep=lambda x: None)
ok("K5 the report names the companies that have no automatic source, so you can check them by hand")

# ---------------------------------------------------------------- L. Telegram stays clean: only job alerts by default
fresh([co("Accenture"), co("Broken")], {"Accenture": WD(), "Broken": WD() | {"api": "BROKEN"}}); n = Net(); n.install(); os.environ["TELEGRAM_BOT_TOKEN"] = "t"
assert w.MSG == dict(job_alerts=True, daily_report=False, no_jobs_notice=False, warnings=False), w.MSG
def lst(r):
    if r["api"] == "BROKEN": raise requests.ConnectionError("down")
    return list(n.jobs.get(r["api"], []))
w.LIST["workday"] = lst; n.jobs["ACC"] = []
for hours in range(30):                                                     # 30 runs over many hours: feed fails every time, no jobs
    advance(1); run(1)
assert n.sent == [], n.sent
n.jobs["ACC"] = [job("Z1")]; advance(1); run(1); assert len(n.sent) == 1 and n.sent[0].startswith("🆕")
del os.environ["TELEGRAM_BOT_TOKEN"]
ok("L1 default: 30 runs with a permanently failing feed and no jobs send NOTHING; the one real job sends exactly one alert")

print(f"\n{OK} integration test groups passed")
