"""Offline logic tests (no internet). Run: python test_watcher.py"""
import sys, json, pathlib, tempfile
sys.argv = [sys.argv[0]]
import watcher as w

# ---- experience parsing ----
cases = [("We need 2-4 years of experience in Java", "ok"), ("0-3 years experience", "ok"), ("1 to 3 years of experience", "ok"),
         ("2-5 years relevant experience", "ok"), ("3-5 years of experience", "no"), ("5+ years of experience in Java", "no"),
         ("minimum 2+ years experience", "ok"), ("0-1 years experience", "no"), ("Strong Java skills, great culture", "unknown"),
         ("Join us within 3-5 years to grow", "unknown")]
for text, want in cases:
    got = w.parse_years(text)[0]; assert got == want, (text, got, want)
print("experience parsing OK")

# ---- fit logic ----
j = dict(id="1", title="Software Engineer II", loc="Hyderabad", req="R1", url="u", posted="Today", age=0)
assert w.analyze(j, "2-4 years experience Java Spring Boot microservices REST", None)[0]
assert not w.analyze(j, "2-4 years experience Python Django", None)[0]                      # no Java
assert w.analyze(j, "2-4 years Java only role", None)[0]                                    # Java alone is enough now
assert not w.analyze(j, "5-8 years experience Java Spring Boot", None)[0]                   # too senior
assert not w.analyze(j, "2-4 years experience Java Spring Boot", "Pune, India")[0]          # wrong city
assert not w.analyze(j, "JavaScript React Node experience 2-4 years", None)[0]              # javascript != java
assert w.analyze(j, "Java Spring Boot developer", None)[0]                                  # years not stated -> alert
print("fit logic OK")

# ---- full run with fake career sites: no repeats ----
tmp = pathlib.Path(tempfile.mkdtemp())
w.SEEN_F, w.RES_F = tmp / "seen.json", tmp / "res.json"
w.CFG["companies"] = [dict(name="Acme", url="x", match="acme", tier="T1")]
w.RES_F.write_text(json.dumps({"Acme": {"type": "workday", "api": "A", "web": "W"}}))
JOBS = [dict(id=f"/job/{i}", req=f"R{i}", title=t, loc="Bengaluru", url=f"W/job/{i}", posted="Today", age=0)
        for i, t in enumerate(["Java Backend Engineer", "Senior Java Engineer", "Software Engineer", "Java Developer"])]
w.LIST["workday"] = lambda r: list(JOBS)
TEXT = {"/job/0": "2-4 years experience. Java, Spring Boot, REST", "/job/2": "6+ years experience Java Spring",
        "/job/3": "0-3 years experience Java microservices Kafka"}
w.DETAIL["workday"] = lambda r, j: (TEXT[j["id"]], "Bengaluru")
sent = []; w.send = lambda t: (sent.append(t) or True)
w.main()
assert len(sent) == 2 and "Java Backend Engineer" in sent[0] and "Java Developer" in sent[1], sent
print("run 1 sent", len(sent), "alerts"); print(sent[0])
w.main()
assert len(sent) == 2, "REPEATED an alert!"
JOBS.append(dict(id="/job/9", req="R9", title="Java Engineer", loc="Hyderabad", url="W/job/9", posted="Today", age=0))
TEXT["/job/9"] = "1-3 years experience Java Spring Boot"; w.DETAIL["workday"] = lambda r, j: (TEXT[j["id"]], "Hyderabad")
w.main()
assert len(sent) == 3 and "Java Engineer" in sent[2]
print("run 2 sent nothing again, run 3 sent only the 1 new job: dedupe OK")
