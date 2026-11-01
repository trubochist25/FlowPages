"""Diagnostic query variants, without changing corrector or ranker."""
from pathlib import Path
import json
import numpy as np
from .compare_selected_model import engines
from ml_search.schemas import SearchRequest
OUT=Path(__file__).parent/'regression_diagnosis_v1'
def main():
    es=engines();rows=[]
    probes=[('Гарри Поттер и философский камень','Гарри Поттер и философский камень'),('гарри поттер философский камень','Гарри Поттер и философский камень'),('Девушка с татуировкой дракона','Девушка с татуировкой дракона'),('татуировкой дракона','Девушка с татуировкой дракона')]
    for query,title in probes:
        r={'query':query,'expected_title':title,'models':{}}
        for name,e in es.items():
            response=e.search(SearchRequest(query=query,limit=50,include_debug=True));target=next((x for x in response.results if x.title==title),None)
            i=next(i for i,b in enumerate(e.books) if b.title==title);cos=e.vector_index.similarities(e.embedder.encode_queries([query])[0]);order=list(np.argsort(-cos,kind='stable'))
            r['models'][name]={'full_rank':next((k+1 for k,x in enumerate(response.results) if x.title==title),None),'raw_semantic_rank':order.index(i)+1,
                'intent':response.intent,'target_breakdown':target.score_breakdown.model_dump() if target else None}
        rows.append(r)
    (OUT/'navigation-variants.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'query':r['query'],'ranks':{n:v['full_rank'] for n,v in r['models'].items()}} for r in rows],ensure_ascii=True))
if __name__=='__main__':main()
