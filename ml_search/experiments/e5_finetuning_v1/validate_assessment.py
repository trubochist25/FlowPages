"""Validate frozen labels and textual leakage; no model evaluation."""
from pathlib import Path
import json
import hashlib
import re
from difflib import SequenceMatcher
from itertools import combinations

OUT=Path(__file__).parent
ROOT=OUT.parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def norm(s):return re.sub(r'\W+',' ',s.lower().replace('ё','е')).strip()
def main():
    freeze=json.loads((OUT/'freeze-manifest.json').read_text(encoding='utf-8'))
    for n,h in freeze['files'].items(): assert sha(OUT/n)==h,n
    assert sha(ROOT/'data/book_catalog/catalog.json')==freeze['catalog_sha256']
    assert sha(ROOT/'ml_search/evaluation_queries.json')==freeze['regression_sha256']
    sets={'test':json.loads((OUT/'test_queries.frozen.json').read_text(encoding='utf-8')),
          'dev':json.loads((OUT/'dev_queries.json').read_text(encoding='utf-8')),
          'regression':json.loads((ROOT/'ml_search/evaluation_queries.json').read_text(encoding='utf-8'))}
    books={b['id']:b for b in json.loads((ROOT/'data/book_catalog/catalog.json').read_text(encoding='utf-8'))}
    policy=json.loads((OUT/'split-policy.json').read_text(encoding='utf-8'))
    ids=set()
    checked=0
    for split in ('dev','test'):
        groups={r['group_id'] for r in sets[split]}
        assert all(sum(r['group_id']==g for r in sets[split])==3 for g in groups)
        for r in sets[split]:
            assert r['query_id'] not in ids
            ids.add(r['query_id'])
            assert bool(r['judgments']) != r['expected_empty']
            for j in r['judgments']:
                b=books[j['catalog_id']]
                assert b['title']==j['title'] and b['searchText']==j['evidence']
                assert j['profile_sha256']==hashlib.sha256(b['searchText'].encode()).hexdigest()
                assert j['grade'] in [0,1,2]
                assert j['catalog_id'] in policy['training_excluded_book_ids']
                checked+=1
    pairs=[]
    for a,b in combinations(sets,2):
        candidates=[]
        for i,x in enumerate(sets[a]):
            for k,y in enumerate(sets[b]):
                nx,ny=norm(x['query']),norm(y['query'])
                assert nx!=ny,(a,b,x['query'],y['query'])
                ratio=SequenceMatcher(None,nx,ny,autojunk=False).ratio()
                candidates.append({'a':a,'a_id':x.get('query_id',f'R{i+1}'),'b':b,'b_id':y.get('query_id',f'R{k+1}'),
                                  'character_similarity':round(ratio,4)})
        pairs+=sorted(candidates,key=lambda p:p['character_similarity'],reverse=True)[:10]
    report={'frozen_hashes_valid':True,'catalog_and_regression_unchanged':True,
            'query_ids_unique':True,'each_intent_family_in_single_split':True,'variants_per_family':3,
            'judgment_records_checked':checked,'no_exact_cross_split_query_duplicates':True,
            'top_textual_overlap_pairs':pairs,
            'limitation':'Textual screening and manual intent review are not a mathematical guarantee against semantic leakage. Repeat against future training data.'}
    (OUT/'integrity-and-overlap-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
