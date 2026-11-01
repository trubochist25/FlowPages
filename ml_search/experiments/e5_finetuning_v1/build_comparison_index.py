"""Build the chosen-model index, only inside this experiment."""
from pathlib import Path
import os,json,hashlib,time
os.environ['HF_HUB_OFFLINE']='1'
import numpy as np
from sentence_transformers import SentenceTransformer
from ml_search.catalog import load_catalog
from ml_search.config import Settings
from ml_search.index import build_index,VectorIndex
ROOT=Path(__file__).parent
OUT=ROOT/'comparison'
NAME='multilingual-e5-small-finetuned-lr1e-5-epoch3'
def main():
    settings=Settings.from_env('small');books=load_catalog(settings.catalog_path,settings.import_report_path)
    model_path=ROOT/'limited_experiment/selected-model'
    frozen=json.loads((ROOT/'limited_experiment/experiment-manifest.json').read_text(encoding='utf-8'))
    for n,d in frozen['selected_files'].items():
        assert hashlib.sha256((ROOT/'limited_experiment'/n).read_bytes()).hexdigest()==d
    target=OUT/'index';target.mkdir(parents=True,exist_ok=True)
    assert not (target/'book-index.npz').exists()
    model=SentenceTransformer(str(model_path),device='cuda',local_files_only=True)
    class GPU:
        model_name=NAME
        def encode_passages(self,texts):
            return model.encode(['passage: '+t for t in texts],batch_size=32,normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
    start=time.perf_counter()
    manifest=build_index(books,GPU(),target/'book-index.npz',target/'manifest.json',settings.catalog_path)
    index=VectorIndex.load(target/'book-index.npz')
    assert index.vectors.shape==(1000,384) and np.isfinite(index.vectors).all()
    assert np.allclose(np.linalg.norm(index.vectors,axis=1),1,atol=1e-5)
    assert np.array_equal(index.product_ids,np.array([b.product_id for b in books]))
    manifest.update({'model_safetensors_sha256':hashlib.sha256((model_path/'model.safetensors').read_bytes()).hexdigest(),
        'model_path':str(model_path.resolve()),'prefix':'passage: ','normalized':True,'device_used_for_build':'cuda',
        'build_seconds':time.perf_counter()-start,'index_sha256':hashlib.sha256((target/'book-index.npz').read_bytes()).hexdigest()})
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2))
if __name__=='__main__':main()
