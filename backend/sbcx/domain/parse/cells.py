# Ported from audit_tools/ext.py (the rule-based extractor that produced labels v1.4).
# The rules are kept as they were; only file/path handling changed. Dense legacy style is
# intentional so diffs against the prototype stay readable; see ruff per-file ignores.
import re

from sbcx.domain.parse.textnorm import norm

NC_RE=re.compile(r'^(not covered|not a covered|no coverage|excluded|not covered\b|no benefit|benefit not covered)',re.I)
def ded_flag(t):
    tl=re.sub(r"[\s\-,]","",t.lower()).replace("’","'")
    if re.search(r"deductible(does|do|will)?(not|n't)(apply)?|deducible(does)?notapply|deductiblewaived|waive[sd]?(the)?deductible|notsubjectto(the)?(\w{0,12})deductible|nodeductible|deductibleiswaived|deductiblenotapply|ded(uctible)?doesnotapply|notsubjecttoded|deductibledoesn'?tapply|withoutdeductible",tl): return False
    if re.search(r"after.{0,25}deductible|deductible.{0,60}before(copays?|coinsurance)|withdeductible|deductible\+|^deductible(then|and|plus|;)|deductibleapplies|subjectto(the)?.{0,15}deductible|afterded\b|dedapplies|deductiblethen|plus.{0,12}deductible|afterdeductible",tl): return True
    return None
def money(x): return float(x.replace(',',''))
PRICE=re.compile(r'(no charge|no cost|no copay(?!ment)|\$\s?[\d,]+(?:\.\d+)?|\d+(?:\.\d+)?\s?%)',re.I)
# "Visit 1: $35; Visit 2 and after: No charge" / "Visits 1-3: $10; Visits 4+: $40": the later charge is
# the structured value (v1.4 convention, applied by hand in audit_tools/fix/zz_later_rule.txt).
VISITS_THEN=re.compile(r'(?i)^\s*(?:[\w /&]{0,40}:\s*)?visits?\s*1(?:\s*-\s*\d+)?\s*:\s*[^;]*?[;,.]\s*(?=(?:visits?\s*\d+\s*(?:\+|and after|or more|and up|-\s*\d+)?\s*:|after\b|subsequent\b))')
FIRSTV=re.compile(r'(?i)\b(first|initial|upfront)\b')
# marker AFTER the later price: "$30 copay for the first 3 visits and 20% coinsurance thereafter", "$40 copay / additional office visit"
POSTFIX=re.compile(r'(?i)\s*(\bthereafter\b|/\s*additional\b|\bfor (each )?additional\b|\bper additional\b)')
# marker BEFORE the later price: "..., then $15", "Additional visits: $30", "Subsequent visits, $25"
PREFIX=re.compile(r'(?i)(\bthen\b|\badditional (office )?visits?\s*:|\bsubsequent (office )?visits?\b,?)')
def later_charge(t):
    """(first-visits head, later-charge text) when the cell prices the first/initial/upfront visits
    differently from later ones; None otherwise. Only the first labeled part of the cell is considered."""
    f=FIRSTV.search(t)
    if not f or f.start()>60 or not re.search(r'(?i)visit|\d|one|two|three|four|five',t[f.start():f.start()+40]): return None
    toks=list(PRICE.finditer(t))
    if len(toks)<2 or toks[0].start()>f.start()+60: return None
    for m in POSTFIX.finditer(t):
        if m.start()<=f.end(): continue
        prev=[x for x in toks if x.end()<=m.start()+1 and x.start()>f.start()-40]
        if len(prev)>=2:
            lp=prev[-1]
            j=lp.start()
            k=max(t.rfind(' and ',0,j),t.rfind(';',0,j),t.rfind(',',0,j))
            if k<toks[0].end(): k=j
            return t[:k].rstrip(' ,;'), t[lp.start():m.start()]+t[m.end():]
    for m in PREFIX.finditer(t):
        if m.start()<=f.end(): continue
        nxt=[x for x in toks if x.start()>=m.end()]
        if nxt and any(x.end()<=m.start() for x in toks):
            return t[:m.start()].rstrip(' ,;'), t[m.end():]
    return None
PARTLABEL=re.compile(r'(?:^|[\s.;])[A-Z][\w /&()\-]{1,40}:\s')
def group_ded_flag(t,toks):
    """Deductible statement closing the first group of alternatives ("Lab: $0 ... or $75 copay/test;
    deductible does not apply. X-ray: 40%") or standing alone right after it ("... or $150 copay. Deductible
    does not apply. All other ..."). Not used when another labeled part comes first (its statement is its own)."""
    if not toks: return None
    sents=re.split(r'(?<=\.)\s+',t)
    first=sents[0]
    if PARTLABEL.search(first,toks[0].end()): return None
    m=re.search(r'[;,]\s*([^;,]*\bdeductible\b[^;,]*?)\.?\s*$',first,re.I)
    if m and not PRICE.search(m.group(1)): return ded_flag(m.group(1))
    if len(sents)>1 and len(sents[1])<45 and re.search(r'(?i)deductible',sents[1]) and not PRICE.search(sents[1]): return ded_flag(sents[1])
    return None
def parse_cost(raw,labrule=True):
    t=norm(raw)
    if not t: return None,''
    tl=t.lower()
    t=re.sub(r'(?i)covered (at|in full at) 100%|paid at 100%|100% covered','No charge',t); tl=t.lower()
    if NC_RE.match(tl): return dict(covered=False,copay=None,coinsurance_pct=None,deductible_applies=None,note=None),''
    if re.match(r'^(n/?a|not applicable|-+)$',tl): return None,''
    c=dict(covered=True,copay=None,coinsurance_pct=None,deductible_applies=None,note=None)
    # split into parts: "Label: price" sequences or ';' separated alternatives
    mf=re.match(r'(?i)^\s*([\w ]{0,20}:\s*)?(the )?first (\d+|one|two|three|four|five)?\s*(\w+ )?(visits?|office visits?)\b.*?(?:\bthen\b|(?=\bsubsequent\b))',t) or re.match(r'(?i)^\s*(\$0|no charge|no copay)( copay(ment)?)? (for|on) (the |your )?first\b.*?\bthen\b',t) or VISITS_THEN.match(t)
    if mf:
        # "First 3 visits $5, then $20 copay" -> the price after "then" is the structured value
        rest=t[mf.end():]
        c2,ex2=parse_cost(rest)
        if c2 and c2['covered'] and (c2['copay'] is not None or c2['coinsurance_pct'] is not None):
            if c2['deductible_applies'] is None: c2['deductible_applies']=ded_flag(t[:mf.end()+40]) if ded_flag(t[:mf.end()]) is not None else None
            head=t[:mf.end()].rstrip(' ,;.') if VISITS_THEN.match(t) else t[:mf.end()].rstrip(' ,;then')
            return c2,(head+('; '+ex2 if ex2 else '')).strip()
    lc=later_charge(t)
    if lc:
        # general "first visits $X ... later $Y" wording (audit 2026-10-27): the later charge is structured
        head,rest=lc
        c2,ex2=parse_cost(rest)
        if c2 and c2['covered'] and (c2['copay'] is not None or c2['coinsurance_pct'] is not None):
            if c2['deductible_applies'] is None: c2['deductible_applies']=ded_flag(head)
            return c2,(head.rstrip(' ,;.')+('; '+ex2 if ex2 else '')).strip()
    toks=list(PRICE.finditer(t))
    if not toks:
        if re.search(r'not covered',tl): return dict(covered=False,copay=None,coinsurance_pct=None,deductible_applies=None,note=None),''
        if ded_flag(t) is not None: c['deductible_applies']=ded_flag(t); return c,''
        if re.search(r'covered|included',tl): return c,t
        return None,t
    first=toks[0]
    # combined first part: "$X copay ... then Y%" or "$X ... + Y%" or "Y% ... after $X copay"
    rest_start=None
    def isd(m): return m.group(0).startswith('$')
    def isp(m): return m.group(0).endswith('%')
    def isn(m): return m.group(0).lower().startswith('no ')
    used=[first]
    if len(toks)>1:
        mid=t[first.end():toks[1].start()].lower()
        if (((isd(first) and isp(toks[1])) or (isp(first) and isd(toks[1]))) and re.search(r'\bthen\b|\+|\bplus\b|\band\b|\bafter\b|copay\s*,?\s*$|copayment\s*,?\s*$|/visit,?\s*$|per visit,?\s*$|^\s*co-?pay(ment)?\s*/\s*[\w\- ]{1,20},\s*$',mid) and not re.search(r'[;:]',mid)) or ((isn(first) and (isp(toks[1]) or isd(toks[1]))) and re.search(r'\bthen\b',mid) and not re.search(r'[;:]',mid)):
            after2=t[toks[1].end():toks[1].end()+60].lower()
            if not re.match(r'^\s*(coinsurance|copay\w*)?\s*(/\w+\s*)?((for|on)\s+)?(all\s+)?other|^\s*(coinsurance|copay\w*)?\s*for (other|all other|outpatient|inpatient|lab|labs|x-ray|surgery)',after2):
                used.append(toks[1])
    for m in used:
        g=m.group(0)
        if isn(m):
            if c['copay'] is None: c['copay']=0.0
            if c['coinsurance_pct'] is None: c['coinsurance_pct']=0.0
        elif isd(m): c['copay']=money(g[1:].strip())
        else: c['coinsurance_pct']=float(g[:-1].strip())
    if len(used)==2 and isn(used[0]):
        # "No charge for first visit, then $X" -> use the later amount
        if isd(used[1]): c['copay']=money(used[1].group(0)[1:]); c['coinsurance_pct']=None
        else: c['coinsurance_pct']=float(used[1].group(0)[:-1]); c['copay']=None
    # "$0 copay" handled as copay 0, coinsurance 0
    if isd(first) and len(used)==1 and c['copay']==0 and not re.search(r'coinsurance',t[first.end():first.end()+40],re.I): c['coinsurance_pct']=0.0
    # first-part text = up to the start of the next unused price token's sentence/part
    end=used[-1].end()
    nxt=[m for m in toks if m.start()>=end]
    cut=len(t)
    dedspan=t
    if nxt:
        pre=t[:nxt[0].start()]
        seg=t[end:nxt[0].start()]
        lb=re.search(r'((?:\b[A-Z][\w/\-&]*\.?,?\s+|\bfor\s+|\bof\s+|\bat\s+|\bthe\s+|\bor\s+|\band\s+)*(?:\b[A-Z][\w/\-&]*\.?\s*:?\s*|\(\w+\)\s*:?\s*)|(?:[A-Z][\w/\-]*\s){0,3}[A-Za-z0-9][\w/\-]*:\s*)$',pre)
        b=max(seg.rfind(';'),seg.rfind('. '),seg.rfind(' or '),seg.rfind(','),seg.rfind(' / '),seg.rfind('/'))
        if lb and lb.start()>end and not re.match(r'(?i)(deductible|copay|coinsurance|per |visit|then)',lb.group(0).strip()): cut=lb.start()
        elif re.search(r'\band\b',seg) and not re.search(r'[;.]',seg): cut=nxt[0].start()
        elif b>=0: cut=end+b
        else: cut=nxt[0].start()
        dedspan=pre[:lb.start()] if (lb and lb.start()>end and not re.match(r'(?i)(deductible|copay|coinsurance|per |visit|then)',lb.group(0).strip())) else pre
        for mb in re.finditer(r'[.;]\s+',seg):
            if re.match(r'\s*[A-Z][\w\- /]{0,30}:',seg[mb.end():]): dedspan=t[:end+mb.start()]; break
    firstpart=t[:cut]; extra=t[cut:].strip(' ;,./')
    c['deductible_applies']=ded_flag(dedspan)
    if c['deductible_applies'] is None and nxt:
        # a single statement at the very end applies to every part
        tail=t[nxt[-1].end():]
        lab=re.search(r'[A-Z][\w\- /&]{0,40}:\s*$',t[:nxt[-1].start()])
        if re.search(r'(?i)deductible',tail) and not re.search(r'(?i)deductible',t[:nxt[-1].start()]) and not (lab and labrule and not re.match(r'^[^;]{0,25};\s*deductible',tail,re.I)): c['deductible_applies']=ded_flag(tail)
    if c['deductible_applies'] is None:
        c['deductible_applies']=group_ded_flag(t,toks)
    return c,extra
