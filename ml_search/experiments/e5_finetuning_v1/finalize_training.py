"""Add only individually checked original-model error candidates."""
from pathlib import Path
import json
import hashlib
import re
import unicodedata
from collections import Counter
from ml_search.catalog import load_catalog
from ml_search.config import Settings

OUT=Path(__file__).parent/'training'
# example, negative, explanation, exact grounding excerpt
NEGATIVE_REVIEWS=[
('TRAIN-B0001-V1',6,'Запрос требует исторических стратегий скрытого влияния. Это практическое уважительное общение без давления и манипуляций, с другим подходом и форматом.', 'без давления и манипуляций'),
('TRAIN-B0002-V2',849,'Нужны домашнее насилие и личные границы. Здесь центральная ситуация — вдовство и письма умершего мужа, а не опасные отношения с живым партнёром.', 'После смерти мужа Джерри от опухоли мозга'),
('TRAIN-B0003-V1',816,'Запрос о защищённости личных финансов при высокой зарплате. Эта книга строит макроэкономическую модель занятости и спроса, не объясняет индивидуальный бюджет.', 'макроэкономическую модель'),
('TRAIN-B0004-V2',352,'Нужен выбор жизненных ценностей и отказ от чужих ожиданий. Это руководство к публичным выступлениям: подготовка речи, память и дикция.', 'публичное выступление'),
('TRAIN-B0011-V2',352,'Нужен путь от зависимости через самостоятельность к взаимовыгодному сотрудничеству. Здесь главный предмет — подготовка уверенного публичного выступления.', 'продуманной структуре речи'),
('TRAIN-B0013-V2',302,'Нужна быстрая мрачная антиутопия о девушке в жестоком шоу. Это реальные мемуары о борьбе за образование, не вымышленная телевизионная арена.', 'борьбе за право девочек получать образование'),
('TRAIN-B0014-V2',43,'Нужна взрослая история контроля и границ в отношениях. Здесь трагедия тайного брака молодых влюблённых и семейной вражды, без центральной ситуации властного партнёра.', 'давнюю вражду своих семей'),
('TRAIN-B0016-V1',294,'Нужны школьное знакомство в дождливом городе и одноклассник-вампир. Здесь девятилетняя девочка одна теряется на лесной тропе, а не вступает в школьную романтическую связь.', 'теряется в лесу'),
('TRAIN-B0016-V2',410,'Обязательна любовь к существу из сверхъестественного мира. Профиль описывает человеческие отношения замужней женщины с лесником в промышленной Англии.', 'механизированному миру промышленной Англии'),
('TRAIN-B0021-V2',817,'Нужна художественная мрачная сатира о вырождении обещанного равенства. Это теоретический политический труд о сломе государственного аппарата, не сатирическая притча.', 'Тон: полемический; теоретический'),
('TRAIN-B0032-V1',979,'Нужны мрачная готика, найденыш, одержимость и месть двух поколений. Здесь уютная сказочная романтика нового начала в Ирландии с психологом и хозяином паба.', 'Тон: романтический; сказочный; уютный'),
('TRAIN-B0032-V2',979,'Запрос про страстную семейную драму на йоркширских пустошах и два поместья. Эта история разворачивается в ирландском коттедже и пабе с другим тоном и ситуацией.', 'коттедж Фейри-Хилл'),
('TRAIN-B0036-V1',294,'Нужен ненадёжный взрослый рассказчик, оправдывающий контроль над падчерицей языком. Здесь сюжет о заблудившейся девочке и страхе в лесу, а не исповедь эксплуатирующего взрослого.', 'девятилетняя Триша Макфарланд'),
('TRAIN-B0041-V2',282,'Нужны быстрые интеллектуальные детективные рассказы и дедукция. Это единый мрачный психологический роман о журналистке, семейной травме и убийствах девочек.', 'репортёр Камилла Прикер'),
('TRAIN-B0042-V2',544,'Плен и одержимость близки, но запрос требует фанатичной читательницы и принудительного написания продолжения. Здесь мужчина похищает художницу ради любви; творчество пленного автора не является задачей.', 'похищает девушку и запирает её в подвале'),
('TRAIN-B0045-V2',67,'Нужен хоррор о подавленной ярости девушки и выпускном бале. Здесь политическая антиутопия о победителях, снова отправленных на арену, без выпускного школьного конфликта.', 'юбилейная Квартальная бойня'),
('TRAIN-B0050-V2',352,'Нужна интимная меланхоличная подростковая художественная проза. Это практический нехудожественный тренинг публичной речи, а не история школьного взросления.', 'регулярным выступлениям'),
('TRAIN-B0053-V2',95,'Мрачная наука близка по тону, но запрос требует горя и попытки отменить смерть. Этот эксперимент разделяет стороны личности врача, а не возвращает умерших.', 'разделить нравственную и тёмную стороны собственной личности'),
('TRAIN-B0055-V2',756,'Нужны записи взросления в тесном убежище и страх обнаружения. Это мемуары французской девушки о буржуазных ожиданиях и интеллектуальном становлении, не дневник тайного укрытия.', 'буржуазной французской семье'),
('TRAIN-B0065-V2',50,'Взросление близко, но нужны реалистические подростковые группировки и классовые ярлыки. Здесь замкнутый школьник, письма и друзья на вечеринках, без центральной вражды банд.', 'письмах неизвестному адресату'),
('TRAIN-B0068-V1',514,'Запрос конкретно о сооснователе Apple. Это биография математика Нэша, его теории игр и психического кризиса, другой человек и область работы.', 'математика Джона Форбса Нэша'),
('TRAIN-B0074-V2',112,'Нужна тревожная сатира на статус и потребительство успешного финансиста. Здесь документальное расследование убийства семьи, не сатирический рассказ банкира.', 'Тон: документальный; сдержанный; мрачный'),
('TRAIN-B0075-V2',736,'Нужны медленные беседы взрослого ученика и умирающего учителя о жизни. Здесь юмористические воспоминания детства натуралиста на Корфу и домашний зверинец.', 'домашний зверинец'),
('TRAIN-B0077-V2',727,'Обязателен трансакционный анализ. Этот профиль объясняет общение через популярные гендерные различия и бытовые привычки; это другая объяснительная система.', 'разные привычки полов'),
('TRAIN-B0093-V1',747,'Нужен владелец гостиницы, рассказывающий хронисту о становлении магом. Здесь документальная история моряка после десяти дней на плоту, не фэнтезийная автобиография волшебника.', 'десять дней на плоту'),
('TRAIN-B0106-V2',163,'Нужна рифмованная абсурдная игровая история для начинающего читателя. Здесь мрачная ироничная проза о юридической охоте опекуна за наследством детей, другой формат и тон.', 'юридическую уловку'),
('TRAIN-B0114-V2',602,'Тревога за детей близка, но нужны готическое заточение и семейное наследство. Здесь дети исчезают, а мать подозревают и ведут срочные поиски; профиль не описывает наследственную изоляцию.', 'срочные поиски'),
('TRAIN-B0141-V2',266,'Нужна история развития цивилизаций и исторического неравенства. Здесь объясняется происхождение биологических видов, не преимущества человеческих обществ.', 'эволюции живого мира'),
('TRAIN-B0159-V2',112,'Нужна семейная хроника преступной власти и преемственности. Эта документальная книга следует за жертвами и убийцами отдельного преступления, а не за династией организованной преступности.', 'убийство семьи Клаттеров'),
('TRAIN-B0163-V1',545,'Нужны трое сирот, опекун-актёр и юридическое присвоение их наследства. Здесь состояние миллиардера завещано взрослой миссионерке, которую ищет адвокат в Бразилии.', 'миссионерке, живущей в бразильских джунглях'),
('TRAIN-B0164-V2',424,'Комедия ошибок подходит по общему жанру, но нужны сказочная магия и озорный дух. Здесь переодевание и разлучённые близнецы, а путаница объясняется ошибочным узнаванием.', 'переодевшись юношей Цезарио'),
('TRAIN-B0170-V2',793,'Нужны мечтатель-рыцарь и практичный оруженосец. Здесь молодой аристократ путешествует с сестрой и другом в европейском туре; рыцарского самообмана и оруженосца нет в профиле.', 'вместе с сестрой Фелисити и лучшим другом Перси'),
('TRAIN-B0171-V2',705,'Нужен трагический древний воинский эпос. Здесь сатирический роман о светском подъёме, долгах и брачном расчёте в эпоху Регентства, а не поэма о героях Трои.', 'общество эпохи Регентства'),
('TRAIN-B0173-V2',260,'Любовь и путешествие во времени близки, но обязательна историческая миссия. Здесь непроизвольные перемещения в собственную жизнь и сохранение брака, не попытка предотвратить историческое убийство.', 'непредсказуемых исчезновений')
]
REJECTED_REVIEWS=[
('TRAIN-B0003-V1',703,'compatible','Финансовая независимость через активы вместо зарплаты прямо соответствует запросу. Другой том нельзя объявлять отрицательным.'),
('TRAIN-B0003-V2',100,'partial_or_compatible','Активы и обязательства подтверждены; сравнение двух отцов прямо не описано. Подростковая адаптация близка и не является безопасным негативом.'),
('TRAIN-B0033-V2',139,'compatible','Те же школьники, дружба, любовь и самоопределение. Продолжение также подходит к этой формулировке.'),
('TRAIN-B0027-V2',139,'partial','Мужская дружба и принятие близки, но депрессия в данном профиле не подтверждена. Не использовать частично подходящую книгу как негатив.'),
('TRAIN-B0126-V2',643,'partial','Космология подходит к части запроса, но широкий обзор Земли и жизни не подтверждён. Это частичный ответ, не безопасный негатив.'),
('TRAIN-B0127-V2',432,'compatible_or_ambiguous','Мрачная исповедь женщины под подозрением и скрытая вина близки к широкому запросу; публичное осуждение требует дальнейшей оценки.'),
('TRAIN-B0161-V2',959,'compatible_or_ambiguous','Созерцательная философия, работа с сознанием и отказ от внутреннего беспокойства близки; противопоставлять созерцательные трактаты рискованно.'),
('TRAIN-B0163-V2',334,'partial_or_ambiguous','Детская изобретательность и мрачная ситуация близки, хотя ирония и безразличие взрослых не подтверждены. Принудительный негатив не добавлять.')
]
ADDITIONAL_POSITIVES=[('TRAIN-B0003-V1',703),('TRAIN-B0033-V2',139)]

def norm(t):
    t=''.join(c for c in unicodedata.normalize('NFKD',t) if not unicodedata.combining(c))
    return re.sub(r'\W+',' ',t.lower().replace('ё','е')).strip()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,data): (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def jsonl(name,rows): (OUT/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')

def main():
    settings=Settings.from_env('small')
    books={b.catalog_id:b for b in load_catalog(settings.catalog_path,settings.import_report_path)}
    policy=json.loads((OUT.parent/'split-policy.json').read_text(encoding='utf-8'))
    excluded=set(policy['training_excluded_book_ids'])
    # Expand dev exclusions as well: the earlier frozen policy expanded test/regression only.
    names={norm(books[i].title) for i in excluded if len(norm(books[i].title).split())>=2}
    source_names={norm(books[i].source_title) for i in excluded if books[i].source_title}
    series={books[i].series for i in excluded if books[i].series}
    extra={i for i,b in books.items() if i not in excluded and
        (any(n in norm(b.title) for n in names) or (b.source_title and norm(b.source_title) in source_names)
         or (b.series and b.series in series))}
    excluded |= extra
    rows=[json.loads(l) for l in (OUT/'train_pairs.jsonl').read_text(encoding='utf-8').splitlines()]
    examples={r['example_id']:r for r in rows}
    mine=json.loads((OUT/'hard-negative-candidates.json').read_text(encoding='utf-8'))
    mined={r['example_id']:r for r in mine['candidates']}
    reviews=[]
    triplets=[]
    for eid,bid,reason,quote in NEGATIVE_REVIEWS:
        r=examples[eid]
        assert r['positive_catalog_id'] not in excluded
        assert bid not in excluded,bid
        candidate=next(c for c in mined[eid]['candidates'] if c['catalog_id']==bid)
        assert quote in books[bid].search_text,(eid,quote)
        assert candidate['rank']<mined[eid]['positive_rank']
        negative={'negative_catalog_id':bid,'negative_product_id':books[bid].product_id,
            'negative_title':books[bid].title,'negative_passage':books[bid].search_text,
            'negative_grade':0,'negative_label':'не подходит','negative_explanation':reason,
            'negative_evidence_anchor':quote,'negative_profile_sha256':hashlib.sha256(books[bid].search_text.encode()).hexdigest(),
            'negative_source_model':mine['source_model'],'negative_original_rank':candidate['rank'],
            'positive_original_rank':mined[eid]['positive_rank'],'negative_cosine':candidate['cosine'],
            'positive_cosine':mined[eid]['positive_cosine'],'negative_mining_query':mined[eid]['corrected_query'],
            'negative_review_status':'assistant_editorial_review_against_catalog',
            'negative_is_query_specific':True}
        r.update(negative)
        triplets.append(r)
        reviews.append({'example_id':eid,'candidate_catalog_id':bid,'decision':'accepted_negative',
                        'reason':reason,'evidence_anchor':quote,'original_rank':candidate['rank'],
                        'positive_original_rank':mined[eid]['positive_rank']})
    for eid,bid,decision,reason in REJECTED_REVIEWS:
        candidate=next(c for c in mined[eid]['candidates'] if c['catalog_id']==bid)
        reviews.append({'example_id':eid,'candidate_catalog_id':bid,'decision':decision,'reason':reason,
                        'evidence':books[bid].search_text,'original_rank':candidate['rank']})
    for eid,bid in ADDITIONAL_POSITIVES:
        assert bid not in excluded
        examples[eid].setdefault('additional_compatible_positives',[]).append({
            'catalog_id':bid,'product_id':books[bid].product_id,'title':books[bid].title,
            'passage':books[bid].search_text,'grade':2,
            'reason':next(r[3] for r in REJECTED_REVIEWS if r[0]==eid and r[1]==bid),
            'profile_sha256':hashlib.sha256(books[bid].search_text.encode()).hexdigest()})
    assert len(rows)==512
    assert len({r['example_id'] for r in rows})==512
    assert all(r['positive_catalog_id'] not in excluded for r in rows)
    jsonl('train.jsonl',rows)
    jsonl('train_triplets.jsonl',triplets)
    write('candidate-review-log.json',{'reviewed':len(reviews),'accepted_negatives':len(triplets),
        'rejected_or_compatible':len(REJECTED_REVIEWS),'reviews':reviews,
        'remaining_candidates':'Unreviewed; must not be used as negatives.'})
    for error in mine['candidates']:
        error['candidates']=[c for c in error['candidates'] if c['catalog_id'] not in excluded]
    mine['supplementary_exclusions_applied']=sorted(extra)
    write('hard-negative-candidates.json',mine)
    batch=json.loads((OUT/'batch-policy.json').read_text(encoding='utf-8'))
    batch['training_excluded_book_ids']=sorted(excluded)
    batch['supplementary_excluded_book_ids']=sorted(extra)
    batch['additional_compatible_positives']=[{'example_id':eid,'book_id':bid} for eid,bid in ADDITIONAL_POSITIVES]
    batch['rules'].append('Respect additional compatible positives; never treat them as negatives for the listed query.')
    write('batch-policy.json',batch)
    preview=['# Примеры обучающих записей','',
             'Всего 512 запросов по 64 основным книгам. Ниже представлены проверенные тройки; '
             'в полной выборке у остальных записей отрицательный пример отсутствует.','']
    for r in triplets:
        preview += [f"## {r['example_id']}",'',f"Запрос: {r['query']}",'',
                    f"Подходит: {r['positive_title']} (catalog_id={r['positive_catalog_id']}).",'',
                    f"Не подходит: {r['negative_title']} (catalog_id={r['negative_catalog_id']}).",'',
                    r['negative_explanation'],'',
                    f"Ранг исходной семантики: подходящая книга {r['positive_original_rank']}, кандидат {r['negative_original_rank']}.",'']
    (OUT/'REVIEWED_EXAMPLES.md').write_text('\n'.join(preview),encoding='utf-8')
    write('training-summary.json',{'examples':len(rows),'primary_positive_books':64,
        'additional_compatible_positive_books':len(ADDITIONAL_POSITIVES),
        'triplets':len(triplets),'reviewed_candidates':len(reviews),
        'queries_mined':mine['queries_mined'],'original_errors_with_candidates':mine['errors_with_eligible_candidates'],
        'supplementary_excluded_books':sorted(extra),'training_excluded_book_count':len(excluded),
        'training_eligible_book_count':len(books)-len(excluded),'catalog_sha256':sha(settings.catalog_path),
        'fixed_dev_test_unchanged':True,'review_basis':'Assistant editorial review against catalog; not independent human review.',
        'model_training_started':False})
    names=['train.jsonl','train_pairs.jsonl','train_triplets.jsonl','candidate-review-log.json',
           'batch-policy.json','hard-negative-candidates.json','training-summary.json',
           'leakage-screen.json','REVIEWED_EXAMPLES.md']
    write('training-manifest.json',{'version':1,'catalog_sha256':sha(settings.catalog_path),
        'original_index_sha256':sha(settings.index_path),
        'assessment_freeze_sha256':sha(OUT.parent/'freeze-manifest.json'),
        'files':{n:sha(OUT/n) for n in names},'model_training_started':False})
    print('Finalized',len(rows),'examples;',len(triplets),'checked triplets;',len(extra),'extra protected editions/series')

if __name__=='__main__':main()
