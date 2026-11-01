"""Two fixed runs; selection uses frozen dev only. No production mutations."""
from pathlib import Path
from collections import Counter,defaultdict
import os,json,hashlib,random,time,math,gc,shutil,sys
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from sentence_transformers.sentence_transformer.losses import MultipleNegativesRankingLoss
from ml_search.catalog import load_catalog
from ml_search.config import Settings

ROOT=Path(__file__).parent
OUT=ROOT/'limited_experiment'
SEED=20260915
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,data):
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def emit(data):
    with (OUT/'training-log.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(data,ensure_ascii=False)+'\n')
    print(json.dumps(data,ensure_ascii=True),flush=True)
def make_plan(rows,books,policy):
    conflicts={frozenset((p['book_a'],p['book_b'])) for p in policy['do_not_place_as_in_batch_negatives']}
    reasons=defaultdict(set)
    for edge in conflicts:reasons[edge].add('existing_compatibility_policy')
    ids=sorted({r['positive_catalog_id'] for r in rows})
    reflective={4,6,11,27,33,50,75,77,80,108,116,127,140,161,164,170}
    # Exclusion is conservative; common genre/tone never creates a negative label.
    near_genres={'Романтика','Ужасы','Триллеры','Детективы','Детская литература','Подростковая литература','Фэнтези','Бизнес и экономика','Психология','Саморазвитие','Философия','Религия','Поэзия','Биографии и мемуары','Научно-популярная литература'}
    tones={}
    for i in ids:
        text=books[i].search_text
        tones[i]={t.strip().lower() for t in text.split('Тон: ')[-1].split('. Темп:')[0].rstrip('.').split(';')} if 'Тон: ' in text else set()
    for a in ids:
        for b in ids:
            if a>=b:continue
            edge=frozenset((a,b))
            if a in reflective and b in reflective:reasons[edge].add('editorial_broad_reflection_relationship_or_gentle_reading_overlap')
            if set(books[a].genres)&set(books[b].genres)&near_genres:reasons[edge].add('shared_specific_genre')
            if tones[a]&tones[b]:reasons[edge].add('shared_profile_tone')
    conflicts |= set(reasons)
    denied=set(policy['training_excluded_book_ids'])
    plans=[]
    for epoch in range(1,4):
        rng=random.Random(SEED+epoch)
        pending=list(rows);rng.shuffle(pending)
        batches=[];repeats=[]
        while pending:
            batch=[]
            for r in pending:
                bid=r['positive_catalog_id']
                if all(bid!=x['positive_catalog_id'] and frozenset((bid,x['positive_catalog_id'])) not in conflicts for x in batch):
                    batch.append(r)
                    if len(batch)==8:break
            selected={r['example_id'] for r in batch}
            pending=[r for r in pending if r['example_id'] not in selected]
            if len(batch)==1:
                bid=batch[0]['positive_catalog_id']
                helpers=[r for r in rows if r['positive_catalog_id']!=bid and frozenset((bid,r['positive_catalog_id'])) not in conflicts]
                assert helpers,('No safe companion',bid)
                helper=rng.choice(helpers);batch.append(helper);repeats.append(helper['example_id'])
            assert 2<=len(batch)<=8
            bids=[r['positive_catalog_id'] for r in batch]
            assert len(set(bids))==len(bids) and not set(bids)&denied
            assert all(frozenset((a,b)) not in conflicts for a in bids for b in bids if a!=b)
            assert len({r['positive_passage'] for r in batch})==len(batch)
            batches.append([r['example_id'] for r in batch])
        flattened=[eid for batch in batches for eid in batch]
        assert set(flattened)=={r['example_id'] for r in rows}
        plans.append({'epoch':epoch,'batches':batches,'batch_size_counts':dict(Counter(map(len,batches))),
            'unique_examples':len(set(flattened)),'companion_repeats':repeats,'presentations':len(flattened)})
    return {'seed':SEED,'max_batch_size':8,'conflicts':[{'books':sorted(edge),'reasons':sorted(reason)} for edge,reason in sorted(reasons.items(),key=lambda x:sorted(x[0]))],
        'epochs':plans,'basis':'Conservative exclusion of known compatibility, shared themes/series, specific genres and exact profile tones. Assistant editorial review; not exhaustive human qrels.'}

def evaluate(model,books,dev,label):
    start=time.perf_counter();model.eval()
    passages=['passage: '+b.search_text for b in books]
    docs=model.encode(passages,batch_size=32,normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
    queries=model.encode(['query: '+q['query'] for q in dev],batch_size=32,normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
    assert docs.shape==(1000,384) and np.isfinite(docs).all() and np.isfinite(queries).all()
    assert np.allclose(np.linalg.norm(docs,axis=1),1,atol=1e-5)
    scores=queries@docs.T
    records=[]
    for q,score in zip(dev,scores):
        order=np.argsort(-score,kind='stable')
        top=[books[i].catalog_id for i in order[:10]]
        grades={j['catalog_id']:j['grade'] for j in q['judgments']}
        good={i for i,g in grades.items() if g==2}
        ranks=[int(np.where(order==i)[0][0])+1 for i,b in enumerate(books) if b.catalog_id in good]
        best=min(ranks) if ranks else None
        dcg=sum((2**grades.get(bid,0)-1)/math.log2(k+2) for k,bid in enumerate(top))
        ideal=sum((2**g-1)/math.log2(k+2) for k,g in enumerate(sorted(grades.values(),reverse=True)[:10]))
        records.append({'query_id':q['query_id'],'group_id':q['group_id'],'category':q['category'],
            'expected_empty':q['expected_empty'],'best_known_good_rank':best,'mrr':1/best if best else None,
            'hit3':int(best<=3) if best else None,'hit10':int(best<=10) if best else None,
            'known_qrel_ndcg10_provisional':dcg/ideal if ideal else None,
            'top10':[{'catalog_id':bid,'score':float(score[bid-1]),'known_grade':grades.get(bid)} for bid in top],
            'known_bad_in_top10':sum(grades.get(bid)==0 for bid in top),
            'unknown_in_top10':sum(bid not in grades for bid in top),'max_cosine':float(score[order[0]])})
    families=defaultdict(list)
    for r in records:
        if not r['expected_empty']:families[r['group_id']].append(r)
    metrics=['mrr','hit3','hit10','known_qrel_ndcg10_provisional']
    family_summary={g:{m:float(np.mean([r[m] for r in rr])) for m in metrics} for g,rr in families.items()}
    summary={m:float(np.mean([r[m] for r in family_summary.values()])) for m in metrics}
    categories={c:{m:float(np.mean([v[m] for g,v in family_summary.items() if next(r['category'] for r in records if r['group_id']==g)==c])) for m in metrics} for c in sorted({r['category'] for r in records if not r['expected_empty']})}
    result={'label':label,'summary':summary,'by_category':categories,'by_family':family_summary,
        'queries':records,'positive_queries':sum(not r['expected_empty'] for r in records),
        'no_match_queries':sum(r['expected_empty'] for r in records),'seconds':time.perf_counter()-start,
        'scope':'Pure semantic retrieval over all 1000 unchanged profiles; raw dev queries; no test. Unknown documents remain ungraded.',
        'no_match_policy':'No threshold selected or production logic changed; cosine distributions recorded, not empty-result accuracy.'}
    write(f'dev-{label}.json',result)
    emit({'event':'dev_evaluation','label':label,'summary':summary,'seconds':result['seconds']})
    return result

def main():
    assert torch.cuda.is_available()
    OUT.mkdir(exist_ok=True)
    assert not (OUT/'preregistration.json').exists(),'Do not overwrite a previous experiment'
    settings=Settings.from_env('small')
    books=load_catalog(settings.catalog_path,settings.import_report_path)
    byid={b.catalog_id:b for b in books}
    rows=[json.loads(l) for l in (ROOT/'training/train.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(rows)==512
    policy=json.loads((ROOT/'training/batch-policy.json').read_text(encoding='utf-8'))
    dev=json.loads((ROOT/'dev_queries.json').read_text(encoding='utf-8'))
    assert len(dev)==60
    frozen=json.loads((ROOT/'freeze-manifest.json').read_text(encoding='utf-8'))
    protected={name:sha(ROOT/name) for name in frozen['files']}
    assert protected==frozen['files']
    for r in rows:
        assert r['positive_passage']==byid[r['positive_catalog_id']].search_text
        assert r['positive_catalog_id'] not in policy['training_excluded_book_ids']
    source=settings.local_model_path
    model_hash=sha(source/'model.safetensors')
    catalog_hash=sha(settings.catalog_path)
    plan=make_plan(rows,byid,policy)
    write('batch-plan.json',plan)
    if '--prepare-only' in sys.argv:
        print(json.dumps({'conflicts':len(plan['conflicts']),'epochs':[{'epoch':e['epoch'],'batch_sizes':e['batch_size_counts'],'companion_repeats':len(e['companion_repeats'])} for e in plan['epochs']]},indent=2))
        return
    hard_rows=[r for r in rows if r['negative_catalog_id'] is not None]
    assert len(hard_rows)==34
    for r in hard_rows:
        assert r['negative_grade']==0 and r['negative_catalog_id'] not in policy['training_excluded_book_ids']
        assert r['negative_passage']==byid[r['negative_catalog_id']].search_text
    events=[]
    for e in plan['epochs']:
        ev=[{'mode':'pairs','ids':b} for b in e['batches']]+[{'mode':'reviewed_triplet','ids':[r['example_id']]} for r in hard_rows]
        random.Random(SEED+100+e['epoch']).shuffle(ev)
        events.append(ev)
    write('step-plan.json',{'epochs':events,'triplets_are_repeated_subset_not_new_queries':True})
    config={'method':'MultipleNegativesRankingLoss','learning_rates':[1e-5,2e-5],'epochs':3,'max_batch_size':8,
        'precision':'BF16 autocast','max_sequence_length':512,'seed':SEED,'weight_decay':0.01,
        'gradient_clip':1.0,'warmup_fraction':0.1,'lr_schedule':'linear warmup then linear decay over 3 epochs',
        'selection_primary':'family_macro_MRR_known_grade2_nonempty_dev','selection_ties':['family_macro_hit10','provisional_known_qrel_ndcg10','earlier_epoch','lower_learning_rate'],
        'baseline_in_selection':False,'baseline_role':'Reference; best trained checkpoint selected even if no gain, with explicit warning.',
        'known_qrel_limitation':'Incomplete qrels. Unknown gains treated as zero ONLY for provisional NDCG; unknown is not an annotation of irrelevance.',
        'scope':'Step 6 only; no test, no regression model selection, no production weights/profile/rules changes',
        'train_sha256':sha(ROOT/'training/train.jsonl'),'dev_sha256':sha(ROOT/'dev_queries.json'),
        'catalog_sha256':catalog_hash,'source_model_sha256':model_hash,'frozen_files_sha256':protected,
        'steps_per_epoch':[len(e) for e in events],
        'hard_negative_policy':'34 reviewed triplets, batch size 1, interleaved once per epoch; no cross-query negative use',
        'manual_batch_review':'Additional reflective-topic compatibility exclusions after preliminary batch review; frozen before final comparison.'}
    write('preregistration.json',config)
    torch.set_num_threads(4)
    model=SentenceTransformer(str(source),device='cuda',local_files_only=True);model.max_seq_length=512
    baseline=evaluate(model,books,dev,'baseline')
    del model;gc.collect();torch.cuda.empty_cache()
    results=[];example_map={r['example_id']:r for r in rows}
    for lr in config['learning_rates']:
        torch.manual_seed(SEED);random.seed(SEED);np.random.seed(SEED)
        run_name=f'lr-{lr:.0e}'
        run=OUT/run_name;run.mkdir()
        model=SentenceTransformer(str(source),device='cuda',local_files_only=True);model.max_seq_length=512
        optimizer=torch.optim.AdamW(model.parameters(),lr=lr,weight_decay=0.01)
        loss_fn=MultipleNegativesRankingLoss(model,scale=20)
        total=sum(len(e) for e in events);warmup=max(1,int(total*0.1))
        def schedule(step):return (step+1)/warmup if step<warmup else max(0,(total-step)/(total-warmup))
        scheduler=torch.optim.lr_scheduler.LambdaLR(optimizer,schedule)
        assert torch.cuda.is_bf16_supported()
        global_step=0
        for epoch_plan in plan['epochs']:
            epoch=epoch_plan['epoch'];model.train();torch.cuda.reset_peak_memory_stats()
            start=time.perf_counter();losses=[]
            for event in events[epoch-1]:
                ids=event['ids']
                batch=[example_map[eid] for eid in ids];optimizer.zero_grad(set_to_none=True)
                with torch.autocast('cuda',dtype=torch.bfloat16):
                    fs=[]
                    columns=[('query','query: '),('positive_passage','passage: ')]
                    if event['mode']=='reviewed_triplet':columns.append(('negative_passage','passage: '))
                    for key,prefix in columns:
                        f=model.tokenize([prefix+r[key] for r in batch])
                        fs.append({k:v.to('cuda') if torch.is_tensor(v) else v for k,v in f.items()})
                    loss=loss_fn(fs,torch.empty(0,device='cuda'))
                assert torch.isfinite(loss)
                loss.backward();grad=torch.nn.utils.clip_grad_norm_(model.parameters(),1.0)
                assert torch.isfinite(grad)
                optimizer.step();scheduler.step();global_step+=1;losses.append(loss.item())
                emit({'event':'training_step','run':run_name,'epoch':epoch,'step':global_step,'batch_size':len(batch),
                    'mode':event['mode'],'loss':losses[-1],'lr_next':optimizer.param_groups[0]['lr']})
            torch.cuda.synchronize()
            checkpoint=run/f'epoch-{epoch}';model.eval();model.save_pretrained(str(checkpoint),safe_serialization=True)
            torch.save({'optimizer':optimizer.state_dict(),'scheduler':scheduler.state_dict(),'global_step':global_step,'epoch':epoch,'seed':SEED},run/'resume-latest.pt')
            emit({'event':'epoch_complete','run':run_name,'epoch':epoch,'training_and_save_seconds':time.perf_counter()-start,
                'mean_loss':float(np.mean(losses)),'peak_cuda_allocated_gib':torch.cuda.max_memory_allocated()/2**30,
                'peak_cuda_reserved_gib':torch.cuda.max_memory_reserved()/2**30})
            result=evaluate(model,books,dev,f'{run_name}-epoch-{epoch}')
            results.append({'run':run_name,'lr':lr,'epoch':epoch,'checkpoint':str(checkpoint.resolve()),'metrics':result['summary']})
            write('checkpoint-comparison.json',{'baseline':baseline['summary'],'checkpoints':results})
        del optimizer,scheduler,loss_fn,model,fs,f,loss;gc.collect();torch.cuda.empty_cache()
    selected=max(results,key=lambda r:(r['metrics']['mrr'],r['metrics']['hit10'],r['metrics']['known_qrel_ndcg10_provisional'],-r['epoch'],-r['lr']))
    selected_path=OUT/'selected-model'
    shutil.copytree(selected['checkpoint'],selected_path)
    # Check the serialized chosen model, not only the in-memory candidate.
    restored=SentenceTransformer(str(selected_path),device='cuda',local_files_only=True)
    selected_eval=evaluate(restored,books,dev,'selected-reloaded')
    assert all(abs(selected_eval['summary'][k]-selected['metrics'][k])<1e-10 for k in selected['metrics'])
    assert sha(source/'model.safetensors')==model_hash and sha(settings.catalog_path)==catalog_hash
    assert {name:sha(ROOT/name) for name in protected}==protected
    selection={'selected':selected,'selected_model':str(selected_path.resolve()),'baseline':baseline['summary'],
        'delta_vs_baseline':{k:selected['metrics'][k]-baseline['summary'][k] for k in selected['metrics']},
        'selection_dev_only':True,'test_evaluated':False,'production_model_replaced':False,
        'dev_primary_improved':selected['metrics']['mrr']>baseline['summary']['mrr'],
        'serialized_checkpoint_revalidated':True,'all_checkpoints':results}
    write('selection.json',selection)
    hashes={p.relative_to(OUT).as_posix():sha(p) for p in selected_path.rglob('*') if p.is_file()}
    write('experiment-manifest.json',{'selected_files':hashes,'selection_sha256':sha(OUT/'selection.json'),
        'preregistration_sha256':sha(OUT/'preregistration.json'),'batch_plan_sha256':sha(OUT/'batch-plan.json'),
        'code_sha256':sha(Path(__file__)),'dev_sha256':sha(ROOT/'dev_queries.json'),'catalog_sha256':catalog_hash,
        'source_model_sha256':model_hash,'test_untouched':True})
    emit({'event':'experiment_complete','selected':selected,'delta_vs_baseline':selection['delta_vs_baseline']})

if __name__=='__main__':main()
