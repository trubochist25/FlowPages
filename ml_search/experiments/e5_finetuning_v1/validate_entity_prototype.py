"""Validate that resolver decisions work through the real scoring path."""
from pathlib import Path
import json,time
from .compare_selected_model import engines
from .compare_integration_variants import resolver
from ml_search.schemas import SearchRequest
from ml_search.text import normalize_text
ROOT=Path(__file__).parent;OUT=ROOT/'integration_variants_v2'
def main():
    result=json.loads((OUT/'results.json').read_text(encoding='utf-8'));probes=result['resolver']['regression_activations'];e=engines()['selected'];rows=[]
    original=e.corrector.title_match
    for p in probes:
        expected=p['catalog_id'];query_norm=normalize_text(p['query'])
        def patched(book,query,expected=expected,query_norm=query_norm):
            score,kind=original(book,query)
            if book.catalog_id==expected and normalize_text(query)==query_norm and score<0.94:return 0.94,'fuzzy_title'
            return score,kind
        e.corrector.title_match=patched
        started=time.perf_counter();response=e.search(SearchRequest(query=p['query'],limit=10,include_debug=True));elapsed=(time.perf_counter()-started)*1000
        rank=next((n+1 for n,r in enumerate(response.results) if r.product_id-e.books[0].product_id+1==expected),None)
        target=next(r for r in response.results if r.product_id-e.books[0].product_id+1==expected)
        rows.append({'query':p['query'],'expected_catalog_id':expected,'rank':rank,'engine_ms':elapsed,'entity_match':target.score_breakdown.entity_match,'total':target.score_breakdown.total})
        e.corrector.title_match=original
    report={'all_resolved_targets_rank1':all(r['rank']==1 for r in rows),'all_use_fuzzy_title_branch':all(r['entity_match']=='fuzzy_title' for r in rows),'cases':rows,
        'implementation':'Experimental per-query resolver decision injected into the existing fuzzy_title score branch; production source unchanged.'}
    (OUT/'real-engine-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=True))
if __name__=='__main__':main()
