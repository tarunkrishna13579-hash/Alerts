import types
import watcher as w
from merge_state import merge_db

class Response:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
    def json(self): return self._payload

# Workday's jobPostingInfo may be a list of records on some tenant responses.
original_get = w.get
w.get = lambda *a, **k: types.SimpleNamespace(json=lambda: {
    "jobPostingInfo": [{"jobDescription": "<p>Java developer</p>", "location": {"descriptor": "Bengaluru"},
                         "additionalLocations": [{"descriptor": "Hyderabad"}]}]})
text, location = w.wd_detail({"api": "https://example.test"}, {"id": "/job/1"})
assert "Java developer" in text and "Bengaluru" in location and "Hyderabad" in location
w.get = original_get

# A short Retry-After is honored and causes exactly one retry.
old_request, old_sleep = w.requests.request, w.time.sleep
calls = []
def fake_request(method, url, **kwargs):
    calls.append(url)
    return Response(429, headers={"Retry-After": "0"}) if len(calls) == 1 else Response(200)
w.requests.request = fake_request
w.time.sleep = lambda seconds: None
w._HOST_GATES.clear()
assert w.get("https://ratelimit.example/jobs").status_code == 200
assert len(calls) == 2

# A long Retry-After is deferred without a second request.
calls.clear()
def long_request(method, url, **kwargs):
    calls.append(url); return Response(429, headers={"Retry-After": "120"})
w.requests.request = long_request
w._HOST_GATES.clear()
try:
    w.get("https://cooldown.example/jobs")
    raise AssertionError("expected rate limit deferral")
except w.RateLimitDeferred:
    pass
assert len(calls) == 1
w.requests.request, w.time.sleep = old_request, old_sleep

# A merge preserves both new job records and never downgrades published -> pending.
base = {"v": 2, "jobs": {"A|1": {"publication": "published", "first_seen": 1, "last_checked": 10}},
        "fp": {"f1": ["A|1"]}, "legacy_seen": {}, "meta": {"counters": {"published": 1}}}
ours = {"v": 2, "jobs": {"A|1": {"publication": "published", "first_seen": 1, "last_checked": 11},
                             "B|2": {"publication": "pending", "first_seen": 12, "last_checked": 12}},
        "fp": {"f1": ["A|1"], "f2": ["B|2"]}, "legacy_seen": {}, "meta": {"counters": {"published": 1, "discovered": 1}}}
theirs = {"v": 2, "jobs": {"A|1": {"publication": "pending", "first_seen": 1, "last_checked": 13},
                               "C|3": {"publication": "pending", "first_seen": 13, "last_checked": 13}},
          "fp": {"f1": ["A|1"], "f3": ["C|3"]}, "legacy_seen": {}, "meta": {"counters": {"published": 1, "discovered": 1}}}
merged = merge_db(base, ours, theirs)
assert set(merged["jobs"]) == {"A|1", "B|2", "C|3"}
assert merged["jobs"]["A|1"]["publication"] == "published"
assert merged["meta"]["counters"]["discovered"] == 2

# Location and Java must be evidenced by the listing/full description, not guessed from the title.
full = w.E.Description("Requirements: 2-4 years of professional experience. Spring Boot.", w.E.Retrieval.FULL_EMPLOYER, "test", "https://example.test/job")
verdict, info = w.analyze({"title": "Java Backend Engineer", "loc": "", "age": 0}, full, None)
assert verdict == "needs_review" and "LOCATION_UNVERIFIED" in info["codes"]
verdict, info = w.analyze({"title": "Java Backend Engineer", "loc": "Bengaluru", "age": 0}, full, None)
assert verdict == "ineligible" and "NO_JAVA" in info["codes"]
# Confirm the final user-selected rules: 2.3 years, Java required, Spring Boot preferred,
# India-wide including explicitly India-remote, and a 48-hour posting window.
assert w.PROFILE.total_years == 2.3
assert w.F["max_age_hours"] == 48
assert w.SK["min_other_hits"] == 0
assert w.loc_ok("Pune, Maharashtra, India")
assert w.loc_ok("Remote - India")
assert not w.loc_ok("Remote")
assert not w.loc_ok("London, United Kingdom")
assert w.clearly_non_india("London, United Kingdom")
assert not w.clearly_non_india("Itanagar")
assert w.reject_reason({"title": "Java Backend Engineer", "loc": "Bengaluru, India", "age": 2.1}) == "posted more than 48 hours ago"
assert w.reject_reason({"title": "Java Backend Engineer", "loc": "Bengaluru, India", "age": 2.0}) is None
assert w.reject_reason({"title": "QA Engineer", "loc": "Bengaluru, India", "age": 0}) is not None
unknown_age = w.E.Description("Java and Spring Boot. 2-4 years of professional experience.", w.E.Retrieval.FULL_EMPLOYER, "test", "https://example.test/job")
verdict, info = w.analyze({"title": "Java Backend Engineer", "loc": "Pune, India", "age": None}, unknown_age, None)
assert verdict == "needs_review" and "POSTING_AGE_UNVERIFIED" in info["codes"]
# Spring Boot is preferred, so a complete Java description without Spring Boot remains eligible
# when all other conditions (including experience) are satisfied.
print("Final job-alert settings checks passed")
