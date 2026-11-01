"""Validate completed comparison and publish report; never rerank the closed test."""
from pathlib import Path
import json, math, hashlib, subprocess, unicodedata, zipfile
import numpy as np
from .compare_selected_model import engines, SearchRequest, SearchFilters

ROOT=Path(__file__).parent
OUT=ROOT/'comparison'
PROJECT=ROOT.parents[2]
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x): (OUT/n).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def canon(s): return unicodedata.normalize('NFKC',s).casefold().replace('ё','е').strip()

def main():
    decision=read(OUT/'decision.json')  # Timing must finish before additional model calls.
    prereg=read(OUT/'comparison-preregistration.json')
    assert sha(ROOT/'compare_selected_model.py')==prereg['code_sha256']
    assert sha(OUT/'acceptance-criteria.json')==prereg['criteria_sha256']
    assert sha(ROOT/'limited_experiment/experiment-manifest.json')==prereg['selected_manifest_sha256']
    for n,h in prereg['frozen_files'].items(): assert sha(ROOT/n)==h,n
    old=read(PROJECT/'backups/before-e5-finetuning-20260915-110931/file-manifest.json')
    originals={r['path']:r['sha256'] for r in old if r['archive']=='project.zip'}
    protected=read(ROOT/'production-unchanged-check.json')
    for n in protected: assert sha(PROJECT/n)==originals[n],n
    manifest=read(OUT/'index/manifest.json')
    assert sha(OUT/'index/book-index.npz')==manifest['index_sha256']
    assert sha(ROOT/'limited_experiment/selected-model/model.safetensors')==manifest['model_safetensors_sha256']
    assert sha(PROJECT/'data/book_catalog/catalog.json')==manifest['catalog_sha256']
    with np.load(OUT/'index/book-index.npz',allow_pickle=False) as data:
        assert data['vectors'].shape==(1000,384) and np.isfinite(data['vectors']).all()
        assert np.max(np.abs(np.linalg.norm(data['vectors'],axis=1)-1))<1e-5
        with np.load(PROJECT/'data/ml_search/indexes/multilingual-e5-small/book-index.npz',allow_pickle=False) as base:
            assert np.array_equal(data['product_ids'],base['product_ids'])
    before=(ROOT/'search-environment-before-training.txt').read_text(encoding='utf-8-sig').splitlines()
    after=subprocess.check_output([str(PROJECT/'ml_search/.venv/Scripts/python.exe'),'-m','pip','freeze'],text=True).splitlines()
    assert sorted(before)==sorted(after)
    test=read(OUT/'test-results.json'); frozen=read(ROOT/'test_queries.frozen.json')
    cases={c['query_id']:c for c in frozen}
    train=[json.loads(l) for l in (ROOT/'training/train.jsonl').read_text(encoding='utf-8').splitlines()]
    seen={r['positive_catalog_id'] for r in train}|{r['negative_catalog_id'] for r in train if r['negative_catalog_id'] is not None}|{a['catalog_id'] for r in train for a in r.get('additional_compatible_positives',[])}
    for name in test:
        for mode in test[name]:
            rows=test[name][mode]['rows'];assert {r['query_id'] for r in rows}==set(cases) and len(rows)==120
            for r in rows:
                c=cases[r['query_id']];g={j['catalog_id']:j['grade'] for j in c['judgments']}
                assert r['query']==c['query'] and r['group_id']==c['group_id']
                good={i for i,v in g.items() if v==2};assert not good&seen
                assert r['known_grades']==[g.get(i) for i in r['top_ids']]
                ideal=sum((2**v-1)/math.log2(k+2) for k,v in enumerate(sorted(g.values(),reverse=True)[:10]))
                dcg=sum((2**g.get(i,0)-1)/math.log2(k+2) for k,i in enumerate(r['top_ids']))
                assert abs(r['ndcg10_provisional']-(dcg/ideal if ideal else 0))<1e-12
    reg=read(OUT/'regression77.json')
    navigation=[]
    for a,b in zip(reg['original']['rows'],reg['selected']['rows']):
        if a['category'] in {'navigational','partial_title','author_only','typo'}:
            navigation.append({'query':a['query'],'category':a['category'],'old_rank':a['rank'],'new_rank':b['rank'],'new_failure':a['rank'] is not None and a['rank']<=3 and (b['rank'] is None or b['rank']>3)})
    es=engines(); checks={}
    probes=read(OUT/'search-safeguards.json')['original']['cases']
    for name,e in es.items():
        byid={b.product_id:b for b in e.books};rows=[]
        for p in probes:
            req=SearchRequest(**p['request']);res=e.search(req);books=[byid[r.product_id] for r in res.results]
            if p['name'].startswith('author-'):
                ok=bool(books) and all(canon(b.author)==canon(req.query) for b in books[:3])
            elif p['name'].startswith('filter-'):
                f=req.filters;ok=True
                for b in books:
                    for field,lo,hi in [('pages',f.pages_min,f.pages_max),('price',f.price_min,f.price_max),('year',f.year_min,f.year_max)]:
                        v=getattr(b,field);ok &= (lo is None or v>=lo) and (hi is None or v<=hi)
                    for selected,actual in [(f.authors,[b.author]),(f.genres,b.genres),(f.moods,b.moods),(f.paces,[b.pace]),(f.age_ratings,[b.age_rating])]:
                        ok &= not selected or bool({canon(s) for s in selected}&{canon(s) for s in actual})
            elif p['name']=='empty':ok=bool(books) and res.state=='results'
            else:ok=not books and res.state==p['request'].get('expected_state',{'punctuation':'invalid_query','impossible-filter':'no_matches'}[p['name']])
            rows.append({'name':p['name'],'passed':bool(ok),'state':res.state,'product_ids':[r.product_id for r in res.results]})
        checks[name]={'cases':rows,'failures':[r['name'] for r in rows if not r['passed']]}
    write('independent-functional-check.json',{'search':checks,'navigation':navigation,'navigation_new_failures':[r for r in navigation if r['new_failure']],
        'harness_corrections':['Author comparison canonicalizes ё/е; Фёдор and Федор denote the same author.','Empty input intentionally browses popular books; punctuation is invalid input.'],
        'empty_browse_same_order':checks['original']['cases'][-3]['product_ids']==checks['selected']['cases'][-3]['product_ids']})
    validation={'passed':not any(c['failures'] for c in checks.values()),
        'protected_production_files_unchanged':len(protected),'service_environment_unchanged':True,'frozen_assessment_unchanged':True,
        'model_index_catalog_hashes_match':True,'closed_test_metrics_recomputed_from_saved_results':True,
        'all_108_positive_test_queries_target_unseen_books':True,'navigation_cases_checked':len(navigation),'production_replaced':False}
    write('validation-results.json',validation)
    assert validation['passed'],validation
    final_decision=dict(decision)
    final_decision['checks']=dict(decision['checks'])
    final_decision['checks']['no_new_navigation_failures']=not any(r['new_failure'] for r in navigation)
    final_decision['all_numeric_and_safety_criteria_pass']=all(final_decision['checks'].values())
    final_decision['navigation_scope_correction']='Includes navigational, partial_title, author_only and typo; initial script omitted the last three categories.'
    final_decision['navigation_new_failures']=[r for r in navigation if r['new_failure']]
    final_decision['decision']='Keep original production search: new navigation failures violate pre-agreed criteria. Large provisional semantic gains justify a later separately evaluated experiment, not deployment of this checkpoint.'
    write('final-decision.json',final_decision)
    decision=final_decision
    stability=read(OUT/'stability.json');lat=read(OUT/'latency.json')['summary'];alc=read(OUT/'alchemy-comparison.json');rec=read(OUT/'recommendation-comparison.json');dev=read(OUT/'dev-results.json')
    lines=['# Сравнение исходной и дообученной модели FlowPages','',
        '## Решение','',
        'Согласованные численные критерии '+('выполнены' if decision['all_numeric_and_safety_criteria_pass'] else 'не выполнены')+'. Рабочий поиск сохранён. Выбор модели после открытия теста не менялся.',
        'Рекомендация: не подключать эту версию. Дополнительная проверка частичных названий и опечаток выявила новые навигационные ошибки, что нарушает согласованный критерий. Прирост семантики оправдывает дальнейший отдельный эксперимент. Текущий закрытый тест нельзя использовать для выбора новой версии.',
        'NDCG предварительный: большинство книг в выдаче не размечены. Перед последующим решением следует дополнить оценки объединённой выдачи обеих моделей.','',
        '## Данные и метод','',
        'Закрытый тест: 120 запросов, 40 семейств; 108 запросов с подходящими книгами (36 семейств) и 12 без соответствия в каталоге. Все положительные тестовые книги исключены из положительных и отрицательных обучающих примеров. Подгруппа обученных тестовых книг пуста.',
        'Модель выбрана только по 60 проверочным запросам: E5 small, lr=1e-5, эпоха 3. Отдельно пересчитаны все 1000 книг; размерность 384, префиксы E5 и нормализация сохранены. Описания, правила и веса полной системы одинаковы.',
        'Запросы и оценки составлены агентом по каталогу; независимой человеческой разметки нет. Оценки 2/1/0 дают прирост 3/1/0 в NDCG. Неразмеченные результаты получают нулевой вклад при вычислении, но не объявляются неподходящими. Метрики усреднены по семействам. Hit означает хотя бы одну книгу с оценкой «хорошо подходит». Запросы без соответствия исключены из NDCG/Hit.','',
        '## Закрытый тест','', '| Режим | Модель | NDCG@10, предварительный | Hit@3 | Hit@10 | CPU p95, мс |','|---|---|---:|---:|---:|---:|']
    for mode,label in [('semantic','Семантика'),('full','Полная система')]:
        for name,title in [('original','Исходная'),('selected','Новая')]:
            s=test[name][mode]['summary'];lines.append(f"| {label} | {title} | {s['ndcg10_provisional']:.4f} | {s['hit3']*100:.2f}% | {s['hit10']*100:.2f}% | {lat[name][mode]['p95_ms']:.2f} |")
    lines += ['', 'Время: обе модели на CPU, 4 потока, прогрев, без кеша векторов запросов; 3 перемежающихся прохода по 120 запросам, 360 измерений на модель и режим. Это локальное время движка, без HTTP и сетевых задержек.','', '### Группы запросов','', '| Группа | Режим | NDCG исходная → новая | Hit@3 исходная → новая | Hit@10 исходная → новая |','|---|---|---:|---:|---:|']
    labels={'plot':'Пересказ','mood':'Настроение','atmosphere':'Атмосфера','colloquial':'Разговорные','negation':'Отрицания'}
    for c,label in labels.items():
        for mode in ['semantic','full']:
            a=test['original'][mode]['by_category'][c];b=test['selected'][mode]['by_category'][c]
            lines.append(f"| {label} | {mode} | {a['ndcg10_provisional']:.3f} → {b['ndcg10_provisional']:.3f} | {a['hit3']*100:.1f}% → {b['hit3']*100:.1f}% | {a['hit10']*100:.1f}% → {b['hit10']*100:.1f}% |")
    lines += ['', '### Устойчивость','']
    for mode in ['semantic','full']:
        s=stability[mode];ci=s['paired_family_bootstrap_95_percent'];lo=s['leave_one_family_out_range']
        lines.append(f"- {mode}: прирост {s['ndcg10_gain']:.4f}; 95% интервал парного bootstrap по семействам [{ci[0]:.4f}; {ci[1]:.4f}] (5000 повторов); исключение одного семейства [{lo[0]:.4f}; {lo[1]:.4f}]. Улучшились {s['improved_families']}, ухудшились {s['worsened_families']}, без изменений {s['unchanged_families']} семейств.")
    lines += ['', 'Этот интервал отражает вариативность запросов в имеющейся разметке и не устраняет её неполноту или редакторское смещение.','', '### Проверочная выборка (не закрытый тест)','']
    for mode in ['semantic','full']:
        a=dev['original'][mode]['summary'];b=dev['selected'][mode]['summary']
        lines.append(f"- {mode}, 48 положительных запросов: NDCG {a['ndcg10_provisional']:.4f} → {b['ndcg10_provisional']:.4f}; Hit@3 {a['hit3']:.2%} → {b['hit3']:.2%}; Hit@10 {a['hit10']:.2%} → {b['hit10']:.2%}.")
    lines += ['', '## Критерии и регрессии','']
    for k,v in decision['checks'].items():lines.append(f"- {k}: {'PASS' if v else 'FAIL'}.")
    lines += ['', '| 77 регрессионных запросов | Исходная | Новая |','|---|---:|---:|']
    for k in ['hit_at_1','hit_at_3','hit_at_10','ndcg_at_10']:
        if k in reg['original']['metrics']:lines.append(f"| {k} | {reg['original']['metrics'][k]:.4f} | {reg['selected']['metrics'][k]:.4f} |")
    lines += ['', 'Hit@3 на регрессионных запросах: 72/77 → 71/77 (−1,30 процентного пункта, допуск 2). Hit@10: 75/77 → 75/77. Общие показатели укладываются в допуск, но скрывают отдельные навигационные провалы.',
        'Дополнительная проверка 23 запросов по названиям, частичным названиям, авторам и опечаткам: «гарри потр философкий камин» — 1 → 4; «татуировка дракона» — 1 → за пределы top-10. Первичный скрипт ошибочно не включал категории partial_title, author_only, typo в навигационный критерий. Его исходный decision.json сохранён, исправленное итоговое решение — final-decision.json. Обязательный критерий отсутствия новых навигационных ошибок НЕ пройден.',
        'Независимая проверка 18 поисковых случаев на обеих моделях прошла: строгие ограничения цены, страниц, года, автора, жанра, настроения, темпа и возраста; пунктуация и невозможный фильтр. Пустой ввод штатно показывает популярные книги в одинаковом порядке. Два первоначальных предупреждения проверочного скрипта исправлены в отдельной проверке: Фёдор/Федор и неверное ожидание пустой выдачи при пустом вводе.','']
    for name in alc:lines.append(f"«Алхимия», {name}: {alc[name]['meaningful_cases']} рецептов, доля содержательных top-3 {alc[name]['meaningful_rate']:.1%}, p95 {alc[name]['p95_ms']:.2f} мс; все обязательные проверки пройдены.")
    lines += ['', 'Рекомендации: 25 случаев на модель; сохранены исключение покупок/корзины/избранного/якоря, число результатов, отсутствие повторов, существование книг, конечность оценок и объяснения. Метаданный показатель близости top-3 снизился с 1,000 до 0,952; это эвристика, а не оценка читательского соответствия.',
        'Пример ограничения эвристики: для «Хартстоппера» исходная модель рекомендовала «Макбета», новая — «Хорошо быть тихоней» и «Чудо». По описаниям новые книги ближе к школьной дружбе и принятию; у «Хорошо быть тихоней» атмосфера тяжелее. Для «48 законов власти» новая предлагает «Государя» и «Манифест Коммунистической партии» вместо подростковых финансов и «Дзена и искусства ухода за мотоциклом»: «Государь» явно тематически близок, «Манифест» подходит лишь частично. Это редакторский разбор двух примеров, не независимая оценка всей рекомендательной выдачи.','',
        '## Примеры изменений полной системы','', '| Запрос | Позиция подходящей книги: исходная → новая | Δ NDCG |','|---|---:|---:|']
    pairs=list(zip(test['original']['full']['rows'],test['selected']['full']['rows']))
    pairs=[(a,b,b['ndcg10_provisional']-a['ndcg10_provisional']) for a,b in pairs if not a['expected_empty']]
    chosen=sorted(pairs,key=lambda x:x[2],reverse=True)[:5]+sorted([p for p in pairs if p[2]<-1e-10],key=lambda x:x[2])
    for a,b,d in chosen:lines.append(f"| {a['query'].replace('|','/')} | {a['rank'] or '>10'} → {b['rank'] or '>10'} | {d:+.3f} |")
    lines += ['', '## Ограничения и сохранённые результаты','',
        'На 12 запросах без соответствия обе полные системы возвращают книги: правильная пустая выдача 0/12. Дообучение не решило отказ от неуместной выдачи. Отрицания проверены отдельной группой, но это не гарантия для любых отрицательных формулировок.',
        f"В среднем {test['original']['full']['summary']['unknown_top10_mean']:.2f} → {test['selected']['full']['summary']['unknown_top10_mean']:.2f} из 10 результатов полной системы не имеют оценки. Перед окончательным решением полезно вслепую разметить объединённые top-10 обеих моделей, допуская несколько подходящих книг. Закрытый тест не использовать для нового подбора этой модели.",
        'Исходные 8 защищённых файлов и зависимости рабочей поисковой среды совпадают с резервной копией. Экспериментальная модель и индекс существуют отдельно; рабочее подключение не изменялось.','',
        f"- Индекс: `{OUT/'index/book-index.npz'}`.",f"- Модель: `{ROOT/'limited_experiment/selected-model'}`.",
        '- Подробные результаты: test-results.json, dev-results.json, regression77.json, latency.json, stability.json, independent-functional-check.json, validation-results.json.',
        f"- Бэкап выбранной модели: `{PROJECT/'backups/e5-limited-experiment-selected-20260915-v1.zip'}`.",
        f"- Бэкап сравнения: `{PROJECT/'backups/e5-model-comparison-20260915-v1.zip'}`."]
    (OUT/'COMPARISON_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    files=[p for p in OUT.rglob('*') if p.is_file() and not any(part.startswith('cache-') for part in p.relative_to(OUT).parts) and p.name!='comparison-manifest.json']
    files += [ROOT/n for n in ['compare_selected_model.py','build_comparison_index.py','finalize_comparison.py','comparison.log','comparison-index-build.log']]
    hashes={str(p.relative_to(PROJECT)).replace('\\','/'):sha(p) for p in files}
    write('comparison-manifest.json',{'files_sha256':hashes,'selected_model_sha256':manifest['model_safetensors_sha256'],
        'backup_selected_model':'backups/e5-limited-experiment-selected-20260915-v1.zip',
        'closed_test_used_once':True,'final_decision':'comparison/final-decision.json','production_replaced':False})
    files.append(OUT/'comparison-manifest.json')
    backup=PROJECT/'backups/e5-model-comparison-20260915-v1.zip'
    assert not backup.exists(),'Do not overwrite comparison backup'
    with zipfile.ZipFile(backup,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:z.write(p,str(p.relative_to(PROJECT)))
    with zipfile.ZipFile(backup) as z:
        assert z.testzip() is None
        for n,h in hashes.items():assert hashlib.sha256(z.read(n)).hexdigest()==h,n
    write('backup-verification.json',{'path':str(backup),'sha256':sha(backup),'bytes':backup.stat().st_size,'entries_verified':len(files),'all_archived_hashes_match':True})
    print(json.dumps(validation))

if __name__=='__main__':main()
