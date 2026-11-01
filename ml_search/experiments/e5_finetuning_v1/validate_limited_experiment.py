"""Integrity checks after model selection; does not open or evaluate test queries."""
from pathlib import Path
from collections import Counter
import json,hashlib,subprocess

ROOT=Path(__file__).parent
OUT=ROOT/'limited_experiment'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
def main():
    manifest=read('experiment-manifest.json');selection=read('selection.json');cfg=read('preregistration.json')
    for name,key in [('selection.json','selection_sha256'),('preregistration.json','preregistration_sha256'),('batch-plan.json','batch_plan_sha256')]:
        assert sha(OUT/name)==manifest[key],name
    for name,digest in manifest['selected_files'].items():assert sha(OUT/name)==digest,name
    assert sha(ROOT/'limited_experiment.py')==manifest['code_sha256']
    assert sha(ROOT/'training/train.jsonl')==cfg['train_sha256']
    for name,digest in cfg['frozen_files_sha256'].items():assert sha(ROOT/name)==digest,name
    assert sha(OUT/'batch-plan.json')==read('batch-review.json')['batch_plan_sha256']
    results=selection['all_checkpoints'];assert len(results)==6
    assert {(r['lr'],r['epoch']) for r in results}=={(lr,e) for lr in [1e-5,2e-5] for e in [1,2,3]}
    chosen=max(results,key=lambda r:(r['metrics']['mrr'],r['metrics']['hit10'],r['metrics']['known_qrel_ndcg10_provisional'],-r['epoch'],-r['lr']))
    assert chosen==selection['selected']
    for r in results:
        checkpoint=Path(r['checkpoint']);assert (checkpoint/'model.safetensors').is_file()
        evaluated=read(f"dev-{r['run']}-epoch-{r['epoch']}.json")
        assert evaluated['summary']==r['metrics']
        assert evaluated['positive_queries']==48 and evaluated['no_match_queries']==12
        assert len(evaluated['by_family'])==16
    for p in (OUT/'selected-model').rglob('*'):
        if p.is_file():assert sha(p)==sha(Path(chosen['checkpoint'])/p.relative_to(OUT/'selected-model'))
    log=[json.loads(l) for l in (OUT/'training-log.jsonl').read_text(encoding='utf-8').splitlines()]
    steps=[r for r in log if r['event']=='training_step']
    for lr in [1e-5,2e-5]:
        run=f'lr-{lr:.0e}'
        for epoch,total in enumerate(cfg['steps_per_epoch'],1):
            these=[r for r in steps if r['run']==run and r['epoch']==epoch]
            assert len(these)==total
            assert Counter(r['mode'] for r in these)['reviewed_triplet']==34
            assert all(r['batch_size']==1 if r['mode']=='reviewed_triplet' else 2<=r['batch_size']<=8 for r in these)
    project=ROOT.parents[2]
    old=json.loads((project/'backups/before-e5-finetuning-20260915-110931/file-manifest.json').read_text(encoding='utf-8'))
    originals={r['path']:r['sha256'] for r in old if r['archive']=='project.zip'}
    protected=json.loads((ROOT/'production-unchanged-check.json').read_text(encoding='utf-8'))
    for name in protected:assert sha(project/name)==originals[name],name
    before=(ROOT/'search-environment-before-training.txt').read_text(encoding='utf-8-sig').splitlines()
    after=subprocess.check_output([str(project/'ml_search/.venv/Scripts/python.exe'),'-m','pip','freeze'],text=True).splitlines()
    assert sorted(before)==sorted(after)
    report={'passed':True,'trained_runs':2,'evaluated_trained_checkpoints':6,'total_optimizer_steps':len(steps),
        'dev_families_with_positive_answers':16,'positive_dev_queries':48,'no_match_dev_queries_not_in_ranking_selection':12,
        'selected_by_preregistered_dev_only_rule':True,'selected_copy_matches_checkpoint':True,
        'production_files_unchanged':len(protected),'service_environment_unchanged':True,'frozen_assessment_unchanged':True,
        'test_model_evaluation_performed':False,'preliminary_run_not_in_comparison':True}
    (OUT/'validation-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
