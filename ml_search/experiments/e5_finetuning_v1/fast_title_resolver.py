"""Indexed prototype of the selected title resolver; production code unchanged."""
from collections import defaultdict
from .compare_integration_variants import info,title_score
class FastTitleResolver:
    def __init__(self,books):
        self.books=books;self.tokens=[info(b['title']) for b in books];self.index=defaultdict(set)
        for n,tokens in enumerate(self.tokens):
            for token in set(tokens):self.index[token[:3]].add(n)
    def resolve(self,query):
        qt=info(query)
        if len(qt)<2:return None
        candidates=set()
        for prefix in {t[:3] for t in qt}:
            candidates.update(self.index.get(prefix,()))
        if not candidates:return None
        scored=sorted(((title_score(query,self.books[n]['title']),self.books[n]['id'],self.books[n]['title']) for n in candidates),reverse=True)
        first=scored[0];second=scored[1] if len(scored)>1 else (0,0,'');margin=first[0]-second[0]
        if (first[0]>=0.80 and margin>=0.045) or (first[0]>=0.66 and margin>=0.12):return {'catalog_id':first[1],'title':first[2],'score':first[0],'margin':margin}
        return None
