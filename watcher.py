#!/usr/bin/env python3
"""Free job-alert watcher.
 normal run : find NEW jobs that fit (Java/Spring, ~2 yrs, Bangalore/Hyderabad) -> Telegram, never repeats a job
 --selftest : check every company, send a working / not-working report to Telegram
 --dry      : print instead of sending, don't save state
"""
import json, os, re, sys, time, html, pathlib, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import requests, yaml

ROOT = pathlib.Path(__file__).parent
SEEN_F, RES_F = ROOT/"state"/"seen.json", ROOT/"state"/"resolved.json"
CFG = yaml.safe_load(open(ROOT/"companies.yaml", encoding="utf-8"))
F, X, SK, HINTS = CFG["filters"], CFG["experience"], CFG["skills"], CFG.get("hints", {})
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
DRY, SELFTEST = "--dry" in sys.argv, "--selftest" in sys.argv
USE_LINKEDIN = os.getenv("USE_LINKEDIN", "1") != "0"   # LinkedIn fallback for companies with no direct feed
MAX_ALERTS, MAX_DETAIL, LI_EVERY, LI_PER_RUN = 20, 12, 30 * 60, 10

def get(url, **kw):  return requests.get(url, headers=UA, timeout=kw.pop("timeout", 20), **kw)
def post(url, **kw): return requests.post(url, headers=UA, timeout=kw.pop("timeout", 20), **kw)
def clean(h):
    h = html.unescape(h or ""); h = re.sub(r"<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(h)).strip()
def age_days(s):
    s = (s or "").lower()
    if "today" in s or "just now" in s: return 0
    if "yesterday" in s: return 1
    m = re.search(r"(\d+)\+?\s*day", s)
    return int(m.group(1)) if m else None
def epoch_age(t):
    if not t: return None
    t = float(t); t = t / 1000 if t > 1e12 else t
    return (time.time() - t) / 86400
def iso_age(s):
    try: return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(s.replace("Z", "+00:00"))).total_seconds() / 86400
    except Exception: return None
def norm(x): return re.sub(r"[^a-z0-9]", "", (x or "").lower())
def dedupe(jobs):
    d = {}
    for j in jobs: d.setdefault(j["id"], j)
    return list(d.values())

# ======================= adapters: LIST[type](conf) -> jobs ; DETAIL[type](conf, job) -> (text, location) =======================
def wd_ping(api):
    for attempt in (1, 2, 3):
        try:
            r = post(api + "/jobs", json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}, timeout=25)
            if r.status_code == 429 and attempt < 3: time.sleep(6 * attempt); continue
            r.raise_for_status()
            return "jobPostings" in r.json()
        except requests.Timeout:
            if attempt == 3: raise
TOTALS = {}
def wd_req(api, body):
    for attempt in range(4):                       # Workday rate-limits shared servers: wait and retry
        resp = post(api + "/jobs", json=body, timeout=40)
        if resp.status_code == 429: time.sleep(5 * (attempt + 1)); continue
        resp.raise_for_status(); return resp.json()
    resp.raise_for_status()
def wd_location_facets(facets):
    """find the ids of the Hyderabad / Bangalore filters inside Workday's own facet list"""
    found = {}
    def walk(items, param):
        for it in items or []:
            p = it.get("facetParameter") or param
            if it.get("values"): walk(it["values"], p)
            elif it.get("id") and p and any(k in (it.get("descriptor") or "").lower() for k in F["locations"]):
                found.setdefault(p, []).append(it["id"])
    walk(facets, None)
    return found
def wd_list(r):
    """newest-first with the city filter applied by Workday itself; falls back to scanning newest jobs worldwide"""
    first = wd_req(r["api"], {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""})
    TOTALS[r["api"]] = first.get("total")
    try: facets = wd_location_facets(first.get("facets"))
    except Exception: facets = {}
    out, page = [], 0
    while page < 15:
        body = {"appliedFacets": facets, "limit": 20, "offset": page * 20, "searchText": ""}
        try: data = first if (page == 0 and not facets) else wd_req(r["api"], body)
        except requests.HTTPError:
            if facets: facets = {}; page = 0; out = []; continue     # facet filter rejected -> plain newest-first scan
            raise
        posts = data.get("jobPostings", [])
        ages = []
        for j in posts:
            p = j.get("externalPath")
            if not p: continue
            bf = j.get("bulletFields") or []
            ag = age_days(j.get("postedOn", "")); ages.append(ag)
            out.append(dict(id=p, req=(bf[0] if bf else p.rsplit("_", 1)[-1]), title=j.get("title", ""),
                            loc=j.get("locationsText", ""), url=r["web"] + p, posted=j.get("postedOn", ""), age=ag))
        if len(posts) < 20 or (ages and all(a is not None and a > F["max_age_days"] for a in ages)): break
        page += 1
    return dedupe(out)
def wd_detail(r, j):
    d = get(r["api"] + j["id"]).json()["jobPostingInfo"]
    loc = " ".join([d.get("location", "")] + (d.get("additionalLocations") or []))
    return clean(d.get("jobDescription", "")), loc

def gh_list(r):
    d = get(f"https://boards-api.greenhouse.io/v1/boards/{r['board']}/jobs?content=true", timeout=40).json()["jobs"]
    return [dict(id=str(j["id"]), req=str(j["id"]), title=j["title"], loc=(j.get("location") or {}).get("name", ""),
                 url=j["absolute_url"], posted=(j.get("updated_at") or "")[:10], age=iso_age(j.get("updated_at") or ""),
                 desc=clean(j.get("content", ""))) for j in d]

def lv_list(r):
    d = get(f"https://api.lever.co/v0/postings/{r['slug']}?mode=json").json()
    return [dict(id=j["id"], req=j["id"][:8], title=j["text"], loc=(j.get("categories") or {}).get("location", ""),
                 url=j["hostedUrl"], posted="", age=epoch_age(j.get("createdAt")),
                 desc=clean(j.get("descriptionPlain", "") + " " + " ".join(l.get("content", "") for l in j.get("lists", [])))) for j in d]

def sr_list(r):
    out = []
    for q in F["search_terms"]:
        d = get(f"https://api.smartrecruiters.com/v1/companies/{r['company_id']}/postings", params={"q": q, "limit": 100}).json()
        for j in d.get("content", []):
            l = j.get("location") or {}
            out.append(dict(id=j["id"], req=j["id"], title=j["name"], loc=f"{l.get('city','')} {l.get('country','')}",
                            url=f"https://jobs.smartrecruiters.com/{r['company_id']}/{j['id']}",
                            posted=(j.get("releasedDate") or "")[:10], age=iso_age(j.get("releasedDate") or "")))
    return dedupe(out)
def sr_detail(r, j):
    d = get(f"https://api.smartrecruiters.com/v1/companies/{r['company_id']}/postings/{j['id']}").json()
    secs = (d.get("jobAd") or {}).get("sections") or {}
    return clean(" ".join((v or {}).get("text", "") for v in secs.values())), None

def ef_list(r):
    out = []
    for q in F["search_terms"]:
        d = get(f"https://{r['sub']}.eightfold.ai/api/apply/v2/jobs",
                params={"domain": r["domain"], "start": 0, "num": 50, "query": q, "location": "India", "sort_by": "timestamp"}).json()
        for p in d.get("positions", []):
            out.append(dict(id=str(p["id"]), req=str(p.get("display_job_id") or p["id"]), title=p["name"], loc=p.get("location", ""),
                            url=p.get("canonicalPositionUrl") or f"https://{r['sub']}.eightfold.ai/careers/job/{p['id']}",
                            posted="", age=epoch_age(p.get("t_create")), desc=clean(p.get("job_description", ""))))
    return dedupe(out)

def oh_list(r):
    out = []
    for q in F["search_terms"]:
        d = get(f"https://{r['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                params={"onlyData": "true", "expand": "requisitionList.secondaryLocations",
                        "finder": f"findReqs;siteNumber={r['site']},limit=50,keyword={q},sortBy=POSTING_DATES_DESC"}).json()
        items = d.get("items") or [{}]
        for j in items[0].get("requisitionList", []):
            out.append(dict(id=str(j["Id"]), req=str(j["Id"]), title=j["Title"], loc=j.get("PrimaryLocation", ""),
                            url=f"https://{r['host']}/hcmUI/CandidateExperience/en/sites/{r['site']}/job/{j['Id']}",
                            posted=(j.get("PostedDate") or "")[:10], age=iso_age((j.get("PostedDate") or "") + "T00:00:00+00:00")))
    return dedupe(out)
def oh_detail(r, j):
    d = get(f"https://{r['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails",
            params={"expand": "all", "onlyData": "true", "finder": f'ById;Id="{j["id"]}",siteNumber={r["site"]}'}).json()
    it = (d.get("items") or [{}])[0]
    return clean(it.get("ExternalDescriptionStr", "") + " " + it.get("ExternalQualificationsStr", "")), None

def li_list(r):
    # NOTE: the real guest endpoint is seeMoreJobPostings (my first version used a wrong name -> 404)
    resp = get("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search",
               params={"keywords": f"{r['name']} java developer", "location": "India",
                       "f_TPR": "r172800", "sortBy": "DD", "start": 0})
    resp.raise_for_status()
    out = []
    for card in resp.text.split("<li>")[1:]:
        href = re.search(r'base-card__full-link[^>]*href="([^"]+)"', card)
        title = re.search(r'base-search-card__title[^>]*>\s*(.*?)\s*</h3>', card, re.S)
        comp = re.search(r'base-search-card__subtitle[^>]*>(.*?)</h4>', card, re.S)
        loc = re.search(r'job-search-card__location[^>]*>\s*(.*?)\s*</span>', card, re.S)
        when = re.search(r'datetime="(\d{4}-\d{2}-\d{2})', card)
        if not (href and title and comp): continue
        if not norm(clean(comp.group(1))).startswith(norm(r["match"])): continue
        link = html.unescape(href.group(1)).split("?")[0]
        jid = re.search(r"(\d{6,})$", link)
        out.append(dict(id=jid.group(1) if jid else link, req=jid.group(1) if jid else "", title=clean(title.group(1)),
                        loc=clean(loc.group(1)) if loc else "", url=link, posted=when.group(1) if when else "",
                        age=iso_age(when.group(1) + "T00:00:00+00:00") if when else None))
    return dedupe(out)
def li_detail(r, j):
    time.sleep(1.5)
    resp = get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{j['id']}")
    resp.raise_for_status()
    m = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', resp.text, re.S)
    return clean(m.group(1)) if m else "", None


ADZ_ON = bool(os.getenv("ADZUNA_APP_ID") and os.getenv("ADZUNA_APP_KEY"))
def adzuna_jobs():
    """free job-board API: recent Java jobs in our cities; used for companies with no direct career feed"""
    out = []
    for city in ("hyderabad", "bangalore"):
        for page in (1, 2):
            r = get(f"https://api.adzuna.com/v1/api/jobs/in/search/{page}",
                    params=dict(app_id=os.getenv("ADZUNA_APP_ID"), app_key=os.getenv("ADZUNA_APP_KEY"), what="java", where=city,
                                results_per_page=50, sort_by="date", max_days_old=max(1, int(F["max_age_days"]))))
            r.raise_for_status()
            for x in r.json().get("results", []):
                out.append(dict(id=str(x["id"]), req=str(x["id"]), title=clean(x.get("title", "")),
                                loc=(x.get("location") or {}).get("display_name", ""), url=x.get("redirect_url", ""),
                                posted=(x.get("created") or "")[:10], age=iso_age(x.get("created") or ""),
                                desc=clean(x.get("description", "")), company=((x.get("company") or {}).get("display_name") or ""),
                                trust_java=True))
    return dedupe(out)

LIST = dict(workday=wd_list, greenhouse=gh_list, lever=lv_list, smartrecruiters=sr_list,
            eightfold=ef_list, oraclehcm=oh_list, linkedin=li_list)
DETAIL = dict(workday=wd_detail, smartrecruiters=sr_detail, oraclehcm=oh_detail, linkedin=li_detail)
LABEL = dict(workday="Workday", greenhouse="Greenhouse", lever="Lever", smartrecruiters="SmartRecruiters",
             eightfold="Eightfold", oraclehcm="Oracle HCM", linkedin="LinkedIn fallback", adzuna="Adzuna job board")

# ======================= auto-discovery of each company's job feed =======================
WD_DCS = ["wd1", "wd5", "wd3", "wd12", "wd2", "wd4", "wd10", "wd103", "wd501"]
def wd_confs(tenant, sites, dc0=None):
    dcs = ([dc0] if dc0 else []) + [d for d in WD_DCS if d != dc0]
    for site in sites:
        for dc in dcs:
            api = f"https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
            yield dict(type="workday", api=api, web=f"https://{tenant}.{dc}.myworkdayjobs.com/en-US/{site}")
        for dc in ("wd1", "wd5", "wd3"):
            yield dict(type="workday", api=f"https://{dc}.myworkdaysite.com/wday/cxs/{tenant}/{site}",
                       web=f"https://{dc}.myworkdaysite.com/recruiting/{tenant}/{site}")
def scan_page(blob):
    for m in re.finditer(r"https?://([a-z0-9\-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?([A-Za-z0-9_\-]+)", blob):
        t, dc, s = m.groups()
        if s.lower() not in ("wday", "login", "assets"):
            yield dict(type="workday", api=f"https://{t}.{dc}.myworkdayjobs.com/wday/cxs/{t}/{s}", web=f"https://{t}.{dc}.myworkdayjobs.com/en-US/{s}")
    for m in re.finditer(r"https?://(wd\d+)\.myworkdaysite\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?recruiting/([a-z0-9\-]+)/([A-Za-z0-9_\-]+)", blob):
        dc, t, s = m.groups()
        yield dict(type="workday", api=f"https://{dc}.myworkdaysite.com/wday/cxs/{t}/{s}", web=f"https://{dc}.myworkdaysite.com/recruiting/{t}/{s}")
    for m in re.finditer(r"(?:boards|job-boards)\.greenhouse\.io/(?!embed)([a-z0-9_\-]+)", blob): yield dict(type="greenhouse", board=m.group(1))
    for m in re.finditer(r"jobs\.lever\.co/([A-Za-z0-9_\-]+)", blob): yield dict(type="lever", slug=m.group(1))
    for m in re.finditer(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_\-]+)", blob): yield dict(type="smartrecruiters", company_id=m.group(1))
    for m in re.finditer(r"https?://([a-z0-9\-]+\.fa\.[a-z0-9\-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[A-Za-z\-]+/sites/([A-Za-z0-9_\-]+)", blob):
        yield dict(type="oraclehcm", host=m.group(1), site=m.group(2))

def candidates(c):
    h = HINTS.get(c["name"])
    if h:
        for hh in (h if isinstance(h, list) else [h]):
            if hh["type"] == "workday": yield from wd_confs(hh["tenant"], hh["sites"], hh.get("dc"))
            else: yield dict(hh)
    try:
        resp = get(c["url"], allow_redirects=True)
        yield from scan_page(resp.url + " " + resp.text[:600000])
    except Exception:
        pass

def reason(e):
    if isinstance(e, requests.HTTPError): return f"HTTP {e.response.status_code}"
    if isinstance(e, requests.Timeout): return "timeout"
    if isinstance(e, requests.ConnectionError): return "no such host"
    return type(e).__name__

def discover(c):
    seen_c, why = set(), {}
    for cand in candidates(c):
        key = json.dumps(cand, sort_keys=True)
        if key in seen_c: continue
        seen_c.add(key)
        try:
            if cand["type"] == "workday":
                time.sleep(0.4)
                if not wd_ping(cand["api"]): continue
            else:
                LIST[cand["type"]](cand)
            return cand
        except Exception as e:
            k = reason(e); why[k] = why.get(k, 0) + 1
            continue
    real = {k: v for k, v in why.items() if k != "no such host"}
    return dict(type="linkedin", why=", ".join(f"{k} x{v}" for k, v in sorted(real.items(), key=lambda x: -x[1])[:3]) or "no job feed found on its career page")

# ======================= fit logic =======================
def loc_ok(s): return any(k in (s or "").lower() for k in F["locations"])
def reject_reason(j):
    t = j["title"].lower()
    if F.get("use_title_filter", True) and (not any(k in t for k in F["include_title"]) or any(k in t for k in F["exclude_title"])): return "title"
    if j.get("age") is not None and j["age"] > F["max_age_days"]: return "older than %sd" % F["max_age_days"]
    loc = (j["loc"] or "").lower()
    if not loc or re.search(r"\d+\s+locations?", loc): return None
    return None if loc_ok(loc) else "location"
def quick_ok(j): return reject_reason(j) is None

def parse_years(text):
    t = re.sub(r"\s+", " ", (text or "").lower())
    near = lambda m: re.search(r"experience|\bexp\b", t[max(0, m.start() - 90): m.end() + 90])
    ranges = []
    for m in re.finditer(r"(\d{1,2})\s*\+?\s*(?:-|–|—|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)", t):
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo <= hi <= 25 and near(m): ranges.append((lo, hi))
    singles = []
    for m in re.finditer(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", t):
        if near(m) and not re.match(r"\s*(?:-|–|to)\s*\d", t[m.end():m.end() + 6]) and int(m.group(1)) <= 25:
            singles.append(int(m.group(1)))
    mx = X["max_min_years"]
    if ranges:
        good = [r for r in ranges if r[0] <= mx and r[1] >= X["my_years"]]
        r = good[0] if good else ranges[0]
        return ("ok" if good else "no"), f"{r[0]}–{r[1]} yrs"
    if singles:
        n = min(singles)
        return ("ok" if n <= mx else "no"), f"{n}+ yrs"
    return "unknown", "not stated"

SKILLS = [("Spring Boot", r"spring\s*boot"), ("Spring", r"\bspring\b(?!\s*boot)"), ("Microservices", r"micro-?services?"),
          ("REST APIs", r"\brest(?:ful)?\b"), ("Multithreading", r"multi-?thread|concurren"), ("Kafka", r"\bkafka\b"),
          ("Hibernate/JPA", r"hibernate|\bjpa\b"), ("SQL/DB", r"\bsql\b|mysql|postgres|pl/?sql|oracle database|oracle db"),
          ("NoSQL", r"mongodb|cassandra|dynamodb|\bnosql\b"), ("Redis", r"\bredis\b"), ("RabbitMQ/MQ", r"rabbitmq|activemq|ibm mq"),
          ("Docker", r"\bdocker\b"), ("Kubernetes", r"kubernetes|\bk8s\b"), ("AWS", r"\baws\b|amazon web services"),
          ("Azure", r"\bazure\b"), ("GCP", r"\bgcp\b|google cloud"), ("CI/CD", r"ci/cd|jenkins|gitlab ci|github actions"),
          ("Git", r"\bgit\b"), ("Maven/Gradle", r"\bmaven\b|\bgradle\b"), ("JUnit/Mockito", r"junit|mockito"),
          ("Design Patterns", r"design patterns?"), ("DSA", r"data structures|algorithms"),
          ("System Design", r"system design|distributed systems?"), ("GraphQL", r"graphql"), ("Python", r"\bpython\b"),
          ("Angular/React", r"\bangular\b|\breact\b"), ("Agile", r"\bagile\b|\bscrum\b")]
def analyze(j, text, locfull):
    """-> (alert?, info dict)"""
    if locfull and not loc_ok(locfull): return False, {"why": "location"}
    blob = (j["title"] + " " + (text or "")).lower()
    if text:
        if not re.search(r"\bjava\b", blob) and not j.get("trust_java"): return False, {"why": "no Java in description"}
        hits = [k for k, p in SKILLS if re.search(p, blob)][:14]
        if len(hits) < SK["min_other_hits"]: return False, {"why": "skills"}
        verdict, label = parse_years(text)
        if verdict == "no" or (verdict == "unknown" and not X["send_if_unknown"]): return False, {"why": "experience " + label}
        return True, dict(exp=label, skills=["Java"] + hits, jd=True)
    t = j["title"].lower()                       # job description unreadable
    if "java" in t or "backend" in t or "back end" in t or "back-end" in t:
        return True, dict(exp="JD not readable - check", skills=[], jd=False)
    return False, {}

# ======================= telegram =======================
def send(text):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if DRY or not tok or not chat:
        print("[would send]", text.replace("\n", " | ")); return True
    for _ in range(3):
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=30,
                          json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True})
        if r.ok: time.sleep(1.1); return True
        if r.status_code == 429:
            time.sleep(r.json().get("parameters", {}).get("retry_after", 5) + 1); continue
        print("telegram error", r.status_code, r.text); return False
    return False
def fmt(name, j, info):
    lines = [f"🆕 {name} - {j['title']}", f"📍 {j['loc'] or 'see posting'}",
             f"🧪 Experience: {info['exp']}"]
    if info["skills"]: lines.append("🛠 Skills asked: " + ", ".join(info["skills"]))
    lines.append(f"🆔 Job ID: {j.get('req') or j['id']}")
    if j.get("posted"): lines.append(f"🕒 Posted: {j['posted']}")
    lines.append(f"🔗 Apply: {j['url']}")
    return "\n".join(lines)

# ======================= main =======================
def load(p, default): return json.load(open(p)) if p.exists() else default
def save(p, obj):
    if DRY: return
    p.parent.mkdir(exist_ok=True); json.dump(obj, open(p, "w"), indent=0, sort_keys=True)

def conf_for(c, resolved):
    r = dict(resolved.get(c["name"]) or {"type": "linkedin"}); r.update(name=c["match"], match=c["match"]) if r["type"] == "linkedin" else None
    return r

def main():
    state = load(SEEN_F, {}); seen = state.setdefault("seen", {}); last = state.setdefault("last_run", {}); fails = state.setdefault("fails", {})
    resolved = load(RES_F, {}); now = time.time(); comps = CFG["companies"]

    def has_feed(n): return resolved.get(n, {}).get("type") not in (None, "linkedin")
    todo = [c for c in comps if not has_feed(c["name"]) and (SELFTEST or c["name"] not in resolved)]
    if todo:
        with ThreadPoolExecutor(3) as ex:
            for c, conf in zip(todo, ex.map(discover, todo)): resolved[c["name"]] = conf
        save(RES_F, resolved)

    def fetch(c):
        r = conf_for(c, resolved)
        try: return c, r, LIST[r["type"]](r), None
        except Exception as e: return c, r, None, (reason(e) if isinstance(e, requests.RequestException) else str(e)[:100])
    direct = [c for c in comps if conf_for(c, resolved)["type"] != "linkedin"]
    li = sorted([c for c in comps if conf_for(c, resolved)["type"] == "linkedin"], key=lambda c: last.get(c["name"], 0))
    with ThreadPoolExecutor(6) as ex: results = list(ex.map(fetch, direct))
    empty = [x for x in results if x[3] is None and not x[2] and (x[1]["type"] == "eightfold" or not TOTALS.get(x[1].get("api")))]
    if empty:                                # feed answers but is empty/wrong (e.g. wrong site name) -> use the job-board route instead
        results = [x for x in results if x not in empty]; li += [x[0] for x in empty]
    if ADZ_ON and li:
        if SELFTEST or now - last.get("__adzuna", 0) >= 25 * 60:
            try: ajobs, aerr = adzuna_jobs(), None; last["__adzuna"] = now
            except Exception as e: ajobs, aerr = [], (reason(e) if isinstance(e, requests.RequestException) else str(e)[:80])
            for c in li:
                mine = [j for j in ajobs if norm(j["company"]).startswith(norm(c["match"]))]
                results.append((c, {"type": "adzuna"}, None if aerr else mine, aerr))
        else:
            results += [(c, {"type": "adzuna"}, None, "skipped") for c in li]
    elif not USE_LINKEDIN:
        results += [(c, conf_for(c, resolved), None, "nofeed") for c in li]
    else:                                   # LinkedIn: one at a time, 3s apart, stop at the first block
        blocked = False
        for i, c in enumerate(li):
            r = conf_for(c, resolved)
            if not SELFTEST and i >= LI_PER_RUN: results.append((c, r, None, "skipped")); continue
            if blocked: results.append((c, r, None, "LinkedIn blocked this server (rate limit)")); continue
            res = fetch(c); results.append(res)
            if res[3] in ("HTTP 429", "HTTP 999", "HTTP 403"): blocked = True
            time.sleep(3)

    if SELFTEST:
        ok, nofeed, bad, lik = [], [], [], []
        for c, r, jobs, err in results:
            if not err and r["type"] in ("linkedin", "adzuna"):
                lik.append(f"🟣 {c['name']}: {len(jobs)} recent Java jobs in your cities, {sum(quick_ok(j) for j in jobs)} pass filter"); continue
            if err == "nofeed": nofeed.append(f"⚪ {c['name']} - {resolved.get(c['name'], {}).get('why', '')}\n   {c['url']}")
            elif err: bad.append(f"❌ {c['name']} ({LABEL[r['type']]}): {err}")
            else:
                tot = TOTALS.get(r.get("api")); mark = "⚠️" if (not jobs and not tot) else "✅"
                ok.append(f"{mark} {c['name']} [{LABEL[r['type']]}]: {len(jobs)} jobs read" + (f" (site total {tot})" if tot is not None else "")
                          + f", {sum(quick_ok(j) for j in jobs)} pass title/location/age filter")
        for title, rows in ((f"SELF-TEST: {len(ok)} companies on direct feeds", ok),
                            (f"{len(lik)} covered via Adzuna job board (company has no direct feed; checked every ~30 min)", lik),
                            (f"{len(bad)} failed to read", bad),
                            (f"{len(nofeed)} with NO automatic feed (check these by hand or send me their job-search URL)", nofeed)):
            for i in range(0, len(rows), 25):
                if rows: send(title + "\n\n" + "\n".join(rows[i:i + 25]))
        return

    queue, summary, fresh_n = [], [], 0
    for c, r, jobs, err in results:
        n = c["name"]
        if err in ("skipped", "nofeed") or (err or "").startswith("LinkedIn blocked"): continue
        if err and r["type"] == "adzuna":
            fails["__adzuna"] = fails.get("__adzuna", 0) + 1; print(f"[Adzuna] FAILED x{fails['__adzuna']}: {err}")
            if fails["__adzuna"] == 12: send("⚠️ Adzuna job-board lookup has failed 12 runs in a row. Check ADZUNA_APP_ID / ADZUNA_APP_KEY secrets.")
            continue
        if err:
            fails[n] = fails.get(n, 0) + 1; print(f"[{n}] FAILED x{fails[n]}: {err}")
            if fails[n] == 12: send(f"⚠️ {n}: career feed failed 12 runs in a row. Run the self-test or fix its entry in companies.yaml.")
            continue
        fails[n] = 0; last[n] = now
        if r["type"] == "adzuna": fails["__adzuna"] = 0
        new = [j for j in jobs if f"{n}|{j['id']}" not in seen]
        fresh_n += sum(1 for j in jobs if j.get("age") is None or j["age"] <= F["max_age_days"])
        cand, why = [], {}
        for j in new:
            rr = reject_reason(j)
            if rr is None: cand.append(j)
            else: seen[f"{n}|{j['id']}"] = now; why[rr] = why.get(rr, 0) + 1   # irrelevant -> never look again
        cap = 5 if r["type"] == "linkedin" else MAX_DETAIL
        for j in cand[:cap]:
            try:
                text, locfull = (j["desc"], None) if j.get("desc") else (DETAIL[r["type"]](r, j) if r["type"] in DETAIL else ("", None))
            except Exception as e:
                key = f"{n}|{j['id']}"; df = state.setdefault("detail_fail", {}); df[key] = df.get(key, 0) + 1
                print(f"[{n}] detail failed ({df[key]}): {e}")
                if df[key] < 3: continue                      # try again next run, don't mark as seen
                text, locfull = "", None
            good, info = analyze(j, text, locfull)
            if good: queue.append((n, j, info))
            else: seen[f"{n}|{j['id']}"] = now; print(f"   rejected [{n}] {j['title'][:60]}: {info.get('why', '?')}")
        summary.append(f"{n}: {len(jobs)} jobs, {len(new)} unseen, {len(cand)} candidates" + (f"  (skipped: {why})" if why else ""))

    sent = 0
    log = state.setdefault("sent_ts", [])
    for n, j, info in queue[:MAX_ALERTS]:
        if send(fmt(n, j, info)): seen[f"{n}|{j['id']}"] = now; sent += 1; log.append(now)
    state["sent_ts"] = [t for t in log if now - t < 2 * 86400]
    # "no jobs" report: if nothing was sent for N hours, say so (quiet at night)
    R = CFG.get("report", {})
    every = R.get("every_hours", 4) * 3600
    ist = dt.datetime.fromtimestamp(now, dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)
    quiet = ist.hour >= R.get("quiet_start", 23) or ist.hour < R.get("quiet_end", 7)
    lr = state.get("last_report")
    if lr is None: state["last_report"] = now
    elif now - lr >= every - 120 and not quiet and os.getenv("TELEGRAM_BOT_TOKEN"):
        if not any(t > lr for t in state["sent_ts"]):
            live = sum(1 for _, _, jobs, err in results if jobs is not None)
            hrs = max(1, round((now - lr) / 3600))
            if send(f"🕓 No new matching jobs in the last {hrs} hours. Bot is running; checked {live} company feeds "
                    f"({fresh_n} postings from the last {F['max_age_days']} days were seen, none fit Java / 2 yrs / Hyderabad-Bangalore)."):
                state["last_report"] = now
        else:
            state["last_report"] = now
    for k in [k for k, t in seen.items() if now - t > 120 * 86400]: del seen[k]
    save(SEEN_F, state)
    print("\n".join(summary)); print(f"alerts sent: {sent}")

if __name__ == "__main__":
    main()
