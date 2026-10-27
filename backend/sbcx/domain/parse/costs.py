# Ported from audit_tools/mk.py (the rule-based extractor that produced labels v1.4).
# The rules are kept as they were; only file/path handling changed. Dense legacy style is
# intentional so diffs against the prototype stay readable; see ruff per-file ignores.
import re

from sbcx.domain.parse.cells import ded_flag, parse_cost
from sbcx.domain.parse.textnorm import dejunk, norm

BOIL=re.compile(r"^\s*(none\.?|\*?\s*(may require )?(prior authorization|pre-?authorization|precertification)[^.;]*|you may have to pay for services that aren.t preventive[^.;]*|ask your provider if the services needed are preventive[^.;]*|then check what your plan will pay( for)?|see your contract\*? for details|see below\*?)\s*[.;]?\s*$",re.I)
def clean_note(s):
    if not s: return None
    s=norm(s)
    parts=[x for x in re.split(r'(?<=[.;])\s+',s) if x.strip()]
    keep=[x for x in parts if not BOIL.match(x)]
    s=' '.join(keep).strip()
    if len(s)>150:
        m=[x for x in re.finditer(r'[.;](\s|$)',s) if x.end()<=150]
        s=s[:m[-1].start()+1] if m and m[-1].end()>=40 else s[:147].rsplit(' ',1)[0]+'...'
    return s or None
def cat(name):
    n=name.lower()
    if 'specialty' in n: return 'specialty'
    if re.search(r'non-?\s?preferred\s+brand|brand( name)?( drugs?)?\s*\(?\s*non-?\s?preferred|brand name nonpreferred',n): return 'non_preferred_brand'
    if re.search(r'preferred\s+brand|brand( name)?( drugs?)?\s*\(?\s*preferred',n): return 'preferred_brand'
    if 'generic' in n: return 'generic'
    if re.search(r'^non-?\s?preferred',n): return 'non_preferred_brand'
    if re.search(r'^preferred (drugs|brand)',n): return 'preferred_brand'
    return 'other'
LBL=re.compile(r'\s+(?=(?:Tier \d|Generic|Preferred|Non-?\s?Preferred|Brand|Specialty|Value|Low Cost|Typically|Preventive|Other generic|Select|Insulin)\b)',re.I)
def split_names(t):
    t=t.strip(' /')
    out=[]; last=0
    for m in LBL.finditer(t):
        pre=t[:m.start()]
        if pre.count('(')>pre.count(')'): continue
        if not re.search(r'(?i)(\)|\bdrugs?|\btier|\btier \d\w?|\bmedications?)$',pre.strip()): continue
        seg=t[last:m.start()].strip()
        if re.fullmatch(r'(?i)tier \d\w?',seg) and not re.match(r'(?i)tier',t[m.end():]): continue
        out.append(seg); last=m.end()
    out.append(t[last:].strip())
    return [x for x in out if x]
def pick(cells,j,hdr,svc=True,nonihcp_oon=False):
    kinds=(hdr or {}).get('kinds'); hc=(hdr or {}).get('cells')
    if kinds and any(k in kinds for k in ('in','nonihcp','oon')):
        hs=next((i for i,c in enumerate(hc) if 'services you may need' in c.lower()),1)
        kinds=list(kinds)
        hs0=next((i for i,c in enumerate(hc) if 'services you may need' in c.lower()),1)
        pcs=[i for i,k in enumerate(kinds) if k in('in','nonihcp','oon')]
        if 'nonihcp' in kinds and len([i for i,k in enumerate(kinds) if k]) >=3:
            kinds=['in' if k=='nonihcp' else k for k in kinds]
        if 'oon' not in kinds and len([k for k in kinds if k in('in',)])>=2:
            last=max(i for i,k in enumerate(kinds) if k=='in')
            if re.search(r'pay the most',hc[last],re.I): kinds[last]='oon'
        if 'oon' not in kinds and 'in' in kinds and 'nonihcp' not in kinds:
            fi=kinds.index('in')
            if fi+1<len(kinds) and kinds[fi+1] is None and fi+1<len(hc)-1 and not re.search(r'limitation|important|exception',hc[fi+1],re.I): kinds[fi+1]='oon'
        ins=[i for i,k in enumerate(kinds) if k=='in']; oons=[i for i,k in enumerate(kinds) if k=='oon']
        if not ins and 'ihcp' in kinds and 'nonihcp' not in kinds:
            ins=[i for i,k in enumerate(kinds) if k=='ihcp']
        if 'nonihcp' in kinds and not ins:
            # IHCP | Non-IHCP only: IHCP column is the in-network price; Non-IHCP counts as out-of-network only when it says Not Covered
            ins=[i for i,k in enumerate(kinds) if k=='ihcp']; ni=kinds.index('nonihcp')
            v=cells[ni-hs+j] if 0<=ni-hs+j<len(cells) else ''
            oons=[ni] if nonihcp_oon else []
        if svc and len(ins)>1:
            v=cells[ins[0]-hs+j] if 0<=ins[0]-hs+j<len(cells) else ''
            if re.match(r'^(not applicable|n/?a)\b',v,re.I): ins=ins[1:]
        pc=[i for i,k in enumerate(kinds) if k]
        ii=ins[0]-hs+j if ins else None; oo=oons[0]-hs+j if oons else None
        li=(max(pc)+1-hs+j) if pc else None
    else:
        ii=j+1; oo=j+2 if len(cells)>=j+4 else None; li=j+3 if oo else j+2
    g=lambda i: cells[i] if i is not None and 0<=i<len(cells) else ''
    return g(ii),(g(oo) if oo is not None else None),g(li)
KEEP=re.compile(r'(?i)\b(limit|limited|maximum|max\b|visits?\b|days?\b|lifetime|per admission|per pregnancy|waived|first \d|one (exam|pair)|\d+ (visits|days|exams?|pairs?|sessions)|copay|coinsurance|\$\d|\d+%|every \d+ months|up to age|through age|under age|age \d+)')
DROP=re.compile(r'(?i)(preauthori|pre-? ?authori|prior authori|precertif|you may have to pay|ask your provider|check what your plan|see your (contract|policy|benefit|plan|certificate)|refer to|for more information|call \d|www\.|http|balance.?bill|charges more than the allowed|cost sharing waived at non-? ?ihcp|cost.sharing does not apply (for|to) preventive|depending on the type of service|maternity care may include|failure to obtain|^none\.?$|may result in)')
def lim_note(lim):
    if not lim: return None
    t=norm(lim).strip()
    t=re.sub(r'[−-]{3,}\s*none\s*[−-]{3,}','',t,flags=re.I).strip()
    if not t: return None
    sents=[x.strip() for x in re.split(r'(?<=[.;])\s+',t) if x.strip()]
    keep=[]
    for i,x in enumerate(sents):
        if DROP.search(x) or not KEEP.search(x): continue
        if not re.match(r'^[A-Z0-9$*(]',x): continue
        if i==len(sents)-1 and not re.search(r'[.;)%\d]$',x) and len(x)>60: continue
        keep.append(x.rstrip(';'))
    return ' '.join(keep) or None
def cost(txt,lim=None,svc=True,noteless=False):
    txt=dejunk(txt); lim=dejunk(lim) if lim else lim
    if txt and re.search(r'reimburse',txt,re.I) and not re.match(r'^\s*(not covered|no charge)',txt,re.I):
        return dict(covered=True,copay=None,coinsurance_pct=None,deductible_applies=None,note=clean_note(txt))
    c,extra=parse_cost(txt or '',labrule=svc)
    if c is None: return None
    if not c['covered']: return c
    if c['copay'] and c['coinsurance_pct']==0: c['coinsurance_pct']=None
    elif c['coinsurance_pct'] and c['copay']==0: c['copay']=None
    elif c['copay']==0 and c['coinsurance_pct'] is None: c['coinsurance_pct']=0.0
    ex=None
    if extra:
        ex=extra.strip(' .;,')
        ex=re.sub(r'(?i)^(/\s*|per\s+)?(visit|admission|stay|prescription)\b(?!\s*\d)[.,;:]?\s*','',ex).strip(' .;,')
        ex=re.sub(r'(?i)^(,\s*)?deductible (does not apply|doesn.t apply|applies)[.;,]?\s*','',ex).strip(' .;,')
        if re.match(r'(?i)^(deductible|ded\b)',ex) and len(ex)<40: ex=None
        if not ex: ex=None
        if ex and re.search(r'(?i)(home delivery|mail order|mail-order|90.day)',ex) and not svc: ex=None
    note=' '.join(x for x in [ex+'.' if ex else '', (lim_note(lim) if not noteless else '') or ''] if x).strip()
    c['note']=clean_note(note)
    if c['deductible_applies'] is None and lim:
        for sent in re.split(r'(?<=[.;])\s*',norm(lim)):
            if re.search(r'(?i)preventive|may apply|if (a|the) deductible',sent): continue
            oonw=re.search(r'(?i)out.of.network|non.?participating|non.?network',sent); inw=re.search(r'(?i)in.?network|network provider|participating',sent.replace('out-of-network','').replace('Out-of-network',''))
            if noteless and inw and not oonw: continue
            if not noteless and oonw and not inw: continue
            mc=re.search(r'(?i)coinsurance',sent); mp=re.search(r'(?i)copay',sent)
            if mc and not mp and c['copay'] is not None and c['coinsurance_pct'] is None: continue
            if mp and not mc and c['coinsurance_pct'] is not None and c['copay'] is None: continue
            if re.search(r'(?i)(coinsurance|copay|copayment|cost.?shar\w*|charges?|benefits?)[^.;]{0,40}(after|subject to)[^.;]{0,20}deductible|deductible[^.;]{0,30}(does not apply|waived|applies)|not subject to[^.;]{0,15}deductible|deductible[^.;]{0,60}before\s*(copays?|coinsurance)',sent):
                f=ded_flag(sent)
                if f is not None: c['deductible_applies']=f; break
    return c
