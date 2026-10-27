# Ported from audit_tools/ext.py (the rule-based extractor that produced labels v1.4).
# The rules are kept as they were; only file/path handling changed. Dense legacy style is
# intentional so diffs against the prototype stay readable; see ruff per-file ignores.
import re

from sbcx.domain.parse.cells import PRICE
from sbcx.domain.parse.questions import before_list, header, indfam, qrow, split_net
from sbcx.domain.parse.textnorm import SV, norm, rows


def extract(md):
    """Rows of one layout view (markdown or pdfplumber tables as pipe rows) -> raw services, drugs, page-1 answers."""
    md0=md
    out={}
    hd=header(md)
    out['coverage_period']=hd['period']
    m=re.search(r'Coverage Period:?\**\s*\**\s*((?:Beginning on or after:?\s*)?\d{1,2}/\d{1,2}/\d{4}(?:\s*[-–—]?\s*\d{1,2}\s*\**\s*/\s*\**\s*\d{1,2}\s*/\s*\d{4})?)',md[:3000].replace('**',''),re.I)
    if m: out['coverage_period']=re.sub(r'\s+',' ',m.group(1)).strip()
    out['plan_type']=hd['plan_type']; out['_head']=hd['raw'][:400]; out['_rest']=hd['rest']
    ded=qrow(md,r'overall\s*deductible'); oop=qrow(md,r'what is\s*the\s*(maximum\s*)?out.{0,4}of.{0,4}pocket\s*limit'); bef=qrow(md,r'covered before you meet|before you meet'); ref=qrow(md,r'referral')
    flat=norm(md)
    if ref is None:
        m=re.search(r'referral to see a\s*specialist\??\s*(yes|no)\b',flat,re.I) or re.search(r'need a referral\s*(?:to see a specialist\??)?\s*(yes|no)\b',flat,re.I); ref=m.group(1) if m else None
        if ref is None:
            if re.search(r'see the specialist you choose without a referral',flat,re.I): ref='No'
            elif re.search(r'specialist[^.]{0,80}only if you have a referral',flat,re.I): ref='Yes'
    if oop is None:
        m=re.search(r'out-of-pocket limit for this plan\??\s*(.{0,200}?)(?=the out-of-pocket limit is|$)',flat,re.I); oop=m.group(1) if m else None
    if ded is None:
        m=re.search(r'overall deductible\??\s*(.{0,200}?)(?=generally,|$)',flat,re.I); ded=m.group(1) if m else None
    def net(s):
        if s is None: return None,None
        i,o=split_net(s); return indfam(i),indfam(o)
    di,do=net(ded); oi,oo=net(oop)
    out['deductible']=dict(in_network=di,out_of_network=do)
    out['out_of_pocket_limit']=dict(in_network=oi,out_of_network=oo)
    out['services_before_deductible']=before_list(bef)
    out['referral_required_for_specialist']=None if ref is None else bool(re.match(r'yes',norm(ref),re.I))
    out['_q']=dict(ded=ded and norm(ded),oop=oop and norm(oop),bef=bef and norm(bef),ref=ref and norm(ref))
    # ---- service table
    R=list(rows(md))
    hdr={}; k=0; svc={}; drugs=[]; mode='pre'; last=None
    kinds=None
    def colkinds(hrow):
        ks=[]
        for c in hrow:
            cl=c.lower()
            if re.search(r'services you may need|common medical|^$|limitation|important information|exceptions',cl): ks.append(None); continue
            if re.search(r'(ihcp\)?|provider) (and|or) non-? ?ihcp',cl): ks.append('in'); continue
            if re.search(r'non-? ?ihcp|\bnihcp|on-? ?ihcp',cl):
                ks.append('oon' if re.search(r'of-? ?network|non[- ]network|ut-? ?o',cl) and not re.search(r'pay more',cl) else ('in' if re.search(r'in-? ?network|pay more',cl) else 'nonihcp')); continue
            if re.search(r'indian health|ihcp|ihs provider|\bihs\b',cl): ks.append('ihcp'); continue
            if re.search(r'pay the least|pay more',cl): ks.append('in'); continue
            if re.search(r'pay the most',cl): ks.append('oon'); continue
            if re.search(r'of-? ?network|non-?\s*network|non-?\s*participating|non-?\s*par\b|out of area',cl): ks.append('oon'); continue
            if re.search(r'network|provider|pharmacy|tier|level|you will pay|participating|preferred',cl): ks.append('in'); continue
            ks.append(None)
        return ks
    pending_hdr=[]
    pend=None
    PR=re.compile(r'\$|%|no charge|not covered|covered|n/a|not applicable|copay',re.I)
    for cells,ln in R:
        joined=' '.join(cells).lower()
        if cells and re.match(r'^(what|are|do|will|is|does|can)\b.*\?$',cells[0],re.I) and re.search(r'(?i)\byou|\bplan\b|deductible|specialist|limit',cells[0]) and not re.search(r'(?i)http|www',cells[0]): continue
        if 'this plan uses a provider network' in joined or 'will you pay less' in joined: continue
        if pend is not None:
            pc,pj,pk=pend; pend=None
            if any(PR.search(x) for x in cells[pj+1:pj+4]) and not any(re.search(SV[x][1],(cells[pj] if pj<len(cells) else '').lower()) for x in range(pk+1,min(pk+3,len(SV)))):
                n=max(len(pc),len(cells))
                cells=[((pc[i] if i<len(pc) else '')+' '+(cells[i] if i<len(cells) else '')).strip() for i in range(n)]
                joined=' '.join(cells).lower()
        if ('services you may need' in joined or ('provider' in joined and 'you will pay the' in joined) or (re.search(r'what you will pay|ihs provider|indian health|network provider|ihcp\)',joined) and not re.search(r'\$\d|\d%|no charge|not covered',joined))) and (max(len(c) for c in cells)<90 or 'services you may need' in joined):
            pending_hdr.append(cells)
            HW=re.compile(r'(common medical event|services you may need|what you will pay|limitations,? exceptions,? (&|and) other important information|(non-ihcp )?(indian health care )?(in-? ?|out-? ?of-? ?)?(network )?provider( \(ihcp\))? \((you )?will pay (the )?(least|more|most)\)|indian health care provider \(ihcp\))',re.I)
            cut=[re.sub(r'\s+',' ',HW.sub(' ',c)).strip() for c in cells]
            if mode!='done' and k<len(SV) and any(re.search(SV[kk][1],c.lower()) for c in cut[:3] for kk in range(k,min(k+2,len(SV)))):
                cells=cut
            else: continue
        # find service
        hit=None
        if cells and re.match(r'^(what|are|do|will|is|does|can)\b.*\?$',cells[0],re.I) and re.search(r'(?i)\byou|\bplan\b|deductible|specialist|limit',cells[0]) and not re.search(r'(?i)http|www',cells[0]): continue
        if mode!='done':
            for j,c in enumerate(cells[:5]):
                cl=c.lower()
                if not cl or len(cl)>(110 if j<3 else 60) or re.match(r'(what|are|do|will|is|does|can) ',cl): continue
                ev=cl.startswith('if you')
                if SV[k][0] in ('childbirth_professional','childbirth_facility') and re.fullmatch(r'childbirth\s*/\s*delivery',cl) and any(re.search(r'\$|%|no charge|not covered',x,re.I) for x in cells[j+1:j+3]):
                    hit=(j,k); break
                for kk in range(k,min(k+(1 if ev else 3),len(SV))):
                    if ((kk==k and re.search(SV[kk][1],cl)) or (kk>k and len(cl)<70 and re.match(SV[kk][1].replace('^',''),cl))):
                        if any(PR.search(x) for x in cells[j+1:j+4]): hit=(j,kk); break
                        elif kk==k and not ev and not any(cells[j+1:]): pend=(cells,j,kk)
                if hit or pend: break
            if pend and not hit: continue
        if hit:
            j,kk=hit
            if cells[j].lower().startswith('if you'):
                m=re.search(SV[kk][1],cells[j].lower()); cells=list(cells); cells[j]=cells[j][m.start():] if m else cells[j]
            if j>=3:
                pre=[c for c in cells[:j] if c and not c.lower().startswith('if you')]
                cells=['',cells[j],(' '.join(pre)+' '+(cells[j+1] if j+1<len(cells) else '')).strip()]+list(cells[j+2:]); j=1
            if pending_hdr:
                # merge header rows column-wise
                n=max(len(h) for h in pending_hdr); merged=[' '.join(h[i] if i<len(h) else '' for h in pending_hdr) for i in range(n)]
                kinds=colkinds(merged)
                if hdr and hdr.get('kinds') and len(hdr['kinds'])==len(kinds) and 'oon' in hdr['kinds'] and 'oon' not in kinds and 'nonihcp' not in kinds:
                    kinds=list(hdr['kinds']); merged=list(hdr['cells'])
                hdr=dict(cells=merged,kinds=kinds); pending_hdr=[]
            svc[SV[kk][0]]=dict(cells=cells,j=j,hdr=hdr,ln=ln)
            # several services packed into one row: find successive service names in the service cell
            sc=cells[j].lower(); seq=[kk]; pos=0
            m0=re.search(SV[kk][1],sc); pos=m0.end() if m0 else 0
            while seq[-1]+1<len(SV):
                nk=seq[-1]+1; m=re.search(SV[nk][1].replace('^',''),sc[pos:])
                if not m: break
                if nk in(SV.index(('outpatient_surgeon_fee',SV[6][1])),) and False: break
                seq.append(nk); pos+=m.end()
            if len(seq)>1:
                n=len(seq); parts=[[] for _ in range(n)]
                for i,c in enumerate(cells):
                    if i<=j:
                        for q in range(n): parts[q].append(c)
                        continue
                    if i==len(cells)-1 and i>j+1 and not re.match(r'(?i)^\s*(no charge|not covered|\$\d|\d+%)',c):
                        for q in range(n): parts[q].append(c if q==0 else '')
                        continue
                    st=[m.start() for m in re.finditer(r'(no charge|no copay|not covered|\$\d|\d+(\.\d+)?\s?%|covered as in|not applicable)',c,re.I)]
                    # drop starts that follow 'then'/'and'/'+' (same part)
                    st2=[x for idx,x in enumerate(st) if idx==0 or not re.search(r'(then|and|\bor|\+|plus|after|copay|copayment|,)\s*$',c[:x].rstrip(), re.I)]
                    if len(st2)==n:
                        bounds=st2[1:]+[len(c)]
                        for q in range(n): parts[q].append(c[(0 if q==0 else st2[q]):bounds[q]].strip())
                    elif not st:
                        for q in range(n): parts[q].append(c if q==0 else '')
                    else:
                        for q in range(n): parts[q].append(c)
                for q,kq in enumerate(seq):
                    svc[SV[kq][0]]=dict(cells=parts[q],j=j,hdr=hdr,ln=ln,packed=n)
                kk=seq[-1]
            last=('svc',SV[kk][0]); k=kk+1
            if SV[kk][0]=='imaging': mode='drug'
            elif mode=='drug': mode='post'
            if SV[kk][0]=='child_dental_checkup': mode='done'
            continue
        pending_hdr=[] if (pending_hdr and len(pending_hdr)>3) else pending_hdr
        if mode=='drug':
            nonempty=[c for c in cells if c]
            if not nonempty: continue
            # drug row: find label cell
            found=False
            sj=svc['imaging']['j']
            order=[sj]+[x for x in range(5) if x!=sj]
            for j in order:
                if j>=len(cells): continue
                c=cells[j]; cl=c.lower()
                if c and not cl.startswith('if you') and not cl.startswith('more information') and len(c)<(130 if j<3 else 70) and j<len(cells)-1 and any(cells[j+1:]) and not PRICE.match(c) and not re.match(r'^(not covered|no charge|retail|mail|copay)',cl):
                    if re.search(r'drug|tier|generic|brand|specialty|preferred|formulary|preventive|value|insulin|medication',cl) and not re.search(r'^(prescription drug )?coverage is available|www\.|http|^(covers|limited|prior auth)',cl):
                        if j>=3:
                            pre=[x for x in cells[:j] if x and not x.lower().startswith(('if you','more information','prescription drug'))]
                            cells=['',cells[j],(' '.join(pre)+' '+(cells[j+1] if j+1<len(cells) else '')).strip()]+list(cells[j+2:]); j=1; c=cells[1]
                        drugs.append(dict(cells=cells,j=j,hdr=hdr,ln=ln,name=c)); found=True; break
            if not found and drugs:
                drugs[-1].setdefault('cont',[]).append(cells)
            continue
        if last and last[0]=='svc' and mode!='done':
            svc[last[1]].setdefault('cont',[]).append(cells)
    out['_svc']=svc; out['_drugs']=drugs; out['_hdr']=hdr
    return out
