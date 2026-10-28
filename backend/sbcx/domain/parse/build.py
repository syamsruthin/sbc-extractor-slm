# Ported from audit_tools/mk.py (the rule-based extractor that produced labels v1.4).
# The rules are kept as they were; only file/path handling changed. Dense legacy style is
# intentional so diffs against the prototype stay readable; see ruff per-file ignores.
import re

from sbcx.domain.parse.anchors import extract
from sbcx.domain.parse.costs import cat, cost, pick, split_names
from sbcx.domain.parse.textnorm import SVK

# header residue that is only coverage-tier words ("Individual and Family ndividual and Family"), audit 2026-10-28
COVERAGE_ONLY=re.compile(r'(?i)[\s:|]*((individual|ndividual|family|and|only|self|employee|spouse|children|child|&|\+|/|,)[\s:|]*)*')
def plan_name(rest,issuer):
    x=rest
    if issuer:
        # issuer glued to the front (logo text), e.g. "WellpointWellpoint Essential ..."
        key=re.sub(r'[^a-z]','',issuer.lower())
        letters=''; cut=0
        for i,ch in enumerate(x):
            if ch.isalpha(): letters+=ch.lower()
            if letters==key: cut=i+1; break
            if not key.startswith(letters): break
        if cut: x=x[cut:].strip(' :-')
    x=x.strip(' .:-')
    m=re.match(r'^([^:]{2,80}?)\s*:\s*(?=\S)',x)
    if m and len(x[m.end():].split())<=2: x=x[:m.start(1)+len(m.group(1))]+' '+x[m.end():]
    elif m and not COVERAGE_ONLY.fullmatch(x[m.end():]) and re.search(r'(?i)health|plan|insurance|inc\b|co-op|company|blue|bcbs|octave|communitycare|harbor|cigna|moda|antidote|sendero|mclaren|providence|regence|bridgespan|premera|imperial|utah',m.group(1)) and not re.search(r'(?i)network\s*[-–]?$',m.group(1)):
        x=x[m.end():]
    x=re.sub(r'\s+[-–]\s+:\s+',' – ',x)
    return x.strip(' :|-.') or None
def spans_both(i,oo,ci):
    """An in-network price printed across both network columns leaves the out-of-network cell blank (the
    SBC template never leaves a price cell blank; it says "Not covered" or gives a price). Audit 2026-10-27."""
    return oo is not None and not oo.strip() and bool(i and i.strip()) and bool(ci and ci['covered']) and (ci['copay'] is not None or ci['coinsurance_pct'] is not None)
def tier_prices_split(price_cells,n):
    """True when some price cell lists one price per tier name (so the names can be split per tier)."""
    for c in price_cells:
        st=[m.start() for m in re.finditer(r'(no charge|not covered|\$\d|\d+(\.\d+)?\s?%|covered as in|not applicable)',c,re.I)]
        st=[x for idx,x in enumerate(st) if idx==0 or not re.search(r'(then|and|\bor|\+|plus|after|copay|copayment|,|/|per)\s*$',c[:x].rstrip(),re.I)]
        if len(st)==n or (len(st)==2*n and re.search(r'(?i)mail|retail|90.day',c)): return True
    return False
def resolve_issuer(rest,issuer_id=None,issuer_hint=None,brands=None,page1_text=''):
    """Issuer brand. Prototype order: known brand for the HIOS issuer id (from reviewed labels),
    then the SBC header, then the CMS issuer name (catalog hint)."""
    iss=(brands or {}).get(issuer_id) if issuer_id else None
    if not iss:
        m=re.match(r'^([^:]{3,70}?(Inc\.?|Company|Plan|Plans|Health|Insurance|Co-Op|of [A-Z][a-z]+(?: [A-Z][a-z]+)?))\s*:',rest)
        iss=m.group(1).strip() if m else None
    if not iss:
        m2=re.match(r'^([^:]{2,60}?)\s*:\s*\S',rest)
        if m2 and len(m2.group(1).split())<=8:
            iss=m2.group(1).strip()
            mi=issuer_hint or ''
            if mi and iss.lower().startswith(mi.lower()) and len(iss)>len(mi): iss=mi
    if not iss: iss=issuer_hint or None
    if iss and iss.startswith('UnitedHealthcare'):
        # UHC SBCs name the legal issuer in the page-1 footer; the family-level guess is often another state's entity
        mf=re.search(r'(UnitedHealthcare[A-Za-z ,.]*?(Inc\.|Company))',page1_text or '')
        if mf: iss=mf.group(1).strip()
    return iss
def build(md,excluded=None,issuer_id=None,issuer_hint=None,brands=None,page1_text=''):
    """One layout view -> label dict in the v1 shape (+ '_o' raw extract and '_src' chosen cells)."""
    o=extract(md); hdr=o['_hdr']
    iss=resolve_issuer(o['_rest'],issuer_id,issuer_hint,brands,page1_text)
    d=dict(plan_name=plan_name(o['_rest'],iss),issuer=iss,plan_type=o['plan_type'],coverage_period=o['coverage_period'],
        deductible=o['deductible'],out_of_pocket_limit=o['out_of_pocket_limit'],
        services_before_deductible=o['services_before_deductible'],referral_required_for_specialist=o['referral_required_for_specialist'],
        services={},drug_tiers=[],excluded_services=[])
    # IHCP | Non-IHCP tables: the Non-IHCP column is used as out-of-network only when it mostly says Not Covered
    nn=0; nt=0
    for r in o['_svc'].values():
        h=r.get('hdr') or hdr
        if h and h.get('kinds') and 'nonihcp' in h['kinds'] and len([k for k in h['kinds'] if k])==2:
            hs=next((i for i,c in enumerate(h['cells']) if 'services you may need' in c.lower()),1)
            i=h['kinds'].index('nonihcp')-hs+r['j']
            if 0<=i<len(r['cells']): nt+=1; nn+=bool(re.match(r'^not covered',r['cells'][i],re.I))
    nonihcp_oon= nt>0 and nn/nt>=0.5
    src={}
    for k in SVK:
        r=o['_svc'].get(k)
        if not r: d['services'][k]=dict(in_network=None,out_of_network=None); continue
        cells=list(r['cells'])
        for c2 in r.get('cont',[]):
            if not c2[r['j']] if r['j']<len(c2) else True:
                for i in range(min(len(cells),len(c2))):
                    if c2[i] and i>r['j']: cells[i]=(cells[i]+' '+c2[i]).strip()
        i,oo,lim=pick(cells,r['j'],r.get('hdr') or hdr,nonihcp_oon=nonihcp_oon)
        src[k]=(i,oo,lim)
        ci=cost(i,lim); co=(cost(oo,lim,noteless=True) if oo is not None else None)
        if spans_both(i,oo,ci): co=dict(ci,note=None); d.setdefault('_spans',[]).append(k)
        if oo and re.search(r'covered as (an )?in-? ?network',oo,re.I) and ci: co=dict(ci,note=None)
        d['services'][k]=dict(in_network=ci,out_of_network=co)
    drows=[]
    dl=[dict(x) for x in o['_drugs']]
    for a,b in zip(dl,dl[1:]):
        bj=b['j']
        nxtc=b['cells'][bj+1] if bj+1<len(b['cells']) else ''
        if re.match(r'(?i)^(copay|copayment|coinsurance|per |/)',nxtc) and a.get('cont'):
            frag=[c for c2 in a['cont'] for c in c2 if c and re.search(r'\$\d|\d%',c)]
            if frag:
                b['cells']=list(b['cells']); b['cells'][bj+1]=frag[-1]+' '+nxtc
                a['cont']=[c2 for c2 in a['cont'] if not any(c in frag for c in c2)]
    for r in dl:
        cells=list(r['cells']); j=r['j']
        # "Generic | Tier 1" written with a literal pipe: re-join the label
        if j+1<len(cells) and re.match(r'(?i)^tier \d\w?$',cells[j+1]) :
            cells=cells[:j]+[cells[j]+' | '+cells[j+1]]+cells[j+2:]; r=dict(r,name=cells[j])
        for c2 in r.get('cont',[]):
            if c2 and j<len(c2) and c2[j] and re.match(r'(?i)^(facility|physician|if you)',c2[j]): break
            for i in range(min(len(cells),len(c2))):
                if c2[i] and i>j: cells[i]=(cells[i]+' '+c2[i]).strip()
        names=split_names(cells[j])
        if len(names)>1 and not tier_prices_split(cells[j+1:],len(names)):
            # several tier names sharing one price ("Tier 1 Preferred Generic / Tier 2 Non-Preferred Generic | $10"): one tier
            names=[cells[j]]
        if len(names)>1:
            n=len(names); parts=[[] for _ in range(n)]
            ok=True
            for i,c in enumerate(cells):
                if i<j:
                    for q in range(n): parts[q].append(c)
                    continue
                if i==j:
                    for q in range(n): parts[q].append(names[q])
                    continue
                st=[m.start() for m in re.finditer(r'(no charge|not covered|\$\d|\d+(\.\d+)?\s?%|covered as in|not applicable)',c,re.I)]
                st=[x for idx,x in enumerate(st) if idx==0 or not re.search(r'(then|and|\bor|\+|plus|after|copay|copayment|,|/|per)\s*$',c[:x].rstrip(),re.I)]
                if len(st)==2*n and n>1 and re.search(r'(?i)mail|retail|90.day',c): st=st[::2]
                if len(st)==n:
                    b=st[1:]+[len(c)]
                    for q in range(n): parts[q].append(c[(0 if q==0 else st[q]):b[q]].strip())
                elif not st:
                    for q in range(n): parts[q].append(c if q==0 else '')
                else:
                    for q in range(n): parts[q].append(c)
            for q in range(n): drows.append((dict(r,name=names[q]),parts[q]))
        else: drows.append((r,cells))
    for r,cells in drows:
        i,oo,lim=pick(cells,r['j'],r.get('hdr') or hdr,svc=False,nonihcp_oon=nonihcp_oon)
        ci=cost(i,lim,svc=False) ; co=cost(oo,lim,svc=False,noteless=True) if oo is not None else None
        if spans_both(i,oo,ci): co=dict(ci,note=None)
        if ci is None: continue
        src['t%d'%(len(d['drug_tiers'])+1)]=(i,oo,lim)
        d['drug_tiers'].append(dict(name=r['name'],category=cat(r['name']),retail=dict(in_network=ci,out_of_network=co)))
    d['excluded_services']=list(excluded or [])
    d['_o']=o; d['_src']=src
    return d
