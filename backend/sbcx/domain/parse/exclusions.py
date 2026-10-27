# Ported from audit_tools/excl.py (the rule-based extractor that produced labels v1.4).
# The rules are kept as they were; only file/path handling changed. Dense legacy style is
# intentional so diffs against the prototype stay readable; see ruff per-file ignores.
import re

import pdfplumber

from sbcx.domain.parse.layout import layout_text

BUL=('•','·','','▪','■','●','◼','','','\uf0b7','l','\uf06e','\uf0a7','➢','✓','\uf0d8','o')
def excl_box(pdf_path):
    """Words of the 'Services Your Plan Generally Does NOT Cover' box, with bullet columns."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            res=None; acc=[]
            for pi,pg in enumerate(pdf.pages):
                if acc and pi>acc[-1][0]+1: break
                txt=pg.extract_text() or ''
                if not re.search(r'(Generally\s*)?[Dd]oes\s*NOT\s*Cover',txt): continue
                words=pg.extract_words(keep_blank_chars=False,use_text_flow=False,extra_attrs=['size'])
                # locate header and end
                top=None; bot=pg.height
                ws=words
                for i,w in enumerate(ws):
                    tt=''.join(x['text'] for x in ws[i:i+3]).lower()
                    if tt.startswith('generallydoesnot') or (w['text']=='Does' and tt.startswith('doesnotcover')) or (w['text'].lower().startswith('generally') and 'doesnot' in tt.replace(' ','')):
                        top=w['bottom']
                        # header may wrap: skip lines up to the closing ')' of "(Check your policy ... services.)"
                        for w2 in ws[i:i+60]:
                            if w2['text'].endswith('services.)') or w2['text'].endswith('services)'): top=max(top,w2['bottom']); break
                        break
                if top is None:
                    if not acc: res=dict(page=pi+1,cols=[],words=[])
                    break
                ended=False
                for w in ws:
                    if w['top']>top+2 and re.match(r'Other',w['text']) :
                        # "Other Covered Services"
                        idx=ws.index(w)
                        if idx+1<len(ws) and ws[idx+1]['text'].lower().startswith('covered'): bot=min(bot,w['top']); ended=True; break
                for w in ws:
                    if w['top']>top+2 and w['top']<bot and w['text'].startswith('*') and len(w['text'])>2 and w['x0']<60: bot=w['top']; break
                box=[w for w in ws if w['top']>top-0.5 and w['bottom']<bot-1]
                import collections as _c
                _L=_c.defaultdict(list)
                for w in box: _L[round(w['top'])].append(w)
                for _t in sorted(_L):
                    _txt=' '.join(x['text'] for x in sorted(_L[_t],key=lambda x:x['x0']))
                    if re.search(r'(?i)for more information about limitations|\bPage \d+ of \d+\b|^\d{4}\.\d{5}|^\[?\*\s*For more',_txt): bot=min(bot,_t-1); break
                box=[w for w in box if w['bottom']<bot-1]
                # lines
                box.sort(key=lambda w:(round(w['top']),w['x0']))
                bullets=[w for w in box if (w['text'] in BUL and w['text']!='l' and w['text']!='o') or w['text'][:1] in ('•','','▪','●','\uf0b7')]
                if not bullets:
                    ls=[w for w in box if w['text'] in('l','o')]
                    xs0=[round(w['x0']) for w in ls]
                    if len(ls)>=3: bullets=[w for w in ls if xs0.count(round(w['x0']))>=2]
                xs=sorted(set(round(w['x0']) for w in bullets))
                cols=[]
                for x in xs:
                    if not cols or x-cols[-1]>40: cols.append(x)
                W=[(w['text'],round(w['x0'],1),round(w['top']+1000*len(acc),1)) for w in box]
                acc.append((pi,cols,W))
                if ended or not W: break
                continue
            if acc:
                allc=sorted(set(c for _,cs,_ in acc for c in cs)); cols=[]
                for x in allc:
                    if not cols or x-cols[-1]>40: cols.append(x)
                res=dict(page=acc[0][0]+1,cols=cols,words=[w for _,_,W in acc for w in W])
        return res
    except Exception: return None
def isbul(t): return t in BUL or t[:1] in ('•','','▪','●','\uf0b7')
CONN=r'(,|\bor|\band|\bthe|\bof|\bfor|\bin|\bwhen|\bto|\bas|\bwith|\bexcept|-|\()$'
def layout_items(p,page):
    t=layout_text(p,page,page+1).replace('\f','\n').split('\n')
    i0=next((i for i,l in enumerate(t) if re.search(r'[Dd]oes\s+NOT\s+Cover',l)),None)
    if i0 is None: return None
    i=i0
    while i<len(t) and not re.search(r'services\.?\)',t[i]): i+=1
    if i-i0>3: i=i0
    L=[]
    for l in t[i+1:]:
        if re.match(r'\s*Other\s+Covered',l) or re.match(r'\s*\*',l): break
        if re.search(r'(?i)for more information about limitations|page \d+ of \d+\s*$|^\s*\*?\s*for more information',l) or re.match(r'(?i)\s*(summary of benefits|coverage period)',l): continue
        L.append(l.rstrip())
    while L and not L[-1].strip(): L.pop()
    L=[l for l in L if l.strip()]
    if not L: return None
    W=max(len(l) for l in L); L=[l.ljust(W) for l in L]
    blank=[all(l[c]==' ' for l in L) for c in range(W)]
    # column starts: non-blank after >=2 blanks
    starts=[];c=0
    while c<W:
        if not blank[c] and (c==0 or (c>=2 and blank[c-1] and blank[c-2]) or not starts):
            starts.append(c)
        c+=1
    # merge starts too close (gap <2 blank cols means same column)
    cols=[];
    for s0 in starts:
        if cols and not any(blank[x] and blank[x-1] for x in range(cols[-1]+1,s0)): continue
        cols.append(s0)
    bp=sorted(m.start() for l in L for m in re.finditer(r'[•▪●\uf0b7]',l))
    if bp:
        bc=[]
        for x in bp:
            if bc and x-bc[-1][-1]<=3: bc[-1].append(x)
            else: bc.append([x])
        bc=[min(g) for g in bc if len(g)>=2]
        if len(bc)>=2: cols=[0]+bc[1:] if bc[0]>0 else bc
    out=[]
    for k,s0 in enumerate(cols):
        e=cols[k+1] if k+1<len(cols) else W
        its=[]
        for l in L:
            txt=re.sub(r'^([•▪●\uf0b7]|[lo](?=\s))\s*','',l[s0:e].strip()).strip()
            if not txt: continue
            if not its or (txt[:1].isupper() and not re.search(CONN,its[-1])): its.append(txt)
            else: its[-1]+=' '+txt
        out+=its
    res=[]
    for it in out:
        it=re.sub(r'\s+',' ',it).strip(' .;').replace('’',"'").rstrip('*').strip(); it=re.sub(r'(?i)\s*(\*?\s*for more information[^.]*?,\s*)?see the plan or policy document at \S+.*$','',it).strip(' .;'); it=re.sub(r'(?i)\s*(\[?\*\s*|\b\d{4}\.\d{5}\w+[^ ]*\s*(-\S+\s*)?|\bCHPLA\w+\s+MC\d+\s*(\[?\*\s*)?)?(For more|$) information about.*$','',it); it=re.sub(r'\s+CHPLA\w+\s+MC\d+$','',it); it=re.sub(r'\s*(documents?/\S*|(document )?at www\.\S+)?\s*Page \d+ of \d+$','',it).strip(' .;'); it=re.sub(r'\b(in|out-of)- network','\\1-network',it)
        if it.endswith('U.S'): it+='.'
        if it and not re.fullmatch(r'([lo•▪●\uf0b7]\s*)+',it): res.append(it)
    return res
def items(r,p):
    """Box words (excl_box) -> excluded service names, read column by column. p = PDF path."""
    if not r: return []
    pages=sorted(set(int(y//1000) for t,x,y in r['words']))
    if len(pages)>1 and r['cols']:
        out=[]
        for k in pages: out+=_items(dict(r,words=[w for w in r['words'] if int(w[2]//1000)==k]),p)
        return out
    return _items(r,p)
def _items(r,p):
    words=r['words']; cols=r['cols']
    nob=not cols
    if nob:
        li=layout_items(p,r['page'])
        if li: return li
    if nob:
        xs=sorted(set(round(x) for t,x,y in words))
        cols=[]
        for x in xs:
            if not cols or x-cols[-1]>60: cols.append(x)
    def col(x):
        c=0
        for i,cx in enumerate(cols):
            if x>=cx-6: c=i
        return c
    per=[]
    for ci in range(len(cols)):
        ws=sorted([(y,x,t) for t,x,y in words if col(x)==ci])
        # cluster into lines by y (tolerance 3.5)
        lines=[]
        for y,x,t in ws:
            if lines and abs(y-lines[-1][0])<=3.5: lines[-1][1].append((x,t))
            else: lines.append([y,[(x,t)]])
        its=[]
        for y,lw in lines:
            lw.sort(); toks=[t for x,t in lw]
            newitem=isbul(toks[0]) and not nob
            if not nob and toks[0] in('l','o') and len(toks)>1 and not toks[1][:1].isupper(): newitem=False
            txt=' '.join(t for t in (toks[1:] if newitem else toks)).strip()
            txt=txt.lstrip('•▪● \uf0b7').strip()
            if not txt: 
                if newitem: its.append('')
                continue
            if nob:
                newitem=(not its) or (txt[:1].isupper() and not re.search(r'(,|\bor|\band|\bthe|\bof|\bfor|\bin|\bwhen|\bto|-|\()$',its[-1]))
            if newitem or not its: its.append(txt)
            else: its[-1]=(its[-1]+' '+txt).strip()
        per.append(its)
    out=[]
    for c in per:
        for it in c:
            it=re.sub(r'\s+',' ',it).strip(' .;')
            it=it.replace('’',"'").rstrip('*').strip(); it=re.sub(r'(?i)\s*(\*?\s*for more information[^.]*?,\s*)?see the plan or policy document at \S+.*$','',it).strip(' .;'); it=re.sub(r'(?i)\s*(\[?\*\s*|\b\d{4}\.\d{5}\w+[^ ]*\s*(-\S+\s*)?|\bCHPLA\w+\s+MC\d+\s*(\[?\*\s*)?)?(For more|$) information about.*$','',it); it=re.sub(r'\s+CHPLA\w+\s+MC\d+$','',it); it=re.sub(r'\s*(documents?/\S*|(document )?at www\.\S+)?\s*Page \d+ of \d+$','',it).strip(' .;'); it=re.sub(r'\b(in|out-of)- network','\\1-network',it)
            if it.endswith('U.S'): it+='.'
            if it: out.append(it)
    return out
