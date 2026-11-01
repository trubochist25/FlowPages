"""Technical MNRL benchmark only; never uses evaluation queries."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import hashlib,json,time,subprocess,statistics,os,threading
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
import torch
import psutil
from sentence_transformers import SentenceTransformer
from sentence_transformers.sentence_transformer.losses import MultipleNegativesRankingLoss

ROOT=Path(__file__).parent
OUT=ROOT/'training_environment'
SOURCE=Path('data/ml_search/local-model')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
class Memory(ctypes.Structure):
    _fields_=[('length',wintypes.DWORD),('load',wintypes.DWORD)]+[(k,ctypes.c_ulonglong) for k in ['total','avail','page','availpage','virtual','availvirtual','extended']]
def ram():
    m=Memory();m.length=ctypes.sizeof(m)
    assert ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return {'total_gib':m.total/2**30,'available_gib':m.avail/2**30}
def gpu():
    return subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,memory.free,driver_version','--format=csv'],text=True).strip()
def main():
    OUT.mkdir(exist_ok=True)
    checkpoint=OUT/'smoke-model'
    assert not checkpoint.exists(),'Preserve previous checkpoint; use a new run directory'
    assert torch.cuda.is_available(),'CUDA required for this benchmark'
    torch.set_num_threads(4);torch.manual_seed(20260915)
    original=sha(SOURCE/'model.safetensors')
    all_rows=[json.loads(l) for l in (ROOT/'training/train.jsonl').read_text(encoding='utf-8').splitlines()]
    ids=[[1,3,4,16,50,53,91,113],[2,6,7,13,41,68,74,141]]
    batches=[[next(r for r in all_rows if r['example_id']==f'TRAIN-B{bid:04}-V1') for bid in group] for group in ids]
    policy=json.loads((ROOT/'training/batch-policy.json').read_text(encoding='utf-8'))
    conflicts={frozenset((r['book_a'],r['book_b'])) for r in policy['do_not_place_as_in_batch_negatives']}
    for group in ids:
        assert len(group)==len(set(group))==8
        assert not set(group)&set(policy['training_excluded_book_ids'])
        assert all(frozenset((a,b)) not in conflicts for a in group for b in group if a!=b)
    rows=[r for batch in batches for r in batch]
    (OUT/'smoke-batches.json').write_text(json.dumps({'book_ids':ids,'examples':rows,'basis':'Distinct mandatory intents checked editorially; all compatibility-policy edges excluded.'},ensure_ascii=False,indent=2),encoding='utf-8')
    before={'ram':ram(),'gpu':gpu()}
    rss_samples=[]
    stop=threading.Event()
    def sample_ram():
        while not stop.wait(0.1):rss_samples.append(psutil.Process().memory_info().rss/2**30)
    sampler=threading.Thread(target=sample_ram,daemon=True);sampler.start()
    start=time.perf_counter()
    model=SentenceTransformer(str(SOURCE),device='cuda',local_files_only=True)
    model.max_seq_length=512
    load_seconds=time.perf_counter()-start
    probe=['query: '+r['query'] for r in rows[:2]]
    initial=model.encode(probe,normalize_embeddings=True,convert_to_tensor=True).detach().cpu()
    optimizer=torch.optim.AdamW(model.parameters(),lr=2e-5,weight_decay=0.01)
    loss_fn=MultipleNegativesRankingLoss(model,scale=20)
    lengths=[len(model.tokenizer(t)['input_ids']) for r in rows for t in ['query: '+r['query'],'passage: '+r['positive_passage']]]
    assert max(lengths)<=512
    use_bf16=torch.cuda.is_bf16_supported()
    dtype=torch.bfloat16 if use_bf16 else torch.float16
    scaler=torch.amp.GradScaler('cuda',enabled=not use_bf16)
    torch.cuda.reset_peak_memory_stats()
    times=[];losses=[];observed=[]
    model.train()
    # Conservative editorially checked batches; no mined negatives added.
    for step in range(12):
        batch=batches[step%2]
        torch.cuda.synchronize();t=time.perf_counter()
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast('cuda',dtype=dtype):
            sentence_features=[]
            for key,prefix in [('query','query: '),('positive_passage','passage: ')]:
                features=model.tokenize([prefix+r[key] for r in batch])
                features={k:v.to('cuda') if torch.is_tensor(v) else v for k,v in features.items()}
                sentence_features.append(features)
            loss=loss_fn(sentence_features,torch.empty(0,device='cuda'))
        assert torch.isfinite(loss)
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        grad=torch.nn.utils.clip_grad_norm_(model.parameters(),1.0)
        assert torch.isfinite(grad)
        scaler.step(optimizer);scaler.update()
        torch.cuda.synchronize();times.append(time.perf_counter()-t);losses.append(loss.item())
        observed.append(gpu())
        print(json.dumps({'step':step+1,'seconds':times[-1],'loss':losses[-1],'allocated_gib':torch.cuda.memory_allocated()/2**30}),flush=True)
    peak_alloc=torch.cuda.max_memory_allocated()/2**30
    peak_reserved=torch.cuda.max_memory_reserved()/2**30
    model.eval()
    expected=model.encode(probe,normalize_embeddings=True,convert_to_tensor=True).detach().cpu()
    assert (initial-expected).abs().max().item()>1e-7,'Weights did not update'
    t=time.perf_counter();model.save_pretrained(str(checkpoint),safe_serialization=True)
    torch.save({'optimizer':optimizer.state_dict(),'steps':12,'seed':20260915},OUT/'optimizer-state.pt')
    save_seconds=time.perf_counter()-t
    del optimizer,model,features,sentence_features,loss,loss_fn
    torch.cuda.empty_cache()
    t=time.perf_counter()
    restored=SentenceTransformer(str(checkpoint),device='cuda',local_files_only=True)
    actual=restored.encode(probe,normalize_embeddings=True,convert_to_tensor=True).detach().cpu()
    reload_seconds=time.perf_counter()-t
    error=(actual-expected).abs().max().item()
    assert error<1e-5,error
    assert torch.isfinite(actual).all()
    state=torch.load(OUT/'optimizer-state.pt',weights_only=True,map_location='cpu')
    resumed=torch.optim.AdamW(restored.parameters(),lr=2e-5)
    resumed.load_state_dict(state['optimizer'])
    assert state['steps']==12
    assert sha(SOURCE/'model.safetensors')==original
    measured=statistics.median(times[2:])
    stop.set();sampler.join()
    report={'purpose':'technical only; not a quality evaluation or selected final objective',
        'torch':torch.__version__,'cuda_runtime':torch.version.cuda,'gpu_name':torch.cuda.get_device_name(0),
        'gpu_capability':torch.cuda.get_device_capability(0),'compiled_architectures':torch.cuda.get_arch_list(),
        'precision':'bf16 autocast' if use_bf16 else 'fp16 autocast','optimizer':'AdamW full model weights',
        'objective':'MultipleNegativesRankingLoss scale 20; normalized cosine; conservative reviewed batches',
        'batch_size':8,'max_sequence_length':512,'actual_max_tokens':max(lengths),
        'distinct_training_examples':16,'optimizer_steps':12,'step_seconds':times,'losses':losses,
        'steady_step_median_seconds':measured,'examples_per_second':8/measured,
        'gpu_peak_allocated_gib':peak_alloc,'gpu_peak_reserved_gib':peak_reserved,
        'gpu_samples':observed,'hardware_before':before,'ram_after':ram(),
        'process_peak_sampled_rss_gib':max(rss_samples),'rss_sampling_interval_seconds':0.1,
        'load_seconds':load_seconds,'save_seconds':save_seconds,'reload_seconds':reload_seconds,
        'reload_max_absolute_embedding_error':error,'optimizer_reload_passed':True,
        'weight_update_max_embedding_difference':(initial-expected).abs().max().item(),
        'original_model_unchanged':True,'full_training_not_started':True,
        'estimate_512_examples_3_epochs_seconds_same_configuration':192*measured,
        'estimate_1000_examples_3_epochs_seconds_same_configuration':375*measured}
    (OUT/'smoke-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2),flush=True)
if __name__=='__main__':main()
