"""Build only catalog-grounded positives; mined negatives are reviewed separately."""
from pathlib import Path
import hashlib
import json
import re
from difflib import SequenceMatcher
from collections import Counter
from .training_seeds import SEEDS
from .validate_assessment import main as validate_assessment
from ml_search.catalog import load_catalog
from ml_search.config import Settings

OUT=Path(__file__).parent/'training'
SOURCE=OUT.parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def norm(t):return re.sub(r'\W+',' ',t.lower().replace('ё','е')).strip()
def main():
    validate_assessment()
    OUT.mkdir(exist_ok=True)
    policy=json.loads((SOURCE/'split-policy.json').read_text(encoding='utf-8'))
    settings=Settings.from_env('small')
    books={b.catalog_id:b for b in load_catalog(settings.catalog_path,settings.import_report_path)}
    reserved=[]
    for name in ('dev_queries.json','test_queries.frozen.json','audit_cases.json'):
        reserved += [{**r,'source':name} for r in json.loads((SOURCE/name).read_text(encoding='utf-8'))]
    reserved += [{**r,'source':'evaluation_queries.json'} for r in json.loads((settings.project_root/'ml_search/evaluation_queries.json').read_text(encoding='utf-8'))]
    examples=[]
    seen=set()
    ids=set()
    overlaps=[]
    for bid,cluster,anchor,queries in sorted(SEEDS):
        assert bid in policy['training_eligible_book_ids'],bid
        assert bid not in ids,bid
        ids.add(bid)
        book=books[bid]
        assert anchor in book.search_text,(bid,anchor)
        assert len(queries)==8,bid
        for v,query in enumerate(queries,1):
            nq=norm(query)
            assert nq not in seen,query
            seen.add(nq)
            assert len(query)<=500
            assert not any(re.search('[а-яё]',word,re.I) and re.search('[a-z]',word,re.I) for word in query.split()),query
            closest=max(reserved,key=lambda r:SequenceMatcher(None,nq,norm(r['query']),autojunk=False).ratio())
            ratio=SequenceMatcher(None,nq,norm(closest['query']),autojunk=False).ratio()
            assert nq!=norm(closest['query'])
            query_id=f'TRAIN-B{bid:04}-V{v}'
            overlaps.append({'query_id':query_id,'reserved_source':closest['source'],
                'reserved_id':closest.get('query_id',closest.get('book_id',closest.get('category'))),
                'character_similarity':round(ratio,4)})
            kind='nonfiction' if any(g in book.genres for g in ['Саморазвитие','Психология','Бизнес и экономика','История','Компьютеры и технологии','Научно-популярная литература','Биографии и мемуары','Религия','Философия']) and 'Классическая литература' not in book.genres else 'fiction_or_children'
            examples.append({'example_id':query_id,'group_id':f'TRAIN-B{bid:04}',
                'query':query,'positive_catalog_id':bid,'positive_product_id':book.product_id,
                'positive_title':book.title,'positive_author':book.author,'positive_passage':book.search_text,
                'positive_grade':2,'positive_label':'хорошо подходит',
                'intent_criterion':query,'positive_explanation':f'Запрос соответствует сведениям текущего профиля «{book.title}»; сюжетные и тональные требования проверены редакционно по приведённому полному профилю.',
                'evidence_anchor':anchor,'evidence_source':f'data/book_catalog/catalog.json#id={bid}',
                'positive_profile_sha256':hashlib.sha256(book.search_text.encode()).hexdigest(),
                'compatibility_cluster':cluster,'book_kind':kind,'source':'manually_authored_synthetic',
                'review_status':'assistant_editorial_review_against_catalog',
                'negative_catalog_id':None,'negative_passage':None,'negative_explanation':None})
    assert len(examples)==512 and len(ids)==64,(len(examples),len(ids))
    (OUT/'train_pairs.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in examples),encoding='utf-8')
    conflicts=[]
    for a in sorted(ids):
        ca=next(s[1] for s in SEEDS if s[0]==a)
        for b in sorted(ids):
            if b<=a:continue
            cb=next(s[1] for s in SEEDS if s[0]==b)
            shared_themes=set(books[a].themes)&set(books[b].themes)
            same_series=books[a].series and books[a].series==books[b].series
            if ca==cb or shared_themes or same_series:
                conflicts.append({'book_a':a,'book_b':b,'reason':'same_compatibility_cluster' if ca==cb else 'shared_theme_or_series',
                                  'shared_themes':sorted(shared_themes)})
    (OUT/'batch-policy.json').write_text(json.dumps({'training_excluded_book_ids':policy['training_excluded_book_ids'],
        'do_not_place_as_in_batch_negatives':conflicts,
        'rules':['Never put two variants or duplicate passages of the same positive book in one batch.',
            'Avoid every listed compatibility pair as in-batch negatives; uncertainty is not a negative label.',
            'Apply reserved-book exclusions to ALL documents in batches, including explicit negatives.',
            'Do not automatically add mined candidates to training.',
            'Do not assume every other document is irrelevant; use checked triplets or conservative batches if ambiguity persists.'],
        'limitation':'Conservative compatibility screen, not exhaustive multi-positive relevance labeling.'},ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'leakage-screen.json').write_text(json.dumps({'train_examples':len(examples),'books':len(ids),
        'excluded_positive_books':0,'exact_duplicates_with_reserved_queries':0,
        'max_character_similarity':max(r['character_similarity'] for r in overlaps),
        'top_30_overlap_pairs':sorted(overlaps,key=lambda r:r['character_similarity'],reverse=True)[:30],
        'manual_review_required':'Review closest pairs by intent before finalizing; string similarity is not semantic proof.'},ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'positive-build-summary.json').write_text(json.dumps({'pairs':len(examples),'books':len(ids),
        'clusters':dict(Counter(s[1] for s in SEEDS)), 'catalog_sha256':sha(settings.catalog_path),
        'source_sha256':sha(SOURCE/'training_seeds.py'),'model_training_started':False,
        'review_basis':'Assistant editorial verification against exact catalog profiles; no independent human review.'},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Built',len(examples),'pairs for',len(ids),'books')

if __name__=='__main__':main()
