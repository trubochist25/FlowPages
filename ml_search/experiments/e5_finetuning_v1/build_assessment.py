"""Create frozen catalog-grounded judgments without running the search model."""
from pathlib import Path
import json
import hashlib
import re
import collections
from .assessment_seeds import GROUPS

OUT=Path(__file__).parent
ROOT=OUT.parents[2]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,data):
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def norm(s): return re.sub(r'\W+',' ',s.lower().replace('ё','е')).strip()

def main():
    catalog_path=ROOT/'data/book_catalog/catalog.json'
    catalog=json.loads(catalog_path.read_text(encoding='utf-8'))
    books={b['id']:b for b in catalog}
    regression_path=ROOT/'ml_search/evaluation_queries.json'
    regression=json.loads(regression_path.read_text(encoding='utf-8'))
    old_titles={t for q in regression for t in q['expected_titles']+q.get('forbidden_titles',[])}
    old_ids={b['id'] for b in catalog if b['title'] in old_titles}
    swaps={71:'dev',154:'dev',98:'dev',88:'dev',145:'dev',184:'test',178:'test',176:'test',186:'test',191:'test'}
    replacements={54:([],[146]),89:([],[54]),71:([],[232]),154:([],[232]),98:([],[197]),
                  88:([],[216]),145:([],[215]),184:([178],[76]),178:([184],[54]),176:([],[129]),191:([],[123]),
                  119:([],[54]),177:([],[221]),215:([],[174]),197:([],[216]),186:([],[157]),202:([],[197])}
    rows={'test':[],'dev':[]}
    family=collections.Counter()
    for seed in GROUPS:
        split,bid,category,criterion,partial,negative,variants=seed
        split=swaps.get(bid,split)
        partial,negative=replacements.get(bid,(partial,negative))
        family[split]+=1
        group=f'{split.upper()}-G{family[split]:02}'
        judgments=[]
        positives=([bid] if bid else [])+([134] if bid==46 else [])
        if bid==46: partial=[]
        for grade,ids in [(2,positives),(1,partial),(0,negative)]:
            for book_id in ids:
                b=books[book_id]
                reason={2:'Профиль подтверждает основной критерий намерения.',
                        1:'Есть близкая тема или атмосфера, но не все отличительные условия намерения.',
                        0:'Профиль описывает другой тип конфликта или ситуацию; ключевое обязательное условие намерения не подтверждено.'}[grade]
                judgments.append({'catalog_id':book_id,'title':b['title'],'author':b['author'],'grade':grade,
                    'label':{2:'хорошо подходит',1:'частично подходит',0:'не подходит'}[grade],
                    'reason':reason,'evidence':b['searchText'],
                    'evidence_source':f'data/book_catalog/catalog.json#id={book_id}',
                    'profile_sha256':hashlib.sha256(b['searchText'].encode()).hexdigest()})
        for v,q in enumerate(variants,1):
            rows[split].append({'query_id':f'{group}-V{v}','group_id':group,'category':category,'query':q,
                'intent_criterion':criterion,'judgments':judgments,
                'expected_titles':[j['title'] for j in judgments if j['grade']==2],
                'forbidden_titles':[j['title'] for j in judgments if j['grade']==0],
                'expected_empty':bid is None,'judgment_basis':'catalog_profile_editorial',
                'unjudged_policy':'unknown_not_negative','source_style':'manually_authored_synthetic'})
    # No-match evidence uses catalog-wide topic scans, never search results.
    scans={'test':[r'\bzfs\b|freebsd',r'тибет.*(?:граммат|язык)|(?:граммат|язык).*тибет',
                   r'анкерн.*спуск|спуск.*анкерн',r'аэродинам|профил.*крыл|безмоторн.*планер'],
           'dev':[r'инсулином|хорк|хорьк',r'sinumerik|синумерик',r'санскрит.*(?:метрик|стихослож|размер)|(?:метрик|стихослож|размер).*санскрит',r'adaptec|адаптек']}
    scan_report=[]
    for split in ('test','dev'):
        groups=list(dict.fromkeys(r['group_id'] for r in rows[split] if r['expected_empty']))
        for group,pattern in zip(groups,scans[split]):
            matches=[b['id'] for b in catalog if re.search(pattern,b['title']+' '+b['annotation']+' '+b['searchText'],re.I)]
            scan_report.append({'group_id':group,'pattern':pattern,'matching_catalog_ids':matches,
                'scope':'All 1000 catalog titles, annotations, search profiles; not full books.',
                'interpretation':'No confirmed catalog answer. Lexical absence alone is not proof about full book contents.'})
            for row in rows[split]:
                if row['group_id']==group: row['no_match_evidence']={'pattern':pattern,'matching_catalog_ids':matches,
                    'status':'catalog_supported_no_match' if not matches else 'requires_review'}
    judged={split:{j['catalog_id'] for r in rows[split] for j in r['judgments']} for split in rows}
    assert not judged['test']&judged['dev'], judged['test']&judged['dev']
    assert not (judged['test']|judged['dev'])&old_ids
    assert len(rows['test'])==120 and len(rows['dev'])==60
    assert not {norm(r['query']) for r in rows['test']}&{norm(r['query']) for r in rows['dev']}
    assert all(len(r['query'])<=500 for rs in rows.values() for r in rs)
    assert all(not s['matching_catalog_ids'] for s in scan_report), scan_report
    # Extra guard: reserve same series and editions/collections carrying a reserved title.
    reserved_test=set(judged['test'])
    reserved_regression=set(old_ids)
    def expand(ids):
        series={books[i].get('series') for i in ids if books[i].get('series')}
        titles={norm(books[i]['title']) for i in ids if len(norm(books[i]['title']).split())>=2}
        return ids|{b['id'] for b in catalog if (b.get('series') and b.get('series') in series)
                or any(t in norm(b['title']) for t in titles)}
    reserved_test=expand(reserved_test)
    reserved_regression=expand(reserved_regression)
    assert not judged['dev']&reserved_test, judged['dev']&reserved_test
    excluded=reserved_test|reserved_regression|judged['dev']
    write('dev_queries.json',rows['dev'])
    write('test_queries.frozen.json',rows['test'])
    write('no-match-evidence.json',scan_report)
    write('split-policy.json',{'regression_path':str(regression_path),'regression_queries':len(regression),
        'regression_sha256':sha(regression_path),'test_heldout_book_ids':sorted(reserved_test),
        'regression_reserved_book_ids':sorted(reserved_regression),'dev_reserved_book_ids':sorted(judged['dev']),
        'training_excluded_book_ids':sorted(excluded),'training_eligible_book_ids':sorted(set(books)-excluded),
        'training_rules':['Exclude every listed book from positives, explicit negatives AND in-batch negatives.',
            'Exclude regression/dev/test queries, paraphrases and their intent families from training.',
            'Train/dev/test deduplication must be repeated when training examples exist.',
            'Freeze test; choose parameters/checkpoints using dev only; open test after final selection.',
            'Unjudged documents are unknown, not automatically irrelevant.',
            'Index all 1000 books for assessment, including held-out books.'],
        'test_family_count':family['test'],'dev_family_count':family['dev']})
    checks={'test_queries':len(rows['test']),'dev_queries':len(rows['dev']),
        'families':dict(family),'category_counts':{s:dict(collections.Counter(r['category'] for r in rs)) for s,rs in rows.items()},
        'test_judged_books':len(judged['test']),'dev_judged_books':len(judged['dev']),
        'cross_split_judged_books':0,'exact_query_duplicates':0,'regression_book_overlap':0,
        'empty_queries':{s:sum(r['expected_empty'] for r in rs) for s,rs in rows.items()},
        'catalog_sha256':sha(catalog_path),'search_evaluated_on_new_dev_test':False,
        'labels':'Editorial judgments based on catalog. Not human user behavior or exhaustive qrels.',
        'future_training_leakage_check':'Required after training data construction.'}
    write('assessment-validation.json',checks)
    write('freeze-manifest.json',{'version':1,'status':'frozen_before_training_and_parameter_selection',
        'files':{n:sha(OUT/n) for n in ['test_queries.frozen.json','dev_queries.json','split-policy.json','no-match-evidence.json','assessment-validation.json']},
        'catalog_sha256':sha(catalog_path),'regression_sha256':sha(regression_path)})
    print(json.dumps(checks,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
