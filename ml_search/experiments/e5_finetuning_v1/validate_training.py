"""Validate dataset and protected artifacts without evaluating or training a model."""
from pathlib import Path
from collections import Counter
import hashlib
import json
from ml_search.catalog import load_catalog
from ml_search.config import Settings

ROOT = Path(__file__).parent
OUT = ROOT / 'training'
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def read(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))
def rows(name):
    return [json.loads(l) for l in (OUT / name).read_text(encoding='utf-8').splitlines()]

def main():
    settings = Settings.from_env('small')
    books = {b.catalog_id:b for b in load_catalog(settings.catalog_path, settings.import_report_path)}
    manifest = read('training-manifest.json')
    for name, digest in manifest['files'].items():
        assert sha(OUT / name) == digest, name
    assert sha(settings.catalog_path) == manifest['catalog_sha256']
    assert sha(settings.index_path) == manifest['original_index_sha256']
    assert sha(ROOT / 'freeze-manifest.json') == manifest['assessment_freeze_sha256']
    frozen = json.loads((ROOT / 'freeze-manifest.json').read_text(encoding='utf-8'))
    for name, digest in frozen['files'].items():
        assert sha(ROOT / name) == digest, name
    excluded = set(read('batch-policy.json')['training_excluded_book_ids'])
    train = rows('train.jsonl')
    assert len(train) == len({r['example_id'] for r in train}) == 512
    assert len({r['query'] for r in train}) == 512
    assert set(Counter(r['positive_catalog_id'] for r in train).values()) == {8}
    for r in train:
        bid = r['positive_catalog_id']
        assert bid not in excluded
        assert r['positive_passage'] == books[bid].search_text
        assert r['positive_product_id'] == books[bid].product_id
        assert r['evidence_anchor'] in r['positive_passage']
        assert hashlib.sha256(r['positive_passage'].encode()).hexdigest() == r['positive_profile_sha256']
        compatible = set()
        for a in r.get('additional_compatible_positives', []):
            compatible.add(a['catalog_id'])
            assert a['catalog_id'] not in excluded
            assert a['passage'] == books[a['catalog_id']].search_text
            assert a['product_id'] == books[a['catalog_id']].product_id
        if r['negative_catalog_id'] is not None:
            nid = r['negative_catalog_id']
            assert nid not in excluded | compatible | {bid}
            assert r['negative_passage'] == books[nid].search_text
            assert r['negative_product_id'] == books[nid].product_id
            assert r['negative_evidence_anchor'] in r['negative_passage']
            assert hashlib.sha256(r['negative_passage'].encode()).hexdigest() == r['negative_profile_sha256']
            assert r['negative_original_rank'] < r['positive_original_rank']
            assert r['negative_grade'] == 0 and r['negative_is_query_specific']
    triplets = rows('train_triplets.jsonl')
    assert triplets == [r for r in train if r['negative_catalog_id'] is not None]
    assert len(triplets) == 34
    log = read('candidate-review-log.json')['reviews']
    assert len(log) == 42
    assert {(r['example_id'],r['candidate_catalog_id']) for r in log if r['decision']=='accepted_negative'} == {(r['example_id'],r['negative_catalog_id']) for r in triplets}
    baseline = settings.project_root / 'backups/before-e5-finetuning-20260915-110931/file-manifest.json'
    original = {r['path']:r['sha256'] for r in json.loads(baseline.read_text(encoding='utf-8')) if r['archive']=='project.zip'}
    protected = json.loads((ROOT / 'production-unchanged-check.json').read_text(encoding='utf-8'))
    for name in protected:
        assert sha(settings.project_root / name) == original[name], name
    report = {'passed':True, 'examples':512, 'triplets_subset':34, 'reviewed_candidates':42,
              'protected_training_books':len(excluded), 'frozen_assessment_unchanged':True,
              'production_files_unchanged':len(protected), 'exact_search_profiles':True,
              'training_started':False, 'label_basis':'Assistant editorial review; no independent human review.'}
    (OUT / 'validation-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))

if __name__ == '__main__':
    main()
