"""Evidence-based experience extraction and candidate-fit evaluation.

Two independent stages (nothing in stage 2 re-interprets what stage 1 extracted):
  1. extract_experience_requirements(description) -> JobRequirements   (what the EMPLOYER asked for, with evidence)
  2. evaluate_candidate_fit(requirements, profile) -> FitDecision      (what that means for ME)

Principles: keep the exact source text and its offsets; never invent a number; abstain (NEEDS_REVIEW) when the evidence is
missing, partial, conflicting or ambiguous.
"""
from __future__ import annotations
import re, hashlib, datetime as dt
from dataclasses import dataclass, field, asdict
from enum import Enum


# ----------------------------------------------------------------------------- enums / data model
class Scope(str, Enum):
    OVERALL = "OVERALL"; SKILL_SPECIFIC = "SKILL_SPECIFIC"; ROLE_DOMAIN = "ROLE_DOMAIN"; EDUCATION = "EDUCATION"
    COMPANY_HISTORY = "COMPANY_HISTORY"; OTHER = "OTHER"; UNKNOWN = "UNKNOWN"

class ReqType(str, Enum):
    MANDATORY = "MANDATORY"; PREFERRED = "PREFERRED"; OPTIONAL = "OPTIONAL"; UNKNOWN = "UNKNOWN"

class Bound(str, Enum):
    MINIMUM = "MINIMUM"; RANGE = "RANGE"; EXACT = "EXACT"; MAXIMUM = "MAXIMUM"; UNSPECIFIED = "UNSPECIFIED"

class Verdict(str, Enum):
    ELIGIBLE = "ELIGIBLE"; INELIGIBLE = "INELIGIBLE"; NEEDS_REVIEW = "NEEDS_REVIEW"

class Retrieval(str, Enum):
    FULL_EMPLOYER = "FULL_EMPLOYER"          # full text from the employer's own page / API
    FULL_JOBBOARD = "FULL_JOBBOARD"          # full text from an authorised job-board page (structured JobPosting data present)
    PARTIAL_SNIPPET = "PARTIAL_SNIPPET"      # truncated snippet or page text without structured evidence of the description body
    INACCESSIBLE = "INACCESSIBLE"            # request failed / blocked
    EMPTY = "EMPTY"                          # request worked but there was no description body

FULL_STATUSES = (Retrieval.FULL_EMPLOYER, Retrieval.FULL_JOBBOARD)


@dataclass
class Description:
    text: str = ""
    status: Retrieval = Retrieval.EMPTY
    source_type: str = ""
    source_url: str = ""
    retrieved_at: str = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    error: str = ""
    warnings: list = field(default_factory=list)

    @property
    def complete(self) -> bool: return self.status in FULL_STATUSES
    @property
    def sha1(self) -> str: return hashlib.sha1((self.text or "").encode("utf-8")).hexdigest()
    def meta(self) -> dict:
        w = list(self.warnings)
        if self.complete and len((self.text or "").strip()) < 150 and "SHORT_DESCRIPTION" not in w: w.append("SHORT_DESCRIPTION")   # a warning, never proof either way
        return dict(status=self.status.value, source_type=self.source_type, source_url=self.source_url, retrieved_at=self.retrieved_at,
                    error=self.error, warnings=w, sha1=self.sha1, length=len(self.text or ""))


@dataclass
class ExperienceStatement:
    raw_text: str                 # exactly as written ("7.5 year(s)", "2–4 years", "five-plus years")
    normalized_text: str          # "min 7.5 years" / "2-4 years" / "max 3 years"
    scope: Scope
    requirement_type: ReqType
    skill: str | None
    min_years: float | None
    max_years: float | None
    bound_type: Bound
    source_section: str
    evidence_start: int           # offsets into the description text
    evidence_end: int
    source_url: str
    source_type: str
    classification_status: str    # CLASSIFIED | AMBIGUOUS
    validation_reason: str
    sentence: str = ""            # the sentence that contains the statement (audit trail)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("scope", "requirement_type", "bound_type"): d[k] = d[k].value if hasattr(d[k], "value") else d[k]
        return d


@dataclass
class CandidateProfile:
    total_years: float = 2.2
    skill_years: dict = field(default_factory=dict)           # {"java": 2.2, ...}  only what you are SURE of
    range_slack: float = 0.5                                   # a range whose top is below total_years by more than this fails
    tolerance: float = 0.0                                     # allowance on the overall minimum (0 = none)
    skill_tolerance: float = 0.0                               # allowance on a mandatory skill minimum (0 = none)
    impossible_skill_is_ineligible: bool = True                # mandatory skill years > total career years can never be met
    skill_mode: str = "strict"                                 # "strict": mandatory skill years can fail a job; "info": recorded and shown, never decisive

    def years_for(self, skill: str):
        return {k.lower(): float(v) for k, v in self.skill_years.items()}.get((skill or "").lower())


def profile_from_config(cfg: dict) -> CandidateProfile:
    return CandidateProfile(total_years=float(cfg.get("my_years", 2.2)), skill_years=dict(cfg.get("skill_years") or {}),
                            range_slack=float(cfg.get("range_slack", 0.5)), tolerance=float(cfg.get("tolerance", 0)),
                            skill_tolerance=float(cfg.get("skill_tolerance", 0)),
                            impossible_skill_is_ineligible=bool(cfg.get("impossible_skill_is_ineligible", True)),
                            skill_mode=str(cfg.get("skill_checks", "strict")).lower())


# ----------------------------------------------------------------------------- vocabulary
WORDS = dict(one=1, two=2, three=3, four=4, five=5, six=6, seven=7, eight=8, nine=9, ten=10, eleven=11, twelve=12)
NUM = r"(\d{1,2}(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
YRS = r"(?:years?(?:\(s\))?|yrs?\.?|yr\(s\))['’]?s?(?![a-z])"
PLUS = r"(?:\s*\+|[\s-]*plus\b)"
RANGE_RE = re.compile(NUM + r"\s*\+?\s*(?:-|–|—|to)\s*" + NUM + r"\s*\+?\s*" + YRS, re.I)
BETWEEN_RE = re.compile(r"between\s+" + NUM + r"\s*(?:years?|yrs?)?\s*(?:and|&|-|–|to)\s*" + NUM + r"\s*\+?\s*" + YRS, re.I)
SINGLE_RE = re.compile(NUM + "(?:" + PLUS + r")?\s*" + YRS, re.I)

PREFERRED_RE = re.compile(r"preferred|preferably|good[- ]to[- ]have|nice[- ]to[- ]have|\bplus\b|desirable|desired|added advantage|\badvantage\b|an asset", re.I)
OPTIONAL_RE = re.compile(r"\boptional\b|\bbonus\b", re.I)
EDU_RE = re.compile(r"educat|degree|academic|schooling|diploma|bachelor|master'?s", re.I)
REQCUE_RE = re.compile(r"candidate|\byou\b|must|should|require|minimum|at least|looking for|seeking|need|ideal", re.I)
HISTORY_RE = re.compile(r"founded|established|\bsince\b|history|legacy|operat|serving|in business|decades?|for over|excellence|\bover\b|more than", re.I)
HEAD_RE = re.compile(r"^(?:minimum |basic |required |preferred |desired |key |mandatory |additional )?(?:qualifications?|requirements?|skills?|responsibilit\w+|"
                     r"what you|who you|nice to have|good to have|good-to-have|bonus|about|must have|eligibility|education|experience|exp\b|job description|overview)", re.I)
NONREQ_SECTION_RE = re.compile(r"about|responsibilit|benefits|perks|what we offer|company|who we are|our (?:story|mission|culture)|overview of", re.I)

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
TECH = [("Java", r"\bjava\b(?!\s*script)|\bj2ee\b|core java")] + SKILLS + [
    ("C++", r"c\+\+"), (".NET", r"\.net\b|\bc#"), ("JavaScript", r"javascript|node\.?js"), ("Linux", r"\blinux\b"),
    ("Oracle", r"\boracle\b"), ("Salesforce", r"salesforce"), ("Data/ML", r"machine learning|data science|\bml\b|deep learning|\bllm"),
    ("Testing", r"selenium|automation testing|qa automation"), ("Mainframe", r"mainframe|cobol")]

GENERIC_OBJ = re.compile(r"^(?:(?:an?|the)\s+)?(?:software|it\b|information technology|industry|similar|related|relevant|professional|"
                         r"this\s+(?:field|role|domain|position)|field|comparable|technical\s+role|role\b|position\b)", re.I)
GENERIC_MID = re.compile(r"^(?:relevant|professional|work|working|industry|hands-on|hands on|total|overall|proven|practical|software|it|related|similar|"
                         r"development|engineering|technology|technical|of|in|the|a|and|,|\s)*$", re.I)
REQ_WORDS = re.compile(r"^(?:is|are|will be|would be|being)?\s*(?:required|needed|mandatory|necessary|a must|expected|or more|and above|and over)\b.*", re.I)
CONNECT = re.compile(r"(?:in|with|using|on|of|as|within|across|building|developing|designing|managing|leading|working|handling|delivering|implementing|creating|supporting)\b\s*(.*)", re.I)
EXPERIENCE_CTX = re.compile(r"experience|\bexp\b|\bworked\b|\bworking\b|hands[- ]on|exposure|expertise|proficien", re.I)
OVERALL_WORDS = re.compile(r"\b(?:overall|total|in total|altogether)\b", re.I)


GENERIC_WORDS = set("""non-internship internship professional software development engineering work working industry relevant full-time fulltime hands-on practical technical it related similar
programming coding prior total overall proven commercial post-graduate post graduate applied backend back-end application web enterprise product production real-world""".split())
def generic_phrase(x: str) -> bool:
    toks = re.findall(r"[a-z0-9\-]+", (x or "").lower())
    return any(t in GENERIC_WORDS for t in toks) and all(t in GENERIC_WORDS or t in ("of", "in", "the", "a", "an", "and", "or", "as", "for", "with") for t in toks)

def _plain_end(rest: str) -> bool:
    """what follows the word 'experience' is nothing, 'is required', or a generic object - not a domain such as 'in building backend services'"""
    r = REQ_WORDS.sub("", clip(rest or "")).strip(" .:-)]")
    if not r: return True
    cm = CONNECT.match(r)
    return bool(cm and GENERIC_OBJ.match(cm.group(1).strip()))

def _n(x) -> float: return float(WORDS.get(str(x).lower(), x))
def clause_at(sent: str, pos: int) -> str:
    """the comma/semicolon/'including' delimited clause that contains position pos"""
    start = 0
    for m in re.finditer(r"[,;]|\bincluding\b|\bwith at least\b", sent):
        if m.start() >= pos: return sent[start:m.start()]
        start = m.end()
    return sent[start:]
def clip(x: str) -> str: return re.split(r"[,;(]|\bincluding\b|\bwith at least\b|\bplus\b", x, maxsplit=1)[0].strip()
def tech_in(s: str):
    for label, p in TECH:
        if re.search(p, s or "", re.I): return label
    return None
def fmtn(x) -> str: return f"{x:g}"


# ----------------------------------------------------------------------------- stage 1: statements
def _lines(text: str):
    """yield (line_offset, section, line). 'Label : value' lines carry their label only for themselves;
    a bare heading (nothing after the colon) applies until the next heading."""
    section = ""
    for m in re.finditer(r"[^\n]+", text or ""):
        raw = m.group(0); off = m.start()
        stripped = raw.strip(" \t•-*·")
        if not stripped: continue
        lead = raw.find(stripped)
        pre, sep, rest = stripped.partition(":")
        if sep and len(pre) <= 45 and HEAD_RE.match(pre.strip()):
            if rest.strip(): yield off + lead, pre.strip(), stripped; continue
            section = pre.strip(); continue
        if len(stripped) <= 70 and HEAD_RE.match(stripped) and not re.search(r"\d", stripped):
            section = stripped.rstrip(":"); continue
        yield off + lead, section, stripped


def _sentences(line: str):
    start = 0
    for m in re.finditer(r"(?<=[.;!?])\s+", line):
        yield start, line[start:m.start()]; start = m.end()
    yield start, line[start:]


def _bound(head: str, plus: bool, is_range: bool):
    h = head.lower()
    if is_range: return Bound.RANGE
    if re.search(r"(?:up to|upto|less than|under|maximum(?: of)?|max\.?|not more than|no more than)\s*$", h): return Bound.MAXIMUM
    if re.search(r"(?:exactly|precisely)\s*$", h): return Bound.EXACT
    if plus or re.search(r"(?:at least|minimum(?: of)?|min\.?|no less than|not less than|more than|over|atleast)\s*$", h): return Bound.MINIMUM
    return Bound.UNSPECIFIED


def extract_statements(text: str, source_url: str = "", source_type: str = "") -> list:
    """every duration in the text as an independent, classified record (education / company history / unrelated ones are kept, labelled, and ignored later)"""
    out = []
    for loff, section, line in _lines(text):
        for soff, sent in _sentences(line):
            taken = []
            found = []
            for rx, kind in ((BETWEEN_RE, "range"), (RANGE_RE, "range"), (SINGLE_RE, "single")):
                for m in rx.finditer(sent):
                    if any(a <= m.start() < b or a < m.end() <= b for a, b in taken): continue
                    taken.append(m.span()); found.append((kind, m))
            for kind, m in sorted(found, key=lambda x: x[1].start()):
                head, tail = sent[max(0, m.start() - 45): m.start()], sent[m.end(): m.end() + 90]
                plus = False
                if kind == "range":
                    lo, hi = _n(m.group(1)), _n(m.group(2))
                    if not lo <= hi < 30: continue
                    bound = Bound.RANGE
                else:
                    lo, hi = _n(m.group(1)), None
                    plus = bool(re.search(r"\+|plus", m.group(0), re.I))
                    bound = _bound(head, plus, False)
                    if lo == 0 and bound != Bound.MAXIMUM: continue
                    if bound == Bound.MAXIMUM: lo, hi = None, lo
                raw = re.sub(r"['’]s?$", "", m.group(0).strip())
                norm = (f"{fmtn(lo)}-{fmtn(hi)} years" if bound == Bound.RANGE else f"max {fmtn(hi)} years" if bound == Bound.MAXIMUM
                        else f"exactly {fmtn(lo)} years" if bound == Bound.EXACT else f"min {fmtn(lo)} years")
                s_off = loff + soff + m.start()
                out.append(_classify(dict(raw=raw, norm=norm, lo=lo, hi=hi, bound=bound, sent=sent, m=m, head=head, tail=tail, section=section,
                                          start=s_off, end=s_off + len(raw), url=source_url, stype=source_type)))
    return out


def _classify(c: dict) -> ExperienceStatement:
    sent, m, head, tail, section = c["sent"], c["m"], c["head"], c["tail"], c["section"]
    around = sent[max(0, m.start() - 90): m.end() + 90]
    before = re.split(r"\)|\band\b|;|,", sent[max(0, m.start() - 22): m.start()])[-1]
    scope, skill, status, why = Scope.UNKNOWN, None, "CLASSIFIED", ""
    head_nb = re.sub(r"(?:minimum(?: of)?|at least|min\.?|more than|over)\s*$", "", head, flags=re.I)

    if EDU_RE.search(sent[m.end(): m.end() + 22]) or EDU_RE.search(before):
        scope, why = Scope.EDUCATION, "duration belongs to education, not work experience"
    elif NONREQ_SECTION_RE.search(section) and not REQCUE_RE.search(sent) and (OVERALL_WORDS.search(sent) is None):
        scope, why = Scope.COMPANY_HISTORY, f"statement sits in a non-requirement section ({section!r})"
    elif re.search(r"\b(?:we|our|company|firm)\b", before + " " + head, re.I) and HISTORY_RE.search(sent) and not REQCUE_RE.search(sent):
        scope, why = Scope.COMPANY_HISTORY, "describes the employer's history, not a candidate requirement"
    elif not (EXPERIENCE_CTX.search(around) or re.search(r"experience|\bexp\b", section, re.I) or OVERALL_WORDS.search(sent)
              or (re.search(r"[|\t]\s*$", head) and tech_in(head))):
        tm = re.match(r"\s*(?:of|in)\s+(.{1,60})", tail)
        if tm and re.search(r"(?:within|in|over|after|for|next|last|past|during|than|every|each)\s*$", head, re.I):
            scope, why = Scope.OTHER, "a time frame, not a requirement"
        elif tm and tech_in(clip(tm.group(1))) and not GENERIC_OBJ.match(clip(tm.group(1))):
            scope, skill = Scope.SKILL_SPECIFIC, tech_in(clip(tm.group(1)))
        elif tm:
            scope, status, why = Scope.ROLE_DOMAIN, "AMBIGUOUS", "duration followed by a domain phrase without the word 'experience'"
        else:
            scope, why = Scope.OTHER, "no work-experience context around the duration"
    else:
        t1 = re.match(r"\s*(?:of\s+)?(?:(?:hands[- ]on|relevant|professional|work|working|practical|proven|strong|solid)\s+)*(?:experience|exp)\s*"
                      r"(?:in|with|using|on|of|working with|developing|building|designing)\s+(.{1,80})", tail, re.I)
        t2 = re.match(r"\s*(?:of\s+)?(.{1,70}?)\s+(?:experience|exp)\b", tail, re.I)
        t3 = re.match(r"\s*(?:in|with|using|on|of)\s+(.{1,60})", tail, re.I)
        explicit_overall = bool(OVERALL_WORDS.search(clause_at(sent, m.start())))
        if explicit_overall:
            scope = Scope.OVERALL
            sk = tech_in(clip(t1.group(1))) if t1 else (tech_in(clip(t3.group(1))) if t3 and not re.match(r"experience|exp\b", t3.group(1), re.I) else None)
            if sk: skill, status, why = sk, "AMBIGUOUS", "explicit overall wording followed by a technology; treated as overall, technology noted"
        elif t1 and tech_in(clip(t1.group(1))) and not GENERIC_OBJ.match(clip(t1.group(1))):
            scope, skill = Scope.SKILL_SPECIFIC, tech_in(clip(t1.group(1)))
        elif t2 and tech_in(t2.group(1)) and not GENERIC_MID.match(t2.group(1)):
            scope, skill = Scope.SKILL_SPECIFIC, tech_in(t2.group(1))
        elif t2 and not tech_in(t2.group(1)) and generic_phrase(t2.group(1)) and _plain_end(tail[t2.end():]):
            scope = Scope.OVERALL                                                    # "2+ years of non-internship professional software development experience"
        elif t3 and not re.match(r"experience|exp\b", t3.group(1), re.I) and tech_in(clip(t3.group(1))) and not GENERIC_OBJ.match(clip(t3.group(1))):
            scope, skill = Scope.SKILL_SPECIFIC, tech_in(clip(t3.group(1)))
        elif re.search(r"([A-Za-z+#.\s/]{2,30})\s*[:\-–(|\t]\s*$", head_nb) and tech_in(head_nb[-30:]) and not re.search(r"experience|total|overall", head_nb, re.I):
            scope, skill = Scope.SKILL_SPECIFIC, tech_in(head_nb[-30:])
        else:
            rest = re.sub(r"^['’]?s?\s*", "", tail)
            rm = re.match(r"(?:of\s+)?(?:(?:hands[- ]on|relevant|professional|work|working|practical|proven|strong|solid|industry|total|overall)\s+)*(?:experience|exp)\b(.*)", rest, re.I)
            if rm:
                obj = REQ_WORDS.sub("", clip(rm.group(1))).strip(" .:-)]")
                rem, n_conn = obj, 0
                while n_conn < 2 and (cm := CONNECT.match(rem)):                       # "working in a software development role"
                    rem, n_conn = cm.group(1).strip(), n_conn + 1
                if not obj or (n_conn and GENERIC_OBJ.match(rem)): scope = Scope.OVERALL
                else: scope, status, why = Scope.ROLE_DOMAIN, "AMBIGUOUS", f"duration tied to a domain phrase ({obj[:40]!r}); cannot tell if it is the overall requirement"
            elif re.search(r"(?:experience|exp)\b[^.:]{0,25}[:\-–(]?\s*(?:minimum|min\.?|at least)?\s*$", head, re.I) or \
                    re.search(r"experience|\bexp\b", section, re.I) and len(sent) <= 60:
                scope = Scope.OVERALL                                                    # "Exp: 4-6 Years", "Experience Required :\nMinimum 4 Years"
            elif re.match(r"\s*(?:of|in|with|as)\s+\w", tail):
                scope, status, why = Scope.ROLE_DOMAIN, "AMBIGUOUS", "duration followed by a domain phrase without the word 'experience'"
            else:
                scope, status, why = Scope.UNKNOWN, "AMBIGUOUS", "could not classify the statement"
    # requirement type
    win = sent[max(0, m.start() - 45): m.start()] + " " + sent[m.end(): m.end() + 60]     # the number's own "+"/"plus" is not a nice-to-have marker
    if OPTIONAL_RE.search(section) or OPTIONAL_RE.search(win): rtype = ReqType.OPTIONAL
    elif PREFERRED_RE.search(section) or PREFERRED_RE.search(win): rtype = ReqType.PREFERRED
    elif NONREQ_SECTION_RE.search(section): rtype = ReqType.UNKNOWN
    else: rtype = ReqType.MANDATORY
    if scope in (Scope.EDUCATION, Scope.COMPANY_HISTORY, Scope.OTHER): rtype = ReqType.UNKNOWN
    return ExperienceStatement(raw_text=c["raw"], normalized_text=c["norm"], scope=scope, requirement_type=rtype, skill=skill,
                               min_years=c["lo"], max_years=c["hi"], bound_type=c["bound"], source_section=section or "description",
                               evidence_start=c["start"], evidence_end=c["end"], source_url=c["url"], source_type=c["stype"],
                               classification_status=status, validation_reason=why, sentence=sent.strip()[:240])


# ----------------------------------------------------------------------------- stage 1: job-level requirements
def _interval(s: ExperienceStatement):
    lo = s.min_years if s.min_years is not None else 0.0
    return lo, s.max_years                                  # max None = open ended


def _intersect(a, b):
    lo = max(a[0], b[0]); hi_a, hi_b = a[1], b[1]
    hi = hi_b if hi_a is None else hi_a if hi_b is None else min(hi_a, hi_b)
    return (lo, hi) if (hi is None or lo <= hi) else None


@dataclass
class JobRequirements:
    statements: list
    description: dict
    overall: dict | None = None
    skills: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    ambiguous: list = field(default_factory=list)
    verification_status: str = "NEEDS_REVIEW"
    reason_codes: list = field(default_factory=list)
    why: str = ""
    profile_total: float = 2.2

    @property
    def verified(self) -> bool: return self.verification_status == "VERIFIED"

    def to_dict(self) -> dict:
        d = asdict(self); d["statements"] = [s.to_dict() for s in self.statements]; return d


def extract_experience_requirements(desc: Description, profile_total: float = 2.2, tolerance: float = 0.0) -> JobRequirements:
    text = desc.text or ""
    sts = extract_statements(text, desc.source_url, desc.source_type)
    req = JobRequirements(statements=sts, description=desc.meta(), profile_total=profile_total)
    req.skills = [s.to_dict() for s in sts if s.scope == Scope.SKILL_SPECIFIC]
    req.ambiguous = [s.to_dict() for s in sts if s.classification_status == "AMBIGUOUS" and s.scope in (Scope.ROLE_DOMAIN, Scope.UNKNOWN)]
    if not desc.complete:
        req.reason_codes.append("DESCRIPTION_NOT_FULL")
        req.why = f"full description not available ({desc.status.value}{': ' + desc.error if desc.error else ''}); nothing is verified"
        return req
    ov = [s for s in sts if s.scope == Scope.OVERALL and s.requirement_type == ReqType.MANDATORY and s.bound_type != Bound.MAXIMUM]
    amb = [s for s in sts if s.scope in (Scope.ROLE_DOMAIN, Scope.UNKNOWN) and s.requirement_type == ReqType.MANDATORY and s.bound_type != Bound.MAXIMUM]
    pref = [s for s in sts if s.scope == Scope.OVERALL and s.requirement_type in (ReqType.PREFERRED, ReqType.OPTIONAL)]
    if not ov:
        if re.search(r"\bfreshers?\b|entry[- ]level|new grad|recent graduate", text, re.I) and not amb:
            req.overall = dict(raw_text="fresher / entry-level", normalized="0+ years", min=0.0, max=None, bound_type="UNSPECIFIED", derivation="employer asks for freshers / entry level",
                               evidence=[], sentence="", section="description")
            req.verification_status = "VERIFIED"; return req
        if amb: req.reason_codes.append("AMBIGUOUS_STATEMENT"); req.why = f"ambiguous statement, cannot tell if it is the overall requirement: \"{amb[0].sentence[:90]}\""
        elif pref: req.reason_codes.append("ONLY_PREFERRED"); req.why = f"only preferred experience stated: {pref[0].raw_text}"
        else: req.reason_codes.append("NO_OVERALL_STATEMENT"); req.why = "no overall experience statement in the description"
        return req
    eff = _interval(ov[0]); used = [ov[0]]
    for s in ov[1:]:
        nxt = _intersect(eff, _interval(s))
        if nxt is None:
            req.conflicts.append(dict(a=ov[0].raw_text, b=s.raw_text, a_sentence=ov[0].sentence, b_sentence=s.sentence))
            req.reason_codes.append("CONFLICTING_OVERALL"); req.why = f"conflicting overall statements: \"{ov[0].raw_text}\" vs \"{s.raw_text}\""
            return req
        eff = nxt; used.append(s)
    for a in amb:                                                   # an unclear statement that would raise the bar -> a human decides
        a_lo, _ = _interval(a)
        if a_lo > max(profile_total + tolerance, eff[0]) or _intersect(eff, _interval(a)) is None:
            req.reason_codes.append("AMBIGUOUS_STATEMENT")
            req.why = f"ambiguous statement may be an overall requirement: \"{a.sentence[:90]}\""; return req
    primary = max(used, key=lambda s: (s.max_years is not None, s.min_years or 0))     # prefer the most specific wording
    deriv = (f"single statement {ov[0].raw_text!r}" if len(used) == 1 else
             "effective requirement is the intersection of compatible statements: " + "; ".join(f"{s.raw_text!r} [{s.source_section}]" for s in used))
    req.overall = dict(raw_text=primary.raw_text if len(used) == 1 else " & ".join(dict.fromkeys(s.raw_text for s in used)),
                       normalized=(f"{fmtn(eff[0])}-{fmtn(eff[1])} years" if eff[1] is not None else f"min {fmtn(eff[0])} years"),
                       min=eff[0], max=eff[1], bound_type=("RANGE" if eff[1] is not None else "MINIMUM"), derivation=deriv,
                       evidence=[dict(start=s.evidence_start, end=s.evidence_end, raw=s.raw_text, section=s.source_section) for s in used],
                       sentence=primary.sentence, section=primary.source_section)
    req.verification_status = "VERIFIED"
    return req


# ----------------------------------------------------------------------------- stage 2: eligibility
@dataclass
class FitDecision:
    verdict: Verdict
    reason_codes: list
    explanation: str
    overall_check: dict
    skill_checks: list

    def to_dict(self) -> dict:
        d = asdict(self); d["verdict"] = self.verdict.value; return d


def evaluate_candidate_fit(req: JobRequirements, p: CandidateProfile) -> FitDecision:
    """Applies the rules to what was extracted. Never changes or reinterprets the employer's requirement."""
    codes, notes, skill_checks = [], [], []
    overall = dict(status="UNVERIFIED", detail=req.why)
    if req.verified:
        o = req.overall; lo, hi = o["min"], o["max"]
        if lo > p.total_years + p.tolerance:
            overall = dict(status="FAIL", detail=f"required minimum {fmtn(lo)} > your {fmtn(p.total_years)} years"); codes.append("OVERALL_ABOVE_PROFILE")
        elif hi is not None and hi < p.total_years - p.range_slack:
            overall = dict(status="FAIL", detail=f"range tops out at {fmtn(hi)}, below your {fmtn(p.total_years)} years"); codes.append("RANGE_BELOW_PROFILE")
        else:
            overall = dict(status="PASS", detail=f"your {fmtn(p.total_years)} years meet the verified requirement ({o['normalized']})")
    else:
        codes += req.reason_codes
    unverifiable = []
    for s in req.skills:
        if s["requirement_type"] != ReqType.MANDATORY.value or s["bound_type"] == Bound.MAXIMUM.value or s["min_years"] is None: continue
        have = p.years_for(s["skill"]); need = s["min_years"]
        chk = dict(skill=s["skill"], required=s["raw_text"], required_min=need, your_years=have, evidence=s["sentence"][:120])
        if p.skill_mode == "info":                                                                  # shown to you, never decides
            chk["result"] = "NOTE" if (have is None or need > have + p.skill_tolerance) else "PASS"; skill_checks.append(chk); continue
        if have is not None:
            if need > have + p.skill_tolerance: chk["result"] = "FAIL"; codes.append("SKILL_ABOVE_PROFILE")
            else: chk["result"] = "PASS"
        elif p.impossible_skill_is_ineligible and need > p.total_years + p.skill_tolerance:
            chk["result"] = "FAIL"; codes.append("SKILL_EXCEEDS_TOTAL_CAREER")                    # nobody has more years in a skill than in a whole career
        else:
            chk["result"] = "UNKNOWN"; unverifiable.append(f"{s['skill']} {s['raw_text']}"); codes.append("MANDATORY_SKILL_UNVERIFIABLE")
        skill_checks.append(chk)
    failed = [c for c in codes if c in ("OVERALL_ABOVE_PROFILE", "RANGE_BELOW_PROFILE", "SKILL_ABOVE_PROFILE", "SKILL_EXCEEDS_TOTAL_CAREER")]
    if failed:
        verdict = Verdict.INELIGIBLE
        bad = [overall["detail"]] if overall["status"] == "FAIL" else []
        bad += [f"{c['skill']} {c['required']} (you: {c['your_years'] if c['your_years'] is not None else 'n/a'})" for c in skill_checks if c["result"] == "FAIL"]
        expl = "fails: " + "; ".join(bad)
    elif not req.verified or not req.description.get("status", "").startswith("FULL"):
        verdict = Verdict.NEEDS_REVIEW; expl = req.why or "description not verified"
    elif unverifiable and p.skill_mode != "info":
        verdict = Verdict.NEEDS_REVIEW; expl = "mandatory skill requirement cannot be verified, no recorded experience for: " + ", ".join(unverifiable)
    else:
        verdict = Verdict.ELIGIBLE
        sk = [f"{c['skill']} {c['required']}" for c in skill_checks]
        expl = overall["detail"] + (("; skill years shown for information only: " + ", ".join(sk)) if (sk and p.skill_mode == "info") else
                                    ("; skill checks passed: " + ", ".join(f"{c['skill']} {c['required']} vs your {fmtn(c['your_years'])}" for c in skill_checks)) if sk else "")
    return FitDecision(verdict, list(dict.fromkeys(codes)), expl, overall, skill_checks)
