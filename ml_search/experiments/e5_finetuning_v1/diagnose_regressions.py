"""Read-only attribution of saved regressions; no integration tuning or test reselection."""
from pathlib import Path
import json,math
import numpy as np
from .compare_selected_model import engines
from .prepare_integration_review import sha
from ml_search.schemas import SearchRequest
from ml_search.text import normalize_text
ROOT=Path(__file__).parent;OUT=ROOT/'regression_diagnosis_v1'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def ranked(values,books):return sorted(range(len(books)),key=lambda i:(float(values[i]),books[i].popularity),reverse=True)
def main():
    assert not OUT.exists() or not any(OUT.iterdir());OUT.mkdir(exist_ok=True)
    snapshot=read(ROOT/'integration_review_v1/baseline/snapshot-manifest.json')
    project=ROOT.parents[2]
    for n,h in snapshot['sources_sha256'].items():assert sha(project/n)==h,n
    saved=read(ROOT/'comparison/test-results.json');frozen={r['query_id']:r for r in read(ROOT/'test_queries.frozen.json')};cases=[]
    for a,b in zip(saved['original']['full']['rows'],saved['selected']['full']['rows']):
        if not a['expected_empty'] and b['ndcg10_provisional']<a['ndcg10_provisional']-1e-10:
            cases.append({'id':a['query_id'],'kind':'test_decline','query':a['query'],'targets':[j['catalog_id'] for j in frozen[a['query_id']]['judgments'] if j['grade']>0]})
    reg=read(ROOT/'comparison/regression77.json');cat=read(project/'data/book_catalog/catalog.json');bytitle={b['title']:b['id'] for b in cat}
    for a,b in zip(reg['original']['rows'],reg['selected']['rows']):
        if a['category'] in {'navigational','partial_title','author_only','typo'} and a['rank'] and a['rank']<=3 and (b['rank'] is None or b['rank']>3):
            cases.append({'id':'NAV-'+str(len(cases)+1),'kind':'navigation_decline','query':a['query'],'targets':[bytitle[t] for t in a['expected_titles']]})
    cases.append({'id':'DEV-IDIOT','kind':'development_decline','query':'Помню русского героя с необычной открытостью: он попадает между двумя женщинами и одержимым ревнивцем','targets':[bytitle['Идиот']]})
    for qid in ['TEST-G04-V2','TEST-G06-V3','TEST-G12-V2']:
        c=frozen[qid];cases.append({'id':qid,'kind':'improvement_control','query':c['query'],'targets':[j['catalog_id'] for j in c['judgments'] if j['grade']==2]})
    es=engines();books=es['original'].books
    train=[json.loads(l) for l in (ROOT/'training/train.jsonl').read_text(encoding='utf-8').splitlines()]
    seen={r['positive_catalog_id'] for r in train}|{r['negative_catalog_id'] for r in train if r['negative_catalog_id'] is not None}|{a['catalog_id'] for r in train for a in r.get('additional_compatible_positives',[])}
    output=[]
    for c in cases:
        rr={};scores={}
        for name,e in es.items():
            intent=e.analyze(c['query']);raw=e.vector_index.similarities(e.embedder.encode_queries([c['query']])[0])
            cos=e.vector_index.similarities(e.embedder.encode_queries([intent.corrected_query])[0])
            raw_order=list(np.argsort(-raw,kind='stable'));sem_order=list(np.argsort(-cos,kind='stable'))
            rows=[]
            for i,b in enumerate(books):
                lex,entity=e._lexical_score(b,intent);meta,_=e._metadata_score(b,intent)
                pop=math.log1p(b.popularity)/math.log1p(e._max_popularity);rating=e._rating_score(b,None);sem=(float(cos[i])+1)/2
                total=e._combine_scores(semantic=sem,lexical=lex,metadata=meta,popularity=pop,rating=rating,entity_match=entity,has_query=True,has_metadata_preferences=e._has_metadata_preferences(intent))
                rows.append({'catalog_id':b.catalog_id,'title':b.title,'cosine':float(cos[i]),'semantic':sem,'lexical':lex,'metadata':meta,'popularity':pop,'rating':rating,'entity_match':entity,'total':total})
            order=ranked([r['total'] for r in rows],books);floor=max(0.5,rows[order[0]]['total']-0.16)
            passing=[i for i in order if rows[i]['total']>=floor];pool=passing[:e.max_results]
            response=e.search(SearchRequest(query=c['query'],limit=50,include_debug=True))
            assert [books[i].product_id for i in pool]==[r.product_id for r in response.results],c['id']
            for r in response.results:
                i=r.product_id-books[0].product_id;assert abs(rows[i]['total']-r.score)<1e-6
            def describe(i):
                r=dict(rows[i]);r.update({'raw_semantic_rank':raw_order.index(i)+1,'corrected_semantic_rank':sem_order.index(i)+1,'combined_rank_before_cutoff':order.index(i)+1,
                    'passes_score_floor':i in passing,'survives_top50':i in pool,'returned_rank':pool.index(i)+1 if i in pool else None,
                    'trained_book':books[i].catalog_id in seen,'profile':books[i].search_text,
                    'title_matching_variants':[{'variant':v,'score':e.corrector.title_match(books[i],normalize_text(v))[0],'entity':e.corrector.title_match(books[i],normalize_text(v))[1]} for v in intent.query_variants]})
                return r
            rr[name]={'intent':intent.as_dict(),'eligible_books':len(books),'floor':floor,'passing_floor':len(passing),'pool_size':len(pool),
                'cosine_mean':float(cos.mean()),'cosine_std':float(cos.std()),'targets':[describe(i-1) for i in c['targets']],
                'top5':[describe(i) for i in pool[:5]],'raw_semantic_top5':[{'id':books[i].catalog_id,'title':books[i].title} for i in raw_order[:5]]}
            scores[name]=rows
        assert rr['original']['intent']==rr['selected']['intent']
        for a,b in zip(scores['original'],scores['selected']):
            for k in ['lexical','metadata','popularity','rating','entity_match']:assert a[k]==b[k],k
        # Two counterfactuals isolate score calibration from changed semantic ordering.
        cf={}
        oldcos=np.array([r['cosine'] for r in scores['original']]);newcos=np.array([r['cosine'] for r in scores['selected']])
        has_preferences=es['selected']._has_metadata_preferences(intent)
        for label,cos in [('new_cosine_with_old_mean',newcos-newcos.mean()+oldcos.mean()),('new_cosine_with_old_mean_and_std',(newcos-newcos.mean())*oldcos.std()/newcos.std()+oldcos.mean())]:
            totals=[]
            for i,r in enumerate(scores['selected']):
                totals.append(es['selected']._combine_scores(semantic=float(np.clip((cos[i]+1)/2,0,1)),lexical=r['lexical'],metadata=r['metadata'],popularity=r['popularity'],rating=r['rating'],entity_match=r['entity_match'],has_query=True,has_metadata_preferences=has_preferences))
            order=ranked(totals,books);floor=max(0.5,totals[order[0]]-0.16);pool=[i for i in order if totals[i]>=floor][:50]
            cf[label]={'floor':floor,'pool_size':len(pool),'targets':[{'id':i,'rank_before_cutoff':order.index(i-1)+1,'returned_rank':pool.index(i-1)+1 if i-1 in pool else None} for i in c['targets']],
                'note':'Per-query diagnostic calibration using baseline distribution; not a deployable tuned setting.'}
        output.append({**c,'models':rr,'counterfactual_calibration':cf,'intent_identical':True,'all_nonsemantic_scores_identical':True})
        print(json.dumps({'completed':c['id']}),flush=True)
    for n,h in snapshot['sources_sha256'].items():assert sha(project/n)==h,n
    (OUT/'traces.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'validation.json').write_text(json.dumps({'passed':True,'cases':len(cases),'all1000books_scored_per_case':True,'trace_matches_actual_engine_results':True,'production_sources_unchanged':len(snapshot['sources_sha256']),'no_model_or_weights_changed':True}),encoding='utf-8')
if __name__=='__main__':main()
