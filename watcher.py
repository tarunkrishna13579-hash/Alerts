#!/usr/bin/env python3
"""Free job-alert watcher.
 normal run : find NEW jobs that fit (Java/Spring, ~2 yrs, Bangalore/Hyderabad) -> Telegram, never repeats a job
 --selftest : check every company, send a working / not-working report to Telegram
 --dry      : print instead of sending, don't save state
"""
import json, os, re, sys, time, html, pathlib, datetime as dt, random, email.utils
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urljoin, parse_qs
import requests, yaml

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

ROOT = pathlib.Path(__file__).parent
SEEN_F, RES_F = ROOT/"state"/"seen.json", ROOT/"state"/"resolved.json"
CFG = yaml.safe_load(open(ROOT/"companies.yaml", encoding="utf-8"))
F, X, SK, HINTS = CFG["filters"], CFG["experience"], CFG["skills"], CFG.get("hints", {})
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
DRY, SELFTEST = "--dry" in sys.argv, "--selftest" in sys.argv
MAX_ALERTS, MAX_DETAIL = 20, 12

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
    try: return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(s.replace("Z", "+00:00"))).total_seconds() / 86400
    except Exception: return None
def norm(x): return re.sub(r"[^a-z0-9]", "", (x or "").lower())
def dedupe(jobs):
    d = {}
    for j in jobs: d.setdefault(j["id"], j)
    return list(d.values())

# ======================= adapters: LIST[type](conf) -> jobs ; DETAIL[type](conf, job) -> (text, location) =======================
def retry_delay(resp, attempt, cap=30):
    """Bounded Retry-After-aware delay. Never spin on a rate-limited ATS."""
    raw = (resp.headers or {}).get("Retry-After", "")
    delay = None
    try:
        delay = max(0.0, float(raw))
    except (TypeError, ValueError):
        try:
            when = email.utils.parsedate_to_datetime(raw)
            if when.tzinfo is None: when = when.replace(tzinfo=dt.timezone.utc)
            delay = max(0.0, (when - dt.datetime.now(dt.timezone.utc)).total_seconds())
        except Exception:
            pass
    if delay is None: delay = min(cap, 2 ** attempt)
    return min(cap, delay) + random.uniform(0, 0.35)


def wd_ping(api):
    last = None
    for attempt in range(3):
        try:
            r = post(api + "/jobs", json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}, timeout=25)
            if r.status_code == 429:
                last = requests.HTTPError("HTTP 429: Workday rate limit", response=r)
                if attempt < 2: time.sleep(retry_delay(r, attempt)); continue
                raise last
            r.raise_for_status()
            return "jobPostings" in r.json()
        except requests.Timeout:
            if attempt == 2: raise
    if last: raise last
    return False
TOTALS = {}
def wd_req(api, body):
    for attempt in range(3):
        resp = post(api + "/jobs", json=body, timeout=40)
        if resp.status_code == 429:
            if attempt < 2:
                time.sleep(retry_delay(resp, attempt)); continue
            resp.raise_for_status()
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("Workday request exhausted retries")
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
            ag = age_days(j.get("postedOn", "")); ages.append(ag)
            out.append(dict(id=p, req=wd_req_id(j, p), title=j.get("title", ""),
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

def page_text(url):
    """full job text from an employer page: schema.org JobPosting JSON-LD if present, else the visible page text"""
    r = get(url, timeout=25, allow_redirects=True); r.raise_for_status()
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', r.text, re.S | re.I):
        try: data = json.loads(m.group(1))
        except Exception: continue
        for d in (data if isinstance(data, list) else [data]):
            if isinstance(d, dict) and d.get("@type") == "JobPosting" and d.get("description"): return clean(d["description"])
    return clean(re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", r.text))[:30000]

def ld_job_posts(blob):
    """Read schema.org JobPosting records embedded in an employer's own page."""
    found = []
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', blob, re.S | re.I):
        try: data = json.loads(html.unescape(m.group(1)))
        except Exception: continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list): stack.extend(item); continue
            if not isinstance(item, dict): continue
            if isinstance(item.get("@graph"), list): stack.extend(item["@graph"])
            kinds = item.get("@type", [])
            if isinstance(kinds, str): kinds = [kinds]
            if "JobPosting" in kinds: found.append(item)
    return found

def ld_location(j):
    vals = j.get("jobLocation") or j.get("jobLocationType") or []
    if isinstance(vals, dict): vals = [vals]
    out = []
    for x in vals if isinstance(vals, list) else []:
        addr = x.get("address", {}) if isinstance(x, dict) else {}
        if isinstance(addr, dict):
            out += [str(addr.get(k, "")) for k in ("addressLocality", "addressRegion", "addressCountry")]
    return " ".join(v for v in out if v)

def careerhtml_list(r):
    """Extract job cards or JobPosting JSON-LD from a public employer career listing."""
    resp = get(r["url"], timeout=35, allow_redirects=True); resp.raise_for_status()
    body, base, out = resp.text, resp.url, []
    for j in ld_job_posts(body):
        url = urljoin(base, j.get("url") or j.get("sameAs") or "")
        if not url: continue
        ident = j.get("identifier") or {}
        req = ident.get("value", "") if isinstance(ident, dict) else str(ident)
        date = str(j.get("datePosted") or "")
        out.append(dict(id=str(req or url), req=str(req or ""), title=clean(j.get("title", "")),
                        loc=ld_location(j), url=url, posted=date[:10], age=iso_age(date) if date else None,
                        desc=clean(j.get("description", ""))))
    if not out:
        for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', body, re.S | re.I):
            href, title = html.unescape(m.group(1)), clean(m.group(2))
            path = urlparse(href).path.lower()
            if path.startswith("/jobposting/region/"): continue
            # Job boards commonly put city, requisition, and slug in separate
            # path segments (for example /job/hyderabad/title/board/id).
            route = re.search(r"/(?:job|jobs|jobposting|jobdetail)/[^/?#]+(?:/[^/?#]+){0,5}/?$", path, re.I)
            # Some employers use /about/careers/<numeric requisition>/<slug>.
            # This is a real posting route, unlike the careers landing/search pages.
            if not route:
                route = re.search(r"/careers/(\d{4,})/([^/?#]+)/?$", path, re.I)
            query = parse_qs(urlparse(href).query)
            has_id = bool(re.search(r"\d{4,}|(?:jid|job|req)[-_]?\d+", href, re.I) or query.get("jobid") or query.get("reqid"))
            if not route and not (query.get("jobid") or query.get("reqid")): continue
            if len(title) < 4 or len(title) > 180: continue
            if norm(title) in {"jobs", "savedjobs", "login", "returninguserlogin", "here", "search", "0"}: continue
            if not has_id and not any(x in title.lower() for x in ("engineer", "developer", "analyst", "architect", "consultant", "manager", "specialist", "scientist", "designer", "programmer")): continue
            url = urljoin(base, href.split("#")[0])
            tail = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
            req = next((query[k][0] for k in ("jobid", "reqid") if query.get(k)), "")
            req = req or tail
            start = max(0, m.start() - 1800); end = min(len(body), m.end() + 2400)
            card = clean(body[start:end])
            loc = next((x for x in ("Bengaluru", "Bangalore", "Hyderabad") if x.lower() in card.lower()), "")
            dm = re.search(r"(?i)(today|yesterday|\d+\+?\s*days?(?:\s+ago)?|\d{4}-\d{2}-\d{2})", card)
            posted = dm.group(1) if dm else ""
            age = age_days(posted)
            if age is None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", posted): age = iso_age(posted + "T00:00:00+00:00")
            out.append(dict(id=req, req=req, title=title, loc=loc, url=url, posted=posted, age=age))
    out = dedupe(out)
    if not out: raise ValueError("no public job cards found on the employer's career listing")
    return out

def careerhtml_detail(r, j):
    resp = get(j["url"], timeout=35, allow_redirects=True); resp.raise_for_status()
    posts = ld_job_posts(resp.text)
    if posts:
        item = posts[0]
        return clean(item.get("description", "")), ld_location(item)
    text = clean(re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", resp.text))[:30000]
    loc = next((x for x in ("Bengaluru", "Bangalore", "Hyderabad") if x.lower() in text.lower()), None)
    return text, loc
def adz_detail(r, j):
    try:
        t = page_text(j["url"])
        if len(t) >= max(600, int(len(j.get("desc", "")) * 1.5)): return t, None
    except Exception as e:
        print(f"   full page not readable ({reason(e) if isinstance(e, requests.RequestException) else type(e).__name__})")
    j["incomplete"] = True
    return j.get("desc", ""), None

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

LIST = dict(workday=wd_list, greenhouse=gh_list, lever=lv_list, smartrecruiters=sr_list,
            eightfold=ef_list, oraclehcm=oh_list, careerhtml=careerhtml_list)
DETAIL = dict(workday=wd_detail, smartrecruiters=sr_detail, oraclehcm=oh_detail,
              careerhtml=careerhtml_detail, adzuna=adz_detail)
LABEL = dict(workday="Workday", greenhouse="Greenhouse", lever="Lever", smartrecruiters="SmartRecruiters",
             eightfold="Eightfold", oraclehcm="Oracle HCM", careerhtml="Official career page", adzuna="Adzuna job board",
             nofeed="No validated automatic feed")

# ======================= auto-discovery of each company's job feed =======================
def wd_confs(tenant, sites, dc0=None):
    """Build only an explicitly supplied Workday host; never guess data centers or sites."""
    if not dc0:
        return
    for site in sites:
        api = f"https://{tenant}.{dc0}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
        yield dict(type="workday", api=api, web=f"https://{tenant}.{dc0}.myworkdayjobs.com/en-US/{site}")
def scan_page(blob):
    for m in re.finditer(r"https?://([a-z0-9\-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?([A-Za-z0-9_\-]+)", blob):
        t, dc, s = m.groups()
        if s.lower() not in ("wday", "login", "assets"):
            yield dict(type="workday", api=f"https://{t}.{dc}.myworkdayjobs.com/wday/cxs/{t}/{s}", web=f"https://{t}.{dc}.myworkdayjobs.com/en-US/{s}")
    for m in re.finditer(r"https?://(wd\d+)\.myworkdaysite\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?recruiting/([a-z0-9\-]+)/([A-Za-z0-9_\-]+)", blob):
        dc, t, s = m.groups()
        yield dict(type="workday", api=f"https://{dc}.myworkdaysite.com/wday/cxs/{t}/{s}", web=f"https://{dc}.myworkdaysite.com/recruiting/{t}/{s}")
    for m in re.finditer(r"(?:boards|job-boards)\.greenhouse\.io/(?!embed(?:/|\b))([a-z0-9_\-]+)", blob): yield dict(type="greenhouse", board=m.group(1))
    for m in re.finditer(r"boards\.greenhouse\.io/embed/job_board(?:/js)?\?for=([a-z0-9_\-]+)", blob, re.I):
        yield dict(type="greenhouse", board=m.group(1))
    for m in re.finditer(r"jobs\.lever\.co/([A-Za-z0-9_\-]+)", blob): yield dict(type="lever", slug=m.group(1))
    for m in re.finditer(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_\-]+)", blob): yield dict(type="smartrecruiters", company_id=m.group(1))
    for m in re.finditer(r"https?://([a-z0-9\-]+)\.eightfold\.ai(?:/|\b)", blob, re.I):
        yield dict(type="eightfold", sub=m.group(1).lower())
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
        for cand in scan_page(resp.url + " " + resp.text[:600000]):
            if cand["type"] == "eightfold" and not cand.get("domain"):
                host = re.sub(r"^www\.", "", (urlparse(resp.url).hostname or "").lower())
                if host.startswith("careers."): host = host[len("careers."):]
                special = {"capitalonecareers.com": "capitalone.com"}
                cand["domain"] = special.get(host, host)
            yield cand
    except Exception:
        pass

def reason(e):
    if isinstance(e, requests.HTTPError): return f"HTTP {e.response.status_code}"
    if isinstance(e, requests.Timeout): return "timeout"
    if isinstance(e, requests.ConnectionError): return "no such host"
    return type(e).__name__

def discover(c):
    """Discover and validate a feed linked from the employer's official careers page."""
    seen_c, why = set(), {}
    for cand in candidates(c):
        key = json.dumps(cand, sort_keys=True)
        if key in seen_c: continue
        seen_c.add(key)
        try:
            if cand["type"] == "workday":
                if not wd_ping(cand["api"]): continue
            else:
                LIST[cand["type"]](cand)
            return cand
        except Exception as e:
            k = reason(e); why[k] = why.get(k, 0) + 1
            # A rate limit is host-level evidence: stop probing guessed tenants/sites.
            if k == "HTTP 429":
                break
    real = {k: v for k, v in why.items() if k != "no such host"}
    detail = ", ".join(f"{k} x{v}" for k, v in sorted(real.items(), key=lambda x: -x[1])[:3]) or "no supported feed found on the official careers page"
    return dict(type="nofeed", why=detail, careers_url=c.get("url", ""))

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

WORDS = dict(one=1, two=2, three=3, four=4, five=5, six=6, seven=7, eight=8, nine=9, ten=10)
NUM = r"(\d{1,2}(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)"
YRS = r"(?:years?(?:\(s\))?|yrs?)(?![a-z])"
RANGE_RE = re.compile(NUM + r"\s*\+?\s*(?:-|–|—|to)\s*" + NUM + r"\s*\+?\s*" + YRS, re.I)
SINGLE_RE = re.compile(NUM + r"\s*(?:\+|plus)?\s*" + YRS, re.I)
OPTIONAL = re.compile(r"preferred|good to have|nice to have|\bplus\b|bonus|desirable|desired|added advantage|\badvantage\b|optional", re.I)
EDU = re.compile(r"educat|degree|academic|schooling|diploma", re.I)
HEAD_RE = re.compile(r"^(?:minimum |basic |required |preferred |desired |key |mandatory |additional )?(?:qualifications?|requirements?|skills?|responsibilit\w+|what you|who you|nice to have|good to have|bonus|about|must have|eligibility|education|experience)", re.I)
def _n(x): return float(WORDS.get(str(x).lower(), x))
def clip(x): return re.split(r"[,;(]|\bincluding\b|\bwith at least\b|\bplus\b", x, maxsplit=1)[0].strip()   # object of "experience in ..." stops at the next clause

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
TECH = [("Java", r"\bjava\b(?!\s*script)")] + SKILLS + [
    ("C++", r"c\+\+"), (".NET", r"\.net\b|\bc#"), ("JavaScript", r"javascript|node\.?js"), ("Linux", r"\blinux\b"),
    ("Oracle", r"\boracle\b"), ("Salesforce", r"salesforce"), ("Data/ML", r"machine learning|data science|\bml\b|deep learning|\bllm"),
    ("Testing", r"selenium|automation testing|qa automation"), ("Mainframe", r"mainframe|cobol")]
def tech_in(s):
    for label, p in TECH:
        if re.search(p, s or "", re.I): return label
    return None
GENERIC_OBJ = re.compile(r"^(?:the\s+)?(?:software|it\b|information|industry|a\s+similar|similar|related|relevant|backend|back-end|back end|application|programming|"
                         r"development|engineering|technology|technical|professional|a\s+related|this\s+field|the\s+field|designing and developing software)", re.I)
GENERIC_MID = re.compile(r"^(?:relevant|professional|work|working|industry|hands-on|hands on|total|overall|proven|practical|software|it|related|similar|"
                         r"development|engineering|technology|technical|of|in|the|a|and|,|\s)*$", re.I)

def split_sections(text):
    """yield (section, line). 'Label : value' lines carry their label only for themselves; a bare heading carries until the next heading."""
    section = ""
    for raw in (text or "").split("\n"):
        line = raw.strip(" \t•-*·")
        if not line: continue
        pre, sep, rest = line.partition(":")
        if sep and len(pre) <= 45 and HEAD_RE.match(pre.strip()):
            if rest.strip(): yield pre.strip(), line; continue
            section = pre.strip(); continue
        if len(line) <= 70 and HEAD_RE.match(line) and not re.search(r"\d", line):
            section = line.rstrip(":"); continue
        yield section, line

def statements(text):
    """every 'N years' / 'N-M years' that is about work experience, classified as overall or skill-specific, mandatory or preferred"""
    out = []
    for section, line in split_sections(text):
        for sent in re.split(r"(?<=[.;!?])\s+", line):
            taken = []
            for rx, is_range in ((RANGE_RE, True), (SINGLE_RE, False)):
                for m in rx.finditer(sent):
                    if is_range:
                        lo, hi = _n(m.group(1)), _n(m.group(2))
                        if not lo <= hi < 30: continue
                        taken.append(m.span())
                    else:
                        if any(a <= m.start() < b for a, b in taken): continue
                        lo, hi = _n(m.group(1)), None
                        if lo >= 20 or lo == 0: continue
                        if re.search(r"(?:up to|less than|under|maximum|max\.?|upto)\s*$", sent[max(0, m.start() - 14):m.start()], re.I): continue
                    around = sent[max(0, m.start() - 90): m.end() + 90]
                    if not re.search(r"experience|\bexp\b|\bworked\b|\bhands[- ]on\b", around, re.I): continue
                    before = re.split(r"\)|\band\b|;|,", sent[max(0, m.start() - 22): m.start()])[-1]       # an education word belonging to an earlier clause doesn't count
                    if EDU.search(sent[m.end(): m.end() + 22]) or EDU.search(before): continue
                    tail, head = sent[m.end(): m.end() + 90], sent[max(0, m.start() - 45): m.start()]
                    scope, skill = "overall", None
                    t1 = re.match(r"\s*(?:of\s+)?(?:(?:hands[- ]on|relevant|professional|work|working|practical|proven|strong|solid)\s+)*(?:experience|exp)\s*"
                                  r"(?:in|with|using|on|of|working with|developing|building|designing)\s+(.{1,80})", tail, re.I)
                    t2 = re.match(r"\s*(?:of\s+)?(.{1,40}?)\s+(?:experience|exp)\b", tail, re.I)
                    if t1 and tech_in(clip(t1.group(1))) and not GENERIC_OBJ.match(clip(t1.group(1))): scope, skill = "skill", tech_in(clip(t1.group(1)))
                    elif t2 and tech_in(t2.group(1)) and not GENERIC_MID.match(t2.group(1)): scope, skill = "skill", tech_in(t2.group(1))
                    elif (t3 := re.match(r"\s*(?:in|with|using|on|of)\s+(.{1,60})", tail, re.I)) and not re.match(r"experience|exp\b", t3.group(1), re.I) \
                            and tech_in(clip(t3.group(1))) and not GENERIC_OBJ.match(clip(t3.group(1))): scope, skill = "skill", tech_in(clip(t3.group(1)))
                    elif re.search(r"([A-Za-z+#.\s/]{2,30})\s*[:\-–(]\s*$", head) and tech_in(head[-30:]) and not re.search(r"experience|total|overall", head, re.I):
                        scope, skill = "skill", tech_in(head[-30:])
                    mandatory = not (OPTIONAL.search(section) or OPTIONAL.search(sent[max(0, m.start() - 45): m.end() + 60]))
                    out.append(dict(lo=lo, hi=hi, scope=scope, skill=skill, mandatory=mandatory, section=section or "description",
                                    sentence=sent.strip(), text=m.group(0)))
    return out

def _consistent(a, b):
    """two overall statements agree if same minimum and (same maximum or one has no maximum)"""
    return a["lo"] == b["lo"] and (a["hi"] is None or b["hi"] is None or a["hi"] == b["hi"])

def extract_experience(text, url=""):
    """structured, auditable result. Overall and skill-specific experience are kept apart; ambiguity -> NEEDS_REVIEW, never a guess."""
    ex = dict(overall_experience_min=None, overall_experience_max=None, overall_experience_original_text="", skill_specific_experience=[],
              mandatory_or_preferred="", source_url=url, source_section="", experience_verified=False, verification_status="NEEDS_REVIEW", why="")
    if len((text or "").strip()) < 150:
        ex["why"] = "job description missing or incomplete"; return ex
    sts = statements(text)
    ex["skill_specific_experience"] = [dict(skill=s["skill"], min=s["lo"], max=s["hi"], mandatory=s["mandatory"], original_text=s["text"],
                                           sentence=s["sentence"][:200], section=s["section"]) for s in sts if s["scope"] == "skill"]
    ov = [s for s in sts if s["scope"] == "overall" and s["mandatory"]]
    pref = [s for s in sts if s["scope"] == "overall" and not s["mandatory"]]
    if not ov:
        if re.search(r"\bfreshers?\b|entry[- ]level|new grad|recent graduate", text, re.I):
            ex.update(overall_experience_min=0.0, overall_experience_original_text="fresher / entry-level", mandatory_or_preferred="mandatory",
                      source_section="description", experience_verified=True, verification_status="VERIFIED"); return ex
        ex["why"] = ("only preferred experience stated: " + pref[0]["text"]) if pref else "no overall experience statement in the description"
        return ex
    base = ov[0]
    for s in ov[1:]:
        if not _consistent(base, s):
            ex["why"] = f"conflicting overall statements: \"{base['text']}\" vs \"{s['text']}\""; return ex
        if s["hi"] is not None and base["hi"] is None: base = s                         # prefer the more specific range
    ex.update(overall_experience_min=base["lo"], overall_experience_max=base["hi"], overall_experience_original_text=base["text"],
              mandatory_or_preferred="mandatory", source_section=base["section"], experience_verified=True, verification_status="VERIFIED",
              sentence=base["sentence"][:220])
    return ex

def evaluate_fit(ex):
    """-> ('eligible'|'ineligible'|'needs_review', reason)  against my_years (2.2) and my per-skill years"""
    if ex["verification_status"] != "VERIFIED": return "needs_review", ex["why"]
    mine, lo, hi = X["my_years"], ex["overall_experience_min"], ex["overall_experience_max"]
    if lo > mine + X.get("tolerance", 0): return "ineligible", f"overall experience {ex['overall_experience_original_text']} is above your {mine:g} yrs"
    if hi is not None and hi < mine - X.get("range_slack", 0.5): return "ineligible", f"overall range {ex['overall_experience_original_text']} is below your {mine:g} yrs"
    have = {k.lower(): v for k, v in (X.get("skill_years") or {}).items()}
    for s in ex["skill_specific_experience"]:
        mine_s = have.get(s["skill"].lower(), mine)          # nobody can have more years in a skill than in their whole career
        if s["mandatory"] and s["min"] > mine_s + X.get("skill_tolerance", 1.0):
            return "ineligible", f"mandatory {s['skill']} {s['original_text']} vs your {mine_s:g} yrs"
    return "eligible", ""

def analyze(j, text, locfull):
    """-> (verdict, info) with verdict eligible | ineligible | needs_review"""
    if locfull and not loc_ok(locfull): return "ineligible", {"why": "location"}
    blob = (j["title"] + " " + (text or "")).lower()
    if (text or j.get("trust_java")) and not re.search(r"\bjava\b(?!\s*script)", blob) and not j.get("trust_java"): return "ineligible", {"why": "no Java in description"}
    hits = [k for k, p in SKILLS if re.search(p, blob)][:14]
    if text and len(hits) < SK["min_other_hits"]: return "ineligible", {"why": "skills"}
    if j.get("incomplete"): return "needs_review", {"why": "only a short job-board snippet was available, not the full description", "ex": None, "skills": ["Java"] + hits}
    ex = extract_experience(text, j.get("url", ""))
    verdict, why = evaluate_fit(ex)
    return verdict, dict(why=why, ex=ex, skills=["Java"] + hits, jd=bool(text))

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
    ex = info["ex"]; mx = ex["overall_experience_max"]
    lines = [f"🆕 {name} - {j['title']}", f"📍 {j['loc'] or 'see posting'}",
             f"🧪 Overall experience (verified): {ex['overall_experience_original_text']}",
             f"   JD: \"{ex.get('sentence', '')[:170]}\"" + (f"  [{ex['source_section']}]" if ex["source_section"] not in ("", "description") else "")]
    sk = [f"{s['skill']} {s['original_text']} ({'mandatory' if s['mandatory'] else 'preferred'})" for s in ex["skill_specific_experience"]][:6]
    if sk: lines.append("🔧 Skill-specific (not overall): " + "; ".join(sk))
    if info["skills"]: lines.append("🛠 Skills asked: " + ", ".join(info["skills"]))
    lines.append(f"🆔 Job ID: {j.get('req') or j['id']}")
    if j.get("posted"): lines.append(f"🕒 Posted: {j['posted']}")
    lines.append(f"🔗 Apply: {j['url']}")
    return "\n".join(lines)

# ======================= persistent job database =======================
DB_F = ROOT / "state" / "db.json"
REPOST_ALERT = bool(CFG.get("repost_alert", False))      # default OFF: a re-listed job is recorded, never re-sent
NO_REQ_SOURCES = ("adzuna",)                              # secondary job-board listings have no official requisition id

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
    text = fmt(rec["company"], j, rec["info"])
    return ("🔁 Re-listed\n" + text) if rec.get("relist_alert") else text

def conf_for(c, resolved):
    r = dict(resolved.get(c["name"]) or {"type": "nofeed", "why": "not yet validated", "careers_url": c.get("url", "")})
    if r["type"] in ("adzuna", "nofeed"):
        r.update(name=c["match"], match=c["match"])
    return r

def main():
    db = load_db(); jobs_db, meta = db["jobs"], db["meta"]
    last = meta.setdefault("last_run", {}); fails = meta.setdefault("fails", {})
    source_cooldowns = meta.setdefault("source_cooldowns", {})
    C = meta.setdefault("counters", {})                   # counts since the last report
    def bump(k, n=1): C[k] = C.get(k, 0) + n
    resolved = load(RES_F, {}); now = time.time(); comps = CFG["companies"]
    lreqs = legacy_reqs(db)

    def has_feed(n): return resolved.get(n, {}).get("type") in LIST
    # Recheck every unresolved official careers page on every scheduled pass.
    # If a company exposes a usable feed later, discover it and poll it in this same run.
    todo = [c for c in comps if not has_feed(c["name"])]
    if todo:
        with ThreadPoolExecutor(10) as ex:
            for c, conf in zip(todo, ex.map(discover, todo)):
                resolved[c["name"]] = conf
        save(RES_F, resolved)

    def fetch(c):
        r = conf_for(c, resolved)
        if r["type"] == "nofeed": return c, r, None, "nofeed"
        until = source_cooldowns.get(c["name"], 0)
        if until > now:
            stamp = dt.datetime.fromtimestamp(until, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            return c, r, None, f"cooldown until {stamp}"
        try: return c, r, LIST[r["type"]](r), None
        except Exception as e: return c, r, None, (reason(e) if isinstance(e, requests.RequestException) else str(e)[:100])

    direct = [c for c in comps if conf_for(c, resolved)["type"] in LIST]
    fallback = [c for c in comps if conf_for(c, resolved)["type"] == "nofeed"]
    with ThreadPoolExecutor(10) as ex: results = list(ex.map(fetch, direct))

    # A validated feed that is temporarily failing can use Adzuna as a secondary source.
    # Keep each official-source failure visible even when a secondary source is tried.
    failed_direct = [x for x in results if x[3] and x[3] not in ("skipped", "nofeed")]
    empty = [x for x in results if x[3] is None and not x[2] and
             (x[1]["type"] == "eightfold" or (x[1].get("api") and not TOTALS.get(x[1].get("api"))))]
    if empty:
        results = [x for x in results if x not in empty]
    fallback += [x[0] for x in failed_direct + empty]

    # Only fetch Adzuna once per check batch; only use it when credentials are configured.
    if ADZ_ON and fallback:
        try: ajobs, aerr = adzuna_jobs(), None; last["__adzuna"] = now
        except Exception as e: ajobs, aerr = [], (reason(e) if isinstance(e, requests.RequestException) else str(e)[:80])
        for c in fallback:
            mine = [j for j in ajobs if norm(j["company"]).startswith(norm(c["match"]))]
            results.append((c, {"type": "adzuna", "fallback_for": conf_for(c, resolved)["type"]}, None if aerr else mine, aerr))
    else:
        results += [(c, conf_for(c, resolved), None, "nofeed") for c in fallback]
    # Keep direct-source failures visible in self-test if a fallback also ran.
    if SELFTEST:
        for c, r, jobs, err in failed_direct:
            print(f"[source fallback] {c['name']} primary {r['type']} failed: {err}; attempted authorized fallback")

    # Persist cooldowns so a rate-limited/access-restricted source is not hammered every 10 minutes.
    for c, r, jobs, err in results:
        if err == "HTTP 429": source_cooldowns[c["name"]] = max(source_cooldowns.get(c["name"], 0), now + 30 * 60)
        elif err in ("HTTP 403", "HTTP 999"): source_cooldowns[c["name"]] = max(source_cooldowns.get(c["name"], 0), now + 6 * 60 * 60)
    # Track the source state for every company. A failed feed is visible immediately
    # on status change instead of becoming silent until the 12-failure warning.
    previous_health = meta.setdefault("source_health", {})
    current_health = {}
    for c, r, jobs, err in results:
        name, source = c["name"], r["type"]
        if source == "adzuna":
            primary = "no_feed" if r.get("fallback_for") == "nofeed" else "failed"
            detail = resolved.get(name, {}).get("why", "No validated official feed") if primary == "no_feed" else f"Primary {r.get('fallback_for', 'career')} feed failed"
            current_health.setdefault(name, {"primary": primary, "primary_detail": detail, "secondary": "not_configured"})
            current_health[name]["secondary"] = "ok" if not err else ("failed" if err != "skipped" else "skipped")
            current_health[name]["secondary_detail"] = f"{len(jobs or [])} listings" if not err else str(err)
            continue
        row = current_health.setdefault(name, {"secondary": "not_configured"})
        if err == "nofeed": row.update(primary="no_feed", primary_detail=resolved.get(name, {}).get("why", "No validated official feed"))
        elif err and str(err).startswith("cooldown until"): row.update(primary="cooldown", primary_detail=str(err))
        elif err: row.update(primary="failed", primary_detail=str(err))
        else: row.update(primary="ok", primary_detail=f"{LABEL.get(source, source)}: {len(jobs or [])} listings")
    health_events = []
    for c in comps:
        name = c["name"]
        row = current_health.setdefault(name, {"primary": "no_feed", "primary_detail": "No source was run", "secondary": "not_configured"})
        pstat = row.get("primary", "no_feed")
        sstat = row.get("secondary", "not_configured")
        overall = "ok" if pstat == "ok" else "secondary_only" if sstat == "ok" else pstat
        row["status"] = overall
        row["checked_at"] = int(now)
        old = previous_health.get(name, {})
        old_status = old.get("status")
        if old_status != overall and (overall in ("no_feed", "failed", "cooldown", "secondary_only") or
                                      old_status in ("no_feed", "failed", "cooldown", "secondary_only")):
            detail = row.get("primary_detail", "")
            if overall == "secondary_only": detail += f"; Adzuna: {row.get('secondary_detail', 'read')}"
            health_events.append((name, old_status or "unverified", overall, detail))
        previous_health[name] = row
    if health_events and not SELFTEST and os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        for start in range(0, len(health_events), 18):
            lines = [f"• {n}: {before} → {after}" + (f" ({detail[:130]})" if detail else "")
                     for n, before, after, detail in health_events[start:start + 18]]
            send("🚨 Career-feed coverage changed\n" + "\n".join(lines))
    if SELFTEST:
        save_db(db)
        ok, nofeed, bad, lik = [], [], [], []
        for c, r, jobs, err in results:
            if not err and r["type"] == "adzuna":
                origin = f" (fallback for {r['fallback_for']})" if r.get("fallback_for") else ""
                lik.append(f"🟣 {c['name']} [{LABEL[r['type']]}{origin}]: {len(jobs)} jobs read, {sum(quick_ok(j) for j in jobs)} pass title/location/age filter"); continue
            if err == "nofeed":
                why = resolved.get(c['name'], {}).get('why', 'No validated automatic feed on the official career site')
                nofeed.append(f"⚪ {c['name']} - {why}\n   Official careers page: {c['url']}")
            elif err: bad.append(f"❌ {c['name']} ({LABEL.get(r['type'], r['type'])}): {err}")
            else:
                tot = TOTALS.get(r.get("api")); mark = "⚠️" if (not jobs and not tot) else "✅"
                ok.append(f"{mark} {c['name']} [{LABEL[r['type']]}]: {len(jobs)} jobs read" + (f" (site total {tot})" if tot is not None else "")
                          + f", {sum(quick_ok(j) for j in jobs)} pass title/location/age filter")
        send(f"SELF-TEST: {len(comps)} companies in your list\n• validated official career feeds read: {len(ok)}\n• secondary feeds read (Adzuna): {len(lik)}\n• failed source reads: {len(bad)}\n• no automatic feed / manual careers link: {len(nofeed)}")
        for title, rows in ((f"{len(ok)} companies on official career feeds", ok),
                            (f"{len(lik)} covered via Adzuna job board (company has no direct feed; checked every ~30 min)", lik),
                            (f"{len(bad)} failed to read", bad),
                            (f"{len(nofeed)} with NO automatic feed (check these by hand or send me their job-search URL)", nofeed)):
            for i in range(0, len(rows), 25):
                if rows: send(title + "\n\n" + "\n".join(rows[i:i + 25]))
        return

    # ---------- discovery -> database (every job is looked at once; known jobs are skipped without re-analysis) ----------
    summary, fresh_n, run_seen, per_co = [], 0, set(), {}
    for c, r, jobs, err in results:
        n, src = c["name"], r["type"]
        if err in ("skipped", "nofeed"): continue
        if err and src == "adzuna":
            fails["__adzuna"] = fails.get("__adzuna", 0) + 1; print(f"[Adzuna] FAILED x{fails['__adzuna']}: {err}")
            if fails["__adzuna"] == 12: send("⚠️ Adzuna job-board lookup has failed 12 runs in a row. Check ADZUNA_APP_ID / ADZUNA_APP_KEY secrets.")
            continue
        if err:
            fails[n] = fails.get(n, 0) + 1; print(f"[{n}] FAILED x{fails[n]}: {err}")
            if fails[n] == 12: send(f"⚠️ {n}: career feed failed 12 runs in a row. Run the self-test or fix its entry in companies.yaml.")
            continue
        fails[n] = 0; last[n] = now
        if src == "adzuna": fails["__adzuna"] = 0
        fresh_n += sum(1 for j in jobs if j.get("age") is None or j["age"] <= F["max_age_days"])
        cap, analysed, line = MAX_DETAIL, 0, dict(new=0, known=0, dup=0)
        for j in jobs:
            key, has_req = identity(n, src, j)
            if key in run_seen: bump("known_skipped"); line["known"] += 1; continue          # pagination / multi-location repeats
            run_seen.add(key)
            rec = jobs_db.get(key)
            if rec:                                                                       # ---- already known: no download, no analysis
                rec["last_checked"] = now
                if src == "workday" and j["id"] not in rec.setdefault("paths", []):
                    rec["paths"].append(j["id"]); rec.setdefault("relisted", []).append({"ts": now, "path": j["id"]}); bump("relisted")
                    if REPOST_ALERT and rec["publication"] == "published":
                        rec["publication"] = "pending"; rec["relist_alert"] = True
                bump("known_skipped"); line["known"] += 1; continue
            if key in lreqs or f"{n}|{j['id']}" in db["legacy_seen"]: bump("known_skipped"); line["known"] += 1; continue   # sent/seen by the older version
            fp = fingerprint(n, j)
            rr = reject_reason(j)
            base = dict(company=n, title=j["title"], req=str(j.get("req") or j["id"]), url=j["url"], source=src, loc=j["loc"], posted=j.get("posted", ""),
                        posted_est=(dt.date.today() - dt.timedelta(days=int(j["age"]))).isoformat() if j.get("age") is not None else "",
                        first_seen=now, last_checked=now, has_req=has_req, paths=[j["id"]], publication="none", info={})
            if rr:                                                                        # clearly not for us: remember it, never look again
                jobs_db[key] = dict(base, eligibility="ineligible", reason=rr); bump("discovered"); bump("ineligible"); line["new"] += 1
                db["fp"].setdefault(fp, []).append(key); continue
            kind, other = cross_duplicate(db, key, has_req, src, fp)
            if kind == "dup":                                                             # same vacancy already known from another platform
                jobs_db[key] = dict(base, eligibility="duplicate", reason="same vacancy as " + other, dup_of=other)
                bump("discovered"); bump("duplicate_across_sources"); line["dup"] += 1; continue
            if analysed >= cap: continue                                                  # leave for the next run (no record -> retried)
            try:
                text, locfull = (j["desc"], None) if (j.get("desc") and not j.get("snippet")) else (DETAIL[src](r, j) if src in DETAIL else ("", None))
            except Exception as e:
                df = meta.setdefault("detail_fail", {}); df[key] = df.get(key, 0) + 1
                print(f"[{n}] detail failed ({df[key]}): {e}")
                if df[key] < 3: continue
                text, locfull = "", None
            analysed += 1
            if locfull and (not j["loc"] or re.search(r"\d+\s+locations?", j["loc"].lower())): j["loc"] = locfull.strip()[:80]
            base.update(loc=j["loc"]); fp = fingerprint(n, j)
            verdict, info = analyze(j, text, locfull)
            bump("discovered"); line["new"] += 1; db["fp"].setdefault(fp, []).append(key)
            if verdict in ("ineligible", "needs_review"):                                # kept in the database, NOT shown as a match
                jobs_db[key] = dict(base, eligibility=verdict, reason=info.get("why", "?"), experience=info.get("ex"))
                bump(verdict); print(f"   {verdict.replace('_', ' ')} [{n}] {j['title'][:60]}: {info.get('why', '?')}"); continue
            jobs_db[key] = dict(base, eligibility="eligible", experience=info["ex"], info=info, publication="pending",
                                ambiguous_with=other if kind == "ambiguous" else None)
            bump("eligible")
            if kind == "ambiguous": bump("ambiguous_flagged")
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
    live = sum(1 for _, _, jb, e in results if jb is not None)
    due = [h for h in R.get("digest_hours_ist", [10, 16, 23]) if ist.hour >= h]            # the latest slot that has passed today
    today, done = ist.strftime("%Y-%m-%d"), meta.setdefault("digests", {})
    if tg and due and due[-1] not in done.get(today, []):
        top = sorted(meta.get("by_company", {}).items(), key=lambda x: -x[1])[:5]
        health_rows = [(n, h) for n, h in previous_health.items() if n in {c["name"] for c in comps}]
        health_counts = {k: sum(1 for _, h in health_rows if h.get("status") == k)
                         for k in ("ok", "secondary_only", "no_feed", "failed", "cooldown")}
        health_note = (f"\nFeed coverage: {health_counts['ok']} official OK, {health_counts['secondary_only']} secondary only, "
                       f"{health_counts['no_feed']} no feed, {health_counts['failed'] + health_counts['cooldown']} failing/cooldown")
        problem_rows = [(n, h) for n, h in health_rows if h.get("status") != "ok"]
        if problem_rows:
            health_note += "\nFeed attention:\n" + "\n".join(
                f"• {n}: {h.get('status')} — {h.get('primary_detail', h.get('secondary_detail', ''))[:110]}" for n, h in problem_rows[:12])
            if len(problem_rows) > 12: health_note += f"\n• …and {len(problem_rows) - 12} more (see self-test for the full company list)"
        msg = (f"📊 Job bot report ({due[-1]}:00 IST)\nCompany source reads this run: {live}"
               + health_note + "\nSince the last report:\n"
               f"• new jobs found: {C.get('discovered', 0)}\n• already-known jobs skipped: {C.get('known_skipped', 0)}\n"
               f"• duplicates across sites: {C.get('duplicate_across_sources', 0)}\n• eligible: {C.get('eligible', 0)}  unverified: {C.get('unverified', 0)}  ineligible: {C.get('ineligible', 0)}\n"
               f"• alerts sent: {C.get('published', 0)}  failed deliveries: {C.get('failed_deliveries', 0)}\n• re-listed known jobs (not re-sent): {C.get('relisted', 0)}"
               + ("\nMost new jobs from: " + ", ".join(f"{a} {b}" for a, b in top) if top else ""))
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
    elif every and now - lr >= every - 120 and not quiet and tg:
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
