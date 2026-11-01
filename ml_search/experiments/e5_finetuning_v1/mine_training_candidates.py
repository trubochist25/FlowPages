"""Mine candidates from original-model errors, never label them automatically."""
from pathlib import Path
import os
import json
import sys
import numpy as np
from ml_search.config import Settings
from ml_search.cli import make_embedder
from ml_search.search import SearchEngine

OUT=Path(__file__).parent/'training'
def main():
    sys.stdout.reconfigure(encoding='utf-8')
    os.environ['ML_SEARCH_OFFLINE']='1'
    settings=Settings.from_env('small')
    embedder=make_embedder(settings,'e5')
    engine=SearchEngine.from_settings(settings,embedder)
    rows=[json.loads(l) for l in (OUT/'train_pairs.jsonl').read_text(encoding='utf-8').splitlines()]
    policy=json.loads((OUT.parent/'split-policy.json').read_text(encoding='utf-8'))
    allowed=set(policy['training_eligible_book_ids'])
    # First variant has the most concrete anchors, second one emphasizes tone.
    chosen=[r for r in rows if r['example_id'].endswith(('V1','V2'))]
    corrected=[engine.analyze(r['query']).corrected_query for r in chosen]
    vectors=embedder.encode_queries(corrected)
    candidates=[]
    for row,text,vector in zip(chosen,corrected,vectors):
        similarities=engine.vector_index.similarities(vector)
        order=np.argsort(-similarities,kind='stable')
        target=next(i for i,b in enumerate(engine.books) if b.catalog_id==row['positive_catalog_id'])
        positive_rank=int(np.flatnonzero(order==target)[0])+1
        mined=[]
        for rank,i in enumerate(order,1):
            b=engine.books[i]
            if rank>=positive_rank or rank>20:break
            if b.catalog_id not in allowed or b.catalog_id==row['positive_catalog_id']:continue
            mined.append({'catalog_id':b.catalog_id,'product_id':b.product_id,'title':b.title,
                'passage':b.search_text,'cosine':float(similarities[i]),'rank':rank,
                'status':'unreviewed_candidate_not_negative'})
        if mined:candidates.append({'example_id':row['example_id'],'query':row['query'],'corrected_query':text,
            'positive_catalog_id':row['positive_catalog_id'],'positive_title':row['positive_title'],
            'positive_passage':row['positive_passage'],'positive_cosine':float(similarities[target]),
            'positive_rank':positive_rank,'candidates':mined})
    result={'source_model':embedder.model_name,'queries_mined':len(chosen),'errors_with_eligible_candidates':len(candidates),
            'mode':'original_model_semantic_ranking_of_corrected_query_all_1000_books',
            'reserved_books_removed_from_candidate_export':True,'candidates':candidates}
    (OUT/'hard-negative-candidates.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Mined',len(chosen),'training queries;',len(candidates),'with candidates ahead of positive')
if __name__=='__main__':main()
