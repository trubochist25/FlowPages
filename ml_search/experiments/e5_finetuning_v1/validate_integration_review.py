"""Integrity and completeness validation for baseline and source-blind materials."""
from pathlib import Path
import json,hashlib,math
from .prepare_integration_review import sha
from .score_pooled_review import metrics
ROOT=Path(__file__).parent;OUT=ROOT/'integration_review_v1';PROJECT=ROOT.parents[2]
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def main():
    snap=read(OUT/'baseline/snapshot-manifest.json')
    for n,h in snap['sources_sha256'].items():assert sha(PROJECT/n)==h,n
    backup=read(OUT/'baseline/backup-verification.json');assert sha(Path(backup['path']))==backup['sha256']
    pool=read(OUT/'blind-review/pool.json');key=read(OUT/'private/pool-key.json');saved=read(ROOT/'comparison/test-results.json');source=read(ROOT/'test_queries.frozen.json')
    assert len(pool)==len(key)==len(source)==120
    seen=set();total=0
    for q,k,c in zip(pool,key,source):
        assert q['query']==c['query'] and q['query_id']==k['query_id'] and k['source_query_id']==c['query_id']
        assert len(q['candidates'])==len(k['candidates'])
        for a,b in zip(q['candidates'],k['candidates']):
            assert a['candidate_id']==b['candidate_id'] and a['candidate_id'] not in seen
            assert a['grade'] is None and a['reason']==''
            assert set(a)=={'candidate_id','title','author','search_text','grade','reason'}
            seen.add(a['candidate_id']);total+=1
        ids={r['catalog_id'] for r in k['candidates']}
        assert len(ids)==len(k['candidates'])
        for name in ['original','selected']:
            for mode in ['semantic','full']:
                r=next(r for r in saved[name][mode]['rows'] if r['query_id']==c['query_id']);assert set(r['top_ids'])<=ids
                for b in k['candidates']:assert b['positions'][f'{name}/{mode}']==(r['top_ids'].index(b['catalog_id'])+1 if b['catalog_id'] in r['top_ids'] else None)
    new=OUT/'new-assessment';policy=read(new/'split-policy.json');dev=read(new/'dev_queries.draft.json');test=read(new/'test_queries.draft.json')
    for n,h in policy['freeze_draft_sha256'].items():assert sha(new/n)==h
    assert len(dev)==51 and len(test)==99
    assert not {r['family_id'] for r in dev}&{r['family_id'] for r in test}
    assert len({r['query'] for r in dev+test})==150
    assert all(r['judgments'] is None and r['expected_empty'] is None and not r['model_evaluation_performed'] for r in dev+test)
    assert abs(metrics([1,2],{1:2,2:1})['ndcg10']-1)<1e-12
    expected=(1+3/math.log2(3))/(3+1/math.log2(3))
    assert abs(metrics([2,1],{1:2,2:1})['ndcg10']-expected)<1e-12
    assert metrics([3],{1:2,3:0})['hit10']==0
    try:metrics([3],{1:2})
    except KeyError:pass
    else:raise AssertionError('Missing labels must not become negative')
    pilot=read(OUT/'agent-pilot-results-v2.json');assert pilot['complete_queries']==2 and pilot['complete_families']==0
    assert not pilot['full_quality_conclusion_ready'] and not pilot['independent_human_assessment_verified']
    report={'passed':True,'baseline_sources_unchanged':len(snap['sources_sha256']),'baseline_backup_hash_verified':True,'pool_queries':120,'pool_pairs':total,
        'all_four_rankings_covered':True,'public_review_hides_model_ranks_prior_grades':True,'fresh_query_drafts':150,'dev_test_families_disjoint':True,
        'scorer_dcg_and_missing_label_handling_verified':True,'agent_pilot_complete_queries':2,
        'full_pooled_assessment_completed':False,'fresh_independent_test_ready':False,'production_modified':False}
    (OUT/'validation-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
if __name__=='__main__':main()
