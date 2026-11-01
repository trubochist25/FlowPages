from pathlib import Path
import json,time
import numpy as np
from .fast_title_resolver import FastTitleResolver
ROOT=Path(__file__).parent;OUT=ROOT/'integration_variants_v2';PROJECT=ROOT.parents[2]
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def main():
    books=read(PROJECT/'data/book_catalog/catalog.json');fast=FastTitleResolver(books);result=read(OUT/'results.json')
    reg=read(PROJECT/'ml_search/evaluation_queries.json');expected={r['query']:r for r in result['resolver']['regression_activations']}
    assert all((fast.resolve(c['query']) or {}).get('catalog_id')==(expected.get(c['query']) or {}).get('catalog_id') for c in reg)
    assert all(fast.resolve(c['query']) is None for c in read(ROOT/'dev_queries.json'))
    fresh=[]
    for n in ['dev_queries.draft.json','test_queries.draft.json']:fresh+=read(ROOT/'integration_review_v1/new-assessment'/n)
    assert all(fast.resolve(c['query']) is None for c in fresh)
    probes=read(OUT/'resolver-probes.json')
    assert all((fast.resolve(c['query']) or {}).get('catalog_id')==c['resolved_id'] for c in probes)
    held=read(OUT/'resolver-heldout-stress.json')
    assert all((fast.resolve(c['query']) or {}).get('catalog_id')==(c['resolved'] or {}).get('catalog_id') for c in held['heldout_title_transposition'])
    assert all((fast.resolve(c['query']) or {}).get('catalog_id')==(c['resolved'] or {}).get('catalog_id') for c in held['thematic_false_activation'])
    samples=[c['query'] for c in reg]*20;times=[]
    for q in samples:
        t=time.perf_counter();fast.resolve(q);times.append((time.perf_counter()-t)*1000)
    report={'passed':True,'same_decisions_as_reference_cases':len(reg)+len(fresh)+len(probes)+len(held['heldout_title_transposition'])+len(held['thematic_false_activation']),
        'construction_ms_not_in_query_latency':None,'latency':{'samples':len(times),'mean_ms':float(np.mean(times)),'p95_ms':float(np.percentile(times,95)),'max_ms':max(times)},
        'production_changed':False}
    t=time.perf_counter();FastTitleResolver(books);report['construction_ms_not_in_query_latency']=(time.perf_counter()-t)*1000
    (OUT/'fast-resolver-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
if __name__=='__main__':main()
