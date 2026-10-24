#!/usr/bin/env python3
"""Free job-alert watcher.
 normal run : find NEW jobs that fit (Java/Spring, ~2 yrs, Bangalore/Hyderabad) -> Telegram, never repeats a job
 --selftest : check every company, send a working / not-working report to Telegram
 --dry      : print instead of sending, don't save state
"""
import json, os, re, sys, time, html, hashlib, pathlib, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import urllib.parse as up
import requests, yaml
import experience as E

ROOT = pathlib.Path(__file__).parent
SEEN_F, RES_F = ROOT/"state"/"seen.json", ROOT/"state"/"resolved.json"
CFG = yaml.safe_load(open(ROOT/"companies.yaml", encoding="utf-8"))
F, X, SK, HINTS = CFG["filters"], CFG["experience"], CFG["skills"], CFG.get("hints", {})
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
DRY, SELFTEST = "--dry" in sys.argv, "--selftest" in sys.argv
MSG = dict(job_alerts=True, daily_report=False, no_jobs_notice=False, warnings=False); MSG.update(CFG.get("messages") or {})   # default: ONLY job alerts
MAX_ALERTS, MAX_DETAIL = 20, 12
DISCOVERY_BUDGET = 1500                      # seconds of route discovery per run before it carries on next time

def get(url, **kw):  return requests.get(url, headers=UA, timeout=kw.pop("timeout", 20), **kw)
def post(url, **kw): return requests.post(url, headers=UA, timeout=kw.pop("timeout", 20), **kw)
def clean(h):
    h = html.unescape(h or "")
    h = re.sub(r"(?i)</(?:p|div|li|ul|ol|h\d|tr|section)>|<br\s*/?>", "\n", h)
    h = html.unescape(re.sub(r"<[^>]+>", " ", h))
    h = re.sub(r"[ \t\r\f\xa0]+", " ", h)
    return re.sub(r"\s*\n\s*", "\n", h).strip()
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
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if t.tzinfo is None: t = t.replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 86400
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
            d = r.json()
            return "jobPostings" in d and d.get("total", 1) > 0
        except requests.Timeout:
            if attempt == 3: raise
TOTALS = {}
PAGES = {}                                    # pagination status per feed, shown by the self-test
def feed_key(r): return r.get("api") or f"{r.get('type')}:{r.get('host') or r.get('board') or r.get('slug') or r.get('company_id') or r.get('sub')}"
WD_LOCK = __import__("threading").BoundedSemaphore(4)                       # at most 4 Workday requests at once
def wd_req(api, body):
    import random
    with WD_LOCK:
        time.sleep(random.uniform(0.1, 0.5))
        return _wd_req(api, body)
def _wd_req(api, body):
    for attempt in range(4):                       # Workday rate-limits shared servers: wait and retry
        resp = post(api + "/jobs", json=body, timeout=40)
        if resp.status_code in (429, 503): time.sleep(8 * (attempt + 1)); continue
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
def wd_req_id(j, path):
    """official requisition id; the trailing -1/-2 on the page path is Workday's re-listing counter, not part of the id"""
    for b in (j.get("bulletFields") or []):
        if re.search(r"\d{4,}", str(b)): return str(b).strip()
    return re.sub(r"-\d{1,2}$", "", path.rsplit("_", 1)[-1])
def wd_list(r):
    """newest-first with the city filter applied by Workday itself; falls back to scanning newest jobs worldwide"""
    first = wd_req(r["api"], {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""})
    TOTALS[r["api"]] = first.get("total")
    try: facets = wd_location_facets(first.get("facets"))
    except Exception: facets = {}
    out, page, stop = [], 0, "STOPPED at the 15-page cap, more jobs may exist"
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
            ag = age_days(j.get("postedOn", "")); ages.append(ag)
            out.append(dict(id=p, req=wd_req_id(j, p), title=j.get("title", ""),
                            loc=j.get("locationsText", ""), url=r["web"] + p, posted=j.get("postedOn", ""), age=ag))
        if len(posts) < 20: stop = "reached the end of the list"; break
        if ages and all(a is not None and a > F["max_age_days"] for a in ages): stop = f"newest-first scan reached jobs older than {F['max_age_days']} days"; break
        page += 1
    PAGES[r["api"]] = f"{page + 1} page(s) read; {stop}"
    return dedupe(out)
def wd_detail(r, j):
    d = get(r["api"] + j["id"]).json()["jobPostingInfo"]
    loc = " ".join([d.get("location", "")] + (d.get("additionalLocations") or []))
    return clean(d.get("jobDescription", "")), loc

def gh_list(r):
    d = get(f"https://boards-api.greenhouse.io/v1/boards/{r['board']}/jobs" + ("?content=true" if r.get("content") else ""), timeout=40).json()["jobs"]
    PAGES[feed_key(r)] = "whole board returned in one response"
    return [dict(id=str(j["id"]), req=str(j["id"]), title=j["title"], loc=(j.get("location") or {}).get("name", ""), url=j["absolute_url"],
                 posted=((j.get("first_published") or j.get("updated_at") or ""))[:10], age=iso_age(j.get("first_published") or j.get("updated_at") or ""),
                 updated=j.get("updated_at") or "", **({"desc": clean(j.get("content", ""))} if r.get("content") else {})) for j in d]
def gh_detail(r, j):
    d = get(f"https://boards-api.greenhouse.io/v1/boards/{r['board']}/jobs/{j['id']}", timeout=30).json()
    return clean(d.get("content", "")), (d.get("location") or {}).get("name", "")

def lv_list(r):
    d = get(f"https://api.lever.co/v0/postings/{r['slug']}?mode=json").json()
    PAGES[feed_key(r)] = "whole board returned in one response"
    return [dict(id=j["id"], req=j["id"][:8], title=j["text"], loc=(j.get("categories") or {}).get("location", ""),
                 url=j["hostedUrl"], posted="", age=epoch_age(j.get("createdAt")),
                 desc=clean(j.get("descriptionPlain", "") + " " + " ".join(l.get("content", "") for l in j.get("lists", [])))) for j in d]

def ab_list(r):
    d = get(f"https://api.ashbyhq.com/posting-api/job-board/{r['org']}", timeout=40).json()
    PAGES[feed_key(r)] = "whole board returned in one response"
    return [dict(id=str(j["id"]), req=str(j["id"]), title=j.get("title", ""), loc=j.get("location", "") or "", url=j.get("jobUrl") or f"https://jobs.ashbyhq.com/{r['org']}/{j['id']}",
                 posted=(j.get("publishedAt") or "")[:10], age=iso_age(j.get("publishedAt") or ""), updated=j.get("publishedAt") or "",
                 desc=(j.get("descriptionPlain") or clean(j.get("descriptionHtml", "")))) for j in d.get("jobs", []) if j.get("isListed", True)]

def sr_list(r):
    out, stop, pages = [], "reached the end of the list", 0
    for q in F["search_terms"][:3]:
        for page in range(3):
            d = get(f"https://api.smartrecruiters.com/v1/companies/{r['company_id']}/postings", params={"q": q, "limit": 100, "offset": page * 100}).json()
            rows = d.get("content", []); pages += 1
            for j in rows:
                l = j.get("location") or {}
                out.append(dict(id=j["id"], req=j["id"], title=j["name"], loc=f"{l.get('city','')} {l.get('country','')}",
                                url=f"https://jobs.smartrecruiters.com/{r['company_id']}/{j['id']}",
                                posted=(j.get("releasedDate") or "")[:10], age=iso_age(j.get("releasedDate") or "")))
            if len(rows) < 100: break
            if page == 2: stop = "STOPPED at 3 pages per search term, more jobs may exist"
    PAGES[feed_key(r)] = f"{pages} request(s); {stop}"
    return dedupe(out)
def sr_detail(r, j):
    d = get(f"https://api.smartrecruiters.com/v1/companies/{r['company_id']}/postings/{j['id']}").json()
    secs = (d.get("jobAd") or {}).get("sections") or {}
    return clean(" ".join((v or {}).get("text", "") for v in secs.values())), None

def ef_list(r):
    out, stop, pages = [], "reached the end of the list", 0
    for q in F["search_terms"][:3]:
        for page in range(4):
            d = get(f"https://{r['sub']}.eightfold.ai/api/apply/v2/jobs",
                    params={"domain": r["domain"], "start": page * 50, "num": 50, "query": q, "location": "India", "sort_by": "timestamp"}).json()
            pos = d.get("positions", []); pages += 1
            for p in pos:
                out.append(dict(id=str(p["id"]), req=str(p.get("display_job_id") or p["id"]), title=p["name"], loc=p.get("location", ""),
                                url=p.get("canonicalPositionUrl") or f"https://{r['sub']}.eightfold.ai/careers/job/{p['id']}",
                                posted="", age=epoch_age(p.get("t_create")), desc=clean(p.get("job_description", ""))))
            if len(pos) < 50: break
            if page == 3: stop = "STOPPED at 4 pages per search term, more jobs may exist"
    PAGES[feed_key(r)] = f"{pages} request(s); {stop}"
    return dedupe(out)

def oh_list(r):
    out, stop, pages = [], "reached the end of the list", 0
    for q in F["search_terms"][:3]:
        for page in range(5):
            d = get(f"https://{r['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                    params={"onlyData": "true", "expand": "requisitionList.secondaryLocations",
                            "finder": f"findReqs;siteNumber={r['site']},limit=50,offset={page * 50},keyword={q},sortBy=POSTING_DATES_DESC"}).json()
            rows = ((d.get("items") or [{}])[0]).get("requisitionList", []); pages += 1
            ages = []
            for j in rows:
                ag = iso_age((j.get("PostedDate") or "") + "T00:00:00+00:00"); ages.append(ag)
                out.append(dict(id=str(j["Id"]), req=str(j["Id"]), title=j["Title"], loc=j.get("PrimaryLocation", ""),
                                url=f"https://{r['host']}/hcmUI/CandidateExperience/en/sites/{r['site']}/job/{j['Id']}",
                                posted=(j.get("PostedDate") or "")[:10], age=ag))
            if len(rows) < 50: break
            if ages and all(a is not None and a > F["max_age_days"] for a in ages): break
            if page == 4: stop = "STOPPED at 5 pages per search term, more jobs may exist"
    PAGES[feed_key(r)] = f"{pages} request(s); {stop}"
    return dedupe(out)
def oh_detail(r, j):
    d = get(f"https://{r['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails",
            params={"expand": "all", "onlyData": "true", "finder": f'ById;Id="{j["id"]}",siteNumber={r["site"]}'}).json()
    it = (d.get("items") or [{}])[0]
    return clean(it.get("ExternalDescriptionStr", "") + " " + it.get("ExternalQualificationsStr", "")), None


def page_text(url):
    """-> (text, structured). structured=True only when the page carries schema.org JobPosting data with the description body."""
    r = get(url, timeout=25, allow_redirects=True); r.raise_for_status()
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', r.text, re.S | re.I):
        try: data = json.loads(m.group(1))
        except Exception: continue
        for d in (data if isinstance(data, list) else [data]):
            if isinstance(d, dict) and d.get("@type") == "JobPosting" and d.get("description"): return clean(d["description"]), True
    return clean(re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", r.text))[:30000], False

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
                                trust_java=True, snippet=True))
    return dedupe(out)

def adzuna_probe(c):
    """does Adzuna list ANY job of this company? (a company with zero Java jobs today is different from a company Adzuna does not index)"""
    try:
        r = get("https://api.adzuna.com/v1/api/jobs/in/search/1", params=dict(app_id=os.getenv("ADZUNA_APP_ID"), app_key=os.getenv("ADZUNA_APP_KEY"),
                                                                               what=c["name"], results_per_page=20))
        r.raise_for_status()
        return any(norm(((x.get("company") or {}).get("display_name") or "")).startswith(norm(c["match"])) for x in r.json().get("results", []))
    except Exception:
        return None

# ---------- generic career-page adapters: work for ANY site that publishes schema.org JobPosting data (Google-for-Jobs markup) ----------
def jobposting(page_html):
    """the schema.org JobPosting object (JSON-LD) of a page, or None"""
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page_html or "", re.S | re.I):
        try: data = json.loads(m.group(1).strip())
        except Exception: continue
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list): stack.extend(d); continue
            if not isinstance(d, dict): continue
            t = d.get("@type")
            if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t): return d
            if "@graph" in d: stack.append(d["@graph"])
    return None

def jp_location(jp):
    out, locs = [], jp.get("jobLocation")
    for l in (locs if isinstance(locs, list) else [locs] if locs else []):
        a = (l or {}).get("address") or {}
        if isinstance(a, str): out.append(a); continue
        ctry = a.get("addressCountry"); ctry = ctry if isinstance(ctry, str) else (ctry or {}).get("name")
        out.append(", ".join(str(x) for x in (a.get("addressLocality"), a.get("addressRegion"), ctry) if x))
    if jp.get("jobLocationType") == "TELECOMMUTE": out.append("Remote")
    return " | ".join(x for x in out if x)

def gen_detail(r, j):
    """official job page -> (description, location). Fills in the real title / requisition id / posting date from the JobPosting data."""
    time.sleep(0.4)
    resp = get(j["url"], timeout=30, allow_redirects=True); resp.raise_for_status()
    jp = jobposting(resp.text)
    if not jp:
        j["partial_page"] = True                      # no structured description body: we cannot call it complete
        return clean(re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", resp.text))[:30000], None
    ident = jp.get("identifier")
    if isinstance(ident, dict): ident = ident.get("value") or ident.get("name")
    if ident: j["req"] = str(ident)
    if jp.get("title"): j["title"] = clean(str(jp["title"]))
    dp = str(jp.get("datePosted") or "")
    if dp: j["posted"] = dp[:10]; j["age"] = iso_age(dp if "T" in dp else dp + "T00:00:00+00:00")
    return clean(str(jp.get("description") or "")), jp_location(jp)

def _sitemap_urls(url, depth=0):
    resp = get(url, timeout=40); resp.raise_for_status()
    body = resp.content
    if body[:2] == b"\x1f\x8b":
        import gzip; body = gzip.decompress(body)
    text = body.decode("utf-8", "replace")
    if "<sitemapindex" in text:
        out = []
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text)[:60]:
            if depth < 2 and re.search(r"job|career|position|opening|vacanc|posting|requisition|search", up.urlparse(loc).path, re.I):
                try: out += _sitemap_urls(html.unescape(loc), depth + 1)
                except Exception: continue                                              # one broken child sitemap must not hide the others
        return out
    out = []
    for blk in re.findall(r"<url>(.*?)</url>", text, re.S):
        loc = re.search(r"<loc>\s*([^<\s]+)\s*</loc>", blk); lm = re.search(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", blk)
        if loc: out.append((html.unescape(loc.group(1)), lm.group(1) if lm else ""))
    return out

JOB_URL_RE = r"/jobs?/|/job-|/careers?/[^/]*\d{4,}|/position|/opening|/vacanc|jobid=|requisition|/jobdetail|/job-detail|/details?/\d"
def sm_list(r):
    rx = re.compile(r.get("match") or JOB_URL_RE, re.I); items, out = [], []
    for sm in r["sitemaps"]: items += _sitemap_urls(sm)
    for loc, lm in items:
        if not rx.search(loc): continue
        age = iso_age(lm if "T" in lm else lm + "T00:00:00+00:00") if lm else None
        if age is not None and age > F["max_age_days"] + 1: continue               # lastmod >= posting date, so older entries cannot be fresh postings
        slug = loc.rstrip("/").rsplit("/", 1)[-1]
        out.append(dict(id=loc.split("#")[0], req="", title=re.sub(r"[-_]+", " ", re.sub(r"\.\w+$", "", slug))[:90], loc="", url=loc.split("#")[0],
                        posted=lm[:10] if lm else "", age=age))
    PAGES[feed_key(r)] = f"{len(items)} sitemap URLs read, {len(out)} job pages" + ("" if any(o["age"] is not None for o in out) or not out else "") + (" (no lastmod: new-URL detection)" if out and all(o["age"] is None for o in out) else "")
    return dedupe(out)

def hl_list(r):
    link = re.compile(r["link"], re.I); out, seen, pages = [], set(), 0
    for page in range(1, int(r.get("pages", 6)) + 1):
        resp = get(r["url"].format(page=page), timeout=30, allow_redirects=True); resp.raise_for_status(); pages += 1; new = 0
        for href, label in re.findall(r'<a\s[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', resp.text, re.S | re.I):
            u = up.urljoin(resp.url, html.unescape(href)).split("#")[0].split("?")[0]
            if not link.search(u) or u in seen: continue
            seen.add(u); new += 1
            out.append(dict(id=u, req="", title=(clean(label)[:90] or u.rstrip("/").rsplit("/", 1)[-1]), loc="", url=u, posted="", age=None))
        if not new or "{page}" not in r["url"]: break
    PAGES[feed_key(r)] = f"{pages} listing page(s) read, {len(out)} job links (no posting dates: new-URL detection)"
    return dedupe(out)


def _path(d, p):
    if p in ("", None): return d
    for k in str(p).split("."):
        if isinstance(d, list):
            try: d = d[int(k)]
            except Exception: return None
        elif isinstance(d, dict): d = d.get(k)
        else: return None
        if d is None: return None
    return d
def _loc_text(v):
    if v is None: return ""
    if isinstance(v, str): return v
    if isinstance(v, dict): return str(v.get("display") or v.get("name") or v.get("city") or "")
    return " | ".join(x for x in (_loc_text(i) for i in v) if x)
def _when(v, fmt):
    if not v: return None
    try:
        if fmt: t = dt.datetime.strptime(str(v).strip(), fmt).replace(tzinfo=dt.timezone.utc); return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 86400
    except Exception: return None
    v = str(v); return iso_age(v if "T" in v else v + "T00:00:00+00:00")
def _desc(x, parts):
    out = []
    for label, p in parts:
        t = clean(str(_path(x, p) or ""))
        if t: out.append((label + ":\n" if label else "") + t)
    return "\n".join(out)
def ja_list(r):
    out, size, p0 = [], int(r.get("page_size", 20)), int(r.get("start_page", 1))
    for page in range(p0, p0 + int(r.get("pages", 5))):
        data = get(r["url"].format(page=page, offset=(page - p0) * size, size=size), timeout=40).json()
        rows = _path(data, r.get("list", "")) or []
        for x in rows:
            jid = str(_path(x, r["id"]) or "")
            if not jid: continue
            posted = _path(x, r.get("posted"))
            j = dict(id=jid, req=jid, title=clean(str(_path(x, r["title"]) or "")), loc=_loc_text(_path(x, r.get("loc"))),
                     url=re.sub(r"\{([^}]+)\}", lambda m: str(_path(x, m.group(1)) or ""), r["job_url"]),
                     posted=str(posted or "")[:10], age=_when(posted, r.get("posted_format")))
            if r.get("desc"): j["desc"] = _desc(x, r["desc"])
            out.append(j)
        if len(rows) < size: break
    PAGES[feed_key(r)] = f"{len(out)} jobs read from the site's JSON feed"
    return dedupe(out)
def ja_detail(r, j):
    d = get(r["detail_url"].replace("{id}", j["id"]).replace("{jobId}", j["id"]), timeout=30).json()
    return _desc(d, r["detail_desc"]), None

LIST = dict(workday=wd_list, json_api=ja_list, ashby=ab_list, greenhouse=gh_list, lever=lv_list, smartrecruiters=sr_list,
            eightfold=ef_list, oraclehcm=oh_list, sitemap=sm_list, html_listing=hl_list)
DETAIL = dict(json_api=ja_detail, greenhouse=gh_detail, workday=wd_detail, smartrecruiters=sr_detail, oraclehcm=oh_detail, sitemap=gen_detail, html_listing=gen_detail)
LABEL = dict(json_api="Site JSON feed", ashby="Ashby", workday="Workday", greenhouse="Greenhouse", lever="Lever", smartrecruiters="SmartRecruiters",
             eightfold="Eightfold", oraclehcm="Oracle HCM", adzuna="Adzuna job board (optional backup)",
             sitemap="Career-site sitemap + JobPosting data", html_listing="Career-page job list", none="no route")

# ======================= auto-discovery of each company's job feed =======================
WD_DCS = ["wd1", "wd5", "wd3", "wd12", "wd501", "wd103"]
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

def tenant_guesses(c):
    """likely Workday tenant names: from hints, the company name and the careers-page domain"""
    out = []
    for hh in ([HINTS[c["name"]]] if not isinstance(HINTS.get(c["name"]), list) else HINTS[c["name"]]) if HINTS.get(c["name"]) else []:
        if hh.get("tenant"): out.append(hh["tenant"])
    words = re.findall(r"[a-z0-9]+", c["name"].lower())
    out += [norm(c["name"]), words[0] if words else "", "".join(words[:2])]
    host = up.urlparse(c["url"]).hostname or ""
    parts = [p for p in host.split(".") if p not in ("www", "jobs", "careers", "career", "com", "in", "co", "org", "net", "io")]
    out += parts[-1:]
    seen, res = set(), []
    for t in out:
        if t and t not in seen and len(t) > 2: seen.add(t); res.append(t)
    return res[:3]

def wd_root_confs(tenant):
    """a Workday tenant's root address redirects to its public job site - that gives us the real site name"""
    for dc in WD_DCS:
        time.sleep(0.3)
        try: resp = get(f"https://{tenant}.{dc}.myworkdayjobs.com/", timeout=8, allow_redirects=True)
        except Exception: continue
        if not (up.urlparse(resp.url).hostname or "").endswith("myworkdayjobs.com"): continue
        found = set()
        m = re.match(r"/(?:[a-z]{2}-[A-Za-z]{2}/)?([A-Za-z0-9_\-]+)", up.urlparse(resp.url).path)
        if m: found.add(m.group(1))
        found |= set(re.findall(r"/wday/cxs/" + re.escape(tenant) + r"/([A-Za-z0-9_\-]+)", resp.text[:300000]))
        for site in found:
            if site.lower() in ("wday", "login", "assets", "favicon.ico", "robots.txt"): continue
            yield dict(type="workday", api=f"https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}", web=f"https://{tenant}.{dc}.myworkdayjobs.com/en-US/{site}")

def robots_sitemaps(base_url):
    root = f"{up.urlparse(base_url).scheme}://{up.urlparse(base_url).netloc}"
    try:
        txt = get(root + "/robots.txt", timeout=15).text
        sms = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", txt)
    except Exception: sms = []
    return sms or [root + "/sitemap.xml"]

def job_link_pattern(page_html, base):
    """if the careers page itself lists job links, return a regex that matches them"""
    links = {up.urljoin(base, html.unescape(h)).split("#")[0].split("?")[0] for h in re.findall(r'href=["\']([^"\'#]+)["\']', page_html or "")}
    for rx in (r"/jobs?/\d{5,}", r"/job/[^/]+/[^/]+", r"/jobs?/[^/?]+/\d{4,}", r"/jobdetail|/job-detail|/jobs/view", r"/position[s]?/\d+", r"/careers?/[^/]+/\d{4,}", r"/jobs?/[a-z0-9-]{12,}"):
        if len([l for l in links if re.search(rx, l, re.I)]) >= 3: return rx
    return None

def candidates(c):
    h = HINTS.get(c["name"])
    if h:
        for hh in (h if isinstance(h, list) else [h]):
            if hh["type"] == "workday": yield from wd_confs(hh["tenant"], hh["sites"], hh.get("dc"))
            else: yield dict(hh)
    text, base = "", c["url"]
    try:
        resp = get(c["url"], allow_redirects=True); base, text = resp.url, resp.text[:600000]
        yield from scan_page(resp.url + " " + text)                                    # ATS links inside the careers page
    except Exception:
        pass
    for t in tenant_guesses(c): yield from wd_root_confs(t)                            # Workday tenants found from the company / domain name
    yield dict(type="sitemap", sitemaps=robots_sitemaps(base)[:6])                     # the site's own sitemap (public, meant for crawlers)
    rx = job_link_pattern(text, base)
    if rx: yield dict(type="html_listing", url=base, link=rx, pages=1)                 # job links listed right on the careers page

def reason(e):
    if isinstance(e, requests.HTTPError): return f"HTTP {e.response.status_code}"
    if isinstance(e, requests.Timeout): return "timeout"
    if isinstance(e, requests.ConnectionError): return "no such host"
    return type(e).__name__

def verify_generic(cand, jobs):
    """a sitemap / job-list route only counts if real job pages carry JobPosting data (so the full description can be read)"""
    if len(jobs) < 3: raise ValueError("fewer than 3 job links")
    for j in jobs[:4]:
        try:
            if jobposting(get(j["url"], timeout=25).text): return True
        except Exception: continue
    raise ValueError("job pages carry no JobPosting data")

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
                jobs = LIST[cand["type"]](cand)
                if cand["type"] in ("sitemap", "html_listing"): verify_generic(cand, jobs)
            return cand
        except Exception as e:
            k = reason(e) if isinstance(e, requests.RequestException) else str(e)[:50]; why[k] = why.get(k, 0) + 1
            continue
    real = {k: v for k, v in why.items() if k != "no such host"}
    return dict(type="none", why=", ".join(f"{k} x{v}" for k, v in sorted(real.items(), key=lambda x: -x[1])[:3]) or "no job feed found on its career page")

# ======================= fit logic =======================
def loc_ok(s): return any(k in (s or "").lower() for k in F["locations"])
SKIP_RE = re.compile(r"\b(?:" + "|".join(re.escape(x) for x in F.get("skip_titles", ["qa"])) + r")\b", re.I)
def reject_reason(j):
    t = j["title"].lower()
    if F.get("skip_titles") and SKIP_RE.search(j["title"]): return "title (not a backend engineering role)"
    if F.get("use_title_filter", True) and (not any(k in t for k in F["include_title"]) or any(k in t for k in F["exclude_title"])): return "title"
    if j.get("age") is not None and j["age"] > F["max_age_days"]: return "older than %sd" % F["max_age_days"]
    loc = (j["loc"] or "").lower()
    if not loc or re.search(r"\d+\s+locations?", loc): return None
    return None if loc_ok(loc) else "location"
def quick_ok(j): return reject_reason(j) is None

PROFILE = E.profile_from_config(X)                     # your 2.2 years and per-skill years (companies.yaml -> experience)
SKILLS = E.SKILLS

def analyze(j, desc, locfull):
    """-> (verdict 'eligible'|'ineligible'|'needs_review', info). Stage 1 extracts what the employer wrote, stage 2 applies my profile."""
    if locfull and not loc_ok(locfull): return "ineligible", {"why": "location", "codes": ["LOCATION"]}
    if j.get("age") is not None and j["age"] > F["max_age_days"] + 0.5: return "ineligible", {"why": f"posted more than {F['max_age_days']} days ago", "codes": ["TOO_OLD"]}
    blob = (j["title"] + " " + (desc.text or "")).lower()
    if desc.complete and not j.get("trust_java") and not re.search(r"\bjava\b(?!\s*script)", blob): return "ineligible", {"why": "no Java in description", "codes": ["NO_JAVA"]}
    hits = [k for k, p in SKILLS if re.search(p, blob)][:14]
    if desc.complete and len([h for h in hits if h in MY_SKILLS]) < SK["min_other_hits"]: return "ineligible", {"why": "no skills from your resume in the description", "codes": ["SKILLS"]}
    req = E.extract_experience_requirements(desc, PROFILE.total_years, PROFILE.tolerance)
    dec = E.evaluate_candidate_fit(req, PROFILE)
    return dec.verdict.value.lower(), dict(why=dec.explanation, codes=dec.reason_codes, req=req.to_dict(), decision=dec.to_dict(), desc=desc.meta(), skills=["Java"] + hits)

def fetch_description(src, r, j, key, meta):
    """-> (Description, locfull) or (None, None) when the fetch failed and should be retried next run (3 tries, then INACCESSIBLE)"""
    url = j.get("url", "")
    if j.get("desc") and not j.get("snippet"):
        return E.Description(j["desc"], E.Retrieval.FULL_JOBBOARD if src in NO_REQ_SOURCES else E.Retrieval.FULL_EMPLOYER, f"{src}:listing_api", url), None
    if src == "adzuna":
        snippet = j.get("desc", "")
        try:
            text, structured = page_text(url)
            if structured and len(text) > len(snippet):
                return E.Description(text, E.Retrieval.FULL_JOBBOARD, "adzuna:employer_page_via_redirect (JobPosting data)", url), None
            return E.Description(snippet or text, E.Retrieval.PARTIAL_SNIPPET, "adzuna:snippet", url,
                                 warnings=["no structured JobPosting data on the landing page" if not structured else "page text not longer than snippet"]), None
        except Exception as e:
            return E.Description(snippet, E.Retrieval.PARTIAL_SNIPPET, "adzuna:snippet", url, error=(reason(e) if isinstance(e, requests.RequestException) else type(e).__name__)), None
    if src in DETAIL:
        try: text, locfull = DETAIL[src](r, j)
        except Exception as e:
            df = meta.setdefault("detail_fail", {}); df[key] = df.get(key, 0) + 1
            print(f"[{j.get('title', '')[:40]}] detail failed ({df[key]}): {e}")
            if df[key] < 3: return None, None
            return E.Description("", E.Retrieval.INACCESSIBLE, f"{src}:official_job_page", url, error=(reason(e) if isinstance(e, requests.RequestException) else str(e)[:80])), None
        if j.pop("partial_page", False):
            return E.Description(text or "", E.Retrieval.PARTIAL_SNIPPET, f"{src}:page_without_JobPosting_data", url, warnings=["page has no structured job description"]), locfull
        st = (E.Retrieval.FULL_JOBBOARD if src in NO_REQ_SOURCES else E.Retrieval.FULL_EMPLOYER) if (text or "").strip() else E.Retrieval.EMPTY
        return E.Description(text or "", st, f"{src}:official_job_page", url), locfull
    return E.Description("", E.Retrieval.EMPTY, f"{src}:no_description_source", url), None

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
MY_SKILLS = set(SK.get("profile", [])) | {"Java"}            # skills from your resume (companies.yaml -> skills.profile)
def fmt(name, j, rq, dec, skills, dm):
    o = rq["overall"]
    lines = [f"🆕 {name} — {j['title']}", f"📍 {j['loc'] or 'see posting'}" + (f"  ·  🕒 {j['posted']}" if j.get("posted") else ""),
             f"🎯 Experience (verified): {o['raw_text']} → fits your {PROFILE.total_years:g} yrs"]
    if o.get("sentence"): lines.append(f"   “{o['sentence'][:110]}”")
    notes = [f"{c['skill']} {c['required']}" for c in dec["skill_checks"]][:3]
    if notes: lines.append("🔧 Skill years in JD (info only): " + "; ".join(notes))
    if skills: lines.append("🛠 " + " · ".join(x + (" ✅" if x in MY_SKILLS else "") for x in skills[:10]))
    lines += [f"🆔 {j.get('req') or j['id']}", f"🔗 {j['url']}"]
    return "\n".join(lines)

# ======================= persistent job database =======================
DB_F = ROOT / "state" / "db.json"
REPOST_ALERT = bool(CFG.get("repost_alert", False))      # default OFF: a re-listed job is recorded, never re-sent
NO_REQ_SOURCES = ("adzuna",)                   # job boards have no official requisition id

def load(p, default): return json.load(open(p)) if p.exists() else default
def save(p, obj):
    if DRY: return
    p.parent.mkdir(exist_ok=True); json.dump(obj, open(p, "w"), indent=0, sort_keys=True)

def new_db(): return {"v": 2, "jobs": {}, "fp": {}, "legacy_seen": {}, "meta": {}}
def load_db():
    if DB_F.exists(): db = json.load(open(DB_F))
    else:
        db = new_db()
        if SEEN_F.exists():                               # migrate the older seen.json so nothing already sent is sent again
            old = json.load(open(SEEN_F)); db["legacy_seen"] = old.pop("seen", {}); db["meta"] = old
    for k, v in new_db().items(): db.setdefault(k, v)
    need = ("company", "title", "url", "first_seen", "last_checked", "eligibility", "publication", "loc", "posted", "req")
    bad = [k for k, r in db["jobs"].items() if not (isinstance(r, dict) and all(f in r for f in need))]
    for k in bad: db["jobs"].pop(k)                                   # foreign / damaged records are dropped, never trusted
    if bad: print(f"dropped {len(bad)} job records with an unknown layout")
    if not isinstance(db.get("meta"), dict): db["meta"] = {}
    for rec in db["jobs"].values():
        if rec.get("schema") != 2 and rec.get("publication") == "pending":
            rec.update(publication="none", eligibility="needs_review", needs_revalidation=True, reason="created by an older version; will be re-validated")
        elif rec.get("schema") != 2 and rec.get("eligibility") in ("needs_review", "unverified"): rec["needs_revalidation"] = True
    return db
def save_db(db):                                          # atomic: a crash can never leave a half-written database
    if DRY: return
    DB_F.parent.mkdir(exist_ok=True)
    tmp = DB_F.with_suffix(".tmp"); json.dump(db, open(tmp, "w"), sort_keys=True, separators=(",", ":")); os.replace(tmp, DB_F)

def city(loc):
    l = (loc or "").lower()
    return "hyd" if "hyderabad" in l else "blr" if ("bangalore" in l or "bengaluru" in l) else "other"
def fingerprint(n, j): return f"{norm(n)}|{norm(j['title'])}|{city(j['loc'])}"
def identity(n, src, j):
    """(key, has_official_id). Official requisition id is the primary identity; job boards fall back to their own id."""
    jid = str(j.get("id") or norm(j.get("url", "") + j.get("title", "")))
    if src in NO_REQ_SOURCES: return f"{n}|{src}:{jid}", False
    req = str(j.get("req") or jid)
    return f"{n}|{req}", True

def cross_duplicate(db, key, has_req, src, fp):
    """-> ('dup'|'ambiguous'|None, other_key).  Two DIFFERENT official ids are always two vacancies, even with identical titles."""
    for k2 in db["fp"].get(fp, []):
        r2 = db["jobs"].get(k2)
        if not r2 or k2 == key: continue
        if has_req and r2.get("has_req"): continue                      # distinct requisitions
        if r2["source"] != src: return "dup", k2                        # same vacancy seen on another platform
        return "ambiguous", k2                                          # same platform, no official ids: keep both, but flag
    return None, None

def legacy_reqs(db):
    out = set()
    for k in db["legacy_seen"]:
        n, _, i = k.partition("|")
        if i.startswith("/job/"): out.add(f"{n}|" + re.sub(r"-\d{1,2}$", "", i.rsplit("_", 1)[-1]))
    return out

def rec_message(rec):
    j = dict(title=rec["title"], loc=rec["loc"], posted=rec["posted"], req=rec["req"], id=rec["req"], url=rec["url"])
    text = fmt(rec["company"], j, rec["requirements"], rec["decision"], rec["skills"], rec["description"])
    return ("🔁 Re-listed\n" + text) if rec.get("relist_alert") else text

def conf_for(c, resolved):
    r = dict(resolved.get(c["name"]) or {"type": "none"})
    return r

def main():
    db = load_db(); jobs_db, meta = db["jobs"], db["meta"]
    last = meta.setdefault("last_run", {}); fails = meta.setdefault("fails", {})
    C = meta.setdefault("counters", {})                   # counts since the last report
    def bump(k, n=1): C[k] = C.get(k, 0) + n
    resolved = load(RES_F, {}); now = time.time(); comps = CFG["companies"]
    stale = [k for k, v in resolved.items() if not (isinstance(v, dict) and (v.get("type") in LIST or v.get("type") == "none"))]
    for k in stale: del resolved[k]                                   # written by another version / unknown route type -> discover again
    if stale: print(f"ignored {len(stale)} unrecognised route entries from an older state file: {stale[:8]}")
    lreqs = legacy_reqs(db)

    def has_feed(n): return resolved.get(n, {}).get("type") not in (None, "none")
    tried = lambda n: resolved.get(n, {}).get("tried")
    def due(c):                                                       # unrouted companies are retried: self-test every 6 h, normal runs every 24 h
        n_ = c["name"]
        if n_ not in resolved: return True
        t_ = tried(n_)
        return SELFTEST if t_ is None else now - t_ > (6 if SELFTEST else 24) * 3600
    todo = sorted([c for c in comps if not has_feed(c["name"]) and due(c)], key=lambda c: tried(c["name"]) or 0)
    if not SELFTEST: todo = todo[:12]                                                                            # a normal run never spends long on discovery
    if todo:
        t0 = time.time()
        for i in range(0, len(todo), 10):                                                                        # saved after every batch: a timeout loses nothing
            batch = todo[i:i + 10]
            with ThreadPoolExecutor(5) as ex:
                for c, conf in zip(batch, ex.map(discover, batch)): conf["tried"] = now; resolved[c["name"]] = conf
            save(RES_F, resolved)
            if time.time() - t0 > DISCOVERY_BUDGET and i + 10 < len(todo):
                print(f"discovery time budget used; {len(todo) - i - 10} companies continue in the next run"); break

    def fetch(c):
        r = conf_for(c, resolved)
        try: return c, r, LIST[r["type"]](r), None
        except Exception as e: return c, r, None, (reason(e) if isinstance(e, requests.RequestException) else str(e)[:100])
    direct = [c for c in comps if conf_for(c, resolved)["type"] != "none"]
    li = sorted([c for c in comps if conf_for(c, resolved)["type"] == "none"], key=lambda c: last.get(c["name"], 0))
    with ThreadPoolExecutor(10) as ex: results = list(ex.map(fetch, direct))
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
    else:
        results += [(c, conf_for(c, resolved), None, "nofeed") for c in li]

    health = meta.setdefault("health", {})
    ist_of = lambda ts: (dt.datetime.fromtimestamp(ts, dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).strftime("%d-%b %H:%M IST")
    def note_health(c, r, jobs, err):
        h = health.setdefault(c["name"], {}); h["route"] = r["type"]
        if err in ("skipped", "nofeed"): return
        if err: h["err"], h["err_ts"] = err, now; print(f"[{c['name']}] feed error: {err}")
        else: h.update(ok_ts=now, jobs=len(jobs or []), pages=PAGES.get(feed_key(r), "n/a"), err=None)

    if SELFTEST:
        ok, nofeed, bad, lik = [], [], [], []
        for c, r, jobs, err in results:
            note_health(c, r, jobs, err); h = health[c["name"]]
            if not err and r["type"] == "adzuna":
                cov = adzuna_probe(c) if r["type"] == "adzuna" else None
                lik.append(f"🟣 {c['name']}: {len(jobs)} recent Java jobs in your cities, {sum(quick_ok(j) for j in jobs)} pass filter; "
                           f"Adzuna lists this company: {'YES' if cov else 'NO - not covered' if cov is False else 'unknown'}"); continue
            if err == "nofeed": nofeed.append(f"⚪ {c['name']} - {resolved.get(c['name'], {}).get('why', '')}\n   {c['url']}")
            elif err: bad.append(f"❌ {c['name']} ({LABEL.get(r['type'], r['type'])}): {err}" + (f" · last OK {ist_of(h['ok_ts'])}" if h.get("ok_ts") else " · never read successfully"))
            else:
                tot = TOTALS.get(r.get("api")); mark = "⚠️" if (not jobs and not tot) else "✅"
                ok.append(f"{mark} {c['name']} [{LABEL.get(r['type'], r['type'])}]: {len(jobs)} jobs read" + (f" (site total {tot})" if tot is not None else "")
                          + f", {sum(quick_ok(j) for j in jobs)} pass filter\n   pagination: {PAGES.get(feed_key(r), 'n/a')}")
        save_db(db)
        send(f"SELF-TEST: {len(comps)} companies in your list\n• direct career feeds: {len(ok)}\n• via Adzuna job board: {len(lik)}\n• failed to read: {len(bad)}\n• no automatic feed: {len(nofeed)}")
        for title, rows in ((f"{len(ok)} companies on direct feeds", ok),
                            (f"{len(lik)} covered via Adzuna job board (company has no direct feed; checked every ~30 min)", lik),
                            (f"{len(bad)} failed to read", bad),
                            (f"{len(nofeed)} with NO automatic feed (check these by hand or send me their job-search URL)", nofeed)):
            for i in range(0, len(rows), 20):
                if rows: send(title + "\n\n" + "\n".join(rows[i:i + 20]))
        return

    # ---------- discovery -> database (every job is analysed once; known jobs are skipped without re-analysis) ----------
    summary, fresh_n, run_seen, per_co = [], 0, set(), {}
    def slim(req):
        if not req: return req
        req = dict(req); req["statements"] = [{k: v for k, v in st.items() if k not in ("normalized_text", "source_url", "source_type")} for st in req["statements"]]
        req.pop("description", None); return req
    def apply_analysis(rec, verdict, info, desc, j_updated=None):
        rec.update(schema=2, description=desc.meta(), desc_sha1=desc.sha1, last_retrieval=now, requirements=slim(info.get("req")),
                   decision=info.get("decision"), skills=info.get("skills", []), codes=info.get("codes", []))
        rec["eligibility"], rec["reason"] = verdict, ("" if verdict == "eligible" else info.get("why", "?"))
        if j_updated is not None: rec["updated"] = j_updated
        rec.pop("needs_revalidation", None)
    capture = os.getenv("CAPTURE_DIR")
    def capture_description(n, key, desc):
        if capture and desc.text:
            os.makedirs(capture, exist_ok=True)
            with open(os.path.join(capture, re.sub(r"[^A-Za-z0-9_.-]+", "_", key) + ".txt"), "w", encoding="utf-8") as f:
                f.write(json.dumps(desc.meta()) + "\n" + desc.text)
    for c, r, jobs, err in results:
        n, src = c["name"], r["type"]
        note_health(c, r, jobs, err)
        if err in ("skipped", "nofeed"): continue
        if err and src == "adzuna":
            fails["__adzuna"] = fails.get("__adzuna", 0) + 1; print(f"[Adzuna] FAILED x{fails['__adzuna']}: {err}")
            if fails["__adzuna"] == 12 and MSG["warnings"]: send("⚠️ Adzuna job-board lookup has failed 12 runs in a row. Check ADZUNA_APP_ID / ADZUNA_APP_KEY secrets.")
            continue
        if err:
            fails[n] = fails.get(n, 0) + 1; print(f"[{n}] FAILED x{fails[n]}: {err}")
            if fails[n] == 12 and MSG["warnings"]: send(f"⚠️ {n}: career feed failed 12 runs in a row. Run the self-test or fix its entry in companies.yaml.")
            continue
        fails[n] = 0; last[n] = now
        if src == "adzuna": fails["__adzuna"] = 0
        fresh_n += sum(1 for j in jobs if j.get("age") is None or j["age"] <= F["max_age_days"])
        cap, analysed, line = MAX_DETAIL, 0, dict(new=0, known=0, dup=0)
        undated = src in ("sitemap", "html_listing") and all(j.get("age") is None for j in jobs)
        first_sight = undated and n not in db.setdefault("baseline_done", {})
        bl = db.setdefault("baseline", {}).setdefault(n, {})
        for j in jobs:
            key, has_req = identity(n, src, j)
            if undated:                                                                   # no posting dates: detect NEW urls against a first-sight baseline
                hid = hashlib.sha1(j["id"].encode("utf-8")).hexdigest()[:12]
                if first_sight or hid in bl: bl[hid] = now; bump("known_skipped"); line["known"] += 1; continue
                bl[hid] = now
            if key in run_seen: bump("known_skipped"); line["known"] += 1; continue          # pagination / multi-location repeats
            run_seen.add(key)
            rec = jobs_db.get(key)
            if rec:                                                                       # ---- already known
                rec["last_checked"] = now
                if src == "workday" and j["id"] not in rec.setdefault("paths", []):
                    rec["paths"].append(j["id"]); rec.setdefault("relisted", []).append({"ts": now, "path": j["id"]}); bump("relisted")
                    if REPOST_ALERT and rec["publication"] == "published": rec["publication"] = "pending"; rec["relist_alert"] = True
                why_re = None                                                             # revalidate ONLY on a meaningful change
                if j.get("desc") and not j.get("snippet") and rec.get("desc_sha1") and rec["desc_sha1"] != hashlib.sha1(j["desc"].encode("utf-8")).hexdigest(): why_re = "description changed"
                elif j.get("updated") and rec.get("updated") and rec["updated"] != j["updated"] and rec["publication"] != "published": why_re = "the employer updated the posting"
                elif rec.get("needs_revalidation"): why_re = "re-validation after upgrade"
                elif rec.get("eligibility") == "needs_review" and not (rec.get("description") or {}).get("status", "").startswith("FULL") \
                        and rec.get("retries", 0) < 5 and now - rec.get("last_retrieval", 0) > 6 * 3600: why_re = "retry retrieval of the full description"
                if why_re and analysed < cap:
                    desc, locfull = fetch_description(src, r, j, key, meta)
                    if desc is not None:
                        analysed += 1; before = rec["eligibility"]
                        if locfull and not rec["loc"]: rec["loc"] = locfull.strip()[:80]
                        verdict, info = analyze(dict(j, loc=rec["loc"]), desc, locfull)
                        rec["retries"] = rec.get("retries", 0) + (1 if why_re.startswith("retry") else 0)
                        apply_analysis(rec, verdict, info, desc, j.get("updated")); capture_description(n, key, desc); bump("revalidated")
                        print(f"   revalidated [{n}] {rec['title'][:50]} ({why_re}): {before} -> {verdict}")
                        if rec["publication"] == "published":
                            if verdict != "eligible": rec["changed_after_publish"] = verdict; bump("changed_after_publish")   # recorded, never re-sent
                        elif verdict == "eligible": rec["publication"], rec["first_seen"] = "pending", now
                        continue
                bump("known_skipped"); line["known"] += 1; continue
            if key in lreqs or f"{n}|{j['id']}" in db["legacy_seen"]: bump("known_skipped"); line["known"] += 1; continue   # sent/seen by the older version
            fp = fingerprint(n, j)
            rr = reject_reason(j)
            base = dict(company=n, title=j["title"], req=str(j.get("req") or j["id"]), url=j["url"], source=src, loc=j["loc"], posted=j.get("posted", ""),
                        posted_est=(dt.date.today() - dt.timedelta(days=int(j["age"]))).isoformat() if j.get("age") is not None else "",
                        first_seen=now, last_checked=now, has_req=has_req, paths=[j["id"]], publication="none", schema=2)
            if rr:                                                                        # clearly not for us: remember it, never look again
                jobs_db[key] = dict(base, eligibility="ineligible", reason=rr, codes=["PREFILTER"]); bump("discovered"); bump("ineligible"); line["new"] += 1
                db["fp"].setdefault(fp, []).append(key); continue
            kind, other = cross_duplicate(db, key, has_req, src, fp)
            if kind == "dup":                                                             # same vacancy already known from another platform
                jobs_db[key] = dict(base, eligibility="duplicate", reason="same vacancy as " + other, dup_of=other)
                bump("discovered"); bump("duplicate_across_sources"); line["dup"] += 1; continue
            if analysed >= cap: continue                                                  # leave for the next run (no record -> retried)
            desc, locfull = fetch_description(src, r, j, key, meta)
            if desc is None: continue                                                     # transient failure, retried next run
            analysed += 1
            if locfull and (not j["loc"] or re.search(r"\d+\s+locations?", j["loc"].lower())): j["loc"] = locfull.strip()[:80]
            base.update(loc=j["loc"], title=j["title"], posted=j.get("posted", ""), req=str(j.get("req") or j["id"])); fp = fingerprint(n, j)
            verdict, info = analyze(j, desc, locfull)
            bump("discovered"); line["new"] += 1; db["fp"].setdefault(fp, []).append(key); capture_description(n, key, desc)
            rec = dict(base, ambiguous_with=other if kind == "ambiguous" else None)
            apply_analysis(rec, verdict, info, desc, j.get("updated")); jobs_db[key] = rec
            bump(verdict)
            if verdict == "eligible": rec["publication"] = "pending"
            else: print(f"   {verdict.replace('_', ' ')} [{n}] {j['title'][:60]}: {info.get('why', '?')}")
            if kind == "ambiguous": bump("ambiguous_flagged")
        if undated and first_sight: db["baseline_done"][n] = now
        per_co[n] = per_co.get(n, 0) + line["new"]
        summary.append(f"{n}: {len(jobs)} jobs | new {line['new']} | known skipped {line['known']} | cross-site dup {line['dup']}")
    bc = meta.setdefault("by_company", {})
    for n, k in per_co.items(): bc[n] = bc.get(n, 0) + k
    save_db(db)

    # ---------- publish: a job counts as published ONLY after Telegram confirms delivery ----------
    sent, fails_in_row = 0, 0
    log = meta.setdefault("sent_ts", [])
    pending = sorted((k for k, r in jobs_db.items() if r["publication"] == "pending"), key=lambda k: jobs_db[k]["first_seen"])
    for k in pending:
        rec = jobs_db[k]
        if now - rec["first_seen"] > 3 * 86400 and not rec.get("relist_alert"): rec["publication"] = "expired"; continue
        if sent >= MAX_ALERTS or fails_in_row >= 3: break
        if send(rec_message(rec)):
            rec["publication"], rec["first_published"] = "published", now; rec.pop("relist_alert", None)
            sent += 1; fails_in_row = 0; bump("published"); log.append(now)
            save_db(db)                                                                    # saved right after every confirmed delivery
        else:
            fails_in_row += 1; bump("failed_deliveries")
    meta["sent_ts"] = [t for t in log if now - t < 2 * 86400]

    # ---------- scheduled reports ----------
    ist = dt.datetime.fromtimestamp(now, dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)
    R = CFG.get("report", {}); tg = bool(os.getenv("TELEGRAM_BOT_TOKEN"))
    tg_report, tg_notice = tg and MSG["daily_report"], tg and MSG["no_jobs_notice"]
    live = sum(1 for _, _, jb, e in results if jb is not None)
    due = [h for h in R.get("digest_hours_ist", [10, 16, 23]) if ist.hour >= h]            # the latest slot that has passed today
    today, done = ist.strftime("%Y-%m-%d"), meta.setdefault("digests", {})
    if tg_report and due and due[-1] not in done.get(today, []):
        top = sorted(meta.get("by_company", {}).items(), key=lambda x: -x[1])[:5]
        msg = (f"📊 Job bot report ({due[-1]}:00 IST)\nCompany feeds read this run: {live}\nSince the last report:\n"
               f"• new jobs found: {C.get('discovered', 0)}\n• already-known jobs skipped: {C.get('known_skipped', 0)}\n"
               f"• duplicates across sites: {C.get('duplicate_across_sources', 0)}\n• eligible: {C.get('eligible', 0)}  unverified: {C.get('unverified', 0)}  ineligible: {C.get('ineligible', 0)}\n"
               f"• alerts sent: {C.get('published', 0)}  failed deliveries: {C.get('failed_deliveries', 0)}\n• re-listed known jobs (not re-sent): {C.get('relisted', 0)}  re-validated: {C.get('revalidated', 0)}"
               + ("\nMost new jobs from: " + ", ".join(f"{a} {b}" for a, b in top) if top else ""))
        bad_h = [f"{k} (last OK {ist_of(v['ok_ts']) if v.get('ok_ts') else 'never'})" for k, v in health.items() if v.get("err")]
        if bad_h: msg += "\n⚠️ Not read successfully this run: " + ", ".join(bad_h[:10])
        manual = [c["name"] for c in comps if conf_for(c, resolved)["type"] == "none"]
        if manual: msg += "\n\n👀 Check these by hand (no automatic source): " + ", ".join(manual)
        rv = [(k, r) for k, r in jobs_db.items() if r["eligibility"] == "needs_review" and not r.get("review_reported")][:8]
        if rv:
            msg += "\n\n🔎 Needs your review (experience could not be verified - NOT matches):\n" + "\n".join(
                f"• {r['company']}: {r['title'][:50]} - {r['reason'][:70]}\n  {r['url']}" for k, r in rv)
        if send(msg):
            for k, r in rv: r["review_reported"] = True
            done[today] = done.get(today, []) + [due[-1]]; meta["counters"] = {}; meta["by_company"] = {}
            for d in [d for d in done if d < (ist - dt.timedelta(days=3)).strftime("%Y-%m-%d")]: del done[d]
    every = R.get("every_hours", 4) * 3600
    quiet = ist.hour >= R.get("quiet_start", 23) or ist.hour < R.get("quiet_end", 7)
    lr = meta.get("last_report")
    if lr is None: meta["last_report"] = now
    elif every and now - lr >= every - 120 and not quiet and tg_notice:
        if not any(t > lr for t in meta["sent_ts"]):
            hrs = max(1, round((now - lr) / 3600))
            if send(f"🕓 No new matching jobs in the last {hrs} hours. Bot is running; checked {live} company feeds "
                    f"({fresh_n} postings from the last {F['max_age_days']} days were seen, none new and fitting)."):
                meta["last_report"] = now
        else:
            meta["last_report"] = now
    for k in [k for k, r in jobs_db.items() if now - r["last_checked"] > (365 if r["publication"] == "published" else 90) * 86400]:
        del jobs_db[k]
    for fp in list(db["fp"]): db["fp"][fp] = [k for k in db["fp"][fp] if k in jobs_db]; 
    db["fp"] = {k: v for k, v in db["fp"].items() if v}
    for k in [k for k, t in db["legacy_seen"].items() if now - t > 120 * 86400]: del db["legacy_seen"][k]
    save_db(db)
    print("\n".join(summary)); print(f"alerts sent: {sent}")

if __name__ == "__main__":
    main()
