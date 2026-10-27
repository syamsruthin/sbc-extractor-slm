# Ported from audit_tools/ext.py (the rule-based extractor that produced labels v1.4).
# The rules are kept as they were; only file/path handling changed. Dense legacy style is
# intentional so diffs against the prototype stay readable; see ruff per-file ignores.
import re

from sbcx.domain.parse.cells import money
from sbcx.domain.parse.textnorm import norm, rows


def amounts(s):
    return [money(x) for x in re.findall(r'\$\s?([\d,]+(?:\.\d+)?)',s)]
OONW=re.compile(r'(out-? ?of-? ?network|non-? ?network|non-? ?participating|nonparticipating|non-par\b)',re.I)
def split_net(s):
    """return (in_text,out_text) from a deductible/OOP answer"""
    s=norm(s)
    s=re.sub(r'(\d,\d{2}) (\d)\b',r'\1\2',s)
    s=re.sub(r'\$0[^$]{0,60}?(ihcp|indian health care provider)[^$]*?(?=\$|$)','',s,flags=re.I)
    s=re.sub(r'(?i)for (ihs|ihcp|indian health care) providers?[^.$]*not applicable\.?',' ',s)
    s=re.sub(r'(?i)(for\s+)?(\(?ihs\)?|\(?ihcp\)?|indian health care providers?)( \(ihcp\))?[^$]{0,80}?\$0\b[^$]*?(\$0\b[^$]*?)?(?=\$[1-9]|$)',' ',s)
    s=re.split(r'(?i)pediatric dental is limited',s)[0]
    segs=[x for x in re.split(r'(?<=[.;])\s+',s) if '$' in x]
    if len(segs)>=2 and any(OONW.search(x) for x in segs) and not all(OONW.search(x) for x in segs):
        ins=[x for x in segs if not OONW.search(x)]; oos=[x for x in segs if OONW.search(x)]
        # "for in-network ..." segments that merely mention out-of-network later are rare; take first of each
        return ins[0],oos[0]
    m=OONW.search(s)
    if m:
        a=s[:m.start()]; b=s[m.start():]
        if '$' not in a:  # label after amounts? fall back to whole
            return s,None
        return a,b
    return s,None
def indfam(s):
    if s is None: return None
    s=norm(s)
    am=list(re.finditer(r'\$\s?([\d,]+(?:\.\d+)?)',s))
    if not am: return None
    ind=None; fam=None
    for m in am:
        after=s[m.end():m.end()+22].lower().replace('family individual','individual'); before=s[max(0,m.start()-14):m.start()].lower()
        v=money(m.group(1))
        isfam=bool(re.match(r'\s*(/|per|for an?|for the|each)?\s*(family|fam\b)(?!\s*:?\s*\$)',after)) or (bool(re.search(r'family\s*:?\s*$',before)) and not re.match(r'\s*(/|per)?\s*(individual|person|member|single)',after))
        if isfam:
            if fam is None: fam=v
        else:
            if ind is None: ind=v
            elif fam is None and not re.match(r'\s*(/|per)?\s*(individual|person|member|single|self)',after): fam=v
    if ind is None: ind=fam; fam=None
    return dict(individual=ind,family=fam)
def qrow(md,pat):
    for cells,ln in rows(md):
        if cells and re.search(pat,cells[0],re.I) and len(cells)>1 and cells[1].strip('| '): return cells[1].strip('| ')
    return None
def before_list(s):
    if s is None: return []
    s=norm(s)
    if re.match(r'^(no|not applicable|n/a)\b',s,re.I) or re.search(r'(?i)this plan (has|does) not? (have )?(a )?deductible|no deductible',s): return []
    s=re.sub(r'^yes[.,:]?\s*','',s,flags=re.I)
    s=re.sub(r'\s*"?No charge"? means.*$','',s,flags=re.I)
    s=re.sub(r'(and )?those services listed below as "deductible does not apply\.?"','and services listed as "deductible does not apply"',s,flags=re.I)
    if not s: return []
    s=re.sub(r"^(the )?deductible (doesn.t|does not) apply to\s*",'',s,flags=re.I)
    s=re.sub(r'^benefits available with no charge such as\s*','',s,flags=re.I)
    s=re.sub(r'\s*(are|is|will be)\s+covered (in-network )?before you meet( your)?( the)?[\w\- ]{0,20}?deductible.*$','',s,flags=re.I)
    s=re.sub(r'(mental), (behavioral),? (or|and) (substance)',r'\1§ \2§ \3 \4',s,flags=re.I)
    s=re.sub(r'\s*(are|is)\s+covered before (the|your) deductible( is met)?.*$','',s,flags=re.I)
    s=re.sub(r'\s*(are|is)\s+covered before meeting (the|your) deductible.*$','',s,flags=re.I)
    s=re.sub(r'\s*(do not apply|does not apply|don.t apply) (toward|to) (the|your) deductible.*$','',s,flags=re.I)
    s=re.sub(r'\s*(are|is) covered without (a|the) deductible.*$','',s,flags=re.I)
    s=re.sub(r'^the following( services)?( are covered)?[:,]?\s*','',s,flags=re.I).strip(' .')
    if not s or re.match(r'^(see|refer)',s,re.I): return []
    parts=[]; seps=[]; depth=0; cur=''
    i=0
    while i<len(s):
        ch=s[i]
        if ch=='(': depth+=1
        if ch==')': depth-=1
        if depth==0 and (ch==';' or (ch==',' and ';' not in s)) : parts.append(cur); seps.append(','); cur=''; i+=1; continue
        if depth==0 and s[i:i+5].lower()==' and ' and ';' not in s and not cur.endswith('-'): parts.append(cur); seps.append('and'); cur=''; i+=5; continue
        cur+=ch; i+=1
    parts.append(cur)
    out=[re.sub(r'^(and|or)\s+','',x.strip(' .')).strip().replace('§',',') for x in parts]
    merged=[]
    for ix,x in enumerate(out):
        if not x: continue
        if merged and len(x.split())==1 and x[:1].islower() and ix>0 and seps[ix-1]=='and' and not re.match(r'^(and|or)\b',parts[ix].strip()): merged[-1]=merged[-1]+' and '+x
        elif merged and re.fullmatch(r'(?i)tier \d+\w?',merged[-1]) and re.match(r'(?i)tier',x): merged[-1]=merged[-1]+' and '+x
        else: merged.append(x)
    out=merged
    res=[]
    for x in out:
        for y in re.split(r'\.\s+',x):
            y=y.strip(' .')
            y=re.sub(r'(?i)(IHCP referral) (are|is) covered at no (charge|cost)$',r'\1',y)
            m2=re.match(r'(?i)^((?:in-network )?preventive care) or (.+)$',y)
            if m2: res.append(m2.group(1)); y=m2.group(2)
            if not y or re.match(r'(?i)(for more information|see below|copayments|coinsurance|this plan|regardless)',y): continue
            res.append(y)
    return res
def header(md):
    head=md[:4000]
    cut=re.search(r'The Summary of Benefits|\|\s*\**Important Questions|Important Questions\s*\|',head)
    h=norm(head[:cut.start()] if cut else head[:1200],keep_dash=True)
    h=re.sub(r'\|',' | ',h); h=re.sub(r'\s+',' ',h)
    per=None
    m=re.search(r'Coverage Period:?\s*(.+?)\s*(?=Coverage for|Plan Type|\||$|Summary)',h)
    if m: per=m.group(1).strip(' :')
    pt=None
    m=re.search(r'Plan Type\s*:?\s*(HDHP/PPO|HMO|PPO|EPO|POS|HDHP|[A-Z]{2,5})',h) or re.search(r'Plan Type\W{0,6}(HMO|PPO|EPO|POS)\b',norm(md[:4000]))
    if m: pt=m.group(1).strip()
    x=h
    x=re.sub(r'(?i)summary of benefits and coverage\s*:?\s*what this plan covers\s*(&|and)\s*what (you pay for covered services|it costs)','  ',x)
    x=re.sub(r'(?i)coverage period\s*:?\s*(beginning on or after:?)?\s*[\d/ \-–]+\d','  ',x)
    x=re.sub(r'(?i)coverage for\s*:?\s*(all coverage tiers|individual|family|single|self|member|parent|child(ren)?|and|eligible|only|or|\+|&|/|-|,|\s|two person)+',' ',x)
    x=re.sub(r'(?i)\|?\s*plan type\s*:?\s*(HDHP/PPO|HMO|PPO|EPO|POS|HDHP)\b',' ',x)
    x=re.sub(r'\b\d{5}[A-Z]{2}\d{7}(-\d{2})?\b|\(\s*\d{5}[A-Z]{2}\d{7}\s*\)|m-sbc-\S+',' ',x)
    x=re.sub(r'℠\s*\w*','',x); x=re.sub(r'[®™]','',x)
    x=re.split(r'\s+(?=Non-emergency and non-urgent|This plan |The plan )',x)[0]
    x=re.sub(r'This health plan is offered by [^\d]+?(?=\d{5,}|$)',' ',x)
    x=re.sub(r'^\s*\d{6,8}\s*-\s*',' ',x.strip())
    x=re.sub(r'\s+',' ',x).strip(' |:>-#')
    x=re.split(r'\s*\|\s*The Summary of|\s+The Summary of',x)[0]
    x=re.sub(r'(?i)\s*(\|\s*non-grandfathered|spouse, family|subscriber/(family )?dependent(\s*:\s*subscriber/(family )?dependent)?)\s*$','',x).strip(' |:>-#')
    x=re.sub(r'^\d{1,4}\s+(?=[A-Z])','',x)
    return dict(raw=h,period=per,plan_type=pt,rest=x)
