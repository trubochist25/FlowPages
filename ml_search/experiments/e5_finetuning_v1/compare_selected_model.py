"""Read-only comparison of matched model/index pairs; closes model selection."""
from pathlib import Path
from dataclasses import replace
from collections import defaultdict
import os,json,hashlib,time,math,statistics
os.environ['ML_SEARCH_OFFLINE']='1'
import numpy as np
from ml_search.config import Settings
from ml_search.embeddings import E5Embedder
from ml_search.search import SearchEngine
from ml_search.schemas import SearchRequest,SearchFilters,RecommendationRequest,RecommendationSignal
from ml_search.evaluate_models import rank_metrics
from ml_search import evaluate_alchemy as ae

ROOT=Path(__file__).parent;OUT=ROOT/'comparison'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def notify(d):print(json.dumps(d,ensure_ascii=True),flush=True)
def engines():
    s=Settings.from_env('small')
    base=E5Embedder(s.model_name,OUT/'cache-original',32,s.local_model_path,384)
    name=json.loads((OUT/'index/manifest.json').read_text(encoding='utf-8'))['model_name']
    model_path=ROOT/'limited_experiment/selected-model'
    new=E5Embedder(name,OUT/'cache-selected',32,model_path,384)
    ns=replace(s,model_name=name,local_model_path=model_path,index_path=OUT/'index/book-index.npz',manifest_path=OUT/'index/manifest.json')
    return {'original':SearchEngine.from_settings(s,base),'selected':SearchEngine.from_settings(ns,new)}
def summarize(rows):
    positive=[r for r in rows if not r['expected_empty']]
    groups=defaultdict(list)
    for r in positive:groups[r['group_id']].append(r)
    keys=['ndcg10_provisional','hit3','hit10','mrr']
    fam={g:{k:float(np.mean([r[k] for r in rr])) for k in keys} for g,rr in groups.items()}
    summary={k:float(np.mean([v[k] for v in fam.values()])) for k in keys}
    categories=defaultdict(list)
    for g,values in fam.items():categories[next(r['category'] for r in groups[g])].append(values)
    by_category={c:{k:float(np.mean([v[k] for v in vv])) for k in keys} for c,vv in categories.items()}
    empty=[r for r in rows if r['expected_empty']]
    summary.update({'queries_with_matches':len(positive),'positive_families':len(groups),'no_match_queries':len(empty),
        'no_match_empty_rate':float(np.mean([not r['top_ids'] for r in empty])) if empty else None,
        'unknown_top10_mean':float(np.mean([r['unknown_in_top10'] for r in positive])),
        'mean_ms':float(np.mean([r['processing_ms'] for r in rows])),'p95_ms':float(np.percentile([r['processing_ms'] for r in rows],95))})
    return {'summary':summary,'by_family':fam,'by_category':by_category,'rows':rows}
def score_row(case,top_ids,elapsed,state,seen):
    grades={j['catalog_id']:j['grade'] for j in case['judgments']}
    good={i for i,g in grades.items() if g==2}
    rank=next((k+1 for k,i in enumerate(top_ids) if i in good),None)
    dcg=sum((2**grades.get(i,0)-1)/math.log2(k+2) for k,i in enumerate(top_ids[:10]))
    ideal=sum((2**g-1)/math.log2(k+2) for k,g in enumerate(sorted(grades.values(),reverse=True)[:10]))
    return {'query_id':case['query_id'],'group_id':case['group_id'],'query':case['query'],'category':case['category'],
        'expected_empty':case['expected_empty'],'rank':rank,'mrr':1/rank if rank else 0,'hit3':int(rank is not None and rank<=3),
        'hit10':int(rank is not None and rank<=10),'ndcg10_provisional':dcg/ideal if ideal else 0,
        'top_ids':top_ids[:10],'known_grades':[grades.get(i) for i in top_ids[:10]],'processing_ms':elapsed,'state':state,
        'unknown_in_top10':sum(i not in grades for i in top_ids[:10]),
        'target_books_unseen_in_training':not bool(good&seen),'judged_good_book_ids':sorted(good)}
def evaluate_cases(es,cases,label,seen):
    result={name:{'semantic':[],'full':[]} for name in es}
    for pos,case in enumerate(cases):
        order=list(es) if pos%2==0 else list(reversed(es))
        for name in order:
            engine=es[name]
            t=time.perf_counter();v=engine.embedder.encode_queries([case['query']])[0]
            indices=np.argsort(-engine.vector_index.similarities(v),kind='stable')
            ids=[engine.books[i].catalog_id for i in indices[:10]]
            elapsed=(time.perf_counter()-t)*1000
            result[name]['semantic'].append(score_row(case,ids,elapsed,'always_returns_top10_no_empty_classifier',seen))
            t=time.perf_counter();response=engine.search(SearchRequest(query=case['query'],limit=10))
            ids=[r.product_id-engine.books[0].product_id+1 for r in response.results]
            result[name]['full'].append(score_row(case,ids,(time.perf_counter()-t)*1000,response.state,seen))
        if (pos+1)%15==0:notify({'event':label,'queries_done':pos+1})
    reports={name:{mode:summarize(rr) for mode,rr in modes.items()} for name,modes in result.items()}
    write(f'{label}-results.json',reports);return reports
def regressions(es):
    cases=json.loads((ROOT.parents[2]/'ml_search/evaluation_queries.json').read_text(encoding='utf-8'))
    result={name:[] for name in es}
    for n,case in enumerate(cases):
        for name in list(es) if n%2==0 else list(reversed(es)):
            response=es[name].search(SearchRequest(query=case['query'],limit=10))
            titles=[r.title for r in response.results]
            rank=next((k+1 for k,title in enumerate(titles) if title in case['expected_titles']),None)
            forbidden={title:next((k+1 for k,t in enumerate(titles) if t==title),None) for title in case.get('forbidden_titles',[])}
            result[name].append({**case,'rank':rank,'top_titles':titles,'processing_ms':response.processing_ms,'forbidden_ranks':forbidden})
    reports={name:{'metrics':rank_metrics(rr),'by_category':{c:rank_metrics([r for r in rr if r['category']==c]) for c in sorted({r['category'] for r in rr})},'rows':rr} for name,rr in result.items()}
    write('regression77.json',reports);notify({'event':'regressions_done','metrics':{n:r['metrics'] for n,r in reports.items()}});return reports
def safeguards(es):
    probes=[('author-'+a,SearchRequest(query=a,limit=10),'author',a) for a in ['Стивен Кинг','Джейн Остин','Джордж Оруэлл','Агата Кристи','Фёдор Достоевский']]
    stricts=[{'authors':['Стивен Кинг']},{'genres':['Фэнтези']},{'moods':['уютная']},{'paces':['медленный']},
        {'pages_min':100,'pages_max':250},{'price_min':300,'price_max':600},{'year_min':1900,'year_max':1950},{'age_ratings':['6+']},
        {'authors':['Фёдор Достоевский'],'pages_max':300},{'genres':['Детская литература'],'age_ratings':['0+','6+'],'price_max':900}]
    probes += [(f'filter-{i}',SearchRequest(query='Хочу интересную книгу',filters=SearchFilters(**f),limit=50),'filter',None) for i,f in enumerate(stricts)]
    probes += [('empty',SearchRequest(query=''),'state','empty_query'),('punctuation',SearchRequest(query='!!!'),'state','invalid_query'),
        ('impossible-filter',SearchRequest(query='книга',filters=SearchFilters(pages_max=1)),'state','no_matches')]
    report={}
    for name,engine in es.items():
        byid={b.product_id:b for b in engine.books};rows=[]
        for title,request,kind,value in probes:
            response=engine.search(request)
            if kind=='author':passed=bool(response.results) and all(r.author==value for r in response.results[:3])
            elif kind=='state':passed=not response.results and response.state==value
            else:passed=all(engine._passes_filters(byid[r.product_id],request.filters) for r in response.results)
            rows.append({'name':title,'passed':passed,'results':len(response.results),'state':response.state,'top_titles':[r.title for r in response.results[:3]],'request':request.model_dump()})
        report[name]={'cases':rows,'failures':[r['name'] for r in rows if not r['passed']]}
    write('search-safeguards.json',report);return report
def alchemy(es):
    results={}
    for name,engine in es.items():
        books=engine.books;byid={b.product_id:b for b in books}
        rows,lat,ground=ae.evaluate_meaningful(engine,byid,ae.build_meaningful_cases(books))
        ex=ae.evaluate_strict_exclusions(engine,books,byid);filters=ae.evaluate_filters(engine,books,byid)
        contradictions=ae.evaluate_contradictions();empty=ae.evaluate_empty_states(engine)
        lat+=ex['latencies']+filters['latencies']+empty['latencies']
        checks={'meaningful_top3_at_least_90_percent':sum(r['meaningful'] for r in rows)/len(rows)>=0.9,
            'strict_exclusions_always_hold':not ex['violations'],'strict_filters_always_hold':not filters['violations'],
            'contradictions_always_rejected':not contradictions['accepted'],'no_unexplained_empty_state':not empty['failures'],
            'all_outputs_grounded':not ground,'p95_processing_within_800_ms':float(np.percentile(lat,95))<=800}
        results[name]={'checks':checks,'meaningful_rate':sum(r['meaningful'] for r in rows)/len(rows),'meaningful_cases':len(rows),
            'p95_ms':float(np.percentile(lat,95)),'rows':rows,'strict_exclusions':ex,'strict_filters':filters,'contradictions':contradictions,'empty':empty,'grounding_failures':ground}
        notify({'event':'alchemy_done','model':name,'checks':checks})
    write('alchemy-comparison.json',results);return results
def recommendations(es):
    requests=[]
    books=next(iter(es.values())).books
    for bid in [1,3,7,13,16,27,33,41,53,66,71,76,83,89,94,106,126,140,156,170,173]:
        requests.append((f'similar-{bid}',RecommendationRequest(strategy='similar',anchor_product_id=books[bid-1].product_id,limit=12,random_seed=42,include_debug=True),bid))
    for strategy in ['balanced','explore']:
        requests.append((f'history-{strategy}',RecommendationRequest(strategy=strategy,signals=[RecommendationSignal(product_id=books[i-1].product_id,kind=k) for i,k in [(7,'purchase'),(16,'wishlist'),(41,'cart'),(13,'view')]],limit=15,random_seed=42,include_debug=True),None))
    requests += [('cold',RecommendationRequest(limit=15,random_seed=42),None),('unknown',RecommendationRequest(signals=[RecommendationSignal(product_id=999999,kind='view')],limit=15,random_seed=42),None)]
    results={}
    for name,engine in es.items():
        byid={b.product_id:b for b in books};rows=[]
        for label,request,bid in requests:
            response=engine.recommend(request);ids=[r.product_id for r in response.results]
            forbidden={s.product_id for s in request.signals if s.kind in ['purchase','wishlist','cart']}
            if request.anchor_product_id:forbidden.add(request.anchor_product_id)
            passed=len(ids)==request.limit and len(ids)==len(set(ids)) and not set(ids)&forbidden and all(i in byid for i in ids) and all(math.isfinite(r.score) and r.reasons for r in response.results)
            related=None
            if bid:
                anchor=books[bid-1]
                related=sum(ae._anchor_related(byid[i],anchor) for i in ids[:3])/3
            rows.append({'name':label,'passed_invariants':bool(passed),'top_ids':ids,'top3_related_metadata_proxy':related,
                'authors':len({byid[i].author for i in ids}),'processing_ms':response.processing_ms})
        results[name]={'cases':rows,'failures':[r['name'] for r in rows if not r['passed_invariants']],
            'top3_related_metadata_proxy_mean':float(np.mean([r['top3_related_metadata_proxy'] for r in rows if r['top3_related_metadata_proxy'] is not None]))}
    write('recommendation-comparison.json',results);return results
def latency(es,cases):
    times={name:{'full':[],'semantic':[]} for name in es}
    for repeat in range(3):
        for n,case in enumerate(cases):
            for name in list(es) if (n+repeat)%2==0 else list(reversed(es)):
                engine=es[name]
                t=time.perf_counter();engine.search(SearchRequest(query=case['query'],limit=10));times[name]['full'].append((time.perf_counter()-t)*1000)
                t=time.perf_counter();v=engine.embedder.encode_queries([case['query']])[0];np.argsort(-engine.vector_index.similarities(v));times[name]['semantic'].append((time.perf_counter()-t)*1000)
        notify({'event':'latency_pass_complete','pass':repeat+1})
    summary={name:{mode:{'mean_ms':float(np.mean(v)),'median_ms':float(np.median(v)),'p95_ms':float(np.percentile(v,95)),'samples':len(v)} for mode,v in modes.items()} for name,modes in times.items()}
    write('latency.json',{'protocol':'CPU service environment, four torch threads, interleaved, warmed, no vector cache','summary':summary,'samples':times});return summary
def stability(test):
    result={};rng=np.random.default_rng(20260915)
    for mode in ['semantic','full']:
        old=test['original'][mode]['by_family'];new=test['selected'][mode]['by_family']
        gains=np.array([new[g]['ndcg10_provisional']-old[g]['ndcg10_provisional'] for g in sorted(old)])
        draws=np.mean(rng.choice(gains,(5000,len(gains)),replace=True),axis=1)
        leave=[float(np.delete(gains,k).mean()) for k in range(len(gains))]
        result[mode]={'families':len(gains),'ndcg10_gain':float(gains.mean()),'paired_family_bootstrap_95_percent':[float(v) for v in np.percentile(draws,[2.5,97.5])],
            'leave_one_family_out_range':[min(leave),max(leave)],'improved_families':int(sum(gains>1e-10)),'unchanged_families':int(sum(abs(gains)<=1e-10)),'worsened_families':int(sum(gains<-1e-10))}
    write('stability.json',result);return result
def main():
    criteria=json.loads((OUT/'acceptance-criteria.json').read_text(encoding='utf-8'));assert criteria['approved_by_user']
    assert not (OUT/'test-results.json').exists(),'Never rerun or overwrite closed-test comparison'
    frozen=json.loads((ROOT/'freeze-manifest.json').read_text(encoding='utf-8'))
    for name,digest in frozen['files'].items():assert sha(ROOT/name)==digest
    write('comparison-preregistration.json',{'criteria_sha256':sha(OUT/'acceptance-criteria.json'),'selected_manifest_sha256':sha(ROOT/'limited_experiment/experiment-manifest.json'),
        'frozen_files':frozen['files'],'code_sha256':sha(Path(__file__)),'hardware':'CPU both models, four torch threads','no_settings_changes':True})
    es=engines()
    for engine in es.values():
        for q in ['книга о дружбе','уютная история','детектив']:engine.search(SearchRequest(query=q,limit=10))
    reg=regressions(es);guard=safeguards(es);alc=alchemy(es);rec=recommendations(es)
    train=[json.loads(l) for l in (ROOT/'training/train.jsonl').read_text(encoding='utf-8').splitlines()]
    seen={r['positive_catalog_id'] for r in train}|{r['negative_catalog_id'] for r in train if r['negative_catalog_id'] is not None}|{a['catalog_id'] for r in train for a in r.get('additional_compatible_positives',[])}
    dev=evaluate_cases(es,json.loads((ROOT/'dev_queries.json').read_text(encoding='utf-8')),'dev',seen)
    cases=json.loads((ROOT/'test_queries.frozen.json').read_text(encoding='utf-8'));assert len(cases)==120
    test=evaluate_cases(es,cases,'test',seen);speed=latency(es,cases);stab=stability(test)
    delta=test['selected']['full']['summary']['ndcg10_provisional']-test['original']['full']['summary']['ndcg10_provisional']
    checks={'ndcg_gain_at_least_0_03_provisional':delta>=criteria['minimum_ndcg10_gain'],
        'regression_hit3_drop_within_2pp':reg['selected']['metrics']['hit_at_3']>=reg['original']['metrics']['hit_at_3']-0.02,
        'regression_hit10_drop_within_2pp':reg['selected']['metrics']['hit_at_10']>=reg['original']['metrics']['hit_at_10']-0.02,
        'no_new_search_safeguard_failure':not set(guard['selected']['failures'])-set(guard['original']['failures']),
        'no_new_navigation_failures':not [1 for old,new in zip(reg['original']['rows'],reg['selected']['rows']) if old['category'] in ['navigational','exact_title','author'] and old['rank'] is not None and old['rank']<=3 and (new['rank'] is None or new['rank']>3)],
        'no_new_mandatory_alchemy_failure':not [k for k,v in alc['original']['checks'].items() if v and not alc['selected']['checks'][k]],
        'full_search_p95_ratio_within_1_2':speed['selected']['full']['p95_ms']/speed['original']['full']['p95_ms']<=1.2,
        'no_new_recommendation_invariant_failures':not set(rec['selected']['failures'])-set(rec['original']['failures'])}
    decision={'checks':checks,'full_test_ndcg10_gain_provisional':delta,'all_numeric_and_safety_criteria_pass':all(checks.values()),
        'full_search_p95_ratio':speed['selected']['full']['p95_ms']/speed['original']['full']['p95_ms'],
        'production_replaced':False,'model_reselected_after_test':False,'closed_test_not_used_for_tuning':True,
        'decision':'Keep original production search. '+('Numerical criteria passed, but independently completing pooled relevance judgments is required before a convincing deployment recommendation.' if all(checks.values()) else 'Pre-agreed criteria not met.'),
        'ndcg_is_provisional_due_to_incomplete_qrels':True}
    write('decision.json',decision)
    for name,digest in frozen['files'].items():assert sha(ROOT/name)==digest
    notify({'event':'comparison_complete','decision':decision})
if __name__=='__main__':main()
