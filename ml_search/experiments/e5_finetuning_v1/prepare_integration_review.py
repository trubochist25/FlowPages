"""Snapshot matched pairs and create source-blind pooled assessment material."""
from pathlib import Path
import json, hashlib, random, zipfile, subprocess, datetime, math
from dataclasses import asdict
from collections import Counter
from ml_search.config import Settings

ROOT=Path(__file__).parent; PROJECT=ROOT.parents[2]; OUT=ROOT/'integration_review_v1'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(4*1024*1024),b''):h.update(c)
    return h.hexdigest()
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    assert not OUT.exists(),'Do not overwrite frozen review material'
    OUT.mkdir(); s=Settings.from_env('small'); cat=read(s.catalog_path); books={b['id']:b for b in cat}
    current={k:str(v) if isinstance(v,Path) else v for k,v in asdict(s).items()}
    write(OUT/'baseline/current-settings.json',current)
    subprocess.run([str(PROJECT/'ml_search/.venv/Scripts/python.exe'),'-m','pip','freeze'],stdout=(OUT/'baseline/service-pip-freeze.txt').open('w',encoding='utf-8'),check=True)
    sources=list(s.local_model_path.rglob('*'))+list((ROOT/'limited_experiment/selected-model').rglob('*'))
    sources=[p for p in sources if p.is_file()]
    sources += [s.catalog_path,s.import_report_path,s.index_path,s.manifest_path,ROOT/'comparison/index/book-index.npz',ROOT/'comparison/index/manifest.json']
    sources += list((PROJECT/'ml_search').glob('*.py'))
    sources += [p for p in (ROOT/'comparison').rglob('*') if p.is_file() and not any(part.startswith('cache-') for part in p.relative_to(ROOT/'comparison').parts)]
    sources += [ROOT/'test_queries.frozen.json',ROOT/'dev_queries.json',ROOT/'freeze-manifest.json',ROOT/'training/training-manifest.json',ROOT/'limited_experiment/experiment-manifest.json',ROOT/'limited_experiment/selection.json']
    sources += list((OUT/'baseline').glob('*'))+[Path(__file__)]
    sources=sorted(set(sources)); hashes={p.relative_to(PROJECT).as_posix():sha(p) for p in sources}
    frozen=read(ROOT/'freeze-manifest.json')
    for n,h in frozen['files'].items():assert sha(ROOT/n)==h,n
    index=read(ROOT/'comparison/index/manifest.json')
    assert sha(ROOT/'comparison/index/book-index.npz')==index['index_sha256']
    assert sha(ROOT/'limited_experiment/selected-model/model.safetensors')==index['model_safetensors_sha256']
    snap={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sources_sha256':hashes,'original_settings':current,
        'experimental_pair':index,'old_77_role':'regression_only','old_120_role':'opened_diagnostic_only',
        'old_60_role':'development_already_used','production_modified':False}
    write(OUT/'baseline/snapshot-manifest.json',snap)
    archive=PROJECT/'backups/e5-integration-baseline-20260915-v1.zip';assert not archive.exists()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        for p in sources+[OUT/'baseline/snapshot-manifest.json']:z.write(p,p.relative_to(PROJECT).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for n,h in hashes.items():
            hh=hashlib.sha256()
            with z.open(n) as f:
                for c in iter(lambda:f.read(4*1024*1024),b''):hh.update(c)
            assert hh.hexdigest()==h,n
    write(OUT/'baseline/backup-verification.json',{'path':str(archive),'sha256':sha(archive),'bytes':archive.stat().st_size,'files_verified':len(hashes),'includes_both_models_and_indexes':True})
    print('Snapshot verified',flush=True)
    test=read(ROOT/'comparison/test-results.json');cases=read(ROOT/'test_queries.frozen.json')
    public=[];key=[];rng=random.Random(20260915);coverage=Counter(); unknown=Counter()
    for n,c in enumerate(cases,1):
        qid=f'Q{n:03}'; retrieved={}
        for name in ['original','selected']:
            for mode in ['semantic','full']:
                row=next(r for r in test[name][mode]['rows'] if r['query_id']==c['query_id'])
                retrieved[f'{name}/{mode}']=row['top_ids']
        judged={j['catalog_id']:j['grade'] for j in c['judgments']}
        ids=set(i for seq in retrieved.values() for i in seq)|set(judged); ids=sorted(ids);rng.shuffle(ids)
        candidates=[];mapping=[]
        for k,i in enumerate(ids,1):
            b=books[i];cid=f'{qid}-C{k:02}'
            candidates.append({'candidate_id':cid,'title':b['title'],'author':b['author'],'search_text':b['searchText'],'grade':None,'reason':''})
            mapping.append({'candidate_id':cid,'catalog_id':i,'old_grade':judged.get(i),'positions':{label:(seq.index(i)+1 if i in seq else None) for label,seq in retrieved.items()}})
            coverage['candidate_pairs']+=1;unknown['unjudged_pairs']+=int(i not in judged)
        public.append({'query_id':qid,'query':c['query'],'candidates':candidates,'query_match_status':'unreviewed'})
        key.append({'query_id':qid,'source_query_id':c['query_id'],'family':c['group_id'],'category':c['category'],'expected_empty_before_review':c['expected_empty'],'candidates':mapping})
    write(OUT/'blind-review/pool.json',public);write(OUT/'private/pool-key.json',key)
    write(OUT/'private/prior-qrels.json',cases)
    stats={'queries':len(public),**coverage,**unknown,'pool':'union of both models, semantic and full top-10, plus prior judged books',
        'model_labels_ranks_prior_grades_hidden':True,'fully_graded_queries':0,'independent_human_review_completed':False,
        'real_user_queries_available':False,'new_queries_must_be_marked_synthetic':True}
    write(OUT/'blind-review/status.json',stats)
    # How much unjudged documents can affect the current fixed-qrel conclusions.
    sens={}
    for mode in ['semantic','full']:
        a=test['original'][mode]['rows'];b=test['selected'][mode]['rows'];groups={}
        for old,new,c in zip(a,b,cases):
            if c['expected_empty']:continue
            g={j['catalog_id']:j['grade'] for j in c['judgments']}; union=set(old['top_ids'])|set(new['top_ids'])|set(g)
            def coeff(row,i):return 1/math.log2(row['top_ids'].index(i)+2) if i in row['top_ids'] else 0
            delta={i:coeff(new,i)-coeff(old,i) for i in union};known=sum((2**g[i]-1)*delta[i] for i in g)
            lower=known+sum(3*v for i,v in delta.items() if i not in g and v<0)
            upper=known+sum(3*v for i,v in delta.items() if i not in g and v>0)
            groups.setdefault(c['group_id'],[]).append((lower,upper))
        lows=[sum(x[0] for x in vv)/len(vv) for vv in groups.values()];highs=[sum(x[1] for x in vv)/len(vv) for vv in groups.values()]
        sens[mode]={'family_mean_dcg_gain_possible_lower':sum(lows)/len(lows),'family_mean_dcg_gain_possible_upper':sum(highs)/len(highs),
            'gain_sign_not_guaranteed_for_all_unjudged_assignments':sum(lows)<0<sum(highs),
            'note':'Adversarial DCG sensitivity, not estimated relevance and not an NDCG confidence interval; unknown grades may range 0..2.'}
    write(OUT/'qrel-sensitivity.json',sens)
    write(OUT/'prior-label-audit.json',{'profile_hash_mismatches':[{'query':c['query_id'],'book':j['catalog_id']} for c in cases for j in c['judgments'] if sha_text(books[j['catalog_id']]['searchText'])!=j['profile_sha256']],
        'queries_with_duplicate_judgments':[c['query_id'] for c in cases if len({j['catalog_id'] for j in c['judgments']})!=len(c['judgments'])],
        'families_editorially_inspected':40,'positive_book_choice_obvious_factual_errors_found':0,
        'review_scope':'Agent inspected one representative query, intention and book grades per family; not a blind independent full assessment.',
        'risks':['Prior qrels are sparse.','Several grades were shared across paraphrases; each concrete formulation must be reviewed separately.','Queries authored from catalog profiles favor explicit profile vocabulary.','No-match queries mostly technical manuals, not typical ambiguous reading preferences.']})
    build_html(public)
    print(json.dumps(stats),flush=True)

def sha_text(s):return hashlib.sha256(s.encode('utf-8')).hexdigest()
def build_html(pool):
    payload=json.dumps(pool,ensure_ascii=False).replace('<','\\u003c')
    html='''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Проверка книжной выдачи</title>
<style>body{font:16px system-ui;max-width:1000px;margin:30px auto;padding:0 20px;background:#f8f6f0;color:#23251f}header{position:sticky;top:0;background:#f8f6f0;padding:12px 0;border-bottom:1px solid #ccc}button,select,input{font:inherit;padding:8px;margin:3px}article{background:white;padding:20px;border-radius:12px;margin:18px 0}textarea{width:95%;font:inherit;padding:8px}p{line-height:1.55}.hint{color:#60655a}h2{font-size:22px}</style>
<header><b>Проверка соответствия книг запросу</b><div><button id="prev">← Назад</button><select id="nav"></select><button id="next">Далее →</button><button id="save">Скачать оценки</button><input type="file" id="load" accept=".json"><span id="progress"></span></div></header>
<p class="hint">Оценивайте каждый запрос отдельно. 2 — хорошо подходит; 1 — частично; 0 — не подходит. Если сведений недостаточно, оставьте «Не оценено». Не оценивайте по одному совпадению слов. Отдельно учитывайте атмосферу и отрицания. Источник результатов и исходные позиции скрыты.</p>
<p class="hint">Оценки сохраняются в этой вкладке; регулярно скачивайте файл. Перед закрытием вкладки обязательно скачайте оценки. Отсутствие подходящей книги среди кандидатов не доказывает отсутствие её во всём каталоге.</p><main id="main"></main>
<script>const pool=PAYLOAD;let pos=0;const nav=document.getElementById('nav');for(let i=0;i<pool.length;i++){let o=document.createElement('option');o.value=i;o.textContent=pool[i].query_id;nav.append(o)}
function el(tag,text){let e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e}
function draw(){nav.value=pos;let root=document.getElementById('main');root.replaceChildren();const q=pool[pos];root.append(el('h2',q.query));for(const c of q.candidates){let a=el('article');a.append(el('h3',c.title+' — '+c.author),el('p',c.search_text));let s=el('select');for(const [v,t] of [['','Не оценено'],['2','Хорошо подходит'],['1','Частично подходит'],['0','Не подходит']]){let o=el('option',t);o.value=v;s.append(o)}s.value=c.grade===null?'':String(c.grade);s.onchange=()=>{c.grade=s.value===''?null:Number(s.value);progress()};let t=el('textarea');t.placeholder='Причина оценки: какие условия выполнены или нарушены';t.value=c.reason;t.oninput=()=>c.reason=t.value;a.append(s,t);root.append(a)}progress()}
function progress(){let all=pool.flatMap(q=>q.candidates);document.getElementById('progress').textContent=all.filter(c=>c.grade!==null).length+' / '+all.length+' оценок'}
nav.onchange=()=>{pos=Number(nav.value);draw()};document.getElementById('prev').onclick=()=>{pos=Math.max(0,pos-1);draw()};document.getElementById('next').onclick=()=>{pos=Math.min(pool.length-1,pos+1);draw()};
document.getElementById('save').onclick=()=>{let data={schema_version:1,reviewer_type:'human_unconfirmed',queries:pool.map(q=>({query_id:q.query_id,candidates:q.candidates.map(c=>({candidate_id:c.candidate_id,grade:c.grade,reason:c.reason}))}))};let a=el('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.download='book-relevance-judgments.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
document.getElementById('load').onchange=async e=>{try{const x=JSON.parse(await e.target.files[0].text());let saved=new Map(x.queries.map(q=>[q.query_id,q]));for(const q of pool){let r=saved.get(q.query_id);if(!r)continue;let m=new Map(r.candidates.map(c=>[c.candidate_id,c]));for(const c of q.candidates){let v=m.get(c.candidate_id);if(v&&[null,0,1,2].includes(v.grade)){c.grade=v.grade;c.reason=String(v.reason||'')}}}draw()}catch(err){alert('Не удалось прочитать файл оценок')}};draw();</script></html>'''.replace('PAYLOAD',payload)
    (OUT/'blind-review/review.html').write_text(html,encoding='utf-8')

if __name__=='__main__':main()
