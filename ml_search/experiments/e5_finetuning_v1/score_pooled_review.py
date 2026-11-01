"""Score saved rankings with reviewed pool; never treat missing labels as negatives."""
from pathlib import Path
import argparse,json,math,statistics
ROOT=Path(__file__).parent;OUT=ROOT/'integration_review_v1'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def metrics(ids,g):
    good={i for i,v in g.items() if v==2};rank=next((k+1 for k,i in enumerate(ids[:10]) if i in good),None)
    dcg=sum((2**g[i]-1)/math.log2(k+2) for k,i in enumerate(ids[:10]))
    ideal=sum((2**v-1)/math.log2(k+2) for k,v in enumerate(sorted(g.values(),reverse=True)[:10]))
    return {'ndcg10':dcg/ideal if ideal else None,'hit3':int(rank is not None and rank<=3),'hit10':int(rank is not None),'rank':rank}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('labels',type=Path);ap.add_argument('--reviewer',choices=['agent','human'],required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    assert not args.output.exists(),'Do not overwrite prior review results'
    labels=read(args.labels);public=read(OUT/'blind-review/pool.json');key=read(OUT/'private/pool-key.json');results=read(ROOT/'comparison/test-results.json')
    expected={q['query_id']:{c['candidate_id'] for c in q['candidates']} for q in public}
    qs={};seen=set()
    for q in labels['queries']:
        qid=q['query_id'];assert qid in expected and qid not in qs,'Unknown or duplicate query'
        qs[qid]={}
        for c in q['candidates']:
            cid=c['candidate_id'];assert cid in expected[qid] and cid not in seen,'Unknown or duplicate candidate'
            seen.add(cid);v=c['grade'];assert v is None or type(v)==int and v in (0,1,2),'Invalid grade'
            assert isinstance(c.get('reason',''),str)
            if v is not None:assert c.get('reason','').strip(),'Explain each assigned grade'
            qs[qid][cid]=v
    complete=[];incomplete=[];changes=[]
    for q in key:
        qq=qs.get(q['query_id'],{})
        if set(qq)!=expected[q['query_id']] or any(v is None for v in qq.values()):incomplete.append(q['query_id']);continue
        grades={c['catalog_id']:qq[c['candidate_id']] for c in q['candidates']}
        row={'query_id':q['query_id'],'source_query_id':q['source_query_id'],'family':q['family'],'category':q['category'],'pool_contains_grade2':2 in grades.values(),'pool_contains_any_relevant':any(g>0 for g in grades.values()),'scores':{}}
        for name in ['original','selected']:
            row['scores'][name]={}
            for mode in ['semantic','full']:
                r=next(r for r in results[name][mode]['rows'] if r['query_id']==q['source_query_id'])
                assert set(r['top_ids'])<=set(grades)
                row['scores'][name][mode]=metrics(r['top_ids'],grades)
        for c in q['candidates']:
            if c['old_grade'] is not None and c['old_grade']!=qq[c['candidate_id']]:changes.append({'query_id':q['query_id'],'catalog_id':c['catalog_id'],'old_grade':c['old_grade'],'reviewed_grade':qq[c['candidate_id']]})
        complete.append(row)
    families={q['family'] for q in key};whole=[]
    for f in families:
        required={q['query_id'] for q in key if q['family']==f}
        if required<={q['query_id'] for q in complete}:whole.append(f)
    summaries={}
    for name in ['original','selected']:
        summaries[name]={}
        for mode in ['semantic','full']:
            fvals=[]
            for f in whole:
                rr=[r for r in complete if r['family']==f and r['pool_contains_grade2']]
                if rr:fvals.append({k:statistics.mean(r['scores'][name][mode][k] for r in rr) for k in ['ndcg10','hit3','hit10']})
            summaries[name][mode]={k:statistics.mean(r[k] for r in fvals) if fvals else None for k in ['ndcg10','hit3','hit10']}
    assert abs(metrics([1,2],{1:2,2:1})['ndcg10']-1)<1e-12
    report={'reviewer_type':args.reviewer,'independent_human_assessment_verified':False,'complete_queries':len(complete),'complete_families':len(whole),'incomplete_queries':len(incomplete),
        'all_120_queries_fully_reviewed':len(complete)==120,'full_quality_conclusion_ready':len(complete)==120 and args.reviewer=='human',
        'family_macro_summaries_complete_families_only':summaries,'rows':complete,'prior_label_changes':changes,
        'limitations':['Pool judges top-10 only, not the entire catalog.','No positive in pool does not prove no matching book exists.','Partial reviews cannot establish full-test model superiority.']}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k not in ['rows','prior_label_changes']},ensure_ascii=True))
if __name__=='__main__':main()
