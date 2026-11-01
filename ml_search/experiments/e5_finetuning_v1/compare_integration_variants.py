"""Offline comparison of integration strategies using saved rankings only."""
from pathlib import Path
from collections import defaultdict
import json,math,hashlib,re
import numpy as np
from ml_search.text import normalize_text,tokenize,similarity

ROOT=Path(__file__).parent;OUT=ROOT/'integration_variants_v2';PROJECT=ROOT.parents[2]
COMMON={'хочу','ищу','нужна','нужно','книга','книгу','роман','история','посоветуй','дайте','мне','про','что','нибудь','помню','читать','почитать','автор','часть'}
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def info(s):return [t for t in tokenize(normalize_text(s)) if len(t)>=3 and t not in COMMON]
def token_score(a,b):
    if a==b:return 1.0
    if min(len(a),len(b))>=5 and (a.startswith(b[:max(4,min(len(a),len(b))-2)]) or b.startswith(a[:max(4,min(len(a),len(b))-2)])):return similarity(a,b)
    return similarity(a,b) if min(len(a),len(b))>=4 else 0.0
def title_score(query,title):
    q=info(query);t=info(title)
    if len(q)<2 or len(t)<2:return 0.0
    matched=[];start=0
    for qt in q:
        best=(-1,0.0)
        for j in range(start,len(t)):
            s=token_score(qt,t[j])
            if s>best[1]:best=(j,s)
        if best[1]>=0.74:matched.append(best[1]);start=best[0]+1
    if len(matched)<2:return 0.0
    qcov=len(matched)/len(q);tcov=len(matched)/len(t);quality=sum(matched)/len(matched)
    return quality*(0.68*qcov+0.32*tcov)
def resolver(query,books):
    scored=sorted(((title_score(query,b['title']),b['id'],b['title']) for b in books),reverse=True)
    first,second=scored[0],scored[1]
    margin=first[0]-second[0]
    if (first[0]>=0.80 and margin>=0.045) or (first[0]>=0.66 and margin>=0.12):return {'catalog_id':first[1],'title':first[2],'score':first[0],'margin':margin}
    return None
def prepend(ids,r):return ([r['catalog_id']]+[i for i in ids if i!=r['catalog_id']])[:10] if r else ids
def rrf(a,b,new_weight,k=60):
    ids=set(a)|set(b);scores={i:(1/(k+a.index(i)+1) if i in a else 0)+(new_weight/(k+b.index(i)+1) if i in b else 0) for i in ids}
    return sorted(ids,key=lambda i:(scores[i],-i),reverse=True)[:10]
def qmetric(ids,case):
    g={j['catalog_id']:j['grade'] for j in case['judgments']};good={i for i,v in g.items() if v==2};rank=next((n+1 for n,i in enumerate(ids) if i in good),None)
    dcg=sum((2**g.get(i,0)-1)/math.log2(n+2) for n,i in enumerate(ids));ideal=sum((2**v-1)/math.log2(n+2) for n,v in enumerate(sorted(g.values(),reverse=True)[:10]))
    return {'ndcg10':dcg/ideal if ideal else 0,'hit3':int(rank is not None and rank<=3),'hit10':int(rank is not None),'mrr':1/rank if rank else 0}
def family_summary(rows,cases):
    groups=defaultdict(list)
    for r,c in zip(rows,cases):
        if not c['expected_empty']:groups[c['group_id']].append(qmetric(r,c))
    return {k:float(np.mean([np.mean([r[k] for r in rr]) for rr in groups.values()])) for k in ['ndcg10','hit3','hit10','mrr']}
def regmetric(rows,cases,bytitle):
    ranks=[];nav=[]
    for ids,c in zip(rows,cases):
        expected={i for t in c['expected_titles'] for i in bytitle.get(t,[])};rank=next((n+1 for n,i in enumerate(ids) if i in expected),None);ranks.append(rank)
        if c['category'] in {'navigational','partial_title','author_only','typo'}:nav.append({'query':c['query'],'rank':rank})
    return {'hit1':np.mean([r is not None and r<=1 for r in ranks]),'hit3':np.mean([r is not None and r<=3 for r in ranks]),'hit10':np.mean([r is not None for r in ranks]),'navigation':nav}
def main():
    assert not OUT.exists();OUT.mkdir()
    books=read(PROJECT/'data/book_catalog/catalog.json');bytitle=defaultdict(list)
    for b in books:bytitle[b['title']].append(b['id'])
    devcases=read(ROOT/'dev_queries.json');devres=read(ROOT/'comparison/dev-results.json')
    regcases=read(PROJECT/'ml_search/evaluation_queries.json');regres=read(ROOT/'comparison/regression77.json')
    def saved(dataset,name,mode='full'):
        if dataset=='dev':return [r['top_ids'] for r in devres[name][mode]['rows']]
        return [[i for t in r['top_titles'] for i in bytitle[t][:1]][:10] for r in regres[name]['rows']]
    data={}
    for dataset,cases in [('dev',devcases),('reg',regcases)]:
        old=saved(dataset,'original');new=saved(dataset,'selected');resolved=[resolver(c['query'],books) for c in cases]
        variants={'old':old,'new_current':new,'new_entity':[prepend(x,r) for x,r in zip(new,resolved)],'route_old_for_entity':[o if r else n for o,n,r in zip(old,new,resolved)]}
        for w in [1,1.5,2,3,4]:
            variants[f'rrf_new_{w:g}']=[rrf(o,n,w) for o,n in zip(old,new)]
            variants[f'entity_rrf_new_{w:g}']=[prepend(rrf(o,n,w),r) for o,n,r in zip(old,new,resolved)]
        data[dataset]={'cases':cases,'resolved':resolved,'variants':variants}
    metrics={}
    for name in data['dev']['variants']:
        metrics[name]={'dev':family_summary(data['dev']['variants'][name],devcases),'regression77':regmetric(data['reg']['variants'][name],regcases,bytitle)}
    eligible=[n for n,m in metrics.items() if m['regression77']['hit3']>=metrics['old']['regression77']['hit3']-0.02 and m['regression77']['hit10']>=metrics['old']['regression77']['hit10']-0.02]
    selected=max(eligible,key=lambda n:(metrics[n]['dev']['ndcg10'],metrics[n]['dev']['hit3'],metrics[n]['regression77']['hit3']))
    # Evaluate the fixed choice on the already-opened diagnostic test; never use it in selection.
    testcases=read(ROOT/'test_queries.frozen.json');testres=read(ROOT/'comparison/test-results.json');old=[r['top_ids'] for r in testres['original']['full']['rows']];new=[r['top_ids'] for r in testres['selected']['full']['rows']];resolved=[resolver(c['query'],books) for c in testcases]
    def apply(name):
        if name=='old':return old
        if name=='new_current':return new
        if name=='new_entity':return [prepend(x,r) for x,r in zip(new,resolved)]
        if name=='route_old_for_entity':return [o if r else n for o,n,r in zip(old,new,resolved)]
        entity=name.startswith('entity_');w=float(name.rsplit('_',1)[1]);rows=[rrf(o,n,w) for o,n in zip(old,new)]
        return [prepend(x,r) for x,r in zip(rows,resolved)] if entity else rows
    diagnostic={n:family_summary(apply(n),testcases) for n in ['old','new_current',selected]}
    # Resolver stress: one deterministic deletion typo in a long title token.
    probes=[]
    for b in books:
        toks=info(b['title']);long=next((t for t in toks if len(t)>=6),None)
        if len(toks)<2 or not long:continue
        pos=max(1,len(long)//2);bad=long[:pos]+long[pos+1:];query=' '.join(bad if t==long else t for t in toks)
        r=resolver(query,books);probes.append({'catalog_id':b['id'],'query':query,'resolved_id':r['catalog_id'] if r else None,'correct':bool(r and r['catalog_id']==b['id'])})
        if len(probes)>=300:break
    resolver_stats={'synthetic_title_typo_probes':len(probes),'top1_accuracy':float(np.mean([p['correct'] for p in probes])),
        'activations_dev':sum(r is not None for r in data['dev']['resolved']),'activations_regression77':sum(r is not None for r in data['reg']['resolved']),
        'dev_activations':[{'query':c['query'],**r} for c,r in zip(devcases,data['dev']['resolved']) if r],
        'regression_activations':[{'query':c['query'],'category':c['category'],**r} for c,r in zip(regcases,data['reg']['resolved']) if r]}
    out={'selection_protocol':'dev family-macro NDCG; regression77 Hit@3/10 constraints; closed test excluded from selection','selected':selected,'metrics':metrics,'eligible':eligible,
        'opened_test_diagnostic_after_selection':diagnostic,'resolver':resolver_stats,'limitations':['RRF uses saved top-10 lists; production experiment should fuse deeper lists.','Resolver typo probes are generated from titles and measure navigation robustness, not general search quality.','Existing dev and diagnostic test are synthetic and agent-labeled.']}
    (OUT/'results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'resolver-probes.json').write_text(json.dumps(probes,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'selected':selected,'dev':metrics[selected]['dev'],'reg':{k:v for k,v in metrics[selected]['regression77'].items() if k!='navigation'},'resolver_accuracy':resolver_stats['top1_accuracy']},ensure_ascii=True))
if __name__=='__main__':main()
