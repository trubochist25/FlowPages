"""Archive review artifacts separately from the complete model baseline."""
from pathlib import Path
import json,zipfile,hashlib
from .prepare_integration_review import sha
ROOT=Path(__file__).parent;PROJECT=ROOT.parents[2];OUT=ROOT/'integration_review_v1'
def main():
    files=[p for p in OUT.rglob('*') if p.is_file() and 'validation' not in p.relative_to(OUT).parts and p.name not in {'materials-manifest.json','materials-backup-verification.json'}]
    files += [ROOT/n for n in ['prepare_integration_review.py','prepare_fresh_queries.py','score_pooled_review.py','extend_agent_review_pilot.py','validate_integration_review.py','package_review_materials.py','integration-review-preparation.log','fresh-queries-preparation.log','integration-review-validation.log']]
    hashes={p.relative_to(PROJECT).as_posix():sha(p) for p in files}
    manifest=OUT/'materials-manifest.json'
    manifest.write_text(json.dumps({'files_sha256':hashes,'baseline_backup':'backups/e5-integration-baseline-20260915-v1.zip',
        'public_blind_pool_unlabeled':True,'agent_reviewed_queries':2,'agent_reviewed_pairs':63,'full_pooled_review_completed':False,
        'new_test_ready':False,'new_query_drafts':150,'production_modified':False,'review_ui_javascript_syntax_checked':True},indent=2),encoding='utf-8')
    archive=PROJECT/'backups/e5-integration-review-materials-20260915-v1.zip';assert not archive.exists()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files+[manifest]:z.write(p,p.relative_to(PROJECT).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for n,h in hashes.items():assert hashlib.sha256(z.read(n)).hexdigest()==h,n
    verification={'path':str(archive),'sha256':sha(archive),'bytes':archive.stat().st_size,'files_verified':len(files)+1,'all_archived_hashes_match':True}
    (OUT/'materials-backup-verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8');print(json.dumps(verification))
if __name__=='__main__':main()
