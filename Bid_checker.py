"""
BidCheck - Public Procurement Bid Compliance Verification Assistant (SIH26100)
Single-file Streamlit app.   Run:  pip install streamlit pandas pypdf
                                   streamlit run bidcheck_app.py
Sections: 1) rule engine + keyword baseline  2) synthetic bid generator
          3) evaluation metrics              4) Streamlit UI
"""
import io, json, random, re
from dataclasses import dataclass, asdict
import pandas as pd
import streamlit as st


# ======================================================================
# 1) RULE ENGINE + KEYWORD BASELINE
# ======================================================================
PASS, FAIL, ESC = "PASS", "FAIL", "ESCALATE"
CFG = dict(min_turnover_cr=5.0, min_exp_years=3.0, emd_pct=2.0, min_validity_days=90, year=2026)
RULES = {
    "GSTIN": "Valid GST registration number (15-char format, valid state code)",
    "PAN": "Valid PAN, consistent with the PAN embedded in the GSTIN",
    "TURNOVER": "Average annual turnover of last 3 FY >= Rs 5 Crore",
    "EXPERIENCE": "At least 3 years of similar-work experience",
    "EMD": "EMD / bid security >= 2% of estimated bid value",
    "VALIDITY": "Bid validity >= 90 days",
    "UDYAM": "MSE benefit claimed only with a valid Udyam number",
    "DEBAR": "Declaration of not being blacklisted / debarred",
}
REF = re.compile(r"\b(required|minimum|eligibility criteria|nit clause|must be)\b", re.I)
PENDING = r"appl(?:ied|ication)|pending|under process|in progress|\bARN\b|awaited|acknowledg"
ANNEX = r"annexure|attached|enclosed|enclosure"
GST_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")
PAN_RE = re.compile(r"\b([A-Z]{5}\d{4}[A-Z])\b")
UDY_RE = re.compile(r"UDYAM-[A-Z]{2}-\d{2}-\d{7}")
AMT_RE = re.compile(r"(?:(rs|inr|₹)\.?\s*)?(\d[\d,]*(?:\.\d+)?)\s*(crores?|cr\b|lakhs?|lacs?)?", re.I)
WORDAMT = re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty)\s+(crore|lakh)", re.I)
LOOK = {"O": "0", "I": "1", "S": "5", "B": "8", "Z": "2"}
LOOK_R = {v: k for k, v in LOOK.items()}

@dataclass
class Result:
    rule: str
    verdict: str
    reason: str
    evidence: str = ""

def amount(s):
    for m in AMT_RE.finditer(s):
        if not (m.group(1) or m.group(3)):
            continue
        v, u = float(m.group(2).replace(",", "")), (m.group(3) or "").lower()
        return v * (1e7 if u.startswith("cr") else 1e5 if u[:1] == "l" else 1)
    return None

def lines_with(lines, pat):
    return [l for l in lines if re.search(pat, l, re.I)]

def repair(tok, shape):
    """Fix OCR look-alike confusions (O/0, I/1...). Returns repaired token if it then matches `shape`."""
    out, changed = "", False
    for ch, cls in zip(tok, shape):
        if cls == "d" and not ch.isdigit() and ch in LOOK:
            ch, changed = LOOK[ch], True
        elif cls == "a" and ch.isdigit() and ch in LOOK_R:
            ch, changed = LOOK_R[ch], True
        out += ch
    return out if changed else None

def check_id(lines, pat, rx, shape, name, extra=None):
    ls = lines_with(lines, pat)
    if not ls:
        return Result(name, FAIL, f"No {name} found in bid")
    t = " | ".join(ls)
    m = rx.search(t)
    if m and (extra is None or extra(m.group(1)) is None):
        return Result(name, PASS, f"Valid {name} format", m.group(1))
    if m:
        return Result(name, FAIL, extra(m.group(1)), m.group(1))
    if re.search(PENDING, t, re.I):
        return Result(name, ESC, f"{name} application/registration pending - officer must verify", t)
    if re.search(ANNEX, t, re.I):
        return Result(name, ESC, f"{name} given only as an attachment - officer must verify", t)
    n = len(shape)
    for tok in re.findall(r"\b[A-Z0-9]{%d}\b" % n, t.upper()):
        fixed = repair(tok, shape)
        if fixed and rx.search(fixed):
            return Result(name, ESC, f"{name} unreadable ({tok}); looks like OCR error for {fixed}", tok)
    if re.search(r"not (registered|available|applicable)|exempt|nil", t, re.I):
        return Result(name, FAIL, f"Bidder states no {name}", t)
    return Result(name, FAIL, f"{name} value is malformed/invalid", t)

def r_gstin(L):
    def st(g): return None if 1 <= int(g[:2]) <= 38 else f"Invalid GST state code {g[:2]}"
    return check_id(L, r"\bgst", GST_RE, "ddaaaaaddddaxxx", "GSTIN", st)

def r_pan(L, gstin_res):
    def cross(p):
        if p[3] not in "PCHFATBLJG":
            return f"PAN 4th character '{p[3]}' is not a valid holder type"
        if gstin_res.verdict == PASS and gstin_res.evidence[2:12] != p:
            return f"PAN {p} does not match PAN inside GSTIN ({gstin_res.evidence[2:12]})"
    return check_id(L, r"\bpan\b|permanent account", PAN_RE, "aaaaadddda", "PAN", cross)

def years_fy(line):
    m = re.search(r"(20\d\d)\s*[-–/]\s*(\d{2,4})", line)
    return (m.group(1), line[m.end():]) if m else (None, line)

def r_turnover(L):
    ls = lines_with(L, "turnover")
    if not ls: return Result("TURNOVER", FAIL, "No turnover declared")
    t = " | ".join(ls)
    if re.search(r"cumulative|aggregate|combined", t, re.I):
        return Result("TURNOVER", ESC, "Turnover stated as a cumulative figure; yearly values needed", t)
    if WORDAMT.search(t):
        return Result("TURNOVER", ESC, "Turnover amount written in words; needs manual reading", t)
    if re.search(ANNEX, t, re.I) and amount(t) is None:
        return Result("TURNOVER", ESC, "Turnover only in attachment", t)
    vals, avg_line = {}, None
    for l in ls:
        fy, rest = years_fy(l)
        a = amount(rest)
        if a is None: continue
        if fy: vals[fy] = a
        elif re.search("average", l, re.I): avg_line = a
    prov = re.search(r"provisional|unaudited|approx|estimated", t, re.I)
    if avg_line is not None and not vals: avg, n = avg_line, 3
    else: avg, n = (sum(vals.values()) / len(vals) if vals else 0), len(vals)
    if n == 0: return Result("TURNOVER", FAIL, "No quantified turnover stated", t)
    if n < 3: return Result("TURNOVER", ESC, f"Only {n} financial year(s) given; 3 required", t)
    cr, need = avg / 1e7, CFG["min_turnover_cr"]
    if prov: return Result("TURNOVER", ESC, f"Average Rs {cr:.2f} Cr but figures provisional/unaudited", t)
    ok = cr >= need
    return Result("TURNOVER", PASS if ok else FAIL, f"Average turnover Rs {cr:.2f} Cr {'meets' if ok else 'is below'} Rs {need} Cr", t)

def r_experience(L):
    ls = lines_with(L, "experience|established|incorporated")
    if not ls: return Result("EXPERIENCE", FAIL, "No experience declared")
    t = " | ".join(ls)
    m = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", t, re.I)
    s = re.search(r"(?:since|established in|incorporated in|from)\s*(?:the year\s*)?(\d{4})", t, re.I)
    y = float(m.group(1)) if m else (CFG["year"] - int(s.group(1)) if s else None)
    if re.search(r"approx|about|nearly|around|roughly|\bjv\b|joint venture|partner|subsidiary|parent|promoter|sister", t, re.I):
        return Result("EXPERIENCE", ESC, "Experience is approximate or relies on a JV/parent/partner", t)
    if y is None: return Result("EXPERIENCE", FAIL, "No quantified experience stated", t)
    ok = y >= CFG["min_exp_years"]
    return Result("EXPERIENCE", PASS if ok else FAIL, f"{y:g} years experience {'meets' if ok else 'is below'} {CFG['min_exp_years']:g} years", t)

def r_emd(L):
    ls = lines_with(L, r"\bemd\b|earnest money|bid security")
    if not ls: return Result("EMD", FAIL, "No EMD / bid security declared")
    t = " | ".join(ls)
    e = amount(" ".join(ls))
    est = next((amount(l.split(":", 1)[-1]) for l in lines_with(L, r"estimated (bid |contract )?(value|cost)|tender value")), None)
    if e is None: return Result("EMD", ESC, "EMD amount not stated numerically", t)
    if est is None: return Result("EMD", ESC, "Estimated bid value not found; cannot compute 2%", t)
    p = e / est * 100
    ok = p >= CFG["emd_pct"]
    return Result("EMD", PASS if ok else FAIL, f"EMD is {p:.2f}% of estimated value (need {CFG['emd_pct']}%)", t)

def r_validity(L):
    ls = lines_with(L, r"validity|valid for|valid till|valid until")
    if not ls: return Result("VALIDITY", FAIL, "Bid validity not stated")
    t = " | ".join(ls)
    m = re.search(r"(\d+)\s*(day|week|month)", t, re.I)
    if not m or re.search(r"as per|as specified|as stated|till|until", t, re.I):
        return Result("VALIDITY", ESC, "Validity not stated as a number of days", t)
    d = int(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2).lower()]
    ok = d >= CFG["min_validity_days"]
    return Result("VALIDITY", PASS if ok else FAIL, f"Bid validity {d} days {'meets' if ok else 'is below'} {CFG['min_validity_days']} days", t)

def r_udyam(L):
    ls = lines_with(L, r"\b(mse|msme|udyam|micro|small enterprise)\b")
    t = " | ".join(ls)
    if not ls or re.search(r"not claim|not an? (mse|msme)|not applicable|no mse", t, re.I):
        return Result("UDYAM", PASS, "No MSE benefit claimed (not applicable)")
    m = UDY_RE.search(t)
    if m: return Result("UDYAM", PASS, "MSE claim backed by valid Udyam number", m.group(0))
    if re.search(PENDING + "|" + ANNEX, t, re.I):
        return Result("UDYAM", ESC, "Udyam certificate pending/attached; officer must verify", t)
    return Result("UDYAM", FAIL, "MSE benefit claimed without a valid Udyam number", t)

def r_debar(L):
    ls = lines_with(L, r"black-?list|debar|banned")
    if not ls: return Result("DEBAR", FAIL, "No blacklisting/debarment declaration found")
    t = " | ".join(ls)
    if re.search(r"show[- ]cause|pending|under review|appeal|stay|revoked|lifted|proceedings|notice", t, re.I):
        return Result("DEBAR", ESC, "Debarment history with open/changed status; officer must review", t)
    if re.search(r"not\s+(been\s+)?(black-?listed|debarred|banned)|never been|no (such )?(blacklisting|debarment)", t, re.I):
        return Result("DEBAR", PASS, "Clean declaration given", t)
    if re.search(r"(was|were|has been|have been|stands|been)\s+(black-?listed|debarred|banned)", t, re.I):
        return Result("DEBAR", FAIL, "Bidder declares it was blacklisted/debarred", t)
    return Result("DEBAR", ESC, "Declaration wording unclear", t)

def check_bid(text):
    L = [l.strip() for l in text.splitlines() if l.strip() and not REF.search(l)]
    g = r_gstin(L)
    res = [g, r_pan(L, g), r_turnover(L), r_experience(L), r_emd(L), r_validity(L), r_udyam(L), r_debar(L)]
    return res

def overall(res):
    v = [r.verdict for r in res]
    return FAIL if FAIL in v else ESC if ESC in v else PASS

# ---------- keyword-checklist baseline (presence of a keyword = pass) ----------
KW = {"GSTIN": r"\bgst", "PAN": r"\bpan\b", "TURNOVER": "turnover", "EXPERIENCE": "experience",
      "EMD": r"\bemd\b|earnest money", "VALIDITY": "validity", "DEBAR": r"black-?list|debar"}

def baseline(text):
    out = {r: (PASS if re.search(p, text, re.I) else FAIL) for r, p in KW.items()}
    claims = re.search(r"\b(mse|msme)\b", text, re.I) and not re.search(r"not claim", text, re.I)
    out["UDYAM"] = PASS if not claims or re.search("udyam", text, re.I) else FAIL
    return out

# ======================================================================
# 2) SYNTHETIC BID GENERATOR
# ======================================================================
LOOKALIKE_DIGIT = "O"
def indian(n):
    s = str(int(n)); head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2: parts.insert(0, head[-2:]); head = head[:-2]
    if head: parts.insert(0, head)
    return ",".join(parts + [tail])

def amt(cr, r, words_ok=False):
    return r.choice([f"Rs. {cr:.2f} Crore", f"₹ {indian(cr * 1e7)}", f"Rs. {cr * 100:.0f} Lakh", f"INR {cr:.1f} Cr"])

def rand_pan(r):
    return "".join(r.choice("ABCDEFGHJKLMNPQRSTUVWXY") for _ in range(3)) + "C" + r.choice("ABCDEFGHJKLMNPRSTUVWXY") + f"{r.randint(1000, 9999)}" + r.choice("ABCDEFGHJKLMNPRSTUVWXY")

W = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten", 11: "Eleven", 12: "Twelve"}

def g_gstin(lab, c, r):
    g = c["gstin"]
    if lab == PASS: return r.choice([f"GSTIN: {g}", f"GST Registration No. {g}", f"GST No - {g} (Active)"])
    if lab == FAIL: return r.choice(["GSTIN: Not registered (below threshold)", f"GSTIN: {g[:-2]}", f"GSTIN: 45{g[2:]}"])
    return r.choice([f"GSTIN: Application filed, ARN AA{r.randint(10**9, 10**10-1)}; certificate awaited",
                     f"GSTIN: O{g[1:]}", "GSTIN: as per Annexure-B (attached)"])

def g_pan(lab, c, r):
    p = c["pan"]
    if lab == PASS: return r.choice([f"PAN: {p}", f"Permanent Account Number (PAN) - {p}"])
    if lab == FAIL:
        opts = [f"PAN: {p[:9]}", "PAN: Not available", f"PAN: {p[:3]}X{p[4:]}"]
        if c["labels"]["GSTIN"] == PASS: opts.append("PAN: " + rand_pan(r))
        return r.choice(opts)
    return r.choice([f"PAN: applied for, acknowledgement pending", f"PAN: {p[:5]}O{p[6:]}", "PAN card copy enclosed in Annexure-C"])

def g_turnover(lab, c, r):
    ok = lab == PASS
    vals = [r.uniform(5.4, 11) if ok else r.uniform(1.5, 4.6) for _ in range(3)]
    fys = ["2023-24", "2024-25", "2025-26"]
    if lab == ESC:
        k = r.choice(["two", "prov", "cum"])
        if k == "two": return "\n".join(f"Turnover FY {f}: {amt(v, r)}" for f, v in list(zip(fys, vals))[:2])
        if k == "prov": return "\n".join(f"Turnover FY {f}: {amt(v, r)}" + (" (provisional, unaudited)" if f == "2025-26" else "") for f, v in zip(fys, vals))
        return f"Turnover (cumulative, last 3 years): {amt(sum(vals), r)}"
    if r.random() < .25: return f"Average annual turnover (last 3 FY): {amt(sum(vals) / 3, r)}"
    rows = [f"Turnover FY {f}: {amt(v, r)}" for f, v in zip(fys, vals)]
    if r.random() < .06:            # one year written in words (engine can't read -> should escalate)
        i = r.randrange(3); v = r.randint(5, 11) if ok else r.randint(2, 4)
        rows[i] = f"Turnover FY {fys[i]}: Rs. {W[v]} Crore only"
    return "\n".join(rows)

def g_exp(lab, c, r):
    if lab == PASS:
        y = r.randint(3, 15); return r.choice([f"Experience in similar works: {y} years", f"Experience: similar works executed since {2026 - y}", f"Established in {2026 - y}; experience of {y}+ years"])
    if lab == FAIL:
        if r.random() < .2: return None
        y = r.choice([0.5, 1, 1.5, 2, 2.5]); return r.choice([f"Experience in similar works: {y:g} years", f"Established in {2026 - int(max(y, 1))}"])
    y = r.randint(3, 8); return r.choice([f"Experience: approximately {y} years", f"Experience: {y} years (including experience of JV partner)", f"Experience: {y} years (parent company)"])

def g_emd(lab, c, r):
    est = c["est"]
    if lab == PASS: return f"EMD: Rs. {est * 100 * r.uniform(.021, .03):.2f} Lakh (DD enclosed)"
    if lab == FAIL:
        k = r.random()
        if k < .2: return None
        if k < .45: c["hidden"].append("EMD"); return f"EMD: Rs. {est * 100 * .025:.2f} Lakh (DD to be submitted physically after bid opening)"
        return f"EMD: Rs. {est * 100 * r.uniform(.005, .018):.2f} Lakh"
    return r.choice(["EMD: exemption sought, details in Annexure-D", "Bid security: DD enclosed, amount as stated in tender"])

def g_validity(lab, c, r):
    if lab == PASS: return r.choice([f"Bid validity: {r.randint(90, 180)} days from bid opening", "Bid validity: 4 months", "Bid validity: 16 weeks"])
    if lab == FAIL:
        k = r.random()
        if k < .15: return None
        if k < .35: c["hidden"].append("VALIDITY"); return "Bid validity: 90 days from the date of award"
        return r.choice(["Bid validity: 60 days", "Bid validity: 45 days", "Bid validity: 2 months", "Bid validity: 8 weeks"])
    return r.choice(["Bid validity: as per tender conditions", "Bid valid till 31-03-2027"])

def g_udyam(lab, c, r):
    u = f"UDYAM-PB-{r.randint(1, 30):02d}-{r.randint(0, 9999999):07d}"
    if lab == PASS: return r.choice([None, None, "MSE benefits: Not claimed", f"MSE status claimed for price preference. Udyam Registration No.: {u}"])
    if lab == FAIL: return r.choice(["MSE status claimed; Udyam No.: PB-05-12345", "MSE status claimed (Udyam registration not obtained)"])
    return r.choice(["MSE status claimed; Udyam certificate attached as annexure", "MSE status claimed; Udyam registration application pending"])

def g_debar(lab, c, r):
    if lab == PASS: return r.choice(["Declaration: We have not been blacklisted or debarred by any Government department or PSU.", "We hereby declare that the firm has never been blacklisted / debarred."])
    if lab == FAIL: return r.choice([None, None, "The firm was debarred by the Irrigation Dept. in 2024 for 3 years (till 2027)."])
    return r.choice(["Show-cause notice for debarment received; reply submitted, proceedings pending.", "Debarment order of 2024 stayed by High Court.", "Blacklisting by a PSU was revoked in 2025 after appeal."])

GEN = {"GSTIN": g_gstin, "PAN": g_pan, "TURNOVER": g_turnover, "EXPERIENCE": g_exp, "EMD": g_emd,
       "VALIDITY": g_validity, "UDYAM": g_udyam, "DEBAR": g_debar}
NAMES = ["Alpha Infra", "Bharat Constructions", "Citadel Engineers", "Deccan Builders", "Eastern Power Systems", "Gurukul Supplies", "Himalaya Tech", "Indus Projects"]

def make_bid(i, r):
    pan = rand_pan(r)
    c = dict(pan=pan, gstin=f"{r.randint(1, 37):02d}{pan}{r.randint(1, 9)}Z{r.choice('0123456789ABCDEFGH')}",
             est=round(r.uniform(1, 25), 2), hidden=[])
    labels = {k: PASS for k in RULES}
    if r.random() > .4:
        for k in r.sample(list(RULES), r.choice([1, 1, 2, 3])):
            labels[k] = FAIL if r.random() < .65 else ESC
    c["labels"] = labels
    for k in RULES:           # generate; if a generator declines (None), keep consistent
        pass
    body, truth = {}, dict(labels)
    for k in ["GSTIN", "PAN", "TURNOVER", "EXPERIENCE", "EMD", "VALIDITY", "UDYAM", "DEBAR"]:
        line = GEN[k](labels[k], c, r)
        if line is None and labels[k] == PASS and k not in ("UDYAM",):
            line = GEN[k](labels[k], c, r)
        body[k] = line
    head = [f"BID DOCUMENT  |  Tender Ref: GEM/2026/B/{r.randint(100000, 999999)}",
            f"Bidder: M/s {r.choice(NAMES)} Pvt Ltd", f"Estimated bid value: Rs. {c['est']:.2f} Crore"]
    rest = [v for v in body.values() if v]
    r.shuffle(rest)
    extra = []
    if r.random() < .35: extra.append("Eligibility criteria (NIT clause 4): bidder must not be blacklisted; minimum average turnover Rs. 5 Crore; 3 years experience; bid validity required 90 days; EMD 2% of estimated value.")
    if r.random() < .3: extra.append("Our firm has wide experience across the sector and strong turnover growth.")
    if r.random() < .2: extra.append("Registered office: Ludhiana, Punjab. Contact: procurement@example.com")
    lines = head + rest[:4] + extra + rest[4:]
    return dict(id=f"BID-{i:04d}", text="\n".join(lines), truth=truth, hidden=c["hidden"])

def make_dataset(n=300, seed=7):
    r = random.Random(seed)
    return [make_bid(i + 1, r) for i in range(n)]

# ======================================================================
# 3) EVALUATION
# ======================================================================
def run(n=300, seed=7):
    rows, bids = [], make_dataset(n, seed)
    for b in bids:
        res = {x.rule: x.verdict for x in check_bid(b["text"])}
        base = baseline(b["text"])
        for k in RULES:
            rows.append(dict(bid=b["id"], rule=k, truth=b["truth"][k], engine=res[k], baseline=base[k]))
    return pd.DataFrame(rows), bids

def _m(d, col):
    t, p = d.truth, d[col]
    tp, fp, fn = ((p == FAIL) & (t == FAIL)).sum(), ((p == FAIL) & (t != FAIL)).sum(), ((p != FAIL) & (t == FAIL)).sum()
    amb = (t == ESC).sum()
    return dict(accuracy=(t == p).mean(), precision=tp / (tp + fp) if tp + fp else float("nan"),
                recall=tp / (tp + fn) if tp + fn else float("nan"), escalation_rate=(p == ESC).mean(),
                escalation_recall=((p == ESC) & (t == ESC)).sum() / amb if amb else float("nan"),
                false_clears=int(((p == PASS) & (t != PASS)).sum()))

def per_rule(df, col):
    out = pd.DataFrame({k: _m(g, col) for k, g in df.groupby("rule")}).T
    out.loc["ALL RULES"] = _m(df, col)
    return out

def bid_level(df):
    def roll(s): return FAIL if (s == FAIL).any() else ESC if (s == ESC).any() else PASS
    g = df.groupby("bid")
    b = pd.DataFrame({c: g[c].apply(roll) for c in ["truth", "engine", "baseline"]})
    out = {}
    for c in ["engine", "baseline"]:
        p, t = b[c], b.truth
        cleared = p == PASS
        out[c] = dict(share_auto_cleared=cleared.mean(),
                      auto_clear_precision=(t[cleared] == PASS).mean() if cleared.any() else float("nan"),
                      wrongly_cleared_bids=int((cleared & (t != PASS)).sum()),
                      escalation_rate=(p == ESC).mean(),
                      escalation_recall=((p == ESC) & (t == ESC)).sum() / max((t == ESC).sum(), 1),
                      reject_precision=((p == FAIL) & (t == FAIL)).sum() / max((p == FAIL).sum(), 1),
                      reject_recall=((p == FAIL) & (t == FAIL)).sum() / max((t == FAIL).sum(), 1))
    return pd.DataFrame(out), b

# ======================================================================
# 4) STREAMLIT UI
# ======================================================================
st.set_page_config(page_title="BidCheck - Bid Compliance Verification", page_icon="✅", layout="wide")
ICON = {PASS: "✅ PASS", FAIL: "❌ FAIL", ESC: "⚠️ ESCALATE"}

def read_upload(f):
    name = f.name.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(f).pages)
    raw = f.read().decode("utf-8", errors="ignore")
    if name.endswith(".json"):
        d = json.loads(raw)
        return "\n".join(f"{k}: {v}" for k, v in d.items()) if isinstance(d, dict) else raw
    return raw

@st.cache_data
def evaluation(n, seed):
    return run(n, seed)

st.title("BidCheck - Public Procurement Bid Compliance Verification")
st.caption("SIH26100 prototype. Rule-based checker: names the failed rule, escalates ambiguity to a human officer.")
tab1, tab2, tab3 = st.tabs(["Check a bid", "Evaluation", "Rules & method"])

with tab1:
    c1, c2 = st.columns([1, 1])
    up = c1.file_uploader("Upload a bid (.txt, .pdf, .json)", type=["txt", "pdf", "json", "md"])
    df_, bids = evaluation(300, 7)
    pick = c2.selectbox("...or load a synthetic sample bid", ["-"] + [b["id"] for b in bids[:40]])
    text, truth = "", None
    if up: text = read_upload(up)
    elif pick != "-":
        b = next(b for b in bids if b["id"] == pick); text, truth = b["text"], b["truth"]
    text = st.text_area("Bid text (editable)", text, height=220)
    if st.button("Check bid", type="primary") and text.strip():
        res = check_bid(text); base = baseline(text); ov = overall(res)
        msg = {PASS: ("success", "AUTO-CLEARED: all rules passed"),
               FAIL: ("error", "NON-COMPLIANT: " + ", ".join(r.rule for r in res if r.verdict == FAIL)),
               ESC: ("warning", "ESCALATE TO OFFICER: " + ", ".join(r.rule for r in res if r.verdict == ESC))}[ov]
        getattr(st, msg[0])(f"**{msg[1]}**")
        rows = [{"Rule": r.rule, "Verdict": ICON[r.verdict], "Reason": r.reason, "Evidence": r.evidence[:120],
                 "Keyword baseline": ICON[base[r.rule]]} for r in res]
        if truth: 
            for row in rows: row["Ground truth (synthetic)"] = ICON[truth[row["Rule"]]]
        out = pd.DataFrame(rows); st.dataframe(out, hide_index=True)
        st.download_button("Download report (CSV)", out.to_csv(index=False), "bid_report.csv")

with tab2:
    st.warning("Synthetic data: sample bids are generated with known labels. Figures show how the pipeline behaves, not real GeM performance.")
    n = st.slider("Number of sample bids", 100, 1000, 300, 50); seed = st.number_input("Seed", value=7, step=1)
    df, _ = evaluation(n, int(seed)); bl, _b = bid_level(df)
    a, b_, c, d = st.columns(4)
    a.metric("Share auto-cleared", f"{bl.loc['share_auto_cleared','engine']:.1%}", f"baseline {bl.loc['share_auto_cleared','baseline']:.1%}", delta_color="off")
    b_.metric("Auto-clear precision", f"{bl.loc['auto_clear_precision','engine']:.1%}", f"baseline {bl.loc['auto_clear_precision','baseline']:.1%}", delta_color="off")
    c.metric("Escalation rate (bids)", f"{bl.loc['escalation_rate','engine']:.1%}")
    d.metric("Escalation recall (bids)", f"{bl.loc['escalation_recall','engine']:.1%}", "baseline 0%", delta_color="off")
    st.subheader("Bid level"); st.dataframe(bl.style.format("{:.3f}"))
    st.subheader("Per-rule: checker"); st.dataframe(per_rule(df, "engine").style.format("{:.3f}", na_rep="-"))
    st.subheader("Per-rule: keyword baseline"); st.dataframe(per_rule(df, "baseline").style.format("{:.3f}", na_rep="-"))
    st.caption("precision/recall are for detecting FAIL. escalation_recall = ambiguous cases that were escalated. false_clears = defective items passed silently.")

with tab3:
    st.table(pd.DataFrame({"Rule": list(RULES), "Check": list(RULES.values())}))
    st.markdown(f"""**Thresholds:** {CFG}

**Escalation policy:** a rule escalates (never guesses) when a value is pending, attached elsewhere, approximate, written in words, relies on a JV/parent, is provisional, or is unreadable (possible OCR error).
Absent mandatory information is a FAIL.

**Known limits:** regex-based; defects phrased unusually (e.g. validity counted from award, EMD not yet submitted) can pass silently - the evaluation reports these as `false_clears`. Real GeM bids need OCR and wider rule coverage.""")