"""Validate, report, and archive the integration comparison."""
from pathlib import Path
import json,hashlib,zipfile
from .prepare_integration_review import sha
ROOT=Path(__file__).parent;OUT=ROOT/'integration_variants_v2';PROJECT=ROOT.parents[2]
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def main():
    x=read(OUT/'results.json');fast=read(OUT/'fast-resolver-validation.json');stress=read(OUT/'resolver-heldout-stress.json');engine=read(OUT/'real-engine-validation.json')
    assert x['selected']=='new_entity' and fast['passed'] and engine['all_resolved_targets_rank1']
    assert stress['summary']['title_accuracy']==1 and stress['summary']['thematic_activation_rate']==0
    snap=read(ROOT/'integration_review_v1/baseline/snapshot-manifest.json')
    for n,h in snap['sources_sha256'].items():assert sha(PROJECT/n)==h,n
    frozen=read(ROOT/'integration_review_v1/new-assessment/split-policy.json')
    for n,h in frozen['freeze_draft_sha256'].items():assert sha(ROOT/'integration_review_v1/new-assessment'/n)==h,n
    m=x['metrics'];d=x['opened_test_diagnostic_after_selection']
    lines=['# Сравнение вариантов интеграции новой модели FlowPages','',
    '## Рекомендация','',
    'Лучший следующий вариант — новая модель с её индексом плюс отдельный быстрый распознаватель названий до тематического разбора запроса. Старая модель и объединение двух семантических выдач для этого варианта не нужны.',
    'Это экспериментальный прототип, не изменение рабочего поиска. Его следует перенести в QueryCorrector за переключателем, проверить на размеченной проверочной выборке и только затем один раз оценить новым закрытым тестом.','',
    '## Сравнение','',
    '| Вариант | Dev NDCG@10 | Dev Hit@3 | 77 Hit@1 | 77 Hit@3 | 77 Hit@10 |','|---|---:|---:|---:|---:|---:|']
    labels={'old':'Старая система','new_current':'Новая как сейчас','new_entity':'Новая + названия','route_old_for_entity':'Старая для распознанных названий, новая для остальных','rrf_new_1.5':'RRF, вес новой 1,5','entity_rrf_new_1.5':'Названия + RRF, вес новой 1,5'}
    for n,label in labels.items():
        v=m[n];lines.append(f"| {label} | {v['dev']['ndcg10']:.4f} | {v['dev']['hit3']:.2%} | {v['regression77']['hit1']:.2%} | {v['regression77']['hit3']:.2%} | {v['regression77']['hit10']:.2%} |")
    lines += ['', 'Вариант выбран только по 51 положительному dev-запросу (17 семейств) с ограничениями по 77 регрессионным запросам. Двенадцать dev-запросов без соответствия не входят в NDCG/Hit. Старый открытый тест не участвовал в выборе.',
    f"После выбора диагностический открытый тест дал для выбранного варианта те же предварительные показатели, что и новая модель: NDCG@10 {d['new_entity']['ndcg10']:.4f}, Hit@3 {d['new_entity']['hit3']:.2%}, Hit@10 {d['new_entity']['hit10']:.2%}. Это контроль, а не независимое подтверждение.",'',
    '## Почему выбран распознаватель названий','',
    '- Он сохранил dev NDCG@10 0,9819 и Hit@3/10 100%. На dev не было ни одного срабатывания, поэтому смысловая выдача не изменилась.',
    '- На 77 запросах Hit@1 вырос с 68/77 у новой системы до 70/77; Hit@3 — с 71/77 до 73/77; Hit@10 — с 75/77 до 76/77.',
    '- «гарри потр философкий камин» и «татуировка дракона» вернулись на первое место.',
    '- Через настоящий механизм итогового расчёта все семь распознанных навигационных случаев получили нужную книгу на первом месте. Четыре уже распознавались прежним кодом или были добавлены новой веткой fuzzy_title; три обычных навигационных случая сохранили действующую ветку title.',
    '- Поиск авторов менять сейчас не требуется: ранее проверенные авторские запросы и строгие авторские фильтры проходят. Новый компонент ограничен названиями.', '',
    '## Устойчивость распознавания','',
    '| Проверка | Результат |','|---|---:|',
    f"| 300 названий с удалённой буквой | {x['resolver']['top1_accuracy']:.2%} |",
    f"| 200 других названий с перестановкой букв | {stress['summary']['title_accuracy']:.2%} |",
    f"| 200 тематических запросов: ложные срабатывания | {stress['summary']['thematic_activation_rate']:.2%} |",
    '| 150 новых синтетических смысловых запросов: срабатывания | 0 |',
    '| 60 существующих dev-запросов: срабатывания | 0 |','',
    'Два пропуска в первой проверке — два тома Heartstopper, которые после удаления номера превращаются в одинаковую строку. Отказ от автоматического выбора в таком случае является безопасным поведением.',
    f"Индексированный прототип проверен на {fast['same_decisions_as_reference_cases']} ранее вычисленных случаях. Построение индекса названий занимает {fast['construction_ms_not_in_query_latency']:.1f} мс при запуске. На 1540 измерениях среднее время распознавания {fast['latency']['mean_ms']:.2f} мс, p95 {fast['latency']['p95_ms']:.2f} мс. Полное время после переноса в сервис нужно измерить отдельно; рабочий ориентир p95 допускает около 233 мс сверх исходных 1165 мс.",'',
    '## Почему не выбран поиск двумя моделями','',
    'Reciprocal Rank Fusion улучшил отдельные старые регрессии, но снизил dev NDCG@10 с 0,9819 до 0,9688. В трёх смысловых запросах известная подходящая книга сдвинулась с первого места на третье; в одном случае «Идиот» поднялся с третьего на первое.',
    'Двойная выдача также требует хранить и запускать обе модели и оба индекса. При текущих данных это лишняя сложность без общего выигрыша. В эксперименте объединялись сохранённые top-10, поэтому более глубокий RRF не объявляется окончательно бесполезным; к нему стоит возвращаться только при ошибках, которые не решает маршрутизация.', '',
    '## Почему пока не меняются веса','',
    'Диагностика показала, что приведение новой шкалы к старой восстанавливает часть ухудшений, но одновременно сдвигает «Шестёрку воронов» с 1-го на 11-е место и «Возлюбленную» с 1-го на 7-е. Глобальная перекалибровка сейчас менее надёжна, чем локальное исправление распознавания названий.', '',
    '## Лучший порядок действий','',
    '1. Перенести FastTitleResolver в экспериментальную ветку QueryCorrector. Решение должно выполняться до извлечения жанров, а уверенно распознанной книге назначать существующий fuzzy_title.',
    '2. Добавить переключатель новой пары «модель + индекс» и переключатель распознавателя. Исходный поиск оставить доступным для отката.',
    '3. Разметить 51 подготовленный dev-запрос и отдельный набор реальных либо независимо составленных навигационных опечаток. Нынешние пороги проверялись на известных регрессиях и синтетических искажениях.',
    '4. Проверить полное время, фильтры, авторов, пустую выдачу, «Алхимию» и рекомендации в экспериментальном экземпляре.',
    '5. Зафиксировать вариант и один раз открыть 99 новых тестовых запросов только после завершения их независимой разметки и резервирования тестовых книг.',
    '6. Если появятся смысловые регрессии, исследовать маршрутизацию или более глубокий RRF. Повторное обучение и общую смену весов пока отложить.', '',
    '## Ограничения','',
    '- Проверочная и старая тестовая разметка синтетическая и неполная.',
    '- RRF сравнивался по сохранённым top-10, а не по полным спискам кандидатов.',
    '- Стресс-тесты названий автоматически построены из каталога; они не заменяют реальные опечатки посетителей.',
    '- Порог распознавателя уточнялся после известных ошибок, поэтому итог требует новой независимой навигационной проверки.',
    '- Новые 99 тестовых запросов не запускались и не использовались для выбора.', '',
    'Артефакты: results.json, resolver-probes.json, resolver-heldout-stress.json, fresh-query-resolver-screen.json, real-engine-validation.json, fast-resolver-validation.json.',
    f"Бэкап: `{PROJECT/'backups/e5-integration-variants-20260916-v1.zip'}`."]
    report=OUT/'INTEGRATION_VARIANTS_REPORT.md';report.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    validation={'passed':True,'selected':'new_entity','dev_not_worse_than_new':m['new_entity']['dev']==m['new_current']['dev'],
        'regression_hit1_improved':m['new_entity']['regression77']['hit1']>m['new_current']['regression77']['hit1'],
        'real_engine_targets_rank1':engine['all_resolved_targets_rank1'],'fast_resolver_same_decisions':fast['passed'],
        'heldout_title_accuracy':stress['summary']['title_accuracy'],'heldout_thematic_false_activation_rate':stress['summary']['thematic_activation_rate'],
        'fresh_test_model_results_opened':False,'production_modified':False,'baseline_sources_unchanged':len(snap['sources_sha256'])}
    (OUT/'validation.json').write_text(json.dumps(validation,indent=2),encoding='utf-8')
    files=[p for p in OUT.rglob('*') if p.is_file()]+[ROOT/n for n in ['compare_integration_variants.py','fast_title_resolver.py','validate_fast_title_resolver.py','validate_entity_prototype.py','finish_integration_variants.py','integration-entity-prototype.log']]
    hashes={p.relative_to(PROJECT).as_posix():sha(p) for p in files};manifest=OUT/'manifest.json';manifest.write_text(json.dumps({'files_sha256':hashes,'production_modified':False,'selected_variant':'new_entity'},indent=2),encoding='utf-8')
    archive=PROJECT/'backups/e5-integration-variants-20260916-v1.zip';assert not archive.exists()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files+[manifest]:z.write(p,p.relative_to(PROJECT).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for n,h in hashes.items():assert hashlib.sha256(z.read(n)).hexdigest()==h,n
    (OUT/'backup-verification.json').write_text(json.dumps({'path':str(archive),'sha256':sha(archive),'all_archived_hashes_match':True,'bytes':archive.stat().st_size},indent=2),encoding='utf-8')
    print(json.dumps(validation))
if __name__=='__main__':main()
