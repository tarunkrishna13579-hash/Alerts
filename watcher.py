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
MAX_ALERTS, MAX_DETAIL, LI_EVERY = 20, 12, 30 * 60

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
def dedupe(jobs):
    d = {}
    for j in jobs: d.setdefault(j["id"], j)
    return list(d.values())

# ======================= adapters: LIST[type](conf) -> jobs ; DETAIL[type](conf, job) -> (text, location) =======================
def wd_ping(api):
    r = post(api + "/jobs", json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": "java"}, timeout=8)
    return r.status_code == 200 and "jobPostings" in r.json()
def wd_list(r):
    out = []
    for q in F["search_terms"]:
        for off in (0, 20):
            resp = post(r["api"] + "/jobs", json={"appliedFacets": {}, "limit": 20, "offset": off, "searchText": q})
            resp.raise_for_status()
            posts = resp.json().get("jobPostings", [])
            for j in posts:
                p, bf = j["externalPath"], (j.get("bulletFields") or [])
                out.append(dict(id=p, req=(bf[0] if bf else p.rsplit("_", 1)[-1]), title=j["title"],
                                loc=j.get("locationsText", ""), url=r["web"] + p,
                                posted=j.get("postedOn", ""), age=age_days(j.get("postedOn", ""))))
            if len(posts) < 20: break
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
    kw = f"{r['name']} java spring boot developer"
    resp = get("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobs/search",
               params={"keywords": kw, "location": "India", "f_TPR": "r1209600", "start": 0})
    resp.raise_for_status()
    out = []
    for card in resp.text.split("<li>")[1:]:
        href = re.search(r'base-card__full-link[^>]*href="([^"]+)"', card)
        title = re.search(r'base-search-card__title[^>]*>\s*(.*?)\s*</h3>', card, re.S)
        comp = re.search(r'base-search-card__subtitle[^>]*>(.*?)</h4>', card, re.S)
        loc = re.search(r'job-search-card__location[^>]*>\s*(.*?)\s*</span>', card, re.S)
        if not (href and title and comp): continue
        if r["match"] not in clean(comp.group(1)).lower(): continue
        link = html.unescape(href.group(1)).split("?")[0]
        jid = re.search(r"(\d{6,})$", link)
        out.append(dict(id=jid.group(1) if jid else link, req=jid.group(1) if jid else "", title=clean(title.group(1)),
                        loc=clean(loc.group(1)) if loc else "", url=link, posted="", age=None))
    return dedupe(out)
def li_detail(r, j):
    resp = get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{j['id']}")
    m = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', resp.text, re.S)
    return clean(m.group(1)) if m else "", None

LIST = dict(workday=wd_list, greenhouse=gh_list, lever=lv_list, smartrecruiters=sr_list,
            eightfold=ef_list, oraclehcm=oh_list, linkedin=li_list)
DETAIL = dict(workday=wd_detail, smartrecruiters=sr_detail, oraclehcm=oh_detail, linkedin=li_detail)
LABEL = dict(workday="Workday", greenhouse="Greenhouse", lever="Lever", smartrecruiters="SmartRecruiters",
             eightfold="Eightfold", oraclehcm="Oracle HCM", linkedin="LinkedIn fallback")

# ======================= auto-discovery of each company's job feed =======================
WD_DCS = ["wd1", "wd5", "wd3", "wd12", "wd2", "wd4", "wd10", "wd103", "wd501"]
def wd_confs(tenant, sites):
    for site in sites:
        for dc in WD_DCS:
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
            if hh["type"] == "workday": yield from wd_confs(hh["tenant"], hh["sites"])
            else: yield dict(hh)
    try:
        resp = get(c["url"], allow_redirects=True)
        yield from scan_page(resp.url + " " + resp.text[:600000])
    except Exception:
        pass

def discover(c):
    seen_c = set()
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
        except Exception:
            continue
    return dict(type="linkedin")

# ======================= fit logic =======================
def loc_ok(s): return any(k in (s or "").lower() for k in F["locations"])
def quick_ok(j):
    t = j["title"].lower()
    if not any(k in t for k in F["include_title"]) or any(k in t for k in F["exclude_title"]): return False
    if j.get("age") is not None and j["age"] > F["max_age_days"]: return False
    loc = (j["loc"] or "").lower()
    if not loc or re.search(r"\d+\s+locations?", loc): return True
    return loc_ok(loc)

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

SKILLS = {"Spring Boot": r"spring\s*boot|\bspring\b", "Microservices": r"micro-?services?", "REST APIs": r"\brest(?:ful)?\b",
          "Multithreading": r"multi-?thread|concurren", "Kafka": r"\bkafka\b", "Hibernate/JPA": r"hibernate|\bjpa\b"}
def analyze(j, text, locfull):
    """-> (alert?, info dict)"""
    if locfull and not loc_ok(locfull): return False, {}
    blob = (j["title"] + " " + (text or "")).lower()
    if text:
        if not re.search(r"\bjava\b", blob): return False, {}
        hits = [k for k, p in SKILLS.items() if re.search(p, blob)]
        if len(hits) < SK["min_other_hits"]: return False, {}
        verdict, label = parse_years(text)
        if verdict == "no" or (verdict == "unknown" and not X["send_if_unknown"]): return False, {}
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
    if info["skills"]: lines.append("🛠 " + ", ".join(info["skills"]))
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

    todo = [c for c in comps if SELFTEST or c["name"] not in resolved]
    if todo:
        with ThreadPoolExecutor(8) as ex:
            for c, conf in zip(todo, ex.map(discover, todo)): resolved[c["name"]] = conf
        save(RES_F, resolved)

    def fetch(c):
        r = conf_for(c, resolved)
        if r["type"] == "linkedin" and not SELFTEST and now - last.get(c["name"], 0) < LI_EVERY - 60: return c, r, None, "skipped"
        try: return c, r, LIST[r["type"]](r), None
        except Exception as e: return c, r, None, str(e)[:120]
    with ThreadPoolExecutor(8) as ex: results = list(ex.map(fetch, comps))

    if SELFTEST:
        ok, fb, bad = [], [], []
        for c, r, jobs, err in results:
            if err: bad.append(f"❌ {c['name']} ({LABEL[r['type']]}): {err}")
            elif r["type"] == "linkedin": fb.append(f"🟡 {c['name']}: {len(jobs)} jobs seen")
            else: ok.append(f"✅ {c['name']} [{LABEL[r['type']]}]: {len(jobs)} jobs, {sum(quick_ok(j) for j in jobs)} pass title/location filter")
        for title, rows in ((f"SELF-TEST: {len(ok)} companies on fast direct feeds", ok),
                            (f"{len(fb)} on slower LinkedIn fallback (30+ min delay)", fb), (f"{len(bad)} failed", bad)):
            if rows: send(title + "\n\n" + "\n".join(rows))
        return

    queue, summary = [], []
    for c, r, jobs, err in results:
        n = c["name"]
        if err == "skipped": continue
        if err:
            fails[n] = fails.get(n, 0) + 1; print(f"[{n}] FAILED x{fails[n]}: {err}")
            if fails[n] == 12: send(f"⚠️ {n}: career feed failed 12 runs in a row. Run the self-test or fix its entry in companies.yaml.")
            continue
        fails[n] = 0; last[n] = now
        new = [j for j in jobs if f"{n}|{j['id']}" not in seen]
        cand = []
        for j in new:
            if quick_ok(j): cand.append(j)
            else: seen[f"{n}|{j['id']}"] = now                       # irrelevant -> never look again
        cap = 5 if r["type"] == "linkedin" else MAX_DETAIL
        for j in cand[:cap]:
            try:
                text, locfull = (j["desc"], None) if j.get("desc") else (DETAIL[r["type"]](r, j) if r["type"] in DETAIL else ("", None))
            except Exception as e:
                text, locfull = "", None; print(f"[{n}] detail failed: {e}")
            good, info = analyze(j, text, locfull)
            if good: queue.append((n, j, info))
            else: seen[f"{n}|{j['id']}"] = now
        summary.append(f"{n}: {len(jobs)} jobs, {len(new)} unseen, {len(cand)} candidates")

    sent = 0
    for n, j, info in queue[:MAX_ALERTS]:
        if send(fmt(n, j, info)): seen[f"{n}|{j['id']}"] = now; sent += 1
    if len(queue) > MAX_ALERTS: print(f"{len(queue) - MAX_ALERTS} more alerts wait for the next run")
    for k in [k for k, t in seen.items() if now - t > 120 * 86400]: del seen[k]
    save(SEEN_F, state)
    print("\n".join(summary)); print(f"alerts sent: {sent}")

if __name__ == "__main__":
    main()
